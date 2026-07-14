"""이슈 #27 항차 테이블 마이그레이션 검증.

완료 기준(이슈 #27):
- alembic upgrade head 성공 (conftest migrated_db fixture로 보장)
- chk_actual_fuel_positive: 음수 actual_fuel_ton 입력 시 에러
- FK CASCADE: voyage 삭제 시 voyage_fuel_use 자동 삭제
- status × annual_inclusion_policy CHECK 제약 동작
추가:
- FK RESTRICT: 항차가 있는 vessel 물리 삭제 거부
- downgrade/upgrade 왕복 (§8.1 롤백 안전성)
"""

import pytest
from conftest import run_alembic
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


def test_downgrade_upgrade_roundtrip():
    """downgrade base → upgrade head 왕복이 성공한다 (§8.1 롤백 안전성)."""
    down = run_alembic("downgrade", "base")
    assert down.returncode == 0, f"{down.stdout}\n{down.stderr}"
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"
