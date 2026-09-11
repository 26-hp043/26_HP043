"""DB CHECK 제약 케이스 중 **다른 파일이 덮지 않던 것** (`TEST_PLAN §5.1` · #758).

`DB-CHK-*` 케이스 26개는 케이스 ID 가드(`test_case_id_sync.py`)의 정규식에 걸리지 않아
**있는지 없는지조차 보이지 않았다** — 소문자 접미(`001a`)와 `DB-` 접두를 못 잡았다.
가드를 넓히며 대조해 보니 11개는 이미 다른 파일이 같은 입력으로 검증하고 있었고(그 파일
docstring에 ID를 달았다), **나머지 15개는 제약은 있는데 검사가 없었다.** 그 15개다.

각 검사는 **제약 하나를 정확히 한 번 어기는 INSERT**다. 다른 제약에 먼저 걸리면 엉뚱한
이유로 통과하므로, 어긴 제약의 이름을 오류 문자열에서 확인한다.

케이스: DB-CHK-001a · DB-CHK-001b · DB-CHK-001c · DB-CHK-001d · DB-CHK-001e ·
DB-CHK-002 · DB-CHK-007 · DB-CHK-009 · DB-CHK-010 · DB-CHK-011 · DB-CHK-015 ·
DB-CHK-016 · DB-CHK-017 · DB-CHK-018 · DB-CHK-021 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _vessel(conn, **over) -> str:
    values = {"imo": "7654321", "gt": None, "dwt": None, **over}
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight) "
            "VALUES (:imo, 'CHECK CASE', 'BULK_CARRIER', :gt, :dwt) RETURNING id"
        ),
        values,
    )
    return str(row.scalar_one())


async def _voyage(conn, vessel_id: str, **over) -> None:
    values = {
        "vid": vessel_id,
        "status": "DRAFT",
        "policy": "EXCLUDE",
        "year": None,
        "arr_lat": None,
        **over,
    }
    await conn.execute(
        text(
            "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
            " arrival_lat, arrival_lon) "
            "VALUES (:vid, :status, :policy, :year, 'BUSAN', 'SINGAPORE', 1000, 12, "
            " :arr_lat, CASE WHEN CAST(:arr_lat AS numeric) IS NULL THEN NULL ELSE 0 END)"
        ),
        values,
    )


async def _expect(constraint: str, statement) -> None:
    """``statement``가 **그 제약으로** 거부되는지 본다."""
    with pytest.raises(IntegrityError) as exc:
        await statement
    assert constraint in str(exc.value), f"{constraint}가 아닌 이유로 거부됐다: {exc.value}"


# ─── voyage — 상태 × 집계 정책 (DB-CHK-001a~001e · ORACLE-S-3) ────────────────
#
# `DB-CHK-001`(DRAFT + INCLUDE_AS_PLAN)은 `test_voyage_migrations.py`가 본다. 나머지
# 무효 조합 다섯이 없어 **매트릭스의 1/6만** 검증되고 있었다.


@pytest.mark.parametrize(
    ("status", "policy", "year"),
    [
        ("DRAFT", "INCLUDE_AS_ACTUAL", 2026),  # DB-CHK-001a
        ("CANCELLED", "INCLUDE_AS_PLAN", 2026),  # DB-CHK-001b
        ("ARCHIVED", "INCLUDE_AS_ACTUAL", 2026),  # DB-CHK-001c
        ("COMPLETED", "INCLUDE_AS_PLAN", 2026),  # DB-CHK-001d
        ("PLANNED", "INCLUDE_AS_ACTUAL", 2026),  # DB-CHK-001e
    ],
)
async def test_status_policy_rejects_the_other_invalid_combinations(conn, status, policy, year):
    vessel_id = await _vessel(conn)
    await _expect(
        "chk_status_policy",
        _voyage(conn, vessel_id, status=status, policy=policy, year=year),
    )


# ─── voyage — 그 밖 ───────────────────────────────────────────────────────────


async def test_regulation_year_is_bounded(conn):
    """DB-CHK-002 — 2051년은 규제연도 범위(2019~2050) 밖이다."""
    vessel_id = await _vessel(conn)
    await _expect("chk_regulation_year_range", _voyage(conn, vessel_id, year=2051))


async def test_arrival_latitude_is_bounded(conn):
    """DB-CHK-007 — 도착 위도 999는 범위 밖이다."""
    vessel_id = await _vessel(conn)
    await _expect("chk_arr_lat_range", _voyage(conn, vessel_id, arr_lat=999))


async def test_included_voyage_needs_a_regulation_year(conn):
    """DB-CHK-021 — 집계에 넣는 항차(EXCLUDE가 아닌 것)는 규제연도가 있어야 한다."""
    vessel_id = await _vessel(conn)
    await _expect(
        "chk_year_policy",
        _voyage(conn, vessel_id, status="PLANNED", policy="INCLUDE_AS_PLAN", year=None),
    )


# ─── vessel ──────────────────────────────────────────────────────────────────


async def test_imo_number_must_be_seven_digits(conn):
    """DB-CHK-009 — 6자리 IMO 번호는 거부된다."""
    await _expect("chk_imo_format", _vessel(conn, imo="12345"))


async def test_gross_tonnage_must_be_positive(conn):
    """DB-CHK-010 — 총톤수 0은 거부된다(NULL은 「미입력」이라 허용)."""
    await _expect("chk_gt_positive", _vessel(conn, gt=0))


async def test_deadweight_must_be_positive(conn):
    """DB-CHK-011 — 재화중량톤수 음수는 거부된다."""
    await _expect("chk_dwt_positive", _vessel(conn, dwt=-1))


# ─── voyage_fuel_use ─────────────────────────────────────────────────────────


async def test_fuel_source_is_an_enum(conn):
    """DB-CHK-015 — 연료 출처는 정해진 네 값 중 하나다."""
    vessel_id = await _vessel(conn)
    row = await conn.execute(
        text(
            "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn) "
            "VALUES (:vid, 'DRAFT', 'EXCLUDE', 'BUSAN', 'SINGAPORE', 1000, 12) RETURNING id"
        ),
        {"vid": vessel_id},
    )
    voyage_id = row.scalar_one()
    await _expect(
        "chk_fuel_source",
        conn.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
                " cf_used, source) VALUES (:v, 'HFO', 10, 3.114, 'GUESS')"
            ),
            {"v": voyage_id},
        ),
    )


# ─── voyage_scenario — 열거값 (DB-CHK-016~018) ──────────────────────────────


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("scenario_type", "FAST", "chk_scenario_type"),  # DB-CHK-016
        ("estimated_rating", "F", "chk_scenario_rating"),  # DB-CHK-017
        ("risk_level", "EXTREME", "chk_scenario_risk"),  # DB-CHK-018
    ],
)
async def test_scenario_enums_are_closed(conn, column, value, constraint):
    vessel_id = await _vessel(conn)
    values = {
        "scenario_type": "DIRECT",
        "estimated_rating": "C",
        "risk_level": "MEDIUM",
        column: value,
    }
    await _expect(
        constraint,
        conn.execute(
            text(
                "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, "
                " distance_nm, speed_kn, duration_hours, fuel_ton, cii_value, "
                " estimated_rating, risk_level) "
                "VALUES (:vid, :scenario_type, 'CASE', 1000, 12, 80, 50, 5.0, "
                " :estimated_rating, :risk_level)"
            ),
            {"vid": vessel_id, **values},
        ),
    )
