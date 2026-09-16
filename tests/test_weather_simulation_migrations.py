"""이슈 #103 기상·시뮬레이션·감사 테이블 마이그레이션 검증 (013~015) + 완료 기준.

대상: weather_snapshot(013, + 007이 미뤄둔 voyage_scenario FK 상환),
annual_simulation_run(014), audit_log(015).

완료 기준(이슈 #103):
- `alembic upgrade head` 후 14개 테이블 존재 (본 파일에서 직접 검증)
- 각 테이블의 CHECK, FK, 인덱스가 DB_SCHEMA와 일치
- 왕복(downgrade base → upgrade head)은 test_zz_roundtrip이 커버
"""

import re
import uuid

import pytest
from conftest import insert_returning_id
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

VALID_HASH = "sha256:" + "a" * 64

# CUBRID는 FK의 ON DELETE 규칙을 카탈로그(`db_index`는 is_foreign_key까지만)로 내주지
# 않는다 — `SHOW CREATE TABLE`의 CONSTRAINT 절에서 읽는다 (#1058). 실측 형식::
#
#   CONSTRAINT [fk_voyage_scenario_weather] FOREIGN KEY  ([weather_snapshot_id])
#   REFERENCES [dba.weather_snapshot] ([id]) ON DELETE SET NULL ON UPDATE RESTRICT
_FK_ON_DELETE = re.compile(
    r"CONSTRAINT \[(?P<name>\w+)\] FOREIGN KEY .*? "
    r"ON DELETE (?P<rule>RESTRICT|SET NULL|CASCADE|NO ACTION)"
)

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
    return await insert_returning_id(
        conn,
        "INSERT INTO vessel (imo_number, name, ship_type) "
        "VALUES (:imo, 'TEST VESSEL', 'BULK_CARRIER') RETURNING id",
        {"imo": imo},
    )


async def _insert_weather_snapshot(conn) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO weather_snapshot "
        "(lat, lon, lat_rounded, lon_rounded, fetched_at, source) "
        "VALUES (35.1, 129.0, 35.0, 129.0, now(), 'sample') RETURNING id",
        {},
    )


async def _insert_scenario(conn, vessel_id, weather_snapshot_id=None) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO voyage_scenario "
        "(vessel_id, scenario_type, scenario_name, distance_nm, speed_kn, "
        " duration_hours, fuel_ton, cii_value, estimated_rating, risk_level, "
        " weather_snapshot_id) "
        "VALUES (:vid, 'DIRECT', 'TEST SCENARIO', 1000, 12, 80, 100, "
        " 5.1, 'C', 'MEDIUM', :wid) RETURNING id",
        {"vid": vessel_id, "wid": weather_snapshot_id},
    )


async def _insert_calculation_run(conn, vessel_id) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO calculation_run "
        "(calculation_type, vessel_id, input_hash, parameter_hash, "
        " model_version, result_json, parameters_used) "
        "VALUES ('ANNUAL_MONTE_CARLO', :vid, :ih, :ph, "
        " '{}', '{}', '{}') RETURNING id",
        {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
    )


async def _insert_sim_snapshot(conn, vessel_id) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO simulation_snapshot "
        "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
        "VALUES (:vid, 2026, '[]', :ih, :ph) RETURNING id",
        {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
    )


async def _insert_annual_run(
    conn, calculation_run_id, vessel_id, snapshot_id, target_rating="C", simulation_runs=1000
) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO annual_simulation_run "
        "(calculation_run_id, vessel_id, regulation_year, target_rating, "
        " simulation_runs, snapshot_id) "
        "VALUES (:cid, :vid, 2026, :tr, :runs, :sid) RETURNING id",
        {
            "cid": calculation_run_id,
            "vid": vessel_id,
            "tr": target_rating,
            "runs": simulation_runs,
            "sid": snapshot_id,
        },
    )


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
    # CUBRID의 id는 CHAR(32) hex — 대시 형식은 FK 이전에 coerce 단계에서 거부된다 (#1058).
    with pytest.raises(IntegrityError, match="fk_voyage_scenario_weather"):
        await _insert_scenario(conn, vessel_id, "0" * 32)


# --- annual_simulation_run (014) ---


async def test_annual_sim_insert_ok(conn):
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snap_id = await _insert_sim_snapshot(conn, vessel_id)
    await _insert_annual_run(conn, calc_id, vessel_id, snap_id)


async def test_annual_sim_rejects_rating_e(conn):
    # 케이스 DB-CHK-005 (`TEST_PLAN §5.1`)
    # [M-4]: 목표 등급 E 불가.
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    snap_id = await _insert_sim_snapshot(conn, vessel_id)
    with pytest.raises(IntegrityError, match="chk_target_rating"):
        await _insert_annual_run(conn, calc_id, vessel_id, snap_id, target_rating="E")


async def test_annual_sim_rejects_zero_runs(conn):
    # 케이스 DB-CHK-006 (`TEST_PLAN §5.1`)
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
    """§7.1 [DB-C-3]: 010~015에서 생긴 FK의 ON DELETE 정책이 정본과 일치하는지 카탈로그로 검증.

    🔴 ``fk_annual_simulation_run_snapshot``은 **이 목록에 없다** (`#1058` · `050`).
    CUBRID가 FK 컬럼에 인덱스를 또 두는 것을 거부해 `[S-6]`의 1:1(유니크 인덱스)을 세울 수
    없었고, 사용자가 「FK를 빼고 UNIQUE + 트리거」를 골랐다(결정요청 §0-3⑵).

    **커버리지를 줄인 것이 아니다** — 아래 형제 검사가 그 FK가 하던 일을 양쪽에서 본다.
    """
    expected = {
        "fk_voyage_scenario_weather": "SET NULL",
        "fk_annual_simulation_run_calculation_run": "RESTRICT",
        "fk_annual_simulation_run_vessel": "RESTRICT",
    }
    rules: dict[str, str] = {}
    for table in ("voyage_scenario", "annual_simulation_run"):
        ddl = (await conn.execute(text(f"SHOW CREATE TABLE {table}"))).one()[1]
        for m in _FK_ON_DELETE.finditer(ddl):
            rules[m.group("name")] = m.group("rule")
    assert {name: rules.get(name) for name in expected} == expected
    # 뺀 FK가 정말 없는지도 고정한다 — 누군가 되살리면 `CREATE UNIQUE INDEX`가 다음
    # 마이그레이션에서 `errno=-272`로 서고, 그 이유를 여기서 읽을 수 있어야 한다.
    assert "fk_annual_simulation_run_snapshot" not in rules


async def test_the_dropped_snapshot_fk_still_blocks_a_missing_snapshot(conn):
    """FK의 **자식 쪽**(없는 스냅샷을 가리키지 못함)을 트리거가 대신한다 (`050`)."""
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    # 저장 형식은 CHAR(32) hex다 — 대시 형식을 보내면 트리거에 닿기 전에
    # `Cannot coerce … to type char`로 선다(`#1058`).
    with pytest.raises(IntegrityError, match="trg_annual_sim_snapshot_ref"):
        await _insert_annual_run(conn, calc_id, vessel_id, uuid.uuid4().hex)


async def test_the_dropped_snapshot_fk_parent_side_is_already_stronger(conn):
    """FK의 **부모 쪽**(``ON DELETE RESTRICT``)은 이미 더 강하게 막혀 있다 (`a7d3e9b14f26`).

    ``trg_snapshot_no_delete``가 ``simulation_snapshot``의 DELETE를 **전면** 거부하므로,
    참조하는 행이 없어도 못 지운다 — FK의 RESTRICT가 하던 일을 포함한다. 그래서 FK를
    빼도 부모 쪽에서 잃는 것이 없다.
    """
    vessel_id = await _insert_vessel(conn)
    snap_id = await _insert_sim_snapshot(conn, vessel_id)
    # 아무도 참조하지 않는 스냅샷인데도 지워지지 않는다.
    with pytest.raises(DBAPIError, match="trg_snapshot_no_delete"):
        await conn.execute(
            text("DELETE FROM simulation_snapshot WHERE id = :sid"), {"sid": snap_id}
        )


# --- audit_log (015) ---


async def test_audit_log_insert_ok(conn):
    # action 외 전부 NULL 허용 (§2.14). timestamp는 DEFAULT로 채워진다.
    # CUBRID에는 gen_random_uuid()도 RETURNING도 없다 — id·entity_id는 파이썬에서
    # 만들어 넣고(CHAR(32) hex), 되읽어 확인한다 (#1058).
    audit_id = uuid.uuid4().hex
    await conn.execute(
        text(
            'INSERT INTO audit_log (id, "action", entity_type, entity_id, details_json) '
            "VALUES (:id, 'CALCULATION_RUN', 'calculation_run', :eid, '{}')"
        ),
        {"id": audit_id, "eid": uuid.uuid4().hex},
    )
    row = await conn.execute(
        text('SELECT id, "timestamp" FROM audit_log WHERE id = :id'), {"id": audit_id}
    )
    rec = row.one()
    assert rec.id == audit_id
    assert rec.timestamp is not None


async def test_audit_log_minimal_insert_ok(conn):
    await conn.execute(text("INSERT INTO audit_log (\"action\") VALUES ('IMPORT')"))


# --- 완료 기준 (#103) ---


async def test_all_14_tables_present(conn):
    # CUBRID 카탈로그 `db_class` — 사용자 테이블은 is_system_class = 'NO', class_type = 'CLASS'.
    rows = await conn.execute(
        text(
            "SELECT class_name FROM db_class WHERE is_system_class = 'NO' AND class_type = 'CLASS'"
        )
    )
    tables = {r[0] for r in rows.all()}
    assert tables >= EXPECTED_TABLES


async def test_expected_new_indexes_present(conn):
    # CUBRID 카탈로그 `db_index` (#1058).
    rows = await conn.execute(text("SELECT index_name FROM db_index"))
    indexes = {r[0] for r in rows.all()}
    assert indexes >= EXPECTED_NEW_INDEXES
