"""연도별 CII 이력의 **연료축** (#769) — `PRD §21` 「통계 분석」.

케이스: IT-FUEL-001 ~ IT-FUEL-006 (`TEST_PLAN §3.14`)

``tests/test_cii_history.py``가 보는 것은 **창·상태 구분**이고, 여기가 보는 것은
연도 행 안의 ``fuels`` 배열이다. 둘을 한 파일에 두면 창 규칙을 고치는 사람과 연료
집계를 고치는 사람이 같은 파일에서 부딪힌다.

이 축이 답해야 하는 질문은 하나다 — **어느 연료가 이 배의 등급을 끌고 있나.**
그래서 비중을 **CO₂ 기준**으로 낸다. 톤 기준으로 내면 CF가 낮은 연료를 많이 쓴
해가 실제보다 나빠 보인다(``PRD §8.3`` CF 표 — LNG 2.75 vs HFO 3.114).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.cii_history import list_cii_history

AS_OF = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)

HFO_CF = Decimal("3.114")
LNG_CF = Decimal("2.750")
#: CF가 개정된 뒤에 들어온 같은 유종의 두 번째 snapshot (`#863`).
HFO_CF_OLD = Decimal("3.100")


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _ensure_params(session, *years: int) -> None:
    """규정 파라미터를 멱등하게 심는다 (``test_cii_history``와 같은 방식)."""
    for year in years:
        await session.execute(
            text(
                "INSERT INTO regulation_year "
                "(year, z_factor_percent, effective_from, source_ref, version) "
                f"SELECT {year}, 11.0, '{year}-01-01', 'TEST', '1.0' "
                f"WHERE NOT EXISTS (SELECT 1 FROM regulation_year WHERE year = {year})"
            )
        )
    await session.execute(
        text(
            "INSERT INTO cii_reference_line "
            "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', '4745', 4745, 0.622, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_reference_line WHERE ship_type = 'BULK_CARRIER')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_rating_boundary "
            "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', 0.86, 0.94, 1.06, 1.18, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_rating_boundary WHERE ship_type = 'BULK_CARRIER')"
        )
    )


async def _insert_vessel(session, imo: str) -> str:
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight) "
            f"VALUES ('{imo}', 'FUEL AXIS TEST', 'BULK_CARRIER', 30000, 50000) RETURNING id"
        )
    )
    return str(row.scalar_one())


async def _insert_voyage(
    session,
    vessel_id: str,
    *,
    year: int,
    distance: str,
    fuels: list[tuple[str, str, Decimal]],
) -> None:
    """``fuels``는 ``(유종, 톤, CF snapshot)`` 목록 — 한 항차에 여러 유종을 넣는다."""
    voyage = await session.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, "
            " actual_distance_nm, planned_speed_kn, actual_avg_speed_kn) "
            f"VALUES ('{vessel_id}'::uuid, 'COMPLETED', 'INCLUDE_AS_ACTUAL', {year}, "
            f"'BUSAN', 'SINGAPORE', {distance}, {distance}, 12.0, 11.5) RETURNING id"
        )
    )
    voyage_id = voyage.scalar_one()
    for fuel_type, ton, cf in fuels:
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use "
                "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
                f"VALUES ('{voyage_id}'::uuid, '{fuel_type}', {ton}, {ton}, {cf}, 'SAMPLE')"
            )
        )


async def _insert_not_underway(
    session,
    vessel_id: str,
    *,
    year: int,
    fuel_type: str,
    ton: str,
    cf: Decimal,
) -> None:
    period = await session.execute(
        text(
            "INSERT INTO not_underway_period "
            "(vessel_id, regulation_year, period_type, started_at, ended_at, distance_nm) "
            f"VALUES ('{vessel_id}'::uuid, {year}, 'IN_PORT', "
            f"'{year}-03-01T00:00:00+00:00', '{year}-03-03T00:00:00+00:00', 0) RETURNING id"
        )
    )
    period_id = period.scalar_one()
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use "
            "(period_id, consumer_type, fuel_type, fuel_ton, cf_used) "
            f"VALUES ('{period_id}'::uuid, 'AUX_ENGINE', '{fuel_type}', {ton}, {cf})"
        )
    )


def _year(result: dict, year: int) -> dict:
    return next(row for row in result["years"] if row["regulation_year"] == year)


@pytest.mark.asyncio
async def test_fuel_axis_splits_by_fuel_type(session):
    """IT-FUEL-001 — 연료축이 유종별로 나뉘고, 톤 합이 그 해 총 연료와 같다."""
    await _ensure_params(session, 2025)
    vessel_id = await _insert_vessel(session, "7200401")
    await _insert_voyage(
        session,
        vessel_id,
        year=2025,
        distance="4000.00",
        fuels=[("HFO", "300.00", HFO_CF), ("LNG", "100.00", LNG_CF)],
    )

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2025, to_year=2025, as_of=AS_OF
    )
    row = _year(result, 2025)

    assert [fuel["fuel_type"] for fuel in row["fuels"]] == ["HFO", "LNG"]
    assert {fuel["fuel_type"]: fuel["fuel_ton"] for fuel in row["fuels"]} == {
        "HFO": "300.00",
        "LNG": "100.00",
    }
    # 한 표 안에서 검산이 맞아야 한다 — 유종별 톤의 합 = total_fuel_ton.
    assert sum(Decimal(fuel["fuel_ton"]) for fuel in row["fuels"]) == Decimal(row["total_fuel_ton"])


@pytest.mark.asyncio
async def test_share_is_by_co2_not_by_ton(session):
    """IT-FUEL-002 — 비중은 **CO₂ 기준**이다. 톤 비중과 다른 값이 나와야 한다.

    HFO 300t × 3.114 = 934.2t · LNG 100t × 2.75 = 275t → HFO 77.3%.
    톤 기준이면 75.0%다. **두 값이 같으면 이 검사는 아무것도 보지 않는다.**
    """
    await _ensure_params(session, 2025)
    vessel_id = await _insert_vessel(session, "7200402")
    await _insert_voyage(
        session,
        vessel_id,
        year=2025,
        distance="4000.00",
        fuels=[("HFO", "300.00", HFO_CF), ("LNG", "100.00", LNG_CF)],
    )

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2025, to_year=2025, as_of=AS_OF
    )
    fuels = {fuel["fuel_type"]: fuel for fuel in _year(result, 2025)["fuels"]}

    assert fuels["HFO"]["co2_ton"] == "934.20"
    assert fuels["LNG"]["co2_ton"] == "275.00"
    assert fuels["HFO"]["co2_share_percent"] == "77.3"
    assert fuels["LNG"]["co2_share_percent"] == "22.7"
    # 톤 비중(75.0)과 다르다 — 같으면 CF를 안 쓴 것이다.
    assert fuels["HFO"]["co2_share_percent"] != "75.0"
    assert sum(Decimal(fuel["co2_share_percent"]) for fuel in fuels.values()) == Decimal(100)


@pytest.mark.asyncio
async def test_same_fuel_with_two_cf_snapshots_is_one_row(session):
    """IT-FUEL-003 — CF snapshot이 둘이어도 **유종 한 줄**로 합친다 (`#863`).

    배출량은 묶음별 CF로 계산하되(정본 ``PRD §8.4`` snapshot 보존), 화면에 `HFO`가
    두 줄로 나오면 같은 기름을 두 종류로 읽는다.
    """
    await _ensure_params(session, 2025)
    vessel_id = await _insert_vessel(session, "7200403")
    await _insert_voyage(
        session,
        vessel_id,
        year=2025,
        distance="4000.00",
        fuels=[("HFO", "200.00", HFO_CF)],
    )
    # 같은 해의 **다른 항차**에 구 CF snapshot이 남아 있다 — 한 항차에 같은 유종을
    # 두 번 넣는 것은 `idx_fuel_use_unique`가 막는다(이중 산정 방어 · 마이그레이션 006).
    await _insert_voyage(
        session,
        vessel_id,
        year=2025,
        distance="2000.00",
        fuels=[("HFO", "100.00", HFO_CF_OLD)],
    )

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2025, to_year=2025, as_of=AS_OF
    )
    fuels = _year(result, 2025)["fuels"]

    assert [fuel["fuel_type"] for fuel in fuels] == ["HFO"]
    assert fuels[0]["fuel_ton"] == "300.00"
    # 각 묶음이 **자기 CF로** 곱해진 합이다 — 하나로 뭉뚱그리지 않는다.
    assert fuels[0]["co2_ton"] == str(
        (Decimal("200.00") * HFO_CF + Decimal("100.00") * HFO_CF_OLD).quantize(Decimal("0.01"))
    )
    assert fuels[0]["co2_share_percent"] == "100.0"


@pytest.mark.asyncio
async def test_not_underway_fuel_is_in_the_axis(session):
    """IT-FUEL-004 — 정박 연료도 연료축에 들어간다 (`MEPC.412(84) §4.2`).

    빠뜨리면 「정박해도 연료축이 안 움직이는」 화면이 된다 — 분자에는 들어가 있는데.
    """
    await _ensure_params(session, 2025)
    vessel_id = await _insert_vessel(session, "7200404")
    await _insert_voyage(
        session, vessel_id, year=2025, distance="4000.00", fuels=[("HFO", "300.00", HFO_CF)]
    )
    await _insert_not_underway(
        session, vessel_id, year=2025, fuel_type="LNG", ton="50.00", cf=LNG_CF
    )

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2025, to_year=2025, as_of=AS_OF
    )
    fuels = {fuel["fuel_type"]: fuel for fuel in _year(result, 2025)["fuels"]}

    assert set(fuels) == {"HFO", "LNG"}
    assert fuels["LNG"]["fuel_ton"] == "50.00"
    assert fuels["LNG"]["co2_ton"] == "137.50"


@pytest.mark.asyncio
async def test_rows_are_sorted_by_co2_descending(session):
    """IT-FUEL-005 — 큰 것부터. 순서를 서버가 정해 요청마다 흔들리지 않게 한다."""
    await _ensure_params(session, 2025)
    vessel_id = await _insert_vessel(session, "7200405")
    await _insert_voyage(
        session,
        vessel_id,
        year=2025,
        distance="4000.00",
        # 입력 순서를 **작은 것부터** 넣어 정렬이 실제로 일어나는지 본다.
        fuels=[("LNG", "50.00", LNG_CF), ("HFO", "300.00", HFO_CF)],
    )

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2025, to_year=2025, as_of=AS_OF
    )
    fuels = _year(result, 2025)["fuels"]

    assert [fuel["fuel_type"] for fuel in fuels] == ["HFO", "LNG"]


@pytest.mark.asyncio
async def test_year_without_data_has_an_empty_axis(session):
    """IT-FUEL-006 — 실적이 없는 해는 빈 배열이다. ``null``을 주지 않는다.

    ``null``이면 화면이 배열과 ``null`` 두 갈래를 다뤄야 하고, 한쪽을 잊으면 그
    해에서만 터진다.
    """
    await _ensure_params(session, 2024, 2025)
    vessel_id = await _insert_vessel(session, "7200406")
    await _insert_voyage(
        session, vessel_id, year=2025, distance="4000.00", fuels=[("HFO", "300.00", HFO_CF)]
    )

    result = await list_cii_history(
        session, vessel_id=vessel_id, from_year=2024, to_year=2025, as_of=AS_OF
    )

    assert _year(result, 2024)["data_available"] is False
    assert _year(result, 2024)["fuels"] == []
    assert _year(result, 2025)["fuels"] != []
