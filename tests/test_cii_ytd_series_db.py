"""올해 누적 CII 추이 — 항차 경계마다 한 점 (`API_SPEC §2.18`, #1671).

## 이 파일이 지키는 것

**한 화면에 두 숫자가 생기지 않는 것.** 추이의 마지막 실적 점은 같은 ``as_of``의 `§2.14`
``ytd.attained_cii``와, 마지막 계획 점은 ``year_end_projection.attained_cii``와 **문자 단위로**
같아야 한다. 구현은 같은 조립(:func:`resolve_ytd_at`) · 같은 엔진(``project_deterministic``)을
부르므로 구성상 같지만, 그 구성이 갈리는 순간(예: 잔여 항차를 정렬하다 하나를 빠뜨림)을 잡는
검사가 없으면 화면은 멀쩡한 채 값만 어긋난다 — `#798`이 그렇게 7.65 vs 8.97을 냈다.

수치 자체는 `#353`(YTD 엔진) · `#798`(연말 예상)이 검증한다. 여기서는 **점의 위치·종류·
동치**만 본다.

케이스 (`TEST_PLAN §4.11`): AT-YTDS-001~015.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from conftest import ensure_regulation_year, insert_if_not_exists
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.calc.precision import SERIALIZATION_ROUNDING
from cii_platform.db.demo_seed import DEMO_ANCHOR, VESSEL_ID_BULK
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import NotFoundError, ParameterError, ValidationError
from cii_platform.services.cii_current import (
    WARNING_NO_REMAINING_PLAN,
    get_current_cii,
    resolve_ytd_at,
)
from cii_platform.services.cii_ytd_series import (
    KIND_ACTUAL,
    KIND_IN_PROGRESS,
    KIND_PLAN,
    get_ytd_series,
)

YEAR = 2026
MID_YEAR = datetime(YEAR, 7, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


# ─── 픽스처 — `test_cii_current_db.py`와 같은 모양 ─────────────────────────────


async def _seed_parameters(session) -> None:
    await ensure_regulation_year(session, 2026)
    await ensure_regulation_year(session, 2025)
    await insert_if_not_exists(
        session,
        "INSERT INTO cii_reference_line "
        "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
        "VALUES ('BULK_CARRIER', 'DWT < 279000', 'DWT', '4745', 4745, 0.622, 'TEST')",
    )
    await insert_if_not_exists(
        session,
        "INSERT INTO cii_rating_boundary "
        "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
        "VALUES ('BULK_CARRIER', 'all', 'DWT', 0.86, 0.94, 1.06, 1.18, 'TEST')",
    )


async def _make_vessel(session, **over) -> object:
    await _seed_parameters(session)
    vessel_id = uuid4()
    fields = {
        "id": vessel_id,
        "imo": f"9{vessel_id.int % 1000000:06d}",
        "speed": Decimal("14"),
        "foc": Decimal("30"),
        "fuel": "HFO",
        "state": "UNDER_WAY",
        "detail": "SAILING",
    }
    fields.update(over)
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton, "
            "underway_state, detail_status) VALUES (:id, :imo, 'SERIES TEST', "
            "'BULK_CARRIER', 50000, :fuel, :speed, :foc, :state, :detail)"
        ),
        fields,
    )
    return vessel_id


async def _make_voyage(
    session,
    vessel_id,
    *,
    status="IN_PROGRESS",
    departed_at=None,
    planned_arrival_at=None,
    **over,
):
    voyage_id = uuid4()
    fields = {
        "id": voyage_id,
        "vessel_id": vessel_id,
        "status": status,
        "departed": departed_at or datetime(YEAR, 6, 1, tzinfo=UTC),
        "planned_arrival": planned_arrival_at,
        "policy": "INCLUDE_AS_PLAN",
        "year": YEAR,
        "planned_distance": 3000,
    }
    fields.update(over)
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_departure_at, planned_arrival_at, annual_inclusion_policy, "
            "regulation_year, created_from) "
            "VALUES (:id, :vessel_id, :status, 'Busan', 'Singapore', "
            ":planned_distance, 14, :departed, :planned_arrival, :policy, :year, 'MANUAL')"
        ),
        fields,
    )
    return voyage_id


async def _add_actuals(session, voyage_id, *, distance="5000", fuel="400", arrived_at=None) -> None:
    """실적 확정 항차. ``distance=None``이면 거리 실적을 비워 계획값 대체를 일으킨다."""
    await session.execute(
        text(
            "UPDATE voyage SET status='CONFIRMED', "
            "annual_inclusion_policy='INCLUDE_AS_ACTUAL', "
            "actual_distance_nm=:distance, "
            "actual_arrival_at=:arrived WHERE id=:id"
        ),
        {
            "id": voyage_id,
            "distance": None if distance is None else Decimal(distance),
            "arrived": arrived_at or datetime(YEAR, 6, 20, tzinfo=UTC),
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "actual_fuel_ton, cf_used, source) VALUES (:id, 'HFO', :fuel, :fuel, "
            "3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id, "fuel": Decimal(fuel)},
    )


async def _add_plan(session, vessel_id, *, distance="10000", fuel="1200", planned_arrival_at=None):
    voyage_id = await _make_voyage(
        session,
        vessel_id,
        status="PLANNED",
        policy="INCLUDE_AS_PLAN",
        departed_at=None,
        planned_arrival_at=planned_arrival_at,
    )
    await session.execute(
        text("UPDATE voyage SET planned_distance_nm = :d WHERE id = :id"),
        {"id": voyage_id, "d": Decimal(distance)},
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "cf_used, source) VALUES (:id, 'HFO', :fuel, 3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id, "fuel": Decimal(fuel)},
    )
    return voyage_id


async def _add_planned_fuel(session, voyage_id, *, fuel="300") -> None:
    """진행 중 항차에 계획 연료를 단다 — 연료가 없으면 `#812`가 잔여 계획에서 뺀다."""
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "cf_used, source) VALUES (:id, 'HFO', :fuel, 3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id, "fuel": Decimal(fuel)},
    )


async def _add_period(session, vessel_id, *, started_at: str, ended_at: str | None):
    period_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
            "period_type, started_at, ended_at, distance_nm) VALUES (:id, :vid, 2026, "
            "'AT_ANCHOR', :started, :ended, 0)"
        ),
        {"id": period_id, "vid": vessel_id, "started": started_at, "ended": ended_at},
    )
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'OIL_FIRED_BOILER', 'HFO', 40, 3.114)"
        ),
        {"id": period_id},
    )
    return period_id


async def _two_actuals_one_in_progress_two_plans(session):
    """실적 2건(5/10 · 6/20 도착) · 진행 중 1건(6/25 출항) · 계획 2건(8월 · 9월 도착 예정)."""
    vessel_id = await _make_vessel(session, foc=Decimal("120"))
    first = await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 4, 20, tzinfo=UTC))
    await _add_actuals(session, first, arrived_at=datetime(YEAR, 5, 10, tzinfo=UTC))
    second = await _make_voyage(session, vessel_id)
    await _add_actuals(session, second, distance="6000", fuel="700")
    await _make_voyage(
        session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC), planned_distance=30000
    )
    late = await _add_plan(session, vessel_id, planned_arrival_at=datetime(YEAR, 9, 1, tzinfo=UTC))
    early = await _add_plan(
        session,
        vessel_id,
        distance="4000",
        fuel="300",
        planned_arrival_at=datetime(YEAR, 8, 1, tzinfo=UTC),
    )
    return vessel_id, {"first": first, "second": second, "late": late, "early": early}


def _actual_side(points):
    return [p for p in points if p["kind"] != KIND_PLAN]


def _plan_side(points):
    return [p for p in points if p["kind"] == KIND_PLAN]


# ─────────────────────────────────────────────────────────────────────────────
# 끝점 동치 — 어긋나면 한 화면에 두 숫자
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_last_actual_point_equals_current_ytd(session):
    """AT-YTDS-001 — 실적 쪽 마지막 점 = 같은 ``as_of``의 `§2.14` ``ytd``."""
    vessel_id, _ = await _two_actuals_one_in_progress_two_plans(session)

    series, meta = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    current, current_meta = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    last = _actual_side(series["points"])[-1]
    assert last["attained_cii"] == current["ytd"]["attained_cii"]
    assert last["rating"] == current["ytd"]["rating"]
    assert last["at"] == meta["as_of"] == current_meta["as_of"]
    assert series["required_cii"] == current["ytd"]["required_cii"]
    assert series["boundaries"] == current["ytd"]["boundaries"]


@pytest.mark.asyncio
async def test_last_plan_point_equals_year_end_projection(session):
    """AT-YTDS-002 — 계획 쪽 마지막 점 = ``year_end_projection`` (같은 조립 · 같은 엔진)."""
    vessel_id, _ = await _two_actuals_one_in_progress_two_plans(session)

    series, _ = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    current, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    last = _plan_side(series["points"])[-1]
    projection = current["year_end_projection"]
    assert projection["data_available"] is True
    assert last["attained_cii"] == projection["attained_cii"]
    assert last["rating"] == projection["rating"]
    # 잔여 계획이 남아 있으면 ⑶ ≠ ⑴ — 계획 열이 실적 열과 갈리는지도 함께 본다 (`#798`).
    assert last["attained_cii"] != _actual_side(series["points"])[-1]["attained_cii"]


@pytest.mark.asyncio
async def test_each_actual_point_matches_resolve_ytd_at(session):
    """AT-YTDS-003 — 실적 점 하나하나가 그 시각의 :func:`resolve_ytd_at` 재호출과 같다."""
    vessel_id, _ = await _two_actuals_one_in_progress_two_plans(session)
    vessel = await vessel_repo.get_by_id(session, vessel_id)

    series, _ = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    actual = _actual_side(series["points"])
    assert len(actual) == 3  # 5/10 도착 · 6/20 도착 · as_of
    for point in actual:
        _state, ytd = await resolve_ytd_at(
            session,
            vessel=vessel,
            regulation_year=YEAR,
            at=datetime.fromisoformat(point["at"]),
        )
        assert point["attained_cii"] == str(
            ytd.attained_cii.quantize(Decimal("0.000001"), rounding=SERIALIZATION_ROUNDING)
        )
        assert point["rating"] == ytd.rating


# ─────────────────────────────────────────────────────────────────────────────
# 점의 위치·종류
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_points_are_ascending_and_kinds_are_partitioned(session):
    """AT-YTDS-004 — ``at`` 오름차순 · 실적(ACTUAL) → ``as_of``(IN_PROGRESS) → 계획(PLAN)."""
    vessel_id, ids = await _two_actuals_one_in_progress_two_plans(session)

    series, meta = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    points = series["points"]

    ats = [datetime.fromisoformat(p["at"]) for p in points]
    assert ats == sorted(ats)
    assert [p["kind"] for p in points] == [
        KIND_ACTUAL,
        KIND_ACTUAL,
        KIND_IN_PROGRESS,
        KIND_PLAN,
        KIND_PLAN,
    ]
    # 확정 항차는 도착 시각에 전량 들어간다 — 점의 시각이 도착 시각이다.
    assert points[0]["at"] == datetime(YEAR, 5, 10, tzinfo=UTC).isoformat()
    assert points[0]["voyage_id"] == str(ids["first"])
    assert points[1]["at"] == datetime(YEAR, 6, 20, tzinfo=UTC).isoformat()
    assert points[1]["voyage_id"] == str(ids["second"])
    # ``as_of`` 점 — 진행 중 항차의 경과분(모델값)이 들어 IN_PROGRESS. 시각은 ``as_of`` 자신.
    assert points[2]["at"] == meta["as_of"]
    assert meta["simulated"] is True
    # 계획 점은 **도착 예정 순**이다 — 등록은 9월분이 먼저였다.
    assert [p["voyage_id"] for p in _plan_side(points)] == [str(ids["early"]), str(ids["late"])]
    assert _plan_side(points)[0]["at"] == datetime(YEAR, 8, 1, tzinfo=UTC).isoformat()
    # 계획 열은 항차를 하나씩 더해 가므로 값이 점마다 달라야 한다.
    assert len({p["attained_cii"] for p in _plan_side(points)}) == 2


@pytest.mark.asyncio
async def test_overdue_plan_is_pinned_to_as_of(session):
    """AT-YTDS-005 — 도착 예정이 지난 잔여 항차(`#1323`)의 계획 점은 ``as_of``에 붙는다.

    예정일이 ``as_of``보다 앞이면 그 시각에 점을 찍을 수 없다 — 곡선이 뒤로 간다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    overdue = await _add_plan(
        session, vessel_id, planned_arrival_at=datetime(YEAR, 6, 15, tzinfo=UTC)
    )

    series, meta = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    plan = _plan_side(series["points"])
    assert [p["voyage_id"] for p in plan] == [str(overdue)]
    assert plan[0]["at"] == meta["as_of"]


@pytest.mark.asyncio
async def test_periods_make_a_point_at_started_at(session):
    """AT-YTDS-006 — 정박 구간은 ``started_at``에 점(``period_id``) — 종료·진행 중 둘 다.

    저장소 절단 술어(``started_at <= as_of``)와 같은 시각이다 — 정박 연료가 누적에 들어가는
    순간에 점이 찍혀야 「언제부터 나빠졌나」가 맞다. 값이 그 시각에 바뀌는지도 함께 본다.
    """
    vessel_id = await _make_vessel(session, state="NOT_UNDER_WAY", detail="AT_ANCHOR")
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    ended = await _add_period(
        session, vessel_id, started_at="2026-06-22T00:00:00Z", ended_at="2026-06-24T12:00:00Z"
    )
    open_period = await _add_period(
        session, vessel_id, started_at="2026-06-28T00:00:00Z", ended_at=None
    )

    series, meta = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    actual = _actual_side(series["points"])
    assert [p["kind"] for p in actual] == [KIND_ACTUAL] * 4
    assert [p["at"] for p in actual] == [
        datetime(YEAR, 6, 20, tzinfo=UTC).isoformat(),
        datetime(YEAR, 6, 22, tzinfo=UTC).isoformat(),
        datetime(YEAR, 6, 28, tzinfo=UTC).isoformat(),
        meta["as_of"],
    ]
    assert [p["period_id"] for p in actual] == [None, str(ended), str(open_period), None]
    assert actual[1]["voyage_id"] is None
    # 정박 연료(40 t · 거리 0)가 그 시각에 들어가 값이 나빠진다 — 점마다 값이 다르다.
    values = [Decimal(p["attained_cii"]) for p in actual]
    assert values[0] < values[1] < values[2] == values[3]
    assert meta["simulated"] is False


@pytest.mark.asyncio
async def test_no_actuals_is_not_an_error(session):
    """AT-YTDS-007 — 실적이 없으면 200 · ``ytd_available: false`` · 실적 점 없음(연초 점 금지)."""
    vessel_id = await _make_vessel(session, state="NOT_UNDER_WAY", detail="AT_ANCHOR")

    series, _ = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert series["ytd_available"] is False
    assert series["points"] == []
    assert WARNING_NO_REMAINING_PLAN in series["warnings"]
    assert "REFERENCE_ONLY" in series["warnings"]
    # 경계·기준선은 실적이 없어도 준다 — 밴드는 그릴 수 있다.
    assert series["required_cii"] is not None
    assert set(series["boundaries"]) == {
        "superior_boundary",
        "lower_boundary",
        "upper_boundary",
        "inferior_boundary",
    }


@pytest.mark.asyncio
async def test_past_year_has_no_plan_or_in_progress_points(session):
    """AT-YTDS-008 — 과거 연도는 실적 점만. 지금 뛰는 항차·잔여 계획은 그 해의 것이 아니다."""
    vessel_id, _ = await _two_actuals_one_in_progress_two_plans(session)
    old = await _make_voyage(
        session, vessel_id, departed_at=datetime(2025, 3, 1, tzinfo=UTC), year=2025
    )
    await _add_actuals(session, old, arrived_at=datetime(2025, 3, 20, tzinfo=UTC))

    series, meta = await get_ytd_series(session, vessel_id, year=2025, as_of=MID_YEAR)

    kinds = {p["kind"] for p in series["points"]}
    assert kinds == {KIND_ACTUAL}
    assert [p["voyage_id"] for p in series["points"]][0] == str(old)
    # ``as_of`` 점은 그 해 밖(2026-07-01)이 아니라 **그 해 끝**에 찍힌다 — 값은 그 해 전체다.
    assert series["points"][-1]["at"] == datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    assert series["points"][-1]["attained_cii"] == series["points"][0]["attained_cii"]
    assert meta["simulated"] is False


@pytest.mark.asyncio
async def test_excluded_voyage_makes_no_point_and_substitution_is_flagged(session):
    """AT-YTDS-009 — `EXCLUDE` 항차는 점이 없다(`PRD §3.3.8`) · 계획값 대체 항차는 `substituted`."""
    vessel_id = await _make_vessel(session, state="NOT_UNDER_WAY", detail="AT_ANCHOR")
    kept = await _make_voyage(session, vessel_id)
    await _add_actuals(session, kept, distance=None)  # 거리 실적 없음 → 계획거리 대체
    dropped = await _make_voyage(
        session,
        vessel_id,
        status="CANCELLED",
        policy="EXCLUDE",
        departed_at=datetime(YEAR, 5, 1, tzinfo=UTC),
        planned_arrival_at=datetime(YEAR, 5, 5, tzinfo=UTC),
    )

    series, _ = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    voyage_ids = [p["voyage_id"] for p in series["points"]]
    assert str(dropped) not in voyage_ids
    kept_point = next(p for p in series["points"] if p["voyage_id"] == str(kept))
    assert kept_point["substituted"] is True
    assert "COMPLETED_NO_DISTANCE" in series["warnings"]


@pytest.mark.asyncio
async def test_current_voyage_is_the_first_plan_point(session):
    """AT-YTDS-014 — 진행 중 항차가 **도착 예정과 무관하게 첫 `PLAN` 점**이다 (`#1673` ②).

    `§2.14` ``year_end_projection.drivers[]``가 ⑴ → 진행 항차의 남은 몫 → 잔여 계획 순으로
    설명하므로, 같은 화면의 첫 ``PLAN`` 점이 「⑴ + 진행 항차 계획 전량」이어야 두 설명이
    어긋나지 않는다. 진행 항차보다 **이른** 도착 예정의 잔여 계획을 두어 정렬만으로는
    앞에 올 수 없게 한다.
    """
    vessel_id = await _make_vessel(session, foc=Decimal("120"))
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    current = await _make_voyage(
        session,
        vessel_id,
        departed_at=datetime(YEAR, 6, 25, tzinfo=UTC),
        planned_arrival_at=datetime(YEAR, 9, 15, tzinfo=UTC),
    )
    await _add_planned_fuel(session, current)
    earlier = await _add_plan(
        session, vessel_id, distance="4000", planned_arrival_at=datetime(YEAR, 8, 1, tzinfo=UTC)
    )

    series, meta = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    plan = _plan_side(series["points"])
    assert [p["voyage_id"] for p in plan] == [str(current), str(earlier)]
    # 진행 항차 점은 그 항차의 도착 예정에, 그보다 이른 잔여 계획은 직전 점의 시각을 잇는다.
    assert plan[0]["at"] == datetime(YEAR, 9, 15, tzinfo=UTC).isoformat()
    assert plan[1]["at"] == plan[0]["at"]
    # ``as_of`` 점(경과분)과 첫 ``PLAN`` 점(계획 전량)은 다른 값이고, 둘째 점은 또 다르다.
    as_of_point = _actual_side(series["points"])[-1]
    assert as_of_point["kind"] == KIND_IN_PROGRESS and as_of_point["voyage_id"] == str(current)
    assert len({as_of_point["attained_cii"], plan[0]["attained_cii"], plan[1]["attained_cii"]}) == 3
    assert meta["simulated"] is True


@pytest.mark.asyncio
async def test_two_arrivals_at_the_same_instant_share_one_point(session):
    """AT-YTDS-015 — 같은 순간에 도착한 두 항차는 점 하나 · ``substituted``는 둘 다 본다.

    둘째 항차만 계획값 대체인데 첫 항차만 보면 거짓이 된다.
    """
    vessel_id = await _make_vessel(session, state="NOT_UNDER_WAY", detail="AT_ANCHOR")
    clean = await _make_voyage(session, vessel_id)
    await _add_actuals(session, clean)
    replaced = await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 5, tzinfo=UTC))
    await _add_actuals(session, replaced, distance=None)

    series, _ = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    actual = _actual_side(series["points"])
    assert len(actual) == 2  # 6/20 한 점 + ``as_of``
    assert actual[0]["at"] == datetime(YEAR, 6, 20, tzinfo=UTC).isoformat()
    assert actual[0]["voyage_id"] in {str(clean), str(replaced)}
    assert actual[0]["substituted"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 오류 · 직렬화
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_vessel_is_404(session):
    """AT-YTDS-010."""
    with pytest.raises(NotFoundError):
        await get_ytd_series(session, uuid4(), year=YEAR, as_of=MID_YEAR)


@pytest.mark.asyncio
async def test_year_out_of_range_is_422(session):
    """AT-YTDS-010."""
    vessel_id = await _make_vessel(session)
    with pytest.raises(ValidationError):
        await get_ytd_series(session, vessel_id, year=1900, as_of=MID_YEAR)


@pytest.mark.asyncio
async def test_missing_regulation_year_is_409(session):
    """AT-YTDS-013 — 규제연도 파라미터가 없으면 409 `PARAMETER_ERROR` (`§2.14`와 같은 자리)."""
    vessel_id = await _make_vessel(session)
    with pytest.raises(ParameterError):
        await get_ytd_series(session, vessel_id, year=2045, as_of=MID_YEAR)


@pytest.mark.asyncio
async def test_numbers_are_strings_and_times_are_utc(session):
    """AT-YTDS-011 — `§1.7` 문자열(소수 6자리) · `§1.10` UTC 시각 · 점의 키 집합은 종류와 무관."""
    vessel_id, _ = await _two_actuals_one_in_progress_two_plans(session)

    series, meta = await get_ytd_series(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert meta["as_of"].endswith("+00:00")
    keys = {frozenset(p) for p in series["points"]}
    assert keys == {
        frozenset({"at", "kind", "attained_cii", "rating", "voyage_id", "period_id", "substituted"})
    }
    for point in series["points"]:
        assert point["at"].endswith("+00:00")
        assert isinstance(point["attained_cii"], str)
        assert len(point["attained_cii"].split(".")[1]) == 6
        assert isinstance(point["substituted"], bool)
    assert isinstance(series["required_cii"], str)


# ─────────────────────────────────────────────────────────────────────────────
# 데모 벌크선(…0001) 기준값 · HTTP 경로
# ─────────────────────────────────────────────────────────────────────────────

#: 시드 적재 시각(`DEMO_ANCHOR`) + 3일. 진행 중 항차(출항 −5d 06:00 · 2,300nm · 14kn)가
#: 계획 거리를 다 채운 뒤라(`#1321`) 앵커가 어느 날이든 값이 같다.
DEMO_AS_OF = DEMO_ANCHOR + timedelta(days=3)


def _client():
    return TestClient(app, base_url="https://testserver")


@pytest.mark.asyncio
async def test_demo_bulk_reference_values(session):
    """AT-YTDS-012 — 데모 벌크선의 실측 기준값 (순수 엔진으로 재계산한 값과 대조).

    실적 첫 점 = 2026-01 항차 도착(2/26 23:00Z) 전량 · 마지막 실적 점 = ``ytd`` 8.213830 ·
    계획 열은 잔여 5건을 도착 예정 순으로 더해 8.965893(= ``year_end_projection``)에 닿는다.
    """
    bulk = UUID(VESSEL_ID_BULK)
    series, meta = await get_ytd_series(session, bulk, year=YEAR, as_of=DEMO_AS_OF)
    current, _ = await get_current_cii(session, bulk, year=YEAR, as_of=DEMO_AS_OF)

    actual = _actual_side(series["points"])
    assert actual[0]["at"] == "2026-02-26T23:00:00+00:00"
    assert actual[0]["kind"] == KIND_ACTUAL
    assert actual[0]["attained_cii"] == "8.979906"
    assert actual[-1]["kind"] == KIND_IN_PROGRESS
    assert actual[-1]["attained_cii"] == "8.213830" == current["ytd"]["attained_cii"]
    assert actual[-1]["at"] == meta["as_of"]

    plan = [p["attained_cii"] for p in _plan_side(series["points"])]
    assert plan == ["8.973981", "8.971119", "8.969484", "8.967383", "8.965893"]
    assert plan[-1] == current["year_end_projection"]["attained_cii"]

    # 같은 화면의 두 설명이 어긋나지 않는다 — 추이의 첫 PLAN 점(진행 중 항차를 계획
    # 전량으로 더한 값)은 `§2.14` `drivers[]`의 ⑴ + `CURRENT_VOYAGE`와 **같은 문자열**이다
    # (#1673). 응답 두 문자열을 Decimal로 더해도 6자리라 정확하다.
    drivers = {d["key"]: d["delta_cii"] for d in current["year_end_projection"]["drivers"]}
    assert "BASIS_DIFFERENCE" not in drivers
    assert str(Decimal(actual[-1]["attained_cii"]) + Decimal(drivers["CURRENT_VOYAGE"])) == plan[0]
    assert str(Decimal(plan[0]) + Decimal(drivers["REMAINING_PLAN"])) == plan[-1]


def test_http_route_answers_with_the_same_envelope(migrated_db, app_fresh_engine):
    """AT-YTDS-012 — 라우트가 `§2.14`와 같은 봉투로 답한다 · 404 · 422."""
    with _client() as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        as_of = DEMO_AS_OF.isoformat()

        ok = client.get(
            f"{API_V1_PREFIX}/vessels/{VESSEL_ID_BULK}/cii/ytd-series",
            params={"year": YEAR, "as_of": as_of},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["data"]["vessel_id"] == VESSEL_ID_BULK
        assert body["data"]["ytd_available"] is True
        assert body["meta"]["as_of"] == as_of
        assert body["meta"]["simulated"] is True
        assert {"request_id", "timestamp"} <= set(body["meta"])
        assert body["data"]["points"][-1]["kind"] == KIND_PLAN

        missing = client.get(f"{API_V1_PREFIX}/vessels/{uuid4()}/cii/ytd-series")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "NOT_FOUND"

        bad_year = client.get(
            f"{API_V1_PREFIX}/vessels/{VESSEL_ID_BULK}/cii/ytd-series", params={"year": 1900}
        )
        assert bad_year.status_code == 422
        assert bad_year.json()["error"]["code"] == "VALIDATION_ERROR"
