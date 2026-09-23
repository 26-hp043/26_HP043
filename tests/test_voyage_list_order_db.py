"""항차 목록 · CSV 내보내기의 순서 — 출항 시각 최신순 (#1806).

종전에는 **등록 시각 오름차순**이었고, 그 순서를 실제 DB로 검증하는 테스트가 하나도
없었다 — ``tests/test_voyages_api.py``의 목록 테스트는 가짜 저장소라 SQL 정렬을 거치지
않는다. 여기서는 **등록 순서와 출항 순서를 일부러 엇갈리게** 넣는다. 둘이 같으면
정렬 키를 바꾸지 않아도 통과한다.

규칙(``API_SPEC §3.1``):

1. 출항 시각이 있는 항차가 먼저 — 출항 시각 = 실제 출항, 없으면 계획 출항 · 최신순
2. 출항 시각이 없는 항차(날짜 없는 초안)는 맨 아래
3. 같은 출항 시각끼리는 등록 시각 → id 내림차순
"""

from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from conftest import insert_returning_id
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import ValidationError
from cii_platform.services.voyage import list_voyages


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _insert_vessel(session) -> str:
    return await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type, deadweight) "
        "VALUES ('9180601', 'ORDER TEST', 'BULK_CARRIER', 50000) RETURNING id",
        {},
    )


async def _insert_voyage(
    session,
    vessel_id: str,
    no: str,
    *,
    created_at: str,
    planned_departure_at: str | None = None,
    actual_departure_at: str | None = None,
) -> str:
    return await insert_returning_id(
        session,
        "INSERT INTO voyage (vessel_id, voyage_no, status, annual_inclusion_policy, "
        " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
        " planned_departure_at, actual_departure_at, created_at) "
        "VALUES (:vid, :no, 'DRAFT', 'EXCLUDE', 'BUSAN', 'SINGAPORE', 1000, 12, "
        " :pd, :ad, :created) RETURNING id",
        {
            "vid": vessel_id,
            "no": no,
            "pd": planned_departure_at,
            "ad": actual_departure_at,
            "created": created_at,
        },
    )


@pytest_asyncio.fixture
async def vessel_id(session):
    """등록 순서(created_at)가 항해 순서와 **반대**인 여섯 항차.

    CSV로 지난 항차를 몰아 넣으면 이렇게 된다 — 가장 최근 항차가 가장 먼저 등록되는
    것이 아니다. ``NO-DATE-*`` 둘은 출항 시각이 없는 초안이다.
    """
    vid = await _insert_vessel(session)
    # 등록은 3월 항차가 가장 늦고, 출항은 3월이 가장 최근이다 — 둘이 일부러 갈린다.
    await _insert_voyage(session, vid, "NO-DATE-A", created_at="2026-01-01T00:00:00Z")
    await _insert_voyage(
        session,
        vid,
        "V-2026-03",
        created_at="2026-01-02T00:00:00Z",
        planned_departure_at="2026-03-01T00:00:00Z",
    )
    # 실제 출항이 계획보다 우선한다 — 계획은 1월이지만 실제로는 2월에 떠났다.
    await _insert_voyage(
        session,
        vid,
        "V-2026-02",
        created_at="2026-01-03T00:00:00Z",
        planned_departure_at="2026-01-10T00:00:00Z",
        actual_departure_at="2026-02-01T00:00:00Z",
    )
    await _insert_voyage(
        session,
        vid,
        "V-2026-01",
        created_at="2026-01-04T00:00:00Z",
        planned_departure_at="2026-01-05T00:00:00Z",
    )
    # 같은 출항 시각 — 등록이 늦은 쪽이 먼저다.
    await _insert_voyage(
        session,
        vid,
        "V-2026-01-B",
        created_at="2026-01-05T00:00:00Z",
        planned_departure_at="2026-01-05T00:00:00Z",
    )
    await _insert_voyage(session, vid, "NO-DATE-B", created_at="2026-01-06T00:00:00Z")
    return UUID(vid)


EXPECTED = [
    "V-2026-03",
    "V-2026-02",
    "V-2026-01-B",
    "V-2026-01",
    "NO-DATE-B",
    "NO-DATE-A",
]


@pytest.mark.asyncio
async def test_newest_departure_first_and_undated_last(session, vessel_id):
    """첫 행이 가장 최근에 떠난 항차이고, 출항 시각이 없는 초안은 맨 아래다."""
    data, _ = await list_voyages(session, vessel_id, limit=100)
    assert [row["voyage_no"] for row in data] == EXPECTED


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [1, 2, 4])
async def test_paging_one_by_one_neither_repeats_nor_skips(session, vessel_id, page_size):
    """「더 보기」로 끝까지 이어 받아도 한 번에 받은 순서와 같다.

    ``page_size=4``는 첫 페이지가 **두 묶음의 경계에서 정확히** 끝난다 — 커서가 출항
    시각 있는 마지막 행에서 초안 묶음으로 넘어가야 한다. ``1``은 모든 경계를 커서로 넘는다.
    """
    seen: list[str] = []
    cursor = None
    for _ in range(20):
        data, meta = await list_voyages(session, vessel_id, limit=page_size, cursor=cursor)
        seen.extend(row["voyage_no"] for row in data)
        cursor = meta["next_cursor"]
        if cursor is None:
            break
    assert seen == EXPECTED


@pytest.mark.asyncio
async def test_export_uses_the_same_order(session, vessel_id):
    """CSV 내보내기도 같은 순서다 — 화면 순서와 파일 순서가 갈리지 않는다."""
    rows = await voyage_repo.list_for_export(session, vessel_id=vessel_id)
    assert [row.voyage_no for row in rows] == EXPECTED


@pytest.mark.asyncio
async def test_a_cursor_from_the_old_order_is_rejected(session, vessel_id):
    """정렬이 바뀌기 전의 두 칸 커서는 422 — 다른 정렬의 위치라 이어 받으면 겹치거나 빠진다."""
    import base64

    old = base64.urlsafe_b64encode(
        b"2026-01-02T00:00:00+00:00\x0000000000-0000-0000-0000-000000000001"
    ).decode("ascii")
    with pytest.raises(ValidationError):
        await list_voyages(session, vessel_id, limit=2, cursor=old)
