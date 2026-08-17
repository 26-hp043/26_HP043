"""소프트 삭제 동작 (TEST_PLAN §3.9 · §5.6, #66).

**막으려는 것은 「지웠는데 남아 있다」와 「지웠더니 다시 못 넣는다」 둘이다.**

`vessel`·`voyage`는 실제 DELETE가 아니라 ``is_deleted = true`` 표시로 지운다. 감사
로그·계산 이력이 그 행을 참조하기 때문이다(`DB_SCHEMA §7.1`). 그래서 두 가지가
동시에 성립해야 한다.

1. **조회에서 빠진다** — 남으면 사용자는 지운 배를 계속 본다
2. **자리를 비운다** — IMO는 ``idx_vessel_imo`` partial unique(``WHERE is_deleted =
   false``)라 삭제된 배의 IMO로 다시 등록할 수 있어야 한다. 안 되면 **한 번 잘못 등록한
   IMO를 영영 못 쓴다**

두 번째가 특히 조용하다. 파셜 인덱스의 ``WHERE`` 절이 빠져도 평소에는 아무 일도 없고,
**같은 배를 다시 등록하려는 순간에만** 드러난다.

케이스 (`TEST_PLAN §14.5`):
    IT-SOFTDEL-001 · IT-SOFTDEL-002 · DB-SOFT-001 · DB-SOFT-002
"""

from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError
from cii_platform.services.vessel import create_vessel, delete_vessel, get_vessel, list_vessels
from cii_platform.services.voyage import delete_voyage

IMO = "9330001"


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _new_vessel(session, *, imo: str = IMO, name: str = "SOFTDEL TEST"):
    """서비스 계층으로 등록한다 — 검증·중복 규칙까지 함께 지나가야 의미가 있다."""
    return await create_vessel(
        session,
        imo_number=imo,
        name=name,
        ship_type="BULK_CARRIER",
        deadweight=50000,
    )


async def _insert_vessel_raw(session, *, imo: str, is_deleted: bool) -> None:
    """DB 제약만 보려는 경로 — 서비스의 중복 검사를 지나지 않는다."""
    await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, deadweight, is_deleted) "
            "VALUES (:imo, 'RAW', 'BULK_CARRIER', 50000, :deleted)"
        ),
        {"imo": imo, "deleted": is_deleted},
    )


# ─────────────────────────────────────────────────────────────────────────────
# IT-SOFTDEL-001 · 조회에서 빠진다
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_soft_deleted_vessel_disappears_from_the_list(session):
    """IT-SOFTDEL-001 — 목록에 남으면 사용자는 지운 배를 계속 본다."""
    created = await _new_vessel(session)
    vessel_id = created["id"]

    before, _ = await list_vessels(session, limit=100)
    assert any(row["id"] == vessel_id for row in before)

    await delete_vessel(session, UUID(vessel_id))

    after, _ = await list_vessels(session, limit=100)
    assert not any(row["id"] == vessel_id for row in after)


@pytest.mark.asyncio
async def test_soft_deleted_vessel_is_not_readable_by_id(session):
    """상세 조회도 함께 막힌다.

    목록에서만 빼면 **링크를 아는 사람에게는 계속 보인다.** 목록 필터와 상세 조회가
    같은 조건을 쓰는지 확인한다.
    """
    created = await _new_vessel(session)
    vessel_id = UUID(created["id"])

    await delete_vessel(session, vessel_id)

    with pytest.raises(NotFoundError):
        await get_vessel(session, vessel_id)


@pytest.mark.asyncio
async def test_deleting_twice_is_not_found(session):
    """이미 지운 것은 찾을 수 없다 — REST의 멱등성보다 감사 로그 일관성이 앞선다."""
    created = await _new_vessel(session)
    vessel_id = UUID(created["id"])

    await delete_vessel(session, vessel_id)

    with pytest.raises(NotFoundError):
        await delete_vessel(session, vessel_id)


@pytest.mark.asyncio
async def test_soft_deleted_row_still_exists(session):
    """**표시일 뿐 지워지지 않는다.** 계산 이력이 이 행을 참조한다 (`DB_SCHEMA §7.1`).

    이 단언이 없으면 「soft delete」를 hard delete로 바꿔도 위 테스트들은 통과한다.
    """
    created = await _new_vessel(session)
    vessel_id = created["id"]

    await delete_vessel(session, UUID(vessel_id))

    row = await session.execute(
        text("SELECT is_deleted FROM vessel WHERE id = CAST(:id AS uuid)"), {"id": vessel_id}
    )
    assert row.scalar_one() is True


# ─────────────────────────────────────────────────────────────────────────────
# IT-SOFTDEL-002 · DB-SOFT-001 · 자리를 비운다
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_imo_can_be_registered_again_after_soft_delete(session):
    """IT-SOFTDEL-002 — 안 되면 **한 번 잘못 등록한 IMO를 영영 못 쓴다.**"""
    first = await _new_vessel(session, name="FIRST")
    await delete_vessel(session, UUID(first["id"]))

    second = await _new_vessel(session, name="SECOND")

    assert second["imo_number"] == IMO
    assert second["id"] != first["id"]


@pytest.mark.asyncio
async def test_partial_unique_index_ignores_deleted_rows(session):
    """DB-SOFT-001 — 서비스가 아니라 **인덱스**가 허용하는지 본다.

    서비스 경로만 보면 `find_active_by_imo`의 필터가 통과시키는 것인지 인덱스가
    허용하는 것인지 구분되지 않는다. 인덱스의 ``WHERE is_deleted = false``가 빠져도
    서비스 테스트는 통과한다.
    """
    await _insert_vessel_raw(session, imo="9330002", is_deleted=True)

    # 같은 IMO, 활성 행 — partial 인덱스가 삭제된 행을 세지 않으므로 들어가야 한다.
    await _insert_vessel_raw(session, imo="9330002", is_deleted=False)

    count = await session.execute(text("SELECT count(*) FROM vessel WHERE imo_number = '9330002'"))
    assert count.scalar_one() == 2


@pytest.mark.asyncio
async def test_two_active_rows_with_the_same_imo_are_rejected(session):
    """DB-SOFT-002 — 파셜 인덱스가 **활성 행 사이에서는 여전히 유일**해야 한다.

    이 단언이 없으면 인덱스를 통째로 지워도 위 테스트가 통과한다.
    """
    await _insert_vessel_raw(session, imo="9330003", is_deleted=False)

    with pytest.raises(IntegrityError):
        await _insert_vessel_raw(session, imo="9330003", is_deleted=False)


@pytest.mark.asyncio
async def test_service_still_refuses_duplicate_active_imo(session):
    """활성 중복은 409로 막힌다 — 인덱스에 닿기 전에 서비스가 먼저 답한다."""
    from cii_platform.errors import ConflictError

    await _new_vessel(session, imo="9330004")

    with pytest.raises(ConflictError):
        await _new_vessel(session, imo="9330004", name="DUPLICATE")


# ─────────────────────────────────────────────────────────────────────────────
# 항차 소프트 삭제
# ─────────────────────────────────────────────────────────────────────────────


async def _new_voyage(session, vessel_id: str, *, status: str) -> str:
    policy = {"COMPLETED": "INCLUDE_AS_ACTUAL", "PLANNED": "INCLUDE_AS_PLAN"}.get(status, "EXCLUDE")
    row = await session.execute(
        text(
            "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn) "
            "VALUES (CAST(:vid AS uuid), :st, :pol, 2026, 'BUSAN', 'SINGAPORE', 1000, 12) "
            "RETURNING id"
        ),
        {"vid": vessel_id, "st": status, "pol": policy},
    )
    return str(row.scalar_one())


@pytest.mark.asyncio
async def test_completed_voyage_is_soft_deleted_not_removed(session):
    """완료된 항차는 표시만 지운다 — 연간 집계·리포트의 근거였기 때문이다.

    (`DRAFT`·`CANCELLED`는 hard delete다. 그 갈림은 `#54`가 이미 덮는다.)
    """
    vessel = await _new_vessel(session, imo="9330005")
    voyage_id = await _new_voyage(session, vessel["id"], status="COMPLETED")

    await delete_voyage(session, UUID(voyage_id))

    row = await session.execute(
        text("SELECT is_deleted FROM voyage WHERE id = CAST(:id AS uuid)"), {"id": voyage_id}
    )
    assert row.scalar_one() is True


@pytest.mark.asyncio
async def test_soft_deleted_voyage_leaves_the_annual_aggregation(session):
    """**지운 항차가 집계에 남으면 등급이 틀린다.**

    조회 제외와 집계 제외는 다른 코드 경로다 — 목록만 걸러도 연간 누적에는 남을 수 있고,
    그 차이는 화면에서 보이지 않는다.
    """
    from cii_platform.db.repositories import voyage as voyage_repo

    vessel = await _new_vessel(session, imo="9330006")
    voyage_id = await _new_voyage(session, vessel["id"], status="COMPLETED")
    vessel_uuid = UUID(vessel["id"])

    before = await voyage_repo.list_annual_inclusions(
        session, vessel_id=vessel_uuid, regulation_year=2026, policy="INCLUDE_AS_ACTUAL"
    )
    assert len(before) == 1

    await delete_voyage(session, UUID(voyage_id))

    after = await voyage_repo.list_annual_inclusions(
        session, vessel_id=vessel_uuid, regulation_year=2026, policy="INCLUDE_AS_ACTUAL"
    )
    assert after == []
