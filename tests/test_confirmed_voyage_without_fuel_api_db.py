"""연료 행이 없는 실적 확정 항차 — 누적과 연말 예상이 **같은 사실을 말한다** (#2095).

## 무엇이 어긋나 있었나

실적 확정 항차에 ``voyage_fuel_use`` 행이 한 행도 없으면 거리만 더해지고 연료는 0이다 —
분모만 커져 CII가 실제보다 좋게 나온다. ⑴ 연간 누적은 그 상태에 ``COMPLETED_FUEL_UNFILLED``를
냈는데(`#1095`), 같은 항차를 같은 방식으로 읽는 연말 예상의 확정분 조립
(``annual_simulation._inputs_from_snapshot``)은 **경고 없이** 지나갔다. 한 화면에서 누적은
「연료 기록이 없는 항차가 있다」고 말하고 연말 예상은 아무 말도 하지 않았다.

## 이 파일이 지키는 것

* 그 조립을 쓰는 **네 응답 전부**(`API_SPEC §2.14` 연말 예상 · `§2.18` 누적 추이 ·
  `§6.1` 연간 시뮬레이션 · `§2.17.1` 함대 감축)에 경고가 **실제 응답 본문까지** 실린다.
  서비스 반환값만 보면 응답 조립에서 빠진 것을 보지 못한다(`#433`).
* 거리는 누적과 **같은 쪽**(넣는다)이다 — 기대값은 분수 연산으로 따로 낸다.
* 판정은 누적과 **같은 함수**다(``ytd_cii.has_no_fuel_record``).

## 왜 ``TestClient``가 아닌가

연간 시뮬레이션은 실행을 저장하고 그 행은 지울 수 없다(``trg_snapshot_no_delete``). 커밋하는
``TestClient``로는 전용 선박이 DB에 남아 다른 검사의 선대 집계에 섞인다. 그래서 요청을
**같은 이벤트 루프**(``ASGITransport``)로 보내고 세션 의존성만 롤백되는 트랜잭션에 묶는다 —
라우트·직렬화·오류 처리기는 실제 것이 돈다.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from conftest import ensure_regulation_year, insert_if_not_exists
from fakes import FAKE_CSRF_TOKEN, FAKE_SESSION_TOKEN, install_fake_auth
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.auth.session import SESSION_COOKIE_NAME
from cii_platform.calc.precision import SERIALIZATION_ROUNDING
from cii_platform.db.session import get_session
from cii_platform.services import annual_simulation, request_cache, ytd_cii
from cii_platform.services.annual_simulation import WARNING_PLAN_NO_FUEL, _inputs_from_snapshot
from cii_platform.services.ytd_cii import WARNING_COMPLETED_FUEL_UNFILLED, has_no_fuel_record

YEAR = 2026
MID_YEAR = datetime(YEAR, 7, 1, tzinfo=UTC)

DEADWEIGHT = 50000
#: 확정 항차 둘의 실거리와 계획 항차 하나의 거리(nm).
CONFIRMED_NM = 5000
PLANNED_NM = 3000
#: 연료가 기록된 확정 항차의 실적(t)과 기록 시점 CF, 계획 항차의 계획 연료(t).
CONFIRMED_TON = 400
CONFIRMED_CF = Fraction(3114, 1000)
PLANNED_TON = 200


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def client(session, monkeypatch):
    """실제 라우트를 같은 루프에서 부른다 — 세션만 롤백되는 트랜잭션이다."""
    install_fake_auth(monkeypatch)

    async def override_session():
        try:
            yield session
        finally:
            # 요청 캐시는 ``session.info``에 살고 **요청 하나의 수명**을 전제한다. 여기서는
            # 한 세션을 여러 요청이 나눠 쓰므로, 지우지 않으면 두 번째 요청이 첫 요청이
            # 읽은 연료 행을 그대로 본다(실제 서버에서는 요청마다 세션이 새로 생긴다).
            session.info.pop(request_cache._KEY, None)

    app.dependency_overrides[get_session] = override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://testserver",
        cookies={SESSION_COOKIE_NAME: FAKE_SESSION_TOKEN},
        headers={"X-CSRF-Token": FAKE_CSRF_TOKEN},
    ) as http:
        yield http
    app.dependency_overrides.pop(get_session, None)


async def _voyage(session, vessel_id, *, no: str, confirmed: bool) -> object:
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, voyage_no, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, actual_distance_nm, "
            "actual_departure_at, actual_arrival_at, annual_inclusion_policy, "
            "regulation_year, created_from) "
            "VALUES (:id, :vid, :no, :status, 'Busan', 'Singapore', :planned, 14, :actual, "
            ":departed, :arrived, :policy, :year, 'MANUAL')"
        ),
        {
            "id": voyage_id,
            "vid": vessel_id,
            "no": no,
            "status": "CONFIRMED" if confirmed else "PLANNED",
            "planned": CONFIRMED_NM if confirmed else PLANNED_NM,
            "actual": Decimal(CONFIRMED_NM) if confirmed else None,
            "departed": datetime(YEAR, 6, 1, tzinfo=UTC) if confirmed else None,
            "arrived": datetime(YEAR, 6, 20, tzinfo=UTC) if confirmed else None,
            "policy": "INCLUDE_AS_ACTUAL" if confirmed else "INCLUDE_AS_PLAN",
            "year": YEAR,
        },
    )
    return voyage_id


async def _fuel(session, voyage_id, *, planned: int, actual: int | None) -> None:
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "actual_fuel_ton, cf_used, source) VALUES (:id, 'HFO', :planned, :actual, "
            "3.114, 'USER_INPUT')"
        ),
        {
            "id": voyage_id,
            "planned": Decimal(planned),
            "actual": None if actual is None else Decimal(actual),
        },
    )


@pytest_asyncio.fixture
async def fleet(session) -> dict:
    """확정 2건(하나는 연료 행 없음) + 계획 1건을 가진 전용 선박.

    ``unfilled``가 이 파일의 주인공이다 — 실거리 5,000nm는 있는데 연료 행이 0개다.
    """
    await ensure_regulation_year(session, YEAR)
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
    vessel_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, gross_tonnage, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton) "
            "VALUES (:id, :imo, 'UNFILLED 2095', 'BULK_CARRIER', 30000, :dwt, 'HFO', 14, 30)"
        ),
        {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}", "dwt": DEADWEIGHT},
    )
    filled = await _voyage(session, vessel_id, no="A", confirmed=True)
    await _fuel(session, filled, planned=CONFIRMED_TON, actual=CONFIRMED_TON)
    unfilled = await _voyage(session, vessel_id, no="B", confirmed=True)
    plan = await _voyage(session, vessel_id, no="C", confirmed=False)
    await _fuel(session, plan, planned=PLANNED_TON, actual=None)
    # 계획 항차는 **실행 시점의 활성 CF**로 계산된다(`#832`) — 기대값도 그 값을 읽어 쓴다.
    live_cf = (
        await session.execute(text("SELECT cf FROM fuel_type WHERE code = 'HFO'"))
    ).scalar_one()
    return {
        "vessel_id": vessel_id,
        "unfilled": unfilled,
        "live_cf": Fraction(Decimal(str(live_cf))),
    }


def _published(value: Fraction) -> str:
    """분수 기대값을 응답 표기(소수 6자리 · 직렬화 절단)로 옮긴다."""
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return str(exact.quantize(Decimal("0.000001"), rounding=SERIALIZATION_ROUNDING))


def _cii(co2_ton: Fraction, distance_nm: int) -> Fraction:
    """``CO₂(g) ÷ (DWT × 거리)`` — 서비스와 무관하게 분수로 낸다."""
    return co2_ton * 1_000_000 / (DEADWEIGHT * distance_nm)


async def _current(client, vessel_id) -> dict:
    response = await client.get(
        f"{API_V1_PREFIX}/vessels/{vessel_id}/cii/current",
        params={"year": YEAR, "as_of": MID_YEAR.isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ─── 판정은 한 곳에 있다 ─────────────────────────────────────────────────────


def test_both_assemblies_call_the_same_predicate():
    """누적과 연말 예상이 **같은 함수**로 판정한다 — 두 벌이면 한쪽만 바뀐다(`#2095`)."""
    assert has_no_fuel_record([]) is True
    assert has_no_fuel_record([object()]) is False
    assert annual_simulation.has_no_fuel_record is ytd_cii.has_no_fuel_record
    assert "has_no_fuel_record(" in inspect.getsource(ytd_cii._aggregate)
    assert "has_no_fuel_record(" in inspect.getsource(_inputs_from_snapshot)


def test_snapshot_assembly_keeps_the_distance_and_warns():
    """확정분 조립이 거리는 넣고(누적과 같은 쪽) 경고를 낸다 — 계획 쪽 경고와 섞이지 않는다."""

    class Vessel:
        reference_speed_kn = None
        reference_daily_foc_ton = None

    def actual(fuel_uses):
        return {
            "kind": "ACTUAL",
            "planned_distance_nm": "5000",
            "actual_distance_nm": "5000",
            "fuel_uses": fuel_uses,
        }

    one = {"fuel_type": "HFO", "planned_fuel_ton": "400", "actual_fuel_ton": "400", "cf_used": "3"}
    plan_without_fuel = {"kind": "PLAN", "planned_distance_nm": "3000", "fuel_uses": []}

    completed, _remaining, warnings = _inputs_from_snapshot([actual([one]), actual([])], Vessel())
    assert completed.distance_nm == 10000, "연료 행이 없어도 거리는 확정분에 들어간다"
    assert completed.co2_g == 400 * 3 * 1_000_000
    assert warnings == [WARNING_COMPLETED_FUEL_UNFILLED]

    _c, _r, clean = _inputs_from_snapshot([actual([one])], Vessel())
    assert clean == []

    # 계획 항차의 연료 없음(`#812`)은 **다른 사실**이다 — 그 항차는 빠지고 코드도 다르다.
    _c, _r, plan_only = _inputs_from_snapshot([actual([one]), plan_without_fuel], Vessel())
    assert plan_only == [WARNING_PLAN_NO_FUEL]


# ─── 네 응답 — 실제 본문에서 본다 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ytd_and_year_end_projection_say_the_same_thing(client, session, fleet):
    """⚠️ #2095 완료 기준 — `§2.14`의 누적 경고와 연말 예상 경고가 같은 사실을 말한다.

    값도 함께 고정한다. 연료 행이 없는 항차의 5,000nm가 분모에 들어가 누적·연말 예상이
    모두 **실제보다 낮게** 나온다 — 그 항차에 연료를 적으면 값이 오르고 경고가 사라진다.
    """
    before = await _current(client, fleet["vessel_id"])
    projection = before["year_end_projection"]

    assert WARNING_COMPLETED_FUEL_UNFILLED in before["warnings"], "사전 조건: ⑴은 경고한다"
    assert WARNING_COMPLETED_FUEL_UNFILLED in projection["warnings"]

    confirmed_co2 = CONFIRMED_TON * CONFIRMED_CF
    planned_co2 = PLANNED_TON * fleet["live_cf"]
    # 거리는 두 확정 항차를 **모두** 센다(누적과 같은 쪽) — 연료는 한 항차분뿐이다.
    assert before["ytd"]["total_distance_nm"].startswith(str(2 * CONFIRMED_NM))
    assert before["ytd"]["attained_cii"] == _published(_cii(confirmed_co2, 2 * CONFIRMED_NM))
    assert projection["attained_cii"] == _published(
        _cii(confirmed_co2 + planned_co2, 2 * CONFIRMED_NM + PLANNED_NM)
    )

    await _fuel(session, fleet["unfilled"], planned=CONFIRMED_TON, actual=CONFIRMED_TON)
    after = await _current(client, fleet["vessel_id"])

    assert WARNING_COMPLETED_FUEL_UNFILLED not in after["warnings"]
    assert WARNING_COMPLETED_FUEL_UNFILLED not in after["year_end_projection"]["warnings"]
    assert after["year_end_projection"]["attained_cii"] == _published(
        _cii(2 * confirmed_co2 + planned_co2, 2 * CONFIRMED_NM + PLANNED_NM)
    )
    # 경고가 말하던 것 — 연료가 빠져 있던 동안 연말 예상이 **좋게**(낮게) 나왔다.
    assert Decimal(projection["attained_cii"]) < Decimal(
        after["year_end_projection"]["attained_cii"]
    )


@pytest.mark.asyncio
async def test_ytd_series_carries_the_warning(client, session, fleet):
    """`§2.18` 누적 추이 — 계획 열을 만드는 조립이 같으므로 경고도 같이 실린다."""
    url = f"{API_V1_PREFIX}/vessels/{fleet['vessel_id']}/cii/ytd-series"
    params = {"year": YEAR, "as_of": MID_YEAR.isoformat()}

    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    assert WARNING_COMPLETED_FUEL_UNFILLED in response.json()["data"]["warnings"]

    await _fuel(session, fleet["unfilled"], planned=CONFIRMED_TON, actual=CONFIRMED_TON)
    filled = await client.get(url, params=params)
    assert WARNING_COMPLETED_FUEL_UNFILLED not in filled.json()["data"]["warnings"]


@pytest.mark.asyncio
async def test_annual_simulation_carries_the_warning(client, session, fleet):
    """`§6.1` 연간 시뮬레이션 — 실행 응답과 **저장된 실행의 조회 응답** 양쪽에 실린다."""
    body = {
        "vessel_id": str(fleet["vessel_id"]),
        "regulation_year": YEAR,
        "target_rating": "C",
        "simulation_runs": 1000,
        "random_seed": 12345,
        "as_of": MID_YEAR.isoformat(),
    }

    created = await client.post(f"{API_V1_PREFIX}/annual-simulations", json=body)
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    # 계산 결과 봉투(`API_SPEC §1.3.1`)는 경고를 ``data`` 옆 최상위에 싣는다.
    assert WARNING_COMPLETED_FUEL_UNFILLED in created.json()["warnings"]
    # 누적과 같은 쪽 — 연료 행이 없는 항차도 확정 항차로 세고 거리도 넣는다.
    assert data["deterministic"]["completed_voyage_count"] == 2

    stored = await client.get(f"{API_V1_PREFIX}/annual-simulations/{data['simulation_id']}")
    assert stored.status_code == 200, stored.text
    assert WARNING_COMPLETED_FUEL_UNFILLED in stored.json()["warnings"]

    current = await _current(client, fleet["vessel_id"])
    assert (
        data["deterministic"]["projected_attained_cii"]
        == current["year_end_projection"]["attained_cii"]
    ), "같은 조립 · 같은 as_of — 두 화면의 연말 예상이 같다"

    await _fuel(session, fleet["unfilled"], planned=CONFIRMED_TON, actual=CONFIRMED_TON)
    filled = await client.post(f"{API_V1_PREFIX}/annual-simulations", json=body)
    assert filled.status_code == 200, filled.text
    assert WARNING_COMPLETED_FUEL_UNFILLED not in filled.json()["warnings"]


@pytest.mark.asyncio
async def test_fleet_reduction_carries_the_warning(client, session, fleet):
    """`§2.17.1` 함대 감축 — 선대 경고에 한 번 실린다. 연료를 적으면 사라진다.

    선대 전체를 평가하므로 다른 선박의 상태에 기대지 않게 **같은 요청을 두 번** 본다 —
    이 선박의 그 항차에 연료를 적는 것만으로 경고가 사라져야 한다.
    """
    url = f"{API_V1_PREFIX}/fleet/reduction-plans/evaluate"
    body = {"regulation_year": YEAR, "target": "ALL_C_OR_BETTER"}

    evaluated = await client.post(url, json=body)
    assert evaluated.status_code == 200, evaluated.text
    assert WARNING_COMPLETED_FUEL_UNFILLED in evaluated.json()["data"]["warnings"]

    await _fuel(session, fleet["unfilled"], planned=CONFIRMED_TON, actual=CONFIRMED_TON)
    filled = await client.post(url, json=body)
    assert filled.status_code == 200, filled.text
    assert WARNING_COMPLETED_FUEL_UNFILLED not in filled.json()["data"]["warnings"]
