"""이슈 #28 계산 결과 테이블 마이그레이션 검증.

대상: calculation_run(008), simulation_snapshot(009) — 둘 다 immutable.
추가 대상: calculation_run.weather_snapshot_id 컬럼·FK·자식 인덱스(016, 이슈 #115) —
파일 하단 "calculation_run.weather_snapshot_id" 섹션.

완료 기준(이슈 #28):
- immutable 트리거: UPDATE / DELETE 시 에러 발생 (calculation_run, simulation_snapshot)
- INSERT는 정상 동작
- hash 형식 CHECK 위반(sha256: + 64 hex 아님) 거부
- upgrade → downgrade → 재upgrade 왕복 (§8.1 롤백 안전성)

추가(설계 결정 증명):
- voyage_id FK를 ON DELETE RESTRICT로 구현했으므로, calculation_run이 딸린 voyage의
  물리 DELETE가 거부됨을 검증한다. (정본의 SET NULL × immutable 트리거 모순을 RESTRICT로
  해소한 결정의 근거를 코드로 고정한다.)
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

# sha256: + 64 hex — CHECK를 통과하는 유효 해시.
VALID_HASH = "sha256:" + "a" * 64


async def _insert_vessel(conn, imo="7654321") -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'TEST VESSEL', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_voyage(conn, vessel_id) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn) "
            "VALUES (:vid, 'DRAFT', 'EXCLUDE', 'BUSAN', 'SINGAPORE', 1000, 12) "
            "RETURNING id"
        ),
        {"vid": vessel_id},
    )
    return str(row.scalar_one())


async def _insert_calculation_run(conn, vessel_id, voyage_id=None, weather_snapshot_id=None) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO calculation_run "
            "(calculation_type, vessel_id, voyage_id, weather_snapshot_id, "
            " input_hash, parameter_hash, model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :voy, :wid, :ih, :ph, "
            " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb) "
            "RETURNING id"
        ),
        {
            "vid": vessel_id,
            "voy": voyage_id,
            "wid": weather_snapshot_id,
            "ih": VALID_HASH,
            "ph": VALID_HASH,
        },
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


async def _insert_simulation_snapshot(conn, vessel_id) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO simulation_snapshot "
            "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
            "VALUES (:vid, 2026, '[]'::jsonb, :ih, :ph) "
            "RETURNING id"
        ),
        {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
    )
    return str(row.scalar_one())


# ---------------------------------------------------------------------------
# calculation_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculation_run_insert_ok(conn):
    """유효한 calculation_run INSERT는 정상 동작한다."""
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    assert calc_id


@pytest.mark.asyncio
async def test_calculation_run_update_rejected(conn):
    """immutable 트리거: calculation_run UPDATE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("UPDATE calculation_run SET calculation_type = 'SCENARIO' WHERE id = :id"),
            {"id": calc_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_calculation_run_delete_rejected(conn):
    """immutable 트리거: calculation_run DELETE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("DELETE FROM calculation_run WHERE id = :id"),
            {"id": calc_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_calculation_run_hash_check_rejects_bad_format(conn):
    """chk_input_hash_format: sha256: + 64 hex 형식이 아니면 거부된다."""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO calculation_run "
                "(calculation_type, vessel_id, input_hash, parameter_hash, "
                " model_version, result_json, parameters_used) "
                "VALUES ('VOYAGE_ESTIMATE', :vid, 'not-a-hash', :ph, "
                " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"vid": vessel_id, "ph": VALID_HASH},
        )


@pytest.mark.asyncio
async def test_calculation_type_check_rejects_invalid(conn):
    """chk_calculation_type: 4개 허용값 외 calculation_type은 거부된다. (#84)

    허용값: VOYAGE_ESTIMATE, SCENARIO, ANNUAL_DETERMINISTIC, ANNUAL_MONTE_CARLO.
    (정상 INSERT는 test_calculation_run_insert_ok가 VOYAGE_ESTIMATE로 커버한다.)
    """
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO calculation_run "
                "(calculation_type, vessel_id, input_hash, parameter_hash, "
                " model_version, result_json, parameters_used) "
                "VALUES ('INVALID_TYPE', :vid, :ih, :ph, "
                " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
        )


@pytest.mark.asyncio
async def test_voyage_restrict_delete_with_calculation_run(conn):
    """[이번 RESTRICT 결정의 근거 증명]

    calculation_run이 딸린 voyage의 물리 DELETE는 ON DELETE RESTRICT로 거부된다.
    (정본의 SET NULL이었다면 자식 UPDATE→immutable 트리거로 롤백되어 마찬가지로 실패하나,
     RESTRICT는 FK 위반으로 깔끔히 거부되며 계산 이력을 그대로 보존한다.)
    """
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id)
    await _insert_calculation_run(conn, vessel_id, voyage_id=voyage_id)

    with pytest.raises(IntegrityError):
        await conn.execute(text("DELETE FROM voyage WHERE id = :vid"), {"vid": voyage_id})


# ---------------------------------------------------------------------------
# calculation_run.weather_snapshot_id (016, #115)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calc_run_weather_snapshot_id_defaults_null(conn):
    """weather_snapshot_id는 NULL을 허용한다.

    §2.5 [#102]: weather_model = NONE·캐시 만료 fallback(TECH_SPEC §7.3)은 스냅샷 없이
    계산하는 정상 경로이므로 NULL이 유효한 상태다.
    """
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)

    row = await conn.execute(
        text("SELECT weather_snapshot_id FROM calculation_run WHERE id = :cid"),
        {"cid": calc_id},
    )
    assert row.scalar_one() is None


@pytest.mark.asyncio
async def test_calc_run_references_weather_snapshot(conn):
    """weather_snapshot을 참조하는 calculation_run INSERT는 정상 동작한다."""
    vessel_id = await _insert_vessel(conn)
    snapshot_id = await _insert_weather_snapshot(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id, weather_snapshot_id=snapshot_id)

    row = await conn.execute(
        text("SELECT weather_snapshot_id FROM calculation_run WHERE id = :cid"),
        {"cid": calc_id},
    )
    assert str(row.scalar_one()) == snapshot_id


@pytest.mark.asyncio
async def test_weather_snapshot_restrict_delete_when_referenced(conn):
    """[이슈 #115 완료 기준] 참조된 weather_snapshot의 DELETE는 RESTRICT로 거부된다.

    §2.13 [#102]: 참조된 스냅샷은 TTL 경과와 무관하게 보존되어야 재현성 계약
    (TECH_SPEC §5.4)의 추적성이 성립한다. calculation_run은 immutable(§7.3)이라
    SET NULL(자식 UPDATE)이 트리거에 차단되므로 §7.1이 RESTRICT를 지정한다.
    """
    vessel_id = await _insert_vessel(conn)
    snapshot_id = await _insert_weather_snapshot(conn)
    await _insert_calculation_run(conn, vessel_id, weather_snapshot_id=snapshot_id)

    with pytest.raises(IntegrityError):
        await conn.execute(
            text("DELETE FROM weather_snapshot WHERE id = :sid"), {"sid": snapshot_id}
        )


@pytest.mark.asyncio
async def test_weather_snapshot_delete_ok_when_unreferenced(conn):
    """참조되지 않은 weather_snapshot은 삭제된다 (eviction 정상 경로).

    이 테스트는 016 diff 자체를 증명하는 것이 아니라(FK 추가 전에도 삭제는 성공했다),
    §2.13 [#102]의 "캐시 정리 작업은 참조되지 않는 행만 삭제해야 한다"는 운영 규칙이
    실제로 열려 있음을 행위로 못박아, 향후 누군가 FK를 NOT NULL로 바꾸거나 정책을
    조이는 회귀를 막는 것이 목적이다. RESTRICT가 과잉 차단하지 않음을 함께 보인다.
    (형제 test_weather_snapshot_restrict_delete_when_referenced와 대칭.)
    """
    snapshot_id = await _insert_weather_snapshot(conn)

    await conn.execute(text("DELETE FROM weather_snapshot WHERE id = :sid"), {"sid": snapshot_id})

    row = await conn.execute(
        text("SELECT count(*) FROM weather_snapshot WHERE id = :sid"), {"sid": snapshot_id}
    )
    assert row.scalar_one() == 0


# ---------------------------------------------------------------------------
# simulation_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulation_snapshot_insert_ok(conn):
    """유효한 simulation_snapshot INSERT는 정상 동작한다."""
    vessel_id = await _insert_vessel(conn)
    snap_id = await _insert_simulation_snapshot(conn, vessel_id)
    assert snap_id


@pytest.mark.asyncio
async def test_simulation_snapshot_update_rejected(conn):
    """immutable 트리거: simulation_snapshot UPDATE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    snap_id = await _insert_simulation_snapshot(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("UPDATE simulation_snapshot SET regulation_year = 2027 WHERE id = :id"),
            {"id": snap_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_simulation_snapshot_delete_rejected(conn):
    """immutable 트리거: simulation_snapshot DELETE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    snap_id = await _insert_simulation_snapshot(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("DELETE FROM simulation_snapshot WHERE id = :id"),
            {"id": snap_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_simulation_snapshot_hash_check_rejects_bad_format(conn):
    """chk_snap_param_hash_format: sha256: + 64 hex 형식이 아니면 거부된다."""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO simulation_snapshot "
                "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
                "VALUES (:vid, 2026, '[]'::jsonb, :ih, 'sha256:short')"
            ),
            {"vid": vessel_id, "ih": VALID_HASH},
        )


# (downgrade/upgrade 왕복 및 partial-downgrade immutability 검증은 전역 스키마를
#  변형하므로 test_zz_roundtrip.py로 격리했다. #82)
