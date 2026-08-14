"""annual_simulation_run FK RESTRICT 실동작 검증 (#117 갭 3).

기존 ``test_weather_simulation_migrations``는 ``pg_constraint`` 카탈로그 조회로 FK
정책을 간접 확인했다 — 여기는 **부모 행 물리 DELETE가 실제 ``IntegrityError``로
거부되는지** 직접 검증한다.

``calculation_run``·``simulation_snapshot``의 DELETE는 immutable 트리거가 FK 체크보다
먼저 막는다 — RESTRICT 경로의 직접 검증은 ``vessel`` DELETE가 담당한다
(``fk_annual_simulation_run_vessel`` ON DELETE RESTRICT).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

VALID_HASH = "sha256:" + "c" * 64


async def _insert_vessel(conn, imo: str) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'RESTRICT TEST', 'BULK_CARRIER') RETURNING id"
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


async def _insert_sim_snapshot(conn, vessel_id: str) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO simulation_snapshot "
            "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
            "VALUES (:vid, 2026, '[]'::jsonb, :ih, :ih) RETURNING id"
        ),
        {"vid": vessel_id, "ih": VALID_HASH},
    )
    return str(row.scalar_one())


async def _insert_annual_run(conn, calc_id: str, vessel_id: str, snapshot_id: str) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO annual_simulation_run "
            "(calculation_run_id, vessel_id, regulation_year, target_rating, "
            " simulation_runs, snapshot_id) "
            "VALUES (:cid, :vid, 2026, 'C', 1000, :sid) RETURNING id"
        ),
        {"cid": calc_id, "vid": vessel_id, "sid": snapshot_id},
    )
    return str(row.scalar_one())


async def test_vessel_delete_restricted_by_annual_run(conn):
    """annual_simulation_run이 참조하는 vessel 물리 DELETE → IntegrityError (#117)."""
    vessel_id = await _insert_vessel(conn, "7200101")
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snapshot_id = await _insert_sim_snapshot(conn, vessel_id)
    await _insert_annual_run(conn, calc_id, vessel_id, snapshot_id)

    with pytest.raises(IntegrityError):
        await conn.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})


async def test_annual_run_insert_ok(conn):
    """대조군 — 참조가 온전한 INSERT는 성공 (#117)."""
    vessel_id = await _insert_vessel(conn, "7200202")
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snapshot_id = await _insert_sim_snapshot(conn, vessel_id)
    annual_id = await _insert_annual_run(conn, calc_id, vessel_id, snapshot_id)
    assert annual_id
