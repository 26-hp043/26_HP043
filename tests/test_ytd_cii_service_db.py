"""YTD 서비스 계층 DB 실동작 검증 (#353).

``tests/test_ytd_engine.py``가 수학을 보는 반면, 여기는 **어떤 데이터를 집계에
넣는지의 규칙**을 본다 — 그 규칙이 이 이슈에서 가장 틀리기 쉬운 곳이다.

* ``annual_inclusion_policy``로 거른다 (``PRD §8.1.2``) — ``INCLUDE_AS_PLAN``·
  ``EXCLUDE``는 들어가지 않는다
* ``as_of`` 절단이 항차(도착 시각)와 정박 구간(시작 시각)에 각각 적용된다
* soft delete된 정박 구간은 빠진다
* 데이터가 없으면 **예외가 아니라** ``data_available=False``
* ``#368`` 주입분(:class:`InProgressContribution`)이 반영된다
* ``[ORACLE-C-4B]`` — 실적 연료가 비면 계획값을 쓰고 ``COMPLETED_NO_FUEL``을 붙인다
* not under way **이동 거리**가 분모에 더해진다 (``MEPC.412(84)`` §4.2 · 마이그레이션 028)

파라미터 시드 상태: 마이그레이션 017이 ``fuel_type`` 8행을 넣으므로 HFO는 이미 있다.
나머지는 ``scripts/seed.py`` 경로(#127)이므로 여기서 직접 심는다
(``test_scenario_compare_db.py``와 같은 방식).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.ytd_cii import (
    WARNING_COMPLETED_NO_FUEL,
    InProgressContribution,
    compute_ytd_cii,
)

YEAR = 2026
HFO_CF = Decimal("3.114")


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> str:
    await _seed_parameters(session)
    return await _insert_vessel(session)


async def _seed_parameters(session) -> None:
    """규정 파라미터를 **멱등하게** 심는다.

    ``scripts/seed.py``를 이미 돌린 로컬 DB에서는 2026년 행이 존재한다. 그대로
    INSERT하면 ``uq_regulation_year_year``에 걸리므로, 없을 때만 넣는다. 값은 어느
    쪽이든 ``PRD §13.1`` Fixture 1과 같은 정본값이라 기대값이 갈리지 않는다.
    """
    await session.execute(
        text(
            "INSERT INTO regulation_year "
            "(year, z_factor_percent, effective_from, source_ref, version) "
            "SELECT 2026, 11.0, '2026-01-01', 'TEST', '1.0' "
            "WHERE NOT EXISTS (SELECT 1 FROM regulation_year WHERE year = 2026)"
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


async def _insert_vessel(session, imo: str = "9100001") -> str:
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight) "
            "VALUES (:imo, 'YTD TEST', 'BULK_CARRIER', 30000, 50000) RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_voyage(
    session,
    vessel_id: str,
    *,
    status: str = "COMPLETED",
    policy: str = "INCLUDE_AS_ACTUAL",
    distance: float | None = 1000,
    arrival_at: str | None = "2026-03-01T00:00:00+00",
) -> str:
    row = await session.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, "
            " actual_distance_nm, planned_speed_kn, actual_arrival_at) "
            "VALUES (:vid, :st, :pol, :yr, 'BUSAN', 'SINGAPORE', :dist, :dist, 12, :arr) "
            "RETURNING id"
        ),
        {
            "vid": vessel_id,
            "st": status,
            "pol": policy,
            "yr": None if policy == "EXCLUDE" else YEAR,
            "dist": distance,
            "arr": None if arrival_at is None else datetime.fromisoformat(arrival_at),
        },
    )
    return str(row.scalar_one())


async def _insert_voyage_fuel(
    session,
    voyage_id: str,
    *,
    actual_ton: float | None = 80,
    planned_ton: float | None = 80,
    fuel_type: str = "HFO",
) -> None:
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
            "VALUES (:vid, :ft, :pt, :at, :cf, 'USER_INPUT')"
        ),
        {
            "vid": voyage_id,
            "ft": fuel_type,
            "pt": planned_ton,
            "at": actual_ton,
            "cf": float(HFO_CF),
        },
    )


async def _insert_stay(
    session,
    vessel_id: str,
    *,
    fuel_ton: float = 10,
    started_at: str = "2026-02-01T00:00:00+00",
    is_deleted: bool = False,
    fuel_type: str = "HFO",
    distance_nm: float = 0,
) -> str:
    row = await session.execute(
        text(
            "INSERT INTO not_underway_period "
            "(vessel_id, regulation_year, period_type, started_at, ended_at, is_deleted, "
            " distance_nm) "
            "VALUES (:vid, :yr, 'AT_ANCHOR', :start, NULL, :del, :dist) RETURNING id"
        ),
        {
            "vid": vessel_id,
            "yr": YEAR,
            "start": datetime.fromisoformat(started_at),
            "del": is_deleted,
            "dist": distance_nm,
        },
    )
    period_id = str(row.scalar_one())
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use "
            "(period_id, consumer_type, fuel_type, fuel_ton) "
            "VALUES (:pid, 'AUX_ENGINE', :ft, :ton)"
        ),
        {"pid": period_id, "ft": fuel_type, "ton": fuel_ton},
    )
    return period_id


async def _compute(session, vessel_id: str, **kwargs):
    return await compute_ytd_cii(session, vessel_id=vessel_id, regulation_year=YEAR, **kwargs)


# --- 1. 기본 산출 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actual_voyage_produces_rating(session, vessel_id):
    """실적 확정 항차 1건 = Fixture 1 조건 → attained 4.9824 · 등급 C."""
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)

    result = await _compute(session, vessel_id)

    assert result.data_available is True
    assert result.attained_cii == Decimal("4.9824")
    assert result.rating == "C"
    assert result.voyage_count == 1
    assert result.underway_distance_nm == Decimal("1000.00")


@pytest.mark.asyncio
async def test_no_data_is_not_an_error(session, vessel_id):
    """항차가 없는 선박은 **정상 상태**다 — 예외가 아니라 플래그로 알린다."""
    result = await _compute(session, vessel_id)

    assert result.data_available is False
    assert result.attained_cii is None
    assert result.rating is None
    assert result.voyage_count == 0
    # 계산이 불가능해도 선박 제원은 돌려준다 — 화면이 축(DWT/GT)을 표시해야 한다.
    assert result.transport_capacity == Decimal("50000")
    assert result.capacity_axis == "DWT"


# --- 2. ★ 정박이 등급을 악화시킨다 ---------------------------------------------------


@pytest.mark.asyncio
async def test_stay_worsens_cii_end_to_end(session, vessel_id):
    """★ 같은 항차에 정박 기록만 더하면 CII가 나빠진다 (서비스 경로 전체)."""
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    before = await _compute(session, vessel_id)

    await _insert_stay(session, vessel_id, fuel_ton=10)
    after = await _compute(session, vessel_id)

    assert after.attained_cii > before.attained_cii
    assert after.not_underway_co2_g == Decimal("31140000.0000")
    # 이동이 0인 정박이므로 분모는 그대로다 — 이것이 등급 악화의 성립 근거다.
    assert after.not_underway_distance_nm == Decimal("0.00")
    assert after.total_distance_nm == before.total_distance_nm
    assert after.not_underway_period_count == 1


@pytest.mark.asyncio
async def test_long_stay_flips_the_rating(session, vessel_id):
    """정박 연료가 쌓이면 **등급이 단계적으로 떨어진다** — 화면 경고의 근거.

    Fixture 1 조건의 경계는 상위 ``5.34777…`` · 하위(악화 방향) ``5.95318…``이다
    (``tests/fixtures/cii/bulk_50000_hfo_2026.json``). 분모가 ``5e7``로 고정이므로
    정박 연료 1 t당 분자가 ``3,114,000 g`` = CII ``0.06228``씩 오른다.

    ======  ==================  ==========  ====
    정박 t  분자(g)             attained    등급
    ======  ==================  ==========  ====
    0       249,120,000         4.9824      C
    10      280,260,000         5.6052      D
    30      342,540,000         6.8508      E
    ======  ==================  ==========  ====
    """
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    before = await _compute(session, vessel_id)
    assert before.rating == "C"

    await _insert_stay(session, vessel_id, fuel_ton=10)
    mid = await _compute(session, vessel_id)
    assert mid.attained_cii == Decimal("5.6052")
    assert mid.rating == "D"
    assert mid.attained_cii > mid.required_cii

    # 누적 30 t — 하위 경계 5.95318을 넘어 최하 등급으로 떨어진다.
    await _insert_stay(session, vessel_id, fuel_ton=20, started_at="2026-04-01T00:00:00+00")
    worst = await _compute(session, vessel_id)
    assert worst.attained_cii == Decimal("6.8508")
    assert worst.rating == "E"
    # 등급 E는 악화 방향 경계가 없어 margin이 null이다 (#171 결론 · PRD §9.2).
    assert worst.next_worse_boundary is None
    assert worst.margin is None


# --- 3. 집계 포함 규칙 (PRD §8.1.2) --------------------------------------------------


@pytest.mark.asyncio
async def test_include_as_plan_voyage_is_excluded(session, vessel_id):
    """진행 중 항차의 **계획 전량**은 YTD에 들어가지 않는다 (#368 소관).

    들어가면 12월에 끝날 항차가 1월 조회에서 이미 배출한 것으로 계산된다.
    """
    voyage_id = await _insert_voyage(
        session, vessel_id, status="IN_PROGRESS", policy="INCLUDE_AS_PLAN"
    )
    await _insert_voyage_fuel(session, voyage_id)

    result = await _compute(session, vessel_id)

    assert result.data_available is False
    assert result.voyage_count == 0


@pytest.mark.asyncio
async def test_excluded_voyage_is_excluded(session, vessel_id):
    voyage_id = await _insert_voyage(session, vessel_id, status="DRAFT", policy="EXCLUDE")
    await _insert_voyage_fuel(session, voyage_id)

    result = await _compute(session, vessel_id)

    assert result.data_available is False


@pytest.mark.asyncio
async def test_soft_deleted_stay_is_excluded(session, vessel_id):
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    await _insert_stay(session, vessel_id, fuel_ton=10, is_deleted=True)

    result = await _compute(session, vessel_id)

    assert result.not_underway_co2_g == Decimal(0)
    assert result.not_underway_period_count == 0


# --- 4. as_of 절단 ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_as_of_cuts_later_stay(session, vessel_id):
    """``as_of`` 이후에 **시작한** 정박 구간은 빠진다."""
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    await _insert_stay(session, vessel_id, fuel_ton=10, started_at="2026-02-01T00:00:00+00")
    await _insert_stay(session, vessel_id, fuel_ton=10, started_at="2026-06-01T00:00:00+00")

    cut = datetime(2026, 3, 1, tzinfo=UTC)
    result = await _compute(session, vessel_id, as_of=cut)

    assert result.not_underway_period_count == 1
    assert result.not_underway_co2_g == Decimal("31140000.0000")


@pytest.mark.asyncio
async def test_as_of_cuts_later_voyage(session, vessel_id):
    """``as_of`` 이후에 **도착한** 항차는 빠진다."""
    early = await _insert_voyage(session, vessel_id, arrival_at="2026-02-01T00:00:00+00")
    await _insert_voyage_fuel(session, early)
    late = await _insert_voyage(session, vessel_id, arrival_at="2026-11-01T00:00:00+00")
    await _insert_voyage_fuel(session, late)

    result = await _compute(session, vessel_id, as_of=datetime(2026, 3, 1, tzinfo=UTC))

    assert result.voyage_count == 1
    assert result.underway_distance_nm == Decimal("1000.00")


# --- 4-b. 분모에 들어가는 not under way 이동 거리 (MEPC.412(84) §4.2) ---------------


@pytest.mark.asyncio
async def test_moving_stay_enters_the_denominator(session, vessel_id):
    """★ 운하 통과처럼 **이동이 있는** not under way 구간은 분모를 늘린다.

    빼면 분모가 과소해져 CII가 과대해지고 등급이 실제보다 나쁘게 나온다.
    """
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    before = await _compute(session, vessel_id)

    # 수에즈 통과 약 104 nm — 연료 없이 거리만 있는 구간도 성립한다.
    await _insert_stay(session, vessel_id, fuel_ton=1, distance_nm=104)
    after = await _compute(session, vessel_id)

    assert after.not_underway_distance_nm == Decimal("104.00")
    assert after.total_distance_nm == before.total_distance_nm + Decimal("104.00")
    # 분모가 늘었으므로 같은 연료였다면 CII가 내려간다. 여기서는 연료 1 t가 함께
    # 늘었으므로 분모 효과만 떼어 transport_work로 확인한다.
    assert after.underway_distance_nm == before.underway_distance_nm


@pytest.mark.asyncio
async def test_as_of_cuts_the_distance_too(session, vessel_id):
    """``as_of`` 절단은 연료뿐 아니라 거리에도 같이 걸린다."""
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    await _insert_stay(
        session, vessel_id, fuel_ton=1, distance_nm=104, started_at="2026-02-01T00:00:00+00"
    )
    await _insert_stay(
        session, vessel_id, fuel_ton=1, distance_nm=44, started_at="2026-06-01T00:00:00+00"
    )

    result = await _compute(session, vessel_id, as_of=datetime(2026, 3, 1, tzinfo=UTC))

    assert result.not_underway_distance_nm == Decimal("104.00")


@pytest.mark.asyncio
async def test_soft_deleted_stay_distance_is_excluded(session, vessel_id):
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    await _insert_stay(session, vessel_id, fuel_ton=1, distance_nm=104, is_deleted=True)

    result = await _compute(session, vessel_id)

    assert result.not_underway_distance_nm == Decimal("0")


# --- 5. #368 주입 지점 --------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_progress_contribution_is_added(session, vessel_id):
    """``#368``이 확정해 넘긴 진행 중 누적분이 분자·분모에 모두 반영된다."""
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id)
    before = await _compute(session, vessel_id)

    after = await _compute(
        session,
        vessel_id,
        in_progress=InProgressContribution(
            distance_nm=Decimal("500"), fuel_uses=(("HFO", Decimal("40")),)
        ),
    )

    assert after.underway_distance_nm == before.underway_distance_nm + Decimal("500")
    # 연료 80 → 120 t. 거리도 함께 늘었으므로 CII 자체는 항해 중이라 크게 나빠지지 않는다.
    assert after.total_co2_t > before.total_co2_t


# --- 6. [ORACLE-C-4B] 실적 연료 결측 ------------------------------------------------


@pytest.mark.asyncio
async def test_missing_actual_fuel_falls_back_to_plan_with_warning(session, vessel_id):
    """COMPLETED인데 ``actual_fuel_ton``이 NULL이면 계획값을 쓰고 경고를 붙인다."""
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_voyage_fuel(session, voyage_id, actual_ton=None, planned_ton=80)

    result = await _compute(session, vessel_id)

    assert result.data_available is True
    assert result.attained_cii == Decimal("4.9824")
    assert WARNING_COMPLETED_NO_FUEL in result.warnings
