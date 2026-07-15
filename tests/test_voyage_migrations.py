"""이슈 #27 항차 테이블 마이그레이션 검증.

완료 기준(이슈 #27):
- alembic upgrade head 성공 (conftest migrated_db fixture로 보장)
- chk_actual_fuel_positive: 음수 actual_fuel_ton 입력 시 에러
- FK CASCADE: voyage 삭제 시 voyage_fuel_use 자동 삭제
- status × annual_inclusion_policy CHECK 제약 동작
추가:
- FK RESTRICT: 항차가 있는 vessel 물리 삭제 거부

(downgrade/upgrade 왕복(§8.1)은 전역 스키마를 변형하므로 test_zz_roundtrip.py로 격리했다. #82)
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _insert_vessel(conn, imo="1234567") -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'TEST VESSEL', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_fuel_type(conn, code="HFO") -> None:
    await conn.execute(
        text(
            "INSERT INTO fuel_type (code, display_name, cf, source_ref) "
            "VALUES (:code, 'Heavy Fuel Oil', 3.114, 'MEPC.364(79)')"
        ),
        {"code": code},
    )


async def _insert_voyage(conn, vessel_id, status="DRAFT", policy="EXCLUDE") -> str:
    row = await conn.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn) "
            "VALUES (:vid, :status, :policy, :ry, 'BUSAN', 'SINGAPORE', 1000, 12) "
            "RETURNING id"
        ),
        {
            "vid": vessel_id,
            "status": status,
            "policy": policy,
            # policy != EXCLUDE인 경우 regulation_year NOT NULL 필요 (chk_year_policy).
            "ry": None if policy == "EXCLUDE" else 2026,
        },
    )
    return str(row.scalar_one())


async def _insert_voyage_scenario(
    conn,
    vessel_id,
    *,
    distance_nm=1000,
    speed_kn=12,
    duration_hours=80,
    fuel_ton=50,
) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO voyage_scenario "
            "(vessel_id, scenario_type, scenario_name, distance_nm, speed_kn, "
            " duration_hours, fuel_ton, cii_value, estimated_rating, risk_level) "
            "VALUES (:vid, 'DIRECT', 'TEST SCENARIO', :dist, :spd, "
            " :dur, :fuel, 5.0, 'C', 'MEDIUM') "
            "RETURNING id"
        ),
        {
            "vid": vessel_id,
            "dist": distance_nm,
            "spd": speed_kn,
            "dur": duration_hours,
            "fuel": fuel_ton,
        },
    )
    return str(row.scalar_one())


@pytest.mark.asyncio
async def test_chk_actual_fuel_positive_rejects_negative(conn):
    """actual_fuel_ton 음수는 chk_actual_fuel_positive로 거부된다."""
    vessel_id = await _insert_vessel(conn)
    await _insert_fuel_type(conn)
    voyage_id = await _insert_voyage(conn, vessel_id)

    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO voyage_fuel_use "
                "(voyage_id, fuel_type, actual_fuel_ton, cf_used, source) "
                "VALUES (:vid, 'HFO', -1, 3.114, 'USER_INPUT')"
            ),
            {"vid": voyage_id},
        )


@pytest.mark.asyncio
async def test_voyage_fuel_use_cascade_delete(conn):
    """voyage 삭제 시 voyage_fuel_use가 CASCADE로 함께 삭제된다."""
    vessel_id = await _insert_vessel(conn)
    await _insert_fuel_type(conn)
    voyage_id = await _insert_voyage(conn, vessel_id)
    await conn.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, actual_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'HFO', 50, 3.114, 'USER_INPUT')"
        ),
        {"vid": voyage_id},
    )

    before = await conn.scalar(
        text("SELECT count(*) FROM voyage_fuel_use WHERE voyage_id = :vid"),
        {"vid": voyage_id},
    )
    assert before == 1

    await conn.execute(text("DELETE FROM voyage WHERE id = :vid"), {"vid": voyage_id})

    after = await conn.scalar(
        text("SELECT count(*) FROM voyage_fuel_use WHERE voyage_id = :vid"),
        {"vid": voyage_id},
    )
    assert after == 0


@pytest.mark.asyncio
async def test_status_policy_check_rejects_invalid_combo(conn):
    """DRAFT + INCLUDE_AS_PLAN 조합은 chk_status_policy로 거부된다."""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await _insert_voyage(conn, vessel_id, status="DRAFT", policy="INCLUDE_AS_PLAN")


@pytest.mark.asyncio
async def test_status_policy_check_allows_valid_combo(conn):
    """CONFIRMED + INCLUDE_AS_ACTUAL 조합은 허용된다."""
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(
        conn, vessel_id, status="CONFIRMED", policy="INCLUDE_AS_ACTUAL"
    )
    assert voyage_id


@pytest.mark.asyncio
async def test_voyage_vessel_restrict_delete(conn):
    """항차가 있는 vessel의 물리 삭제는 RESTRICT로 거부된다."""
    vessel_id = await _insert_vessel(conn)
    await _insert_voyage(conn, vessel_id)
    with pytest.raises(IntegrityError):
        await conn.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})


@pytest.mark.asyncio
async def test_fuel_type_no_action_delete(conn):
    """참조 중인 fuel_type의 물리 삭제는 거부된다 (DB_SCHEMA §7.1 ON DELETE NO ACTION).

    전제(#80 검토 보고서): ON DELETE NO ACTION은 PostgreSQL FK의 기본 동작이라
    이 테스트는 006에 ondelete를 명시하기 전/후와 무관하게 통과한다. #80 diff 자체를
    증명하는 것이 아니라, §7.1의 삭제 정책을 행위로 못박아 향후 누군가 CASCADE 등으로
    바꾸는 회귀를 막는 것이 목적이다 (형제 test_voyage_vessel_restrict_delete와 대칭).
    """
    vessel_id = await _insert_vessel(conn)
    await _insert_fuel_type(conn)
    voyage_id = await _insert_voyage(conn, vessel_id)
    await conn.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, actual_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'HFO', 50, 3.114, 'USER_INPUT')"
        ),
        {"vid": voyage_id},
    )
    with pytest.raises(IntegrityError):
        await conn.execute(text("DELETE FROM fuel_type WHERE code = 'HFO'"))


# ---------------------------------------------------------------------------
# voyage_scenario 물리량 양수 CHECK (#84)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_distance_positive_rejects_zero(conn):
    """chk_scenario_distance_positive: distance_nm = 0은 거부된다. (#84)"""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await _insert_voyage_scenario(conn, vessel_id, distance_nm=0)


@pytest.mark.asyncio
async def test_scenario_duration_positive_rejects_negative(conn):
    """chk_scenario_duration_positive: 음수 duration_hours는 거부된다. (#84)"""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await _insert_voyage_scenario(conn, vessel_id, duration_hours=-1)


@pytest.mark.asyncio
async def test_scenario_fuel_positive_rejects_zero(conn):
    """chk_scenario_fuel_positive: fuel_ton = 0은 거부된다. (#84)"""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await _insert_voyage_scenario(conn, vessel_id, fuel_ton=0)


@pytest.mark.asyncio
async def test_scenario_speed_positive_rejects_below_one(conn):
    """chk_scenario_speed_positive: speed_kn = 0.7(1.0 미만)은 거부된다. (#84)

    speed_kn 기준은 voyage(§2.2) chk_speed_positive와 통일해 >= 1.0이다. > 0이었다면
    0.7이 통과해 채택(#58) 시 voyage 쪽에서 뒤늦게 실패했을 것이다.
    """
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await _insert_voyage_scenario(conn, vessel_id, speed_kn=0.7)


@pytest.mark.asyncio
async def test_scenario_speed_boundary_allows_exactly_one(conn):
    """chk_scenario_speed_positive: 경계값 speed_kn = 1.0은 통과한다(>= 검증). (#84)

    이 정상 INSERT는 distance/duration/fuel 양수 제약의 정상 경로도 함께 커버한다.
    >= 1.0을 > 1.0으로 잘못 구현했다면 이 테스트가 실패해 off-by-one을 잡는다.
    """
    vessel_id = await _insert_vessel(conn)
    scenario_id = await _insert_voyage_scenario(conn, vessel_id, speed_kn=1.0)
    assert scenario_id
