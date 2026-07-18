"""이슈 #103 기상·시뮬레이션·감사 테이블 마이그레이션 검증 (013~015) + 완료 기준.

대상: weather_snapshot(013, + 007이 미뤄둔 voyage_scenario FK 상환),
annual_simulation_run(014), audit_log(015).

완료 기준(이슈 #103):
- `alembic upgrade head` 후 14개 테이블 존재 (본 파일에서 직접 검증)
- 각 테이블의 CHECK, FK, 인덱스가 DB_SCHEMA와 일치
- 왕복(downgrade base → upgrade head)은 test_zz_roundtrip이 커버
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

VALID_HASH = "sha256:" + "a" * 64

# DB_SCHEMA §2 정본 테이블 14개 (pg_trgm은 확장이라 제외).
EXPECTED_TABLES = {
    "vessel",
    "voyage",
    "voyage_fuel_use",
    "voyage_scenario",
    "calculation_run",
    "annual_simulation_run",
    "simulation_snapshot",
    "regulation_year",
    "fuel_type",
    "cii_reference_line",
    "cii_rating_boundary",
    "weather_model_parameter",
    "weather_snapshot",
    "audit_log",
}

# 010~015가 생성하는 인덱스 (DB_SCHEMA §2.6, §2.10~§2.14 원문 그대로).
EXPECTED_NEW_INDEXES = {
    "idx_refline_unique",
    "idx_refline_ship_type",
    "idx_boundary_unique",
    "idx_weather_param_unique",
    "idx_weather_cache",
    "idx_sim_snapshot_unique",
    "idx_audit_timestamp",
    "idx_audit_entity",
    "idx_audit_action",
}


async def _insert_vessel(conn, imo="7654321") -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'TEST VESSEL', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_weather_snapshot(conn) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO weather_snapshot "
            "(lat, lon, lat_rounded, lon_rounded, fetched_at, source) "
            "VALUES (35.1, 129.0, 35.0, 129.0, now(), 'sample') RETURNING id"
        )
    )
    return str(row.scalar_one())


async def _insert_scenario(conn, vessel_id, weather_snapshot_id=None) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO voyage_scenario "
            "(vessel_id, scenario_type, scenario_name, distance_nm, speed_kn, "
            " duration_hours, fuel_ton, cii_value, estimated_rating, risk_level, "
            " weather_snapshot_id) "
            "VALUES (:vid, 'DIRECT', 'TEST SCENARIO', 1000, 12, 80, 100, "
            " 5.1, 'C', 'MEDIUM', :wid) RETURNING id"
        ),
        {"vid": vessel_id, "wid": weather_snapshot_id},
    )
    return str(row.scalar_one())


async def _insert_calculation_run(conn, vessel_id) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO calculation_run "
            "(calculation_type, vessel_id, input_hash, parameter_hash, "
            " model_version, result_json, parameters_used) "
            "VALUES ('ANNUAL_MONTE_CARLO', :vid, :ih, :ph, "
            " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb) RETURNING id"
        ),
        {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
    )
    return str(row.scalar_one())


async def _insert_sim_snapshot(conn, vessel_id) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO simulation_snapshot "
            "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
            "VALUES (:vid, 2026, '[]'::jsonb, :ih, :ph) RETURNING id"
        ),
        {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
    )
    return str(row.scalar_one())


async def _insert_annual_run(
    conn, calculation_run_id, vessel_id, snapshot_id, target_rating="C", simulation_runs=1000
) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO annual_simulation_run "
            "(calculation_run_id, vessel_id, regulation_year, target_rating, "
            " simulation_runs, snapshot_id) "
            "VALUES (:cid, :vid, 2026, :tr, :runs, :sid) RETURNING id"
        ),
        {
            "cid": calculation_run_id,
            "vid": vessel_id,
            "tr": target_rating,
            "runs": simulation_runs,
            "sid": snapshot_id,
        },
    )
    return str(row.scalar_one())


# --- weather_snapshot (013) ---


async def test_weather_snapshot_insert_ok(conn):
    await _insert_weather_snapshot(conn)


async def test_scenario_weather_fk_set_null_on_delete(conn):
    # 007이 미뤄둔 fk_voyage_scenario_weather 상환 검증: 스냅샷 삭제 시 시나리오 보존,
    # 포인터만 NULL (§7.1 SET NULL).
    vessel_id = await _insert_vessel(conn)
    snapshot_id = await _insert_weather_snapshot(conn)
    scenario_id = await _insert_scenario(conn, vessel_id, snapshot_id)

    await conn.execute(text("DELETE FROM weather_snapshot WHERE id = :sid"), {"sid": snapshot_id})
    row = await conn.execute(
        text("SELECT weather_snapshot_id FROM voyage_scenario WHERE id = :id"),
        {"id": scenario_id},
    )
    assert row.scalar_one() is None


async def test_scenario_weather_fk_rejects_unknown_snapshot(conn):
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError, match="fk_voyage_scenario_weather"):
        await _insert_scenario(conn, vessel_id, "00000000-0000-0000-0000-000000000000")


# --- annual_simulation_run (014) ---


async def test_annual_sim_insert_ok(conn):
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snap_id = await _insert_sim_snapshot(conn, vessel_id)
    await _insert_annual_run(conn, calc_id, vessel_id, snap_id)


async def test_annual_sim_rejects_rating_e(conn):
    # [M-4]: 목표 등급 E 불가.
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snap_id = await _insert_sim_snapshot(conn, vessel_id)
    with pytest.raises(IntegrityError, match="chk_target_rating"):
        await _insert_annual_run(conn, calc_id, vessel_id, snap_id, target_rating="E")


async def test_annual_sim_rejects_zero_runs(conn):
    # [M-5]: simulation_runs > 0.
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snap_id = await _insert_sim_snapshot(conn, vessel_id)
    with pytest.raises(IntegrityError, match="chk_sim_runs_positive"):
        await _insert_annual_run(conn, calc_id, vessel_id, snap_id, simulation_runs=0)


async def test_annual_sim_snapshot_unique_one_to_one(conn):
    # [S-6]: 1스냅샷 = 1시뮬레이션.
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snap_id = await _insert_sim_snapshot(conn, vessel_id)
    await _insert_annual_run(conn, calc_id, vessel_id, snap_id)
    with pytest.raises(IntegrityError, match="idx_sim_snapshot_unique"):
        await _insert_annual_run(conn, calc_id, vessel_id, snap_id)


async def test_new_fk_delete_rules_match_schema(conn):
    # §7.1 [DB-C-3]: 010~015에서 생긴 FK의 ON DELETE 정책이 정본과 일치하는지 카탈로그로 검증.
    rows = await conn.execute(
        text(
            "SELECT conname, "
            "  CASE confdeltype WHEN 'r' THEN 'RESTRICT' WHEN 'n' THEN 'SET NULL' END "
            "FROM pg_constraint WHERE contype = 'f' AND conname IN "
            "('fk_voyage_scenario_weather', 'fk_annual_simulation_run_calculation_run', "
            " 'fk_annual_simulation_run_vessel', 'fk_annual_simulation_run_snapshot')"
        )
    )
    rules = dict(rows.all())
    assert rules == {
        "fk_voyage_scenario_weather": "SET NULL",
        "fk_annual_simulation_run_calculation_run": "RESTRICT",
        "fk_annual_simulation_run_vessel": "RESTRICT",
        "fk_annual_simulation_run_snapshot": "RESTRICT",
    }


# --- audit_log (015) ---


async def test_audit_log_insert_ok(conn):
    # action 외 전부 NULL 허용 (§2.14). id·timestamp는 DEFAULT로 채워진다.
    row = await conn.execute(
        text(
            "INSERT INTO audit_log (action, entity_type, entity_id, details_json) "
            "VALUES ('CALCULATION_RUN', 'calculation_run', gen_random_uuid(), "
            " '{}'::jsonb) RETURNING id, \"timestamp\""
        )
    )
    rec = row.one()
    assert rec.id is not None
    assert rec.timestamp is not None


async def test_audit_log_minimal_insert_ok(conn):
    await conn.execute(text("INSERT INTO audit_log (action) VALUES ('IMPORT')"))


# --- 완료 기준 (#103) ---


async def test_all_14_tables_present(conn):
    rows = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
    )
    tables = {r[0] for r in rows.all()}
    assert tables >= EXPECTED_TABLES


async def test_expected_new_indexes_present(conn):
    rows = await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
    indexes = {r[0] for r in rows.all()}
    assert indexes >= EXPECTED_NEW_INDEXES
