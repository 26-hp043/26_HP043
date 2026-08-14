"""calculation_run needs_recalc 가드 트리거 실동작 검증 (#283, 마이그레이션 024).

024가 세운 규칙을 DB에서 직접 검증한다:

1. ``needs_recalc`` false→true 플립은 **허용** (다른 컬럼 불변 시)
2. result_json 등 다른 컬럼 UPDATE는 **여전히 거부** (immutable 유지)
3. true→false 되돌림은 **거부** (표시는 누적 전용)
4. DELETE는 **여전히 거부** (계산 이력 보존)
5. ``mark_needs_recalc`` 저장소 함수가 1번 경로로 동작

calculation_run INSERT 시 needs_recalc는 기본 false — 024의 server_default.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

VALID_HASH = "sha256:" + "d" * 64


async def _insert_vessel(conn, imo: str) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'RECALC TEST', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_calculation_run(conn, vessel_id: str) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO calculation_run "
            "(calculation_type, vessel_id, input_hash, parameter_hash, "
            " model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :ih, :ih, "
            "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb) RETURNING id"
        ),
        {"vid": vessel_id, "ih": VALID_HASH},
    )
    return str(row.scalar_one())


async def test_needs_recalc_flip_allowed(conn):
    """플립(false→true, 단일 컬럼)은 가드가 통과시킨다 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300101")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    await conn.execute(
        text("UPDATE calculation_run SET needs_recalc = true WHERE id = :id"),
        {"id": calc_id},
    )
    row = await conn.execute(
        text("SELECT needs_recalc FROM calculation_run WHERE id = :id"), {"id": calc_id}
    )
    assert row.scalar_one() is True


async def test_other_column_update_still_rejected(conn):
    """result_json 변경 UPDATE는 여전히 거부 — immutable 유지 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300202")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("UPDATE calculation_run SET duration_ms = 1 WHERE id = :id"),
            {"id": calc_id},
        )
    assert "immutable" in str(exc.value).lower()


async def test_flip_with_other_column_change_rejected(conn):
    """플립 + 다른 컬럼 동시 변경도 거부 — 플립만 통과 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300303")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = true, duration_ms = 1 WHERE id = :id"),
            {"id": calc_id},
        )


async def test_rollback_flip_rejected(conn):
    """true→false 되돌림은 거부 — 표시는 누적 전용 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300404")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    await conn.execute(
        text("UPDATE calculation_run SET needs_recalc = true WHERE id = :id"),
        {"id": calc_id},
    )
    with pytest.raises(DBAPIError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = false WHERE id = :id"),
            {"id": calc_id},
        )


async def test_delete_still_rejected(conn):
    """DELETE는 종전처럼 거부 — 계산 이력 보존 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300505")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError):
        await conn.execute(text("DELETE FROM calculation_run WHERE id = :id"), {"id": calc_id})


async def test_mark_needs_recalc_repository_flips_only_matching(conn):
    """저장소 함수 — 대상 선박의 미표시 행만 true로 (#283).

    ``conn`` fixture는 함수 단일 트랜잭션이라 트리거 위반이 나면 이후 명령이
    전부 abort된다 — 위반 케이스와 성공 케이스를 한 테스트에 섞지 않는다
    (test_db_hardening_023과 같은 교훈).
    """
    from cii_platform.db.repositories.calculation_run import mark_needs_recalc

    class _SyncExecuteAdapter:
        """conn(run_sync 호환)을 AsyncSession.execute처럼 노출한다."""

        def __init__(self, connection):
            self._conn = connection

        async def execute(self, stmt, params=None):
            return await self._conn.execute(stmt, params or {})

    vessel_id = await _insert_vessel(conn, "7300606")
    other_vessel_id = await _insert_vessel(conn, "7300707")
    await _insert_calculation_run(conn, vessel_id)
    await _insert_calculation_run(conn, vessel_id)
    await _insert_calculation_run(conn, other_vessel_id)

    marked = await mark_needs_recalc(_SyncExecuteAdapter(conn), vessel_id)
    assert marked == 2

    row = await conn.execute(
        text("SELECT count(*) FROM calculation_run WHERE vessel_id = :vid AND needs_recalc = true"),
        {"vid": vessel_id},
    )
    assert row.scalar_one() == 2
    other = await conn.execute(
        text("SELECT count(*) FROM calculation_run WHERE vessel_id = :vid AND needs_recalc = true"),
        {"vid": other_vessel_id},
    )
    assert other.scalar_one() == 0
