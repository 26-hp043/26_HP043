"""진행 중 항차의 누적 거리는 **계획 거리를 넘지 않는다** (`#1321`).

## 무엇이 문제였나

``simulation_clock``의 창 상한은 **시각 하나**뿐이었다 — 도착 실적, 없으면
``planned_arrival_at``(`#649`). 거리는 ``속력 × 경과시간``으로만 났고
``planned_distance_nm``와 **비교하지 않았다.**

`#649`가 막은 것과 다른 구멍이다. `#649`는 「**예정일을 지나도** 자란다」를 막았고,
여기는 **예정일 안에서도** 계획을 넘는다.

계획 거리는 **항로 거리**이고 도착 예정일은 **항만 체류·대기 여유를 포함**한다.
그 여유를 정박 구간으로 넣지 않으면 **여유가 그대로 거리로 바뀐다.** 시연 시드
실측(`DEMO_ANCHOR` 기준):

```
V3 벌크   계획 2,300nm @14kn (소요 6.85일 · 창 12.75일)  ETA 4,284nm = 186.3%
V5 감시선 계획   500nm @13kn (소요 1.60일 · 창  5.75일)  ETA 1,794nm = 358.8%
```

## 왜 네 곳을 함께 보나

같은 값이 ``InProgressContribution``으로 **⑴ YTD → 선대 요약 → 리포트**까지
흐른다(`#750` 경로). ⑵ 「항차 구간값」 카드는 `distance_nm 624 / planned 500`처럼
**계획을 넘은 숫자를 나란히** 보여 준다. 한 곳만 고치면 나머지가 조용히 어긋난다.

케이스 (`TEST_PLAN §14.5`): 정본 정합 — `TECH_SPEC §5.4.1` 진행량 산출
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import ensure_regulation_year, insert_if_not_exists
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.cii_current import (
    WARNING_IN_PROGRESS_PAST_ETA,
    WARNING_IN_PROGRESS_PLANNED_DISTANCE_REACHED,
    get_current_cii,
)
from cii_platform.services.fleet_summary import get_fleet_summary
from cii_platform.services.report import build_annual_report
from cii_platform.services.simulation_clock import compute_progress

YEAR = 2026
DEPARTURE = datetime(YEAR, 6, 1, tzinfo=UTC)

#: 3,000 nm ÷ 14 kn = 214.29 h ≈ 8.93일. 창은 30일이라 **3.4배**가 남는다.
PLANNED_DISTANCE = Decimal("3000")
SPEED = Decimal("14")
DAILY_FOC = Decimal("30")

#: 출항 30일 뒤. 상한이 없으면 14 × 24 × 30 = **10,080 nm**(336%)가 난다.
AS_OF = datetime(YEAR, 7, 1, tzinfo=UTC)
PLANNED_ARRIVAL = datetime(YEAR, 7, 15, tzinfo=UTC)


def _progress(**over):
    params = {
        "as_of": AS_OF,
        "departure_at": DEPARTURE,
        "arrival_at": None,
        "planned_arrival_at": PLANNED_ARRIVAL,
        "planned_distance_nm": PLANNED_DISTANCE,
        "speed_kn": SPEED,
        "daily_foc_ton": DAILY_FOC,
        "reference_speed_kn": SPEED,
    }
    params.update(over)
    return compute_progress(**params)


# --------------------------------------------------------------------------
# 1. 시계 — 자르는 대상과 그 부작용
# --------------------------------------------------------------------------


def test_uncapped_run_would_have_overshot() -> None:
    """**먼저 이 픽스처가 실제로 넘치는지 확인한다.**

    넘치지 않는 입력이면 아래 검사가 **상한이 없어도 전부 통과**한다.
    """
    uncapped = _progress(planned_distance_nm=None)

    assert uncapped.distance_nm > PLANNED_DISTANCE * 3


def test_distance_lands_exactly_on_the_plan() -> None:
    """근사가 아니라 **정확히** 계획값이다.

    화면이 99.99%로 적는 것은 「거의 다 왔다」가 아니라 **틀린 값**이다.
    """
    assert _progress().distance_nm == PLANNED_DISTANCE


def test_the_cap_does_not_depend_on_decimal_precision() -> None:
    """``planned / speed``를 **다시 곱하는** 형태를 쓰지 않는다는 것을 잠근다.

    그 형태는 ``Decimal`` 문맥에 기댄다 — 기본 28자리에서는 우연히 맞아떨어져
    위 검사를 **통과해 버리지만**, ``prec=8``에서는 ``(3000/14)×14 = 2999.9999``로
    계획에 닿지 못한다. 문맥을 좁혀 그 의존을 드러낸다.
    """
    with localcontext() as ctx:
        ctx.prec = 8
        progress = _progress()

    assert progress.distance_nm == PLANNED_DISTANCE


def test_time_stops_with_the_distance() -> None:
    """거리만 자르면 ``underway_hours``가 계속 자란다.

    그러면 **같은 항차의 거리와 시간이 서로 다른 시각을 말한다.**
    """
    progress = _progress()

    assert progress.underway_hours == PLANNED_DISTANCE / SPEED


def test_fuel_stops_with_the_distance() -> None:
    """연료는 거리에서 나오므로(``distance / speed / 24``) 함께 멎어야 한다.

    연료가 계속 자라면 분자만 부풀어 **등급이 실제보다 나쁘게** 나온다.
    """
    capped = _progress()
    later = _progress(as_of=datetime(YEAR, 7, 10, tzinfo=UTC))

    assert later.fuel_ton == capped.fuel_ton
    assert later.distance_nm == capped.distance_nm


def test_the_cap_is_reported() -> None:
    """자르기만 하고 알리지 않으면 사용자는 값이 멈춘 것을 「끝났나」로 읽는다."""
    assert _progress().reached_planned_distance is True


def test_the_capped_value_is_still_simulated() -> None:
    """도착 실적이 **확정된 것이 아니라 아직 입력되지 않은** 것이다 (`#649`와 같다).

    내려 버리면 「계획이 곧 실적」이 된다.
    """
    assert _progress().is_simulated is True


def test_reaching_the_plan_is_not_passing_the_eta() -> None:
    """두 상태는 **다르다** — 계획 거리는 예정일보다 **먼저** 찬다.

    한 코드로 묶으면 화면이 「도착 예정일이 지났습니다」라고 **거짓말을 한다**.
    감시선 시드는 예정일을 **3.6일 앞서** 계획 거리를 채운다.
    """
    progress = _progress()

    assert progress.reached_planned_distance is True
    assert progress.past_planned_arrival is False


def test_a_voyage_within_its_plan_is_untouched() -> None:
    """대조군 — 아직 계획에 못 미치면 아무것도 바뀌지 않는다."""
    early = _progress(as_of=datetime(YEAR, 6, 3, tzinfo=UTC))

    assert early.reached_planned_distance is False
    assert early.distance_nm == SPEED * early.underway_hours
    assert early.distance_nm < PLANNED_DISTANCE


# --------------------------------------------------------------------------
# 2. 네 곳이 같은 값을 말하는가
# --------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    """규정 파라미터. ``tests``는 패키지가 아니라 파일마다 각자 둔다."""
    await ensure_regulation_year(session, YEAR, z_factor=9.0)
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


@pytest_asyncio.fixture
async def vessel(session):
    """확정 실적 1건 + **창이 계획보다 3.4배 긴** 진행 중 항차."""
    await _seed_parameters(session)

    vessel_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton, "
            "underway_state, detail_status) VALUES (:id, :imo, 'DISTANCE CAP TEST', "
            "'BULK_CARRIER', 50000, 'HFO', 14, 30, 'UNDER_WAY', 'SAILING')"
        ),
        {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
    )

    confirmed = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_distance_nm, actual_arrival_at, annual_inclusion_policy, "
            "regulation_year, created_from) "
            "VALUES (:id, :vid, 'CONFIRMED', 'Busan', 'Singapore', 5000, 14, "
            "5000, :arrived, 'INCLUDE_AS_ACTUAL', :year, 'MANUAL')"
        ),
        {
            "id": confirmed,
            "vid": vessel_id,
            "year": YEAR,
            "arrived": datetime(YEAR, 5, 20, tzinfo=UTC),
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "actual_fuel_ton, cf_used, source) VALUES (:id, 'HFO', 400, 400, "
            "3.114, 'USER_INPUT')"
        ),
        {"id": confirmed},
    )

    in_progress = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_departure_at, planned_arrival_at, annual_inclusion_policy, "
            "regulation_year, created_from) "
            "VALUES (:id, :vid, 'IN_PROGRESS', 'Singapore', 'Busan', :dist, 14, "
            ":departed, :eta, 'INCLUDE_AS_PLAN', :year, 'MANUAL')"
        ),
        {
            "id": in_progress,
            "vid": vessel_id,
            "year": YEAR,
            "dist": PLANNED_DISTANCE,
            "departed": DEPARTURE,
            "eta": PLANNED_ARRIVAL,
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "cf_used, source) VALUES (:id, 'HFO', 250, 3.114, 'USER_INPUT')"
        ),
        {"id": in_progress},
    )
    return vessel_id


def _number(value: str) -> Decimal:
    """표시 형식이 아니라 **값**을 본다 — 자릿수 규칙이 바뀌어도 뜻이 남는다."""
    return Decimal(value.replace(",", ""))


@pytest.mark.asyncio
async def test_the_voyage_card_does_not_exceed_its_own_plan(session, vessel) -> None:
    """⑵ 「항차 구간값」 — 같은 카드에 계획과 실적이 **나란히** 뜬다.

    `distance_nm 10,080 / planned_distance_nm 3,000`은 사용자가 그 자리에서
    이상하다는 것을 아는 종류의 값이다.
    """
    data, _ = await get_current_cii(session, vessel, year=YEAR, as_of=AS_OF)
    voyage = data["current_voyage"]

    assert voyage is not None
    assert _number(voyage["distance_nm"]) == PLANNED_DISTANCE


@pytest.mark.asyncio
async def test_ytd_carries_the_capped_contribution(session, vessel) -> None:
    """⑴ YTD — 확정 5,000 nm + 진행분 3,000 nm.

    상한이 없으면 진행분이 10,080 nm가 되어 **진행분 가중치**가 부풀고 누적
    CII가 그 항차 쪽으로 끌린다.
    """
    data, _ = await get_current_cii(session, vessel, year=YEAR, as_of=AS_OF)

    assert _number(data["ytd"]["total_distance_nm"]) == Decimal("5000") + PLANNED_DISTANCE


@pytest.mark.asyncio
async def test_the_reason_reaches_the_response(session, vessel) -> None:
    """왜 값이 더 늘지 않는지 응답이 말한다.

    ⚠️ 예정일(7/15)은 아직 오지 않았으므로 `IN_PROGRESS_PAST_ETA`는 **서면 안 된다** —
    두 코드가 한 덩어리로 붙으면 화면이 거짓말을 한다.
    """
    data, _ = await get_current_cii(session, vessel, year=YEAR, as_of=AS_OF)
    warnings = data["warnings"]

    assert WARNING_IN_PROGRESS_PLANNED_DISTANCE_REACHED in warnings
    assert WARNING_IN_PROGRESS_PAST_ETA not in warnings


@pytest.mark.asyncio
async def test_fleet_summary_agrees(session, vessel) -> None:
    """선대 요약 — 이 값 위에서 위험 배너·정렬·``days_to_d``가 돈다."""
    data, _ = await get_current_cii(session, vessel, year=YEAR, as_of=AS_OF)
    fleet = await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF)

    mine = next(v for v in fleet["vessels"] if v["vessel_id"] == str(vessel))

    assert _number(mine["ytd_attained_cii"]) == _number(data["ytd"]["attained_cii"]).quantize(
        Decimal("0.0001")
    )


@pytest.mark.asyncio
async def test_the_report_prints_the_capped_distance(session, vessel) -> None:
    """리포트 PDF가 이 값을 그대로 인쇄한다 (`#750` 경로의 끝)."""
    document = await build_annual_report(session, vessel, year=YEAR, as_of=AS_OF)

    header = next(s for s in document.sections if s.title == f"{YEAR}년 누적 (YTD)")
    rows = dict(header.rows)

    assert _number(rows["누적 거리 (nm)"]) == Decimal("5000") + PLANNED_DISTANCE


# --------------------------------------------------------------------------
# 3. HTTP에서 한 번 더 본다
# --------------------------------------------------------------------------
#
# 위 검사들은 서비스 함수를 직접 부른다. 응답 조립은 그 바깥에 있고, 새 경고 코드는
# **응답에 실려야** 뜻이 생긴다 — `#433`의 `reduction_plan`이 엔진에서는 나오는데
# 응답에는 안 나간 채 머지된 적이 있다. 화면이 보는 자리에서 한 번 더 확인한다.


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``7``로 시작한다."""
    return f"7{uuid4().int % 1_000_000:06d}"


async def _drop(vessel_id: str) -> None:
    """``TestClient``는 실제로 커밋한다 — 항차 → 선박 순으로 지운다."""
    from uuid import UUID

    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM voyage WHERE vessel_id = :v"), {"v": UUID(vessel_id)})
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": UUID(vessel_id)})
        await s.commit()


async def test_the_http_response_carries_the_capped_value(migrated_db, app_fresh_engine) -> None:
    """실시간 CII 응답의 ⑵ 항차 구간값과 경고를 **화면이 보는 자리에서** 확인한다."""
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    vessel_id: str | None = None
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            csrf = {"X-CSRF-Token": client.cookies["csrf"]}

            created = client.post(
                f"{API_V1_PREFIX}/vessels",
                json={
                    "imo_number": _imo(),
                    "name": "DISTANCE CAP HTTP",
                    "ship_type": "BULK_CARRIER",
                    "deadweight": 50000,
                    "reference_speed_kn": 14,
                    "reference_daily_foc_ton": 30,
                },
                headers=csrf,
            )
            assert created.status_code == 201, created.text
            vessel_id = created.json()["data"]["id"]

            voyage = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages",
                json={
                    "departure_port_name": "SINGAPORE",
                    "arrival_port_name": "BUSAN",
                    "planned_distance_nm": float(PLANNED_DISTANCE),
                    "planned_speed_kn": 14,
                    "planned_departure_at": DEPARTURE.isoformat(),
                    "planned_arrival_at": PLANNED_ARRIVAL.isoformat(),
                    "regulation_year": YEAR,
                    "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 250}],
                },
                headers=csrf,
            )
            assert voyage.status_code == 201, voyage.text
            voyage_id = voyage.json()["data"]["id"]

            # `DRAFT → PLANNED → IN_PROGRESS` (`API_SPEC §3.5`). 한 번에 뛰지 못한다.
            for to_status, policy in (("PLANNED", None), ("IN_PROGRESS", "INCLUDE_AS_PLAN")):
                body: dict[str, object] = {"to_status": to_status}
                if policy is not None:
                    body["annual_inclusion_policy"] = policy
                moved = client.post(
                    f"{API_V1_PREFIX}/voyages/{voyage_id}/transition",
                    json=body,
                    headers=csrf,
                )
                assert moved.status_code == 200, moved.text

            # 출항 실적은 별도 입구다 — 전환 요청은 시각을 받지 않는다.
            departed = client.put(
                f"{API_V1_PREFIX}/voyages/{voyage_id}/actuals",
                json={"actual_departure_at": DEPARTURE.isoformat()},
                headers=csrf,
            )
            assert departed.status_code == 200, departed.text

            current = client.get(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/cii/current",
                params={"year": YEAR, "as_of": AS_OF.isoformat()},
            )

        assert current.status_code == 200, current.text
        body = current.json()["data"]

        assert _number(body["current_voyage"]["distance_nm"]) == PLANNED_DISTANCE
        assert WARNING_IN_PROGRESS_PLANNED_DISTANCE_REACHED in body["warnings"]
        assert WARNING_IN_PROGRESS_PAST_ETA not in body["warnings"]
    finally:
        if vessel_id is not None:
            await _drop(vessel_id)
