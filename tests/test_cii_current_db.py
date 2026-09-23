"""실시간 CII 3종 값 서비스 검증 (#354).

수치 자체는 ``#353``(YTD 엔진)과 ``#368``(시뮬레이션 시계)이 이미 계산하고 각자
테스트가 있다. **이 모듈의 결함은 계산이 아니라 조합에서 난다.**

* **등급이 ⑵에 붙지 않는 것** — ``PRD §3.3`` 표 · ``COR-1``. 항차 하나에 등급을
  붙이면 규제에 없는 말이 만들어진다.
* **진행분을 반쪽만 넣지 않는 것** — 거리만 넣으면 분모 ``Dt``만 늘어
  **항해할수록 등급이 좋아진다.** 실제로 소모율이 없는 선박에서 이 상태가 된다.
* **``as_of``를 한 번만 확정하는 것** — 값마다 시각이 다르면 셋이 서로 모순된다.
* **못 낸 이유를 말하는 것** — 사유 없는 빈칸은 「로딩 중」으로 읽힌다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import ensure_regulation_year, insert_if_not_exists
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.services.cii_current import (
    DRIVER_BASIS_DIFFERENCE,
    DRIVER_CURRENT_VOYAGE,
    DRIVER_REMAINING_PLAN,
    REASON_NO_BASIS,
    REASON_YEAR_COMPLETE,
    WARNING_NO_REMAINING_PLAN,
    WARNING_SIM_NO_FUEL_RATE,
    get_current_cii,
    resolve_in_progress_state,
)

YEAR = 2026
MID_YEAR = datetime(YEAR, 7, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    """규정 파라미터를 멱등하게 심는다 (``test_fleet_summary.py``와 같은 방식)."""
    await ensure_regulation_year(session, 2026)
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
    """이 테스트 전용 선박. 트랜잭션이 롤백되므로 실제 데이터는 그대로다."""
    await _seed_parameters(session)
    vessel_id = uuid4()
    fields = {
        "id": vessel_id,
        "imo": f"9{vessel_id.int % 1000000:06d}",
        "speed": Decimal("14"),
        "foc": Decimal("30"),
        "fuel": "HFO",
        # chk_vessel_state_pair — 둘은 함께 있거나 함께 없어야 한다(마이그레이션 026).
        "state": "UNDER_WAY",
        "detail": "SAILING",
    }
    fields.update(over)
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton, "
            "underway_state, detail_status) VALUES (:id, :imo, 'CURRENT TEST', "
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
        # `#649` — 시계가 예정일에서 자르는지 검증하려면 이 값이 필요하다.
        "planned_arrival": planned_arrival_at,
        # ⚠️ **기본값은 `INCLUDE_AS_PLAN`이다** (`#1085`). 종전에는 `EXCLUDE`였고, 이 파일의
        # 진행분 검사 8건이 **「연간 반영 안 함」 항차가 누적에 들어가는 것을 사전 조건으로**
        # 단언했다 — `#1085`가 고친 결함을 검사가 정답으로 들고 있었다. `_add_actuals`는
        # 실적 확정 시 정책을 `INCLUDE_AS_ACTUAL`로 덮으므로 확정분 경로는 영향이 없다.
        # `EXCLUDE`를 보는 검사는 그 값을 **명시적으로** 넘긴다.
        "policy": "INCLUDE_AS_PLAN",
        "year": YEAR,
        # `#1321` — 시계가 **계획 거리에서도** 자른다. 3,000nm ÷ 14kn ≈ 8.9일이라,
        # 그보다 오래 뛰는 항차를 보려면 계획을 늘려야 한다. 기본값은 그대로 둔다.
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


async def _add_actuals(session, voyage_id, *, distance="5000", fuel="400") -> None:
    """실적 확정 항차 — YTD의 근거를 만든다."""
    await session.execute(
        text(
            "UPDATE voyage SET status='CONFIRMED', "
            "annual_inclusion_policy='INCLUDE_AS_ACTUAL', "
            "actual_distance_nm=:distance, "
            "actual_arrival_at=:arrived WHERE id=:id"
        ),
        {
            "id": voyage_id,
            "distance": Decimal(distance),
            "arrived": datetime(YEAR, 6, 20, tzinfo=UTC),
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


# ─────────────────────────────────────────────────────────────────────────────
# 등급은 ⑴에만 붙는다 — PRD §3.3 표 · COR-1
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rating_is_on_ytd_only(session):
    """⑵ 항차 구간값에 등급을 붙이면 「이 항차는 D등급」이라는 규제에 없는 말이 된다."""
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert data["ytd"]["rating"] is not None
    # 값은 있는데 등급만 없어야 한다 — 필드 자체를 빼면 화면이 「아직 안 온 값」으로
    # 오해하고 스스로 등급을 만들어 낸다.
    assert data["current_voyage"]["attained_cii"] is not None
    assert data["current_voyage"]["rating"] is None


@pytest.mark.asyncio
async def test_projection_has_a_rating(session):
    """⑶은 등급이 붙는다 — `COR-2`가 표기를 「연말 예상 등급」으로 정한다."""
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert data["year_end_projection"]["data_available"] is True
    assert data["year_end_projection"]["rating"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 진행분을 반쪽만 넣지 않는다 — 이 이슈에서 실제로 잡힌 결함
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_distance_without_fuel_is_not_injected(session):
    """소모율이 없으면 시계가 연료를 0으로 낸다. **그 거리를 넣으면 안 된다.**

    분모 `Dt`만 늘고 분자 `M`은 그대로라 **항해할수록 등급이 좋아진다.** 값은
    화면에서 멀쩡해 보이고 방향만 틀린다 — 가장 나쁜 종류의 결함이다.
    """
    vessel_id = await _make_vessel(session, foc=None)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))

    with_clock, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    # 실적만으로 계산한 값과 같아야 한다 — 진행분이 섞이지 않았다는 뜻이다.
    assert with_clock["current_voyage"]["distance_nm"] != "0.00"
    assert with_clock["current_voyage"]["fuel_ton"] == "0.00"
    assert WARNING_SIM_NO_FUEL_RATE in with_clock["warnings"]


@pytest.mark.asyncio
async def test_missing_fuel_rate_is_reported_not_hidden(session):
    """값이 안 변하는 것을 화면이 「출항 전」으로 오해하면 제원을 채울 생각을 못 한다."""
    vessel_id = await _make_vessel(session, foc=None)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert WARNING_SIM_NO_FUEL_RATE in data["warnings"]


@pytest.mark.asyncio
async def test_progress_is_injected_when_both_sides_exist(session):
    """거리와 연료가 둘 다 있으면 진행분이 YTD를 **악화**시킨다.

    진행 중 항차는 실적 항차보다 연비가 나쁘게 설정돼 있으므로 누적 CII가 커진다 —
    시간이 지나면 값이 변한다는 것이 명세 3의 요구다.
    """
    vessel_id = await _make_vessel(session, foc=Decimal("120"))
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    # `#1321` — 계획 거리를 넉넉히 준다. 기본 3,000nm는 14kn로 **8.9일**이면 차고,
    # 그 뒤로는 시계가 값을 늘리지 않는다(그것이 `#1321`이 고친 것이다). 아래 두
    # 시점(6/21 · 7/1)은 출항 6/1에서 20·30일 뒤라 **둘 다 상한 뒤**가 되어 값이
    # 같아진다 — 이 검사가 보려는 것은 상한이 아니라 **진행분이 값을 움직이는가**다.
    await _make_voyage(
        session,
        vessel_id,
        departed_at=datetime(YEAR, 6, 1, tzinfo=UTC),
        planned_distance=30000,
    )

    # 두 시점 **모두** 확정 항차가 이미 집계에 든 뒤로 잡는다. 확정 항차가 중간에
    # 들어오면 그 항차의 연비가 평균을 희석해 값이 좋아지고, 그건 시계가 만든
    # 변화가 아니다 — 비교 대상이 섞이면 이 테스트는 아무것도 고정하지 못한다.
    early, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR, 6, 21, tzinfo=UTC)
    )
    later, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR, 7, 1, tzinfo=UTC)
    )

    assert Decimal(later["ytd"]["attained_cii"]) > Decimal(early["ytd"]["attained_cii"])


# ─────────────────────────────────────────────────────────────────────────────
# 정박 중 악화 — 명세 3-③
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_not_underway_fuel_worsens_the_grade(session):
    """정박 연료는 분자만 늘린다 — 거리가 늘지 않으므로 CII가 나빠진다.

    이것이 `#370` 입력 경로가 존재하는 이유이고, 이 화면이 보여 줘야 하는 것이다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    before, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    period_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
            "period_type, started_at, distance_nm) VALUES (:id, :vid, 2026, "
            "'AT_ANCHOR', '2026-06-25T00:00:00Z', 0)"
        ),
        {"id": period_id, "vid": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'OIL_FIRED_BOILER', 'HFO', 40, 3.114)"
        ),
        {"id": period_id},
    )

    after, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert Decimal(after["ytd"]["attained_cii"]) > Decimal(before["ytd"]["attained_cii"])


@pytest.mark.asyncio
async def test_projection_counts_the_same_berth_co2_as_ytd(session):
    """⑶ 연말 예상의 확정분에 **⑴과 같은** 정박 CO₂가 들어간다 (#1803).

    종전에는 ⑴만 정박을 넣고 ⑶은 빼서, 같은 화면의 두 숫자가 같은 사실(이미 쓴 연료)을
    다르게 셌다 — 정박이 긴 배일수록 「지금은 나쁜데 연말엔 좋아진다」로 읽혔다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _add_plan(session, vessel_id)

    before, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    period_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
            "period_type, started_at, distance_nm) VALUES (:id, :vid, 2026, "
            "'AT_ANCHOR', '2026-06-25T00:00:00Z', 0)"
        ),
        {"id": period_id, "vid": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'OIL_FIRED_BOILER', 'HFO', 40, 3.114)"
        ),
        {"id": period_id},
    )

    after, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    added = Decimal(after["year_end_projection"]["assumptions"]["completed_co2_ton"]) - Decimal(
        before["year_end_projection"]["assumptions"]["completed_co2_ton"]
    )
    assert added == Decimal(after["ytd"]["not_underway_co2_ton"]), (
        "⑶ 확정분에 들어간 정박 CO₂가 ⑴의 정박 CO₂와 다르다"
    )
    assert Decimal(after["year_end_projection"]["attained_cii"]) > Decimal(
        before["year_end_projection"]["attained_cii"]
    ), "정박 연료를 넣었는데 연말 예상이 나빠지지 않았다 — ⑶이 정박을 빼고 있다"


# ─────────────────────────────────────────────────────────────────────────────
# as_of 계약 — #368 ⑵·⑶
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_as_of_is_returned(session):
    """화면은 이 값으로 다시 물어 같은 결과를 얻는다."""
    vessel_id = await _make_vessel(session)
    _, meta = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert meta["as_of"] == MID_YEAR.isoformat()


@pytest.mark.asyncio
async def test_server_resolves_as_of_when_omitted(session):
    """미지정이면 서버가 확정하고 응답에 싣는다 — 계약 ⑵."""
    vessel_id = await _make_vessel(session)
    _, meta = await get_current_cii(session, vessel_id, year=YEAR)
    assert isinstance(meta["as_of"], str) and meta["as_of"]


@pytest.mark.asyncio
async def test_same_as_of_gives_the_same_answer(session):
    """재현성 — `TECH_SPEC §5.4` 「동일 입력 → 동일 결과」."""
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))

    first, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    second, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert first == second


@pytest.mark.asyncio
async def test_simulated_flag_marks_clock_derived_values(session):
    """`PRD R-5` 시뮬레이션 배지의 근거를 **서버가 판정**한다.

    화면이 스스로 판정하면 배지를 감출 근거를 만들 수 있다.
    """
    vessel_id = await _make_vessel(session)
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 1, tzinfo=UTC))

    _, meta = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert meta["simulated"] is True


@pytest.mark.asyncio
async def test_no_voyage_is_not_simulated(session):
    vessel_id = await _make_vessel(session)
    _, meta = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert meta["simulated"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 「없는 것」을 사유와 함께 말한다
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_data_is_not_an_error(session):
    """실적이 없는 선박은 정상 상태다 — 신규 등록 선박이 전부 오류로 보이면 안 된다."""
    vessel_id = await _make_vessel(session)
    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert data["ytd"]["data_available"] is False
    assert data["ytd"]["attained_cii"] is None
    assert data["current_voyage"] is None


@pytest.mark.asyncio
async def test_projection_says_why_it_cannot_be_made(session):
    """사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다."""
    vessel_id = await _make_vessel(session)
    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert data["year_end_projection"]["data_available"] is False
    assert data["year_end_projection"]["reason"] == REASON_NO_BASIS


@pytest.mark.asyncio
async def test_projection_is_not_made_after_year_end(session):
    """남은 기간이 0이면 ⑶은 ⑴과 같은 값이라 따로 낼 이유가 없다."""
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    data, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR + 1, 3, 1, tzinfo=UTC)
    )
    assert data["year_end_projection"]["reason"] == REASON_YEAR_COMPLETE


@pytest.mark.asyncio
async def test_projection_carries_its_assumptions(session):
    """`PRD §3.3` ⑶ — 화면이 「⑶만 크게 표시하지 않는다」를 지키려면 근거가 필요하다.

    `#798`에서 `assumptions`의 내용이 바뀌었다. `daily_distance_nm`·`daily_fuel_ton`은
    **일평균 외삽에서만 의미가 있던 값**이라 남은 거리 기반에서는 뜻이 없다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assumptions = data["year_end_projection"]["assumptions"]

    assert assumptions["method"] == "REMAINING_PLAN"
    for key in (
        "remaining_days",
        "remaining_voyage_count",
        "planned_distance_nm",
        "planned_co2_ton",
        "completed_distance_nm",
        "completed_co2_ton",
    ):
        assert assumptions[key] is not None, key

    # 없어진 필드가 되살아나면 화면이 뜻 없는 숫자를 다시 인쇄한다.
    for gone in ("elapsed_days", "daily_distance_nm", "daily_fuel_ton"):
        assert gone not in assumptions, gone


# ─────────────────────────────────────────────────────────────────────────────
# ⑶ 연말 예상은 「남은 거리 기반」이다 (#798)
#
# 종전 방식(`YTD_DAILY_AVERAGE`)은 지금까지의 일평균을 잔여 기간에 곱해 ⑴에 더했다.
# 거리와 연료를 **같은 비율로** 더하므로 `M/W`가 보존되어 ⑶이 **구조적으로 ⑴과 항상
# 같은 값**이 됐다 — 데모 4척 전부에서 실측됐고, 연간 리포트는 같은 숫자를 「누적」과
# 「연말 예상」 두 제목으로 나란히 인쇄했다.
# ─────────────────────────────────────────────────────────────────────────────


async def _add_plan(session, vessel_id, *, distance="10000", fuel="1200") -> None:
    """잔여 계획 항차 — ⑶의 근거를 만든다 (`annual_inclusion_policy=INCLUDE_AS_PLAN`).

    연료를 **반드시 함께 넣는다.** 연료가 없는 계획 항차는 `#812`가 계산에서 빼므로,
    거리만 넣으면 이 픽스처가 아무 잔여분도 만들지 못한다.
    """
    voyage_id = await _make_voyage(
        session,
        vessel_id,
        status="PLANNED",
        policy="INCLUDE_AS_PLAN",
        departed_at=None,
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


@pytest.mark.asyncio
async def test_projection_differs_from_ytd_when_plans_remain(session):
    """잔여 계획이 있으면 ⑶ ≠ ⑴ — `#798`의 완료 기준 1.

    계획 항차의 **연료 강도**(1200t / 10000nm)를 확정분(400t / 5000nm)과 다르게 둔다.
    같게 두면 남은 거리 기반으로 고쳐도 값이 같아져 이 검사가 통과해 버린다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    projection = data["year_end_projection"]

    assert projection["data_available"] is True
    assert projection["attained_cii"] != data["ytd"]["attained_cii"], (
        "⑶이 ⑴과 같다 — 일평균 외삽으로 되돌아갔다 (#798)"
    )
    assert projection["assumptions"]["remaining_voyage_count"] == 1


@pytest.mark.asyncio
async def test_projection_matches_the_annual_simulation(session):
    """⑶이 기능③의 `projected_attained_cii`와 **문자 단위로 같다** — 완료 기준 2.

    같은 이름의 값이 두 화면에서 다른 숫자였다(`#798` 실측: 7.654488 vs 8.971119).
    두 경로가 같은 함수를 부르므로 이제 갈릴 수 없다 — 한쪽만 고치면 이 검사가 깨진다.

    기능③ 자체를 돌리지 않고 **같은 입력 조립 + 같은 엔진**을 직접 불러 비교한다.
    기능③ 실행은 스냅샷 저장·Monte Carlo를 동반해 이 검사의 대상이 아니다.
    """
    from cii_platform.calc.annual_simulation import project_deterministic
    from cii_platform.services.annual_simulation import (
        collect_annual_inputs,
        load_projection_context,
    )
    from cii_platform.services.cii_current import _publish

    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    context = await load_projection_context(session, vessel_id=vessel_id, regulation_year=YEAR)
    inputs = await collect_annual_inputs(
        session, vessel=context.vessel, vessel_id=vessel_id, year=YEAR, as_of=MID_YEAR
    )
    deterministic = project_deterministic(
        completed=inputs.completed,
        remaining=inputs.remaining,
        transport_capacity=context.transport_capacity,
        required_cii=context.required_cii,
        d_vector=context.d_vector,
    )

    assert data["year_end_projection"]["attained_cii"] == _publish(
        deterministic.attained_cii, "cii"
    )
    assert data["year_end_projection"]["rating"] == deterministic.rating


@pytest.mark.asyncio
async def test_projection_says_when_no_plans_remain(session):
    """잔여 계획이 0건이면 값을 내되 **왜 ⑴과 같은지** 말한다 — `#798` 판단 B.

    빈칸을 두지 않는다: 잔여 계획이 없으면 「연말 = 지금」이 맞는 답이고, 빈칸은
    「아직 로딩 중」으로 읽힌다. 다만 그 답은 **종전 결함(항상 ⑴과 같음)과 화면에서
    구분되지 않으므로** 경고로 성격을 밝힌다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    projection = data["year_end_projection"]

    assert projection["data_available"] is True
    assert projection["attained_cii"] == data["ytd"]["attained_cii"]
    assert WARNING_NO_REMAINING_PLAN in projection["warnings"]
    assert projection["assumptions"]["remaining_voyage_count"] == 0


@pytest.mark.asyncio
async def test_projection_risk_level_is_one_of_the_four(session):
    """`risk_level`이 실재하는 값이다 — `API_SPEC` 예시의 `"WATCH"`는 코드에 없다.

    `calc/rating_engine.py`의 허용값은 넷뿐이다. 정본 예시가 없는 값을 인쇄하고
    있었고(`#798` 곁가지), 이 이슈에서 함께 고쳤다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert data["year_end_projection"]["risk_level"] in {
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 직렬화·오류
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_numbers_are_strings(session):
    """`API_SPEC §1.7` — float으로 되돌리면 Layer 1이 지킨 정밀도가 사라진다."""
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert isinstance(data["ytd"]["attained_cii"], str)
    assert isinstance(data["ytd"]["required_cii"], str)
    # 소수 6자리로 고정된다.
    assert len(data["ytd"]["attained_cii"].split(".")[1]) == 6


@pytest.mark.asyncio
async def test_reference_only_warning_is_always_present(session):
    """`API_SPEC §1.6` — 모든 계산 결과에 붙는다."""
    vessel_id = await _make_vessel(session)
    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert "REFERENCE_ONLY" in data["warnings"]


# ─────────────────────────────────────────────────────────────────────────────
# 도착 예정일 초과 (#649)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_past_eta_stops_the_clock_and_says_so(session):
    """진행 중 항차가 예정일을 지나면 **누적이 멈추고 그 사실이 응답에 실린다**.

    종전에는 상한이 없어 `as_of`가 멀어질수록 거리·연료가 계속 자랐다. 실사용에서
    이 상태는 「운항이 계속되고 있다」가 아니라 **「도착 실적 입력을 잊었다」**이며,
    그 사실이 드러나야 사용자가 고칠 대상을 찾는다.
    """
    vessel_id = await _make_vessel(session)
    departed = datetime(YEAR, 6, 1, tzinfo=UTC)
    eta = datetime(YEAR, 6, 10, tzinfo=UTC)
    await _make_voyage(session, vessel_id, departed_at=departed, planned_arrival_at=eta)

    at_eta, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=eta)
    long_after, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR, 9, 1, tzinfo=UTC)
    )

    assert at_eta["current_voyage"]["distance_nm"] == long_after["current_voyage"]["distance_nm"]
    assert "IN_PROGRESS_PAST_ETA" in long_after["warnings"]


@pytest.mark.asyncio
async def test_before_eta_has_no_warning_and_keeps_growing(session):
    """예정일 전에는 종전과 같다 — 경고도 붙지 않는다."""
    vessel_id = await _make_vessel(session)
    departed = datetime(YEAR, 6, 1, tzinfo=UTC)
    eta = datetime(YEAR, 6, 30, tzinfo=UTC)
    await _make_voyage(session, vessel_id, departed_at=departed, planned_arrival_at=eta)

    early, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR, 6, 5, tzinfo=UTC)
    )
    later, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR, 6, 20, tzinfo=UTC)
    )

    assert Decimal(later["current_voyage"]["distance_nm"]) > Decimal(
        early["current_voyage"]["distance_nm"]
    )
    assert "IN_PROGRESS_PAST_ETA" not in later["warnings"]


@pytest.mark.asyncio
async def test_voyage_without_planned_arrival_is_unchanged(session):
    """예정일이 없는 항차는 종전대로 `as_of`까지 센다 — 없는 상한을 만들지 않는다."""
    vessel_id = await _make_vessel(session)
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 1, tzinfo=UTC))

    data, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR, 9, 1, tzinfo=UTC)
    )

    assert Decimal(data["current_voyage"]["distance_nm"]) > 0
    assert "IN_PROGRESS_PAST_ETA" not in data["warnings"]


@pytest.mark.asyncio
async def test_unknown_vessel_is_404(session):
    with pytest.raises(NotFoundError):
        await get_current_cii(session, uuid4(), year=YEAR, as_of=MID_YEAR)


@pytest.mark.asyncio
async def test_year_out_of_range_is_422(session):
    vessel_id = await _make_vessel(session)
    with pytest.raises(ValidationError):
        await get_current_cii(session, vessel_id, year=1900, as_of=MID_YEAR)


@pytest.mark.asyncio
async def test_year_defaults_to_the_as_of_year(session):
    vessel_id = await _make_vessel(session)
    data, _ = await get_current_cii(session, vessel_id, as_of=MID_YEAR)
    assert data["regulation_year"] == YEAR


@pytest.mark.asyncio
async def test_capacity_basis_comes_from_the_server(session):
    """`DESIGN_SYSTEM §4.1` 🔒 — 화면이 선종에서 단위를 유추하면 서버와 갈라진다."""
    vessel_id = await _make_vessel(session)
    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert data["transport_capacity_basis"] == "DWT"


@pytest.mark.asyncio
async def test_warns_when_reference_speed_is_missing(session):
    """기준 속도가 없으면 **보정을 못 했다는 사실을 알린다** (#796).

    배수 1로 쌓되 조용히 넘어가지 않는다. 소모율도 속도도 있고 모르는 것이 보정
    계수 하나뿐이라 기여를 통째로 빼지는 않지만, 값이 정확하지 않다는 사실은 화면이
    말할 수 있어야 사용자가 제원을 채운다.
    """
    vessel_id = await _make_vessel(session, speed=None)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    # 항차 계획 속도는 있다 — 없는 것은 **선박 기준 속도**뿐이다.
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert "SIMULATION_NO_REFERENCE_SPEED" in data["warnings"]


@pytest.mark.asyncio
async def test_no_reference_speed_warning_when_the_spec_is_present(session):
    """제원이 있으면 경고가 **붙지 않는다** — 늘 붙으면 판정이 무의미하다 (#796)."""
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert "SIMULATION_NO_REFERENCE_SPEED" not in data["warnings"]


@pytest.mark.asyncio
async def test_representative_fuel_survives_a_row_update(session):
    """연료 행 하나를 고쳐도 진행 중 항차의 **대표 유종이 바뀌지 않는다** (#867).

    ## 무엇이 문제였나

    ``voyage_repo.list_fuel_uses``에 ``ORDER BY``가 없어 PostgreSQL이 힙 순서를
    줬다. 소비처(``_voyage_fuel_code``)가 **「첫 항목」에 의존**하므로, 행 하나를
    UPDATE하는 정상 조작만으로 대표 유종이 뒤집혀 CO₂ 기여가 튀었다 — 실측에서
    HFO(CF 3.114)가 DIESEL_GAS_OIL(3.206)로 바뀌었다.

    ## 무엇을 보는가

    2유종 항차에서 조회 → UPDATE → 재조회의 대표 유종이 같은지 본다. 정렬이
    유종순이므로 사전순 앞인 ``DIESEL_GAS_OIL``이 안정적으로 대표가 된다.

    ⚠️ **어느 유종이 대표여야 하는가는 이 검사의 범위가 아니다.** `#885`가 연료를
    **계획 비율로 안분**하도록 바꿨고, 대표 유종은 표시용(계획량 최대, 같으면 유종순
    앞)으로만 남았다 — 아래 두 유종은 계획량이 같아 유종순 앞이 대표다. 여기서 고정하는
    것은 **같은 데이터가 같은 답을 내는가**다.
    """
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    in_progress = await _make_voyage(
        session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    # 2유종 — 삽입 순서를 사전순의 반대로 둬서 정렬이 실제로 일하는지 본다.
    for fuel_type, cf in (("HFO", "3.114"), ("DIESEL_GAS_OIL", "3.206")):
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
                "cf_used, source) VALUES (:id, :ft, 100, :cf, 'USER_INPUT')"
            ),
            {"id": in_progress, "ft": fuel_type, "cf": Decimal(cf)},
        )

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    before = (await resolve_in_progress_state(session, vessel=vessel, as_of=MID_YEAR)).fuel_code

    # 힙 순서를 흔드는 정상 조작 — 실적 연료를 한 줄 채워 넣는다.
    await session.execute(
        text(
            "UPDATE voyage_fuel_use SET actual_fuel_ton = 50 "
            "WHERE voyage_id = :id AND fuel_type = 'HFO'"
        ),
        {"id": in_progress},
    )

    after = (await resolve_in_progress_state(session, vessel=vessel, as_of=MID_YEAR)).fuel_code

    assert before == after, f"행 하나를 고쳤더니 대표 유종이 바뀌었다: {before} → {after}"
    assert before == "DIESEL_GAS_OIL", (
        f"정렬이 유종순이 아니다 — 삽입 순서(HFO 먼저)가 남아 있다: {before}"
    )


async def _add_planned_fuels(session, voyage_id, plans):
    for fuel_type, planned, cf in plans:
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
                "cf_used, source) VALUES (:id, :ft, :planned, :cf, 'USER_INPUT')"
            ),
            {"id": voyage_id, "ft": fuel_type, "planned": planned, "cf": Decimal(cf)},
        )


@pytest.mark.asyncio
async def test_multi_fuel_progress_is_split_by_planned_ratio(session):
    """다유종 진행 항차의 연료가 **계획 비율로 나뉘어** 각 유종의 CF를 받는다 (`#885`).

    종전에는 총 진행 연료 **전량에 첫 유종 하나의 CF**를 곱했다. HFO 60 t + 가스오일
    40 t 계획이면 소수 유종인 가스오일(3.206)이 전체를 대표했다. 같은 축의 다른
    갈래(YTD 항해 연료 `#863` · not under way `030`)는 이미 유종별이었다.

    **합이 총량과 정확히 같은지**도 본다 — 몫마다 곱하면 반올림 찌꺼기로 누적 연료가
    원래보다 미세하게 달라질 수 있어, 마지막 몫은 「총량 − 나머지」로 둔다.
    """
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    in_progress = await _make_voyage(
        session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    await _add_planned_fuels(
        session, in_progress, [("HFO", 60, "3.114"), ("DIESEL_GAS_OIL", 40, "3.206")]
    )

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    state = await resolve_in_progress_state(session, vessel=vessel, as_of=MID_YEAR)
    assert state.contribution is not None, "사전 조건: 진행분이 누적에 들어가야 한다"

    total = state.progress.fuel_ton
    parts = dict(state.contribution.fuel_uses)
    assert set(parts) == {"HFO", "DIESEL_GAS_OIL"}
    assert parts["HFO"] + parts["DIESEL_GAS_OIL"] == total
    # 60 : 40 — 반올림 찌꺼기는 마지막 몫이 흡수하므로 근사로 본다.
    assert abs(parts["HFO"] / total - Decimal("0.6")) < Decimal("1e-20")
    # 표시용 대표는 계획량이 가장 큰 유종이다.
    assert state.fuel_code == "HFO"


@pytest.mark.asyncio
async def test_segment_co2_uses_the_same_split(session):
    """``current_voyage`` 구간 CO₂가 누적 기여분과 **같은 몫**으로 계산된다 (`#885`).

    한쪽만 나누면 같은 항차의 구간 CO₂와 누적에 들어간 CO₂가 설명 없이 다르다.
    """
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    in_progress = await _make_voyage(
        session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    await _add_planned_fuels(
        session, in_progress, [("HFO", 60, "3.114"), ("DIESEL_GAS_OIL", 40, "3.206")]
    )

    data, _meta = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    segment = data["current_voyage"]
    fuel = Decimal(segment["fuel_ton"])
    expected = fuel * (Decimal("0.6") * Decimal("3.114") + Decimal("0.4") * Decimal("3.206"))
    # 공개값은 2자리 반올림이다(`co2_ton`).
    assert abs(Decimal(segment["co2_ton"]) - expected) <= Decimal("0.01"), (
        f"구간 CO₂ {segment['co2_ton']} ≠ 안분 기대값 {expected:.4f}"
    )
    assert segment["fuel_type"] == "HFO"


@pytest.mark.asyncio
async def test_single_fuel_progress_is_unchanged(session):
    """단일 유종 항차는 **종전과 같은 값**을 낸다 — 몫이 1이다 (현재 대다수)."""
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    in_progress = await _make_voyage(
        session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    await _add_planned_fuels(session, in_progress, [("HFO", 80, "3.114")])

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    state = await resolve_in_progress_state(session, vessel=vessel, as_of=MID_YEAR)
    assert state.contribution.fuel_uses == (("HFO", state.progress.fuel_ton),)


@pytest.mark.asyncio
async def test_missing_planned_fuel_falls_back_to_the_first_fuel(session):
    """계획량이 비어 있으면(전부 ``NULL``) **종전대로 첫 유종 하나**다 — 비율을 만들 근거가 없다.

    ``chk_fuel_positive``가 계획량 0을 막으므로 합이 0이 되는 길은 ``NULL``뿐이다 —
    계획 없이 **실적만 기록된** 연료 행이다.
    """
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    in_progress = await _make_voyage(
        session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    await _add_planned_fuels(
        session, in_progress, [("HFO", None, "3.114"), ("DIESEL_GAS_OIL", None, "3.206")]
    )

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    state = await resolve_in_progress_state(session, vessel=vessel, as_of=MID_YEAR)
    # 유종순(`#867`) 첫 항목이 전량을 받는다.
    assert state.contribution.fuel_uses == (("DIESEL_GAS_OIL", state.progress.fuel_ton),)


def test_split_parts_sum_exactly_to_the_total():
    """몫대로 나눈 연료의 합이 **총량과 정확히 같다** — 반올림 찌꺼기가 없다 (`#885`).

    3등분처럼 몫이 딱 떨어지지 않으면 곱한 값의 합이 총량에서 미세하게 벗어난다.
    실측에서 ``91.3333``이 ``91.33329999…``가 됐다. 누적 연료가 원래보다 달라지면 같은
    화면의 「누적 연료」와 CO₂가 설명되지 않는다 — 그래서 마지막 몫을 「총량 − 나머지」로
    둔다. 60:40 같은 비율은 찌꺼기가 없어 위 DB 검사로는 이 보정을 볼 수 없다.
    """
    from cii_platform.services.cii_current import _split_fuel

    third = Decimal(1) / Decimal(3)
    for total in (Decimal("91.3333"), Decimal("0.7777"), Decimal("137.4521")):
        parts = _split_fuel(total, (("A", third), ("B", third), ("C", third)))
        assert sum(ton for _, ton in parts) == total, f"{total}: 합이 어긋남"


# ─── 「연간 반영 안 함」 진행 항차 (#1085) ───────────────────────────────────


@pytest.mark.asyncio
async def test_an_excluded_in_progress_voyage_is_not_accumulated(session):
    """⚠️ #1085 — `EXCLUDE` 진행 항차는 YTD에 **한 톤도 더하지 않는다**.

    `PRD §3.3.8` 「집계에 넣는 항차의 범위」 표가 `EXCLUDE`를 「넣지 않는다」로 정한다.
    확정분은 `list_annual_inclusions`가 정책으로 거르는데 진행분은 `find_in_progress`가
    **상태로만** 골라 정책을 보지 않았다 — `PRD §8.1.2`상 `IN_PROGRESS + EXCLUDE`는
    합법이라 데이터 오류로 걸러지지도 않는다.

    **확정분만 있는 선대와 값이 같아야 한다**가 이 검사의 요지다. 「진행분이 줄었다」가
    아니라 「없는 것과 같다」를 봐야 종전 결함(항해 중에는 늘다가 완료되는 순간 빠져
    누적 CII가 한 번에 뛰는 것)이 잡힌다.
    """
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    baseline, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    excluded = await _make_voyage(
        session,
        vessel_id,
        policy="EXCLUDE",
        departed_at=datetime(YEAR, 6, 25, tzinfo=UTC),
    )
    await _add_planned_fuels(session, excluded, [("HFO", 60, "3.114")])
    after, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert after["ytd"] == baseline["ytd"], "EXCLUDE 진행 항차가 누적을 바꿨다"
    # ⑵ 항차 구간값은 **그대로 보인다** — `§3.3.8`의 3종 표에서 ⑵는 ⑴과 별개 값이고,
    # 집계 범위 표는 ⑴에만 걸린다. 지금 실제로 뛰는 항차를 화면에서 지울 이유가 없다.
    assert after["current_voyage"] is not None


@pytest.mark.asyncio
async def test_a_yearless_in_progress_voyage_still_shows_as_the_current_voyage(session):
    """⚠️ #1336 — **연도를 선언하지 않은 진행 항차가 ⑵에서 사라졌다**.

    `chk_year_policy`(`DB_SCHEMA §2.3`)상 `regulation_year IS NULL`은 **반드시
    `EXCLUDE`**이고 `PRD §8.1.2`상 `IN_PROGRESS + EXCLUDE`는 합법이다. 그런데
    :meth:`InProgressState.for_year`가 ``None != 2026``으로 **상태 전체를 비워**,
    선박은 ``UNDER_WAY``인데 「현재 항차」 카드가 없고 ``meta.simulated``도 내려갔다.

    `#1085`가 이미 **⑴만 비우고 ⑵는 남긴다**로 판단한 자리다 — `for_year`가 그 뒤에서
    되돌리고 있었다.
    """
    vessel_id = await _make_vessel(session)
    await _make_voyage(
        session,
        vessel_id,
        policy="EXCLUDE",
        year=None,
        departed_at=datetime(YEAR, 6, 25, tzinfo=UTC),
    )

    data, meta = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert data["current_voyage"] is not None, "연도 없는 진행 항차가 ⑵에서 사라졌다"
    assert meta["simulated"] is True


@pytest.mark.asyncio
async def test_a_yearless_voyage_adds_nothing_to_the_year_total(session):
    """**⑵를 되살리면서 ⑴까지 되살리지 않는다** (`#1336` · `#1085`).

    이것이 없으면 위 검사를 「`for_year`를 통째로 없앤다」로 만족시킬 수 있고, 그러면
    `#1085`가 막은 것(연간 반영 안 함 항차가 누적에 드는 것)이 되돌아온다.

    ⚠️ **반대쪽(다른 해에 속한다고 선언한 항차)은 여기서 보지 않는다** —
    `tests/test_in_progress_year_scope_db.py`(`#815`)가 본다. `for_year`를 통째로
    없애는 돌연변이는 **그 파일에서 3건**으로 잡힌다. 이 파일만 돌리면 그 과잉
    수정이 통과하므로, 이 함수를 손댈 때는 두 파일을 함께 돌린다.
    """
    vessel_id = await _make_vessel(session)
    confirmed = await _make_voyage(session, vessel_id)
    await _add_actuals(session, confirmed)
    baseline, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    yearless = await _make_voyage(
        session,
        vessel_id,
        policy="EXCLUDE",
        year=None,
        departed_at=datetime(YEAR, 6, 25, tzinfo=UTC),
    )
    await _add_planned_fuels(session, yearless, [("HFO", 60, "3.114")])
    after, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert after["ytd"] == baseline["ytd"], "연도 없는 항차가 누적을 바꿨다"
    assert after["current_voyage"] is not None


@pytest.mark.asyncio
async def test_an_excluded_voyage_does_not_ask_the_user_to_fix_specs(session):
    """⚠️ #1085 — `EXCLUDE` 항차에는 **누적 반영 경고를 띄우지 않는다**.

    `API_SPEC §1.6`의 진행분 경고 문구는 전부 「…진행분이 **누적에 반영되지 않았습니다**.
    …입력해 주세요」 꼴이다. 사용자가 스스로 반영하지 않기로 둔 항차에 그 문구를 띄우면
    **제원을 채우면 반영될 것처럼 읽히는 거짓 안내**가 된다.

    기준 일일 연료소모량이 없는 선박 **두 척**을 같은 조건으로 세우고 정책만 다르게 둔다 —
    `INCLUDE_AS_PLAN`에서 경고가 **나오는 것**까지 함께 보지 않으면 「경고 자체가 죽었다」와
    구분되지 않는다. 정책을 나중에 `UPDATE`로 바꾸지 않는 것은, raw SQL이 ORM identity map을
    갱신하지 않아 :func:`find_in_progress`가 바꾸기 전 객체를 돌려주기 때문이다.
    """

    async def _state(policy: str):
        vessel_id = await _make_vessel(session, foc=None)
        voyage_id = await _make_voyage(
            session,
            vessel_id,
            policy=policy,
            departed_at=datetime(YEAR, 6, 25, tzinfo=UTC),
        )
        await _add_planned_fuels(session, voyage_id, [("HFO", 60, "3.114")])
        vessel = await vessel_repo.get_by_id(session, vessel_id)
        return await resolve_in_progress_state(session, vessel=vessel, as_of=MID_YEAR)

    included = await _state("INCLUDE_AS_PLAN")
    assert WARNING_SIM_NO_FUEL_RATE in included.warnings, "사전 조건: 반영 대상이면 경고가 나온다"

    excluded = await _state("EXCLUDE")
    assert excluded.contribution is None
    assert excluded.warnings == []
    assert excluded.voyage is not None, "화면이 그릴 ⑵의 근거는 남는다"


def test_publish_truncates_every_kind():
    """**모든 종류를 절사한다** (`#1349` → `#1600` · `TECH_SPEC §1.2.1` 「응답 직렬화의 절사」).

    이 서비스의 종류는 전부 전송 자릿수가 표시 자릿수보다 크다 — CII · 비율 · 거리(남은 일수 포함)
    · 연료 · CO₂ · 시간. 기대값은 수치 계약이며 표시 문구가 아니다.
    """
    from cii_platform.services.cii_current import _publish

    assert _publish(Decimal("4.9824996"), "cii") == "4.982499"
    assert _publish(Decimal("-0.0004996"), "cii") == "-0.000499"
    assert _publish(Decimal("0.987585"), "ratio") == "0.98758"
    assert _publish(Decimal("120.505"), "distance_nm") == "120.50"
    assert _publish(Decimal("80.005"), "fuel_ton") == "80.00"
    assert _publish(Decimal("249.125"), "co2_ton") == "249.12"
    assert _publish(Decimal("12.34569"), "hours") == "12.3456"
    assert _publish(None, "cii") is None


@pytest.mark.asyncio
async def test_berth_share_is_reported_so_the_screen_need_not_guess(session):
    """`#1658` — 정박 구간의 **연료·배출 몫**을 응답이 직접 말한다.

    화면은 종전에 「정박 상태 + 구간 수 > 0」으로 「계속 악화 중」을 그렸다. 연료가 없는 구간도
    그렇게 보였는데, 연료가 0이면 분자가 늘지 않아 **등급은 그대로**다(`UIFLOW 2-9`의 구분
    기준이 「정박 연료 기록」이다). 값은 계층 1이 이미 계산한 것을 옮긴 것이라 지어낸 수가 없다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    period_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
            "period_type, started_at, distance_nm) VALUES (:id, :vid, 2026, "
            "'AT_ANCHOR', '2026-06-25T00:00:00Z', 0)"
        ),
        {"id": period_id, "vid": vessel_id},
    )

    # ⑴ 구간만 있고 연료가 없다 — 몫은 0이다.
    empty, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert empty["ytd"]["not_underway_period_count"] == 1
    assert Decimal(empty["ytd"]["not_underway_fuel_ton"]) == 0
    assert Decimal(empty["ytd"]["not_underway_co2_ton"]) == 0

    # ⑵ 연료를 넣으면 몫이 잡힌다.
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'OIL_FIRED_BOILER', 'HFO', 40, 3.114)"
        ),
        {"id": period_id},
    )
    filled, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assert Decimal(filled["ytd"]["not_underway_fuel_ton"]) == Decimal("40")
    # 40 t × CF 3.114 = 124.56 tCO₂ — 응답은 톤 단위 문자열이다.
    assert Decimal(filled["ytd"]["not_underway_co2_ton"]) == Decimal("124.56")
    # 전체 몫보다 클 수 없다.
    assert Decimal(filled["ytd"]["not_underway_co2_ton"]) <= Decimal(filled["ytd"]["total_co2_ton"])


# ─────────────────────────────────────────────────────────────────────────────
# ⑶을 무엇이 올리는가 — `year_end_projection.drivers[]` (#1673)
#
# 「연말 예상이 D」라는 결론만 주면 사용자가 할 수 있는 일이 없다. ⑴에서 ⑶까지를 **시간
# 순으로** 나눈다 — 진행 중 항차의 남은 몫을 더했을 때(`CURRENT_VOYAGE`), 남은 계획을 더했을
# 때(`REMAINING_PLAN`). CII는 비율이라 순서에 따라 값이 달라지므로 순서를 고정했고, 각
# 단계의 누적값을 **전송 자릿수로 먼저 절사한 뒤** 빼서 합이 응답의 두 문자열 차이와
# 정확히 같다. 확정분 집합이 갈리면 `BASIS_DIFFERENCE`로 따로 드러낸다 — 다른 요인에
# 녹이면 합은 맞아도 설명이 틀린다.
# ─────────────────────────────────────────────────────────────────────────────


def _driver_sum(drivers) -> Decimal:
    return sum((Decimal(item["delta_cii"]) for item in drivers), Decimal(0))


async def _add_berth_fuel(session, vessel_id, *, fuel="40") -> None:
    """올해 이미 쓴 정박 연료 — ⑴·⑶ 양쪽 확정분에 같게 들어간다 (`#1803`)."""
    period_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
            "period_type, started_at, distance_nm) VALUES (:id, :vid, 2026, "
            "'AT_ANCHOR', '2026-06-25T00:00:00Z', 0)"
        ),
        {"id": period_id, "vid": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'OIL_FIRED_BOILER', 'HFO', :fuel, 3.114)"
        ),
        {"id": period_id, "fuel": Decimal(fuel)},
    )


async def _add_current_voyage(session, vessel_id, *, planned_fuel="331") -> object:
    """진행 중 항차 — 계획 연료를 **반드시** 넣는다.

    연료가 없는 계획 항차는 `#812`가 ⑶에서 빼므로, 연료 없이 만들면 ⑶이 이 항차를 세지
    않는 상태(경과분만 ⑴에 있고 계획 전량은 어디에도 없음)가 된다. 그 상태는 별도 검사가
    본다(``test_a_current_voyage_the_projection_drops_shows_up_as_a_drop``).
    """
    voyage_id = await _make_voyage(
        session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    await _add_planned_fuels(session, voyage_id, [("HFO", planned_fuel, "3.114")])
    return voyage_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("with_current", "with_plan", "with_berth"),
    [
        (True, True, True),
        (True, True, False),
        (False, True, False),
        (True, False, False),
        (False, False, True),
    ],
)
async def test_drivers_sum_exactly_to_projection_minus_ytd(
    session, with_current, with_plan, with_berth
):
    """합 = ⑶ − ⑴ — **문자열 단위로 정확히** (#1673 완료 기준).

    차이를 절사하면 단계마다 최대 1 ulp가 버려져 합이 어긋난다. 누적값을 먼저 절사한 뒤
    빼야 망원경처럼 접혀 ``trunc(⑶) − trunc(⑴)``가 된다. 다섯 조합 전부에서 본다 —
    진행 중 항차·잔여 계획·정박의 유무가 각 단계의 존재 여부를 바꾸기 때문이다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    if with_current:
        await _add_current_voyage(session, vessel_id)
    if with_plan:
        await _add_plan(session, vessel_id)
    if with_berth:
        await _add_berth_fuel(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    projection = data["year_end_projection"]
    drivers = projection["drivers"]
    keys = [item["key"] for item in drivers]

    assert projection["data_available"] is True
    assert _driver_sum(drivers) == Decimal(projection["attained_cii"]) - Decimal(
        data["ytd"]["attained_cii"]
    ), f"합이 ⑶ − ⑴과 다르다: {drivers}"
    # 순서는 시간 순으로 고정이다 — 비율이라 순서가 바뀌면 값이 바뀐다.
    order = [DRIVER_BASIS_DIFFERENCE, DRIVER_CURRENT_VOYAGE, DRIVER_REMAINING_PLAN]
    assert keys == [key for key in order if key in keys]
    assert (DRIVER_CURRENT_VOYAGE in keys) is with_current
    assert DRIVER_REMAINING_PLAN in keys
    # ⑴과 ⑶은 같은 저장소 함수·같은 절단으로 확정분을 읽는다 — 갈리지 않는다 (실측).
    assert DRIVER_BASIS_DIFFERENCE not in keys
    if not with_plan:
        assert (
            dict(zip(keys, (item["delta_cii"] for item in drivers), strict=True))[
                DRIVER_REMAINING_PLAN
            ]
            == "0.000000"
        ), "잔여 계획이 없으면 그 단계는 0이다"
    for item in drivers:
        # `API_SPEC §1.7` — 6자리 문자열. 음수는 앞에 부호만 붙는다.
        assert Decimal(item["delta_cii"]).as_tuple().exponent == -6, item


@pytest.mark.asyncio
async def test_current_voyage_driver_is_the_planned_whole_minus_the_elapsed_part(session):
    """`CURRENT_VOYAGE`는 「경과분 → 계획 전량」의 변화, `REMAINING_PLAN`은 그 뒤의 나머지다.

    ⑶은 진행 중 항차를 계획 전량으로 세고 ⑴은 경과분으로 센다(`API_SPEC §2.14`). 첫
    단계는 정확히 그 교체다 — 같은 엔진·같은 확정분에 **그 항차의 계획 행만** 더한 값을
    직접 만들어 대조한다. 두 단계의 합이 ⑶ − ⑴이므로, 이 검사와 위 합 검사가 함께
    분해 전체를 고정한다.
    """
    from cii_platform.calc.annual_simulation import project_deterministic
    from cii_platform.services.annual_simulation import (
        _inputs_from_snapshot,
        collect_annual_inputs,
        load_projection_context,
    )
    from cii_platform.services.cii_current import _publish

    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    current_id = await _add_current_voyage(session, vessel_id)
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    drivers = {
        item["key"]: Decimal(item["delta_cii"]) for item in data["year_end_projection"]["drivers"]
    }

    context = await load_projection_context(session, vessel_id=vessel_id, regulation_year=YEAR)
    inputs = await collect_annual_inputs(
        session, vessel=context.vessel, vessel_id=vessel_id, year=YEAR, as_of=MID_YEAR
    )
    current_rows = [row for row in inputs.voyages_json if row["voyage_id"] == str(current_id)]
    assert [row["kind"] for row in current_rows] == ["PLAN"], (
        "사전 조건: 진행 중 항차는 PLAN 행이다"
    )
    _, current_only, _ = _inputs_from_snapshot(current_rows, context.vessel)
    with_current = _publish(
        project_deterministic(
            completed=inputs.completed,
            remaining=current_only,
            transport_capacity=context.transport_capacity,
            required_cii=context.required_cii,
            d_vector=context.d_vector,
        ).attained_cii,
        "cii",
    )

    assert drivers[DRIVER_CURRENT_VOYAGE] == Decimal(with_current) - Decimal(
        data["ytd"]["attained_cii"]
    )
    assert drivers[DRIVER_REMAINING_PLAN] == Decimal(
        data["year_end_projection"]["attained_cii"]
    ) - Decimal(with_current)


@pytest.mark.asyncio
async def test_remaining_plan_driver_has_the_sign_of_the_plan_intensity(session):
    """남은 계획이 확정분보다 연료를 많이 쓰면 양수, 적게 쓰면 음수다.

    확정분은 400 t / 5,000 nm(0.08 t/nm)이다. 계획을 0.12 t/nm으로 두면 연말이 나빠지고
    0.01 t/nm이면 좋아진다 — 부호가 그 방향을 말해야 화면의 「+a / −b」가 뜻을 갖는다.
    """
    worse = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, worse))
    await _add_plan(session, worse, distance="10000", fuel="1200")
    better = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, better))
    await _add_plan(session, better, distance="10000", fuel="100")

    worse_data, _ = await get_current_cii(session, worse, year=YEAR, as_of=MID_YEAR)
    better_data, _ = await get_current_cii(session, better, year=YEAR, as_of=MID_YEAR)

    def remaining(data) -> Decimal:
        return next(
            Decimal(item["delta_cii"])
            for item in data["year_end_projection"]["drivers"]
            if item["key"] == DRIVER_REMAINING_PLAN
        )

    assert remaining(worse_data) > 0
    assert remaining(better_data) < 0


@pytest.mark.asyncio
async def test_drivers_are_empty_when_there_is_no_ytd_to_start_from(session):
    """⑴이 없으면 분해도 없다 — 출발점이 없으면 「합 = ⑶ − ⑴」이 성립할 자리가 없다.

    확정 실적 없이 계획만 있는 선박이다. ⑶은 나온다(남은 계획이 분모를 준다) — 그때
    ⑶ 전체가 계획이고, 빈 목록이 그 사실을 말한다. 필드를 빼지 않는 것은 화면이
    「아직 안 온 값」과 「분해할 것이 없다」를 구분해야 하기 때문이다.
    """
    vessel_id = await _make_vessel(session)
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    assert data["ytd"]["data_available"] is False
    assert data["year_end_projection"]["data_available"] is True
    assert data["year_end_projection"]["drivers"] == []


@pytest.mark.asyncio
async def test_drivers_are_absent_when_the_projection_is_not_made(session):
    """⑶을 못 내면(`YEAR_COMPLETE` · `NO_BASIS`) `drivers` 키 자체가 없다.

    그 블록은 ``attained_cii``도 싣지 않는다 — 없는 값의 분해를 빈 목록으로라도 실으면
    「분해할 것이 없다」로 읽혀 위 검사의 뜻과 섞인다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    complete, _ = await get_current_cii(
        session, vessel_id, year=YEAR, as_of=datetime(YEAR + 1, 1, 1, tzinfo=UTC)
    )
    assert complete["year_end_projection"]["reason"] == REASON_YEAR_COMPLETE
    assert "drivers" not in complete["year_end_projection"]

    empty = await _make_vessel(session)
    no_basis, _ = await get_current_cii(session, empty, year=YEAR, as_of=MID_YEAR)
    assert no_basis["year_end_projection"]["reason"] == REASON_NO_BASIS
    assert "drivers" not in no_basis["year_end_projection"]


@pytest.mark.asyncio
async def test_a_current_voyage_the_projection_drops_shows_up_as_a_drop(session):
    """⑶이 진행 중 항차를 세지 않으면 `CURRENT_VOYAGE`가 그 탈락을 그대로 보인다.

    계획 연료가 없는 진행 중 항차는 ⑴에는 경과분(선박 기본 연료)으로 들어가지만 ⑶은
    `#812`로 뺀다 — 계획 전량이 어디에도 없다. 첫 단계는 「경과분 → ⑶이 세는 몫(없음)」의
    변화이므로 값이 실리고, 합은 여전히 ⑶ − ⑴이다. 조용히 0으로 두지 않는다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    projection = data["year_end_projection"]
    keys = [item["key"] for item in projection["drivers"]]

    assert data["ytd"]["in_progress_voyage_count"] == 1, "사전 조건: 경과분이 ⑴에 있다"
    assert "SIMULATION_PLAN_NO_FUEL" in projection["warnings"], "사전 조건: ⑶이 그 항차를 뺐다"
    assert DRIVER_CURRENT_VOYAGE in keys
    assert _driver_sum(projection["drivers"]) == Decimal(projection["attained_cii"]) - Decimal(
        data["ytd"]["attained_cii"]
    )


@pytest.mark.asyncio
async def test_current_voyage_step_is_skipped_when_it_has_no_distance_to_stand_on(session):
    """확정 거리 0 + ⑶이 진행 항차를 세지 않음 — `CURRENT_VOYAGE`를 생략하고 사슬을 잇는다.

    확정 항차·정박이 없고, 진행 중 항차는 계획 연료가 없어 ⑴에는 경과분(선박 기본 연료)으로
    들어가지만 ⑶은 `#812`로 뺀다. 「확정분 + 진행 항차 계획 전량」은 거리 0이라 CII가
    정의되지 않으므로 그 단계를 만들 수 없다. 종전 구현은 이때 `[]`로 비웠다 — ⑴·⑶이
    둘 다 있는데 「분해할 것이 없다」로 읽혔다. 지금은 `REMAINING_PLAN` 한 줄이 ⑶의
    조립으로 ⑴을 다시 만든 값부터 ⑶까지를 잇고, 합은 그대로 ⑶ − ⑴이다.
    """
    vessel_id = await _make_vessel(session)
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 25, tzinfo=UTC))
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    projection = data["year_end_projection"]

    assert data["ytd"]["data_available"] is True, "사전 조건: ⑴은 경과분으로 나온다"
    assert data["ytd"]["voyage_count"] == 0, "사전 조건: 확정 항차가 없다"
    assert "SIMULATION_PLAN_NO_FUEL" in projection["warnings"], "사전 조건: ⑶이 진행 항차를 뺐다"
    assert projection["data_available"] is True
    assert [item["key"] for item in projection["drivers"]] == [DRIVER_REMAINING_PLAN]
    assert _driver_sum(projection["drivers"]) == Decimal(projection["attained_cii"]) - Decimal(
        data["ytd"]["attained_cii"]
    )


@pytest.mark.asyncio
async def test_an_excluded_in_progress_voyage_has_no_current_voyage_driver(session):
    """「연간 반영 안 함」 진행 항차는 ⑴에도 ⑶에도 없다 — `CURRENT_VOYAGE`를 싣지 않는다.

    `#1085`가 ⑴에서 뺐고 `list_remaining_plans`는 정책이 `INCLUDE_AS_PLAN`인 것만 본다.
    어느 쪽도 세지 않는 항차에 「이 항해를 마치면」 줄을 두면 0이거나 거짓이다. 합은 그대로다.
    """
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    excluded = await _make_voyage(
        session, vessel_id, policy="EXCLUDE", departed_at=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    await _add_planned_fuels(session, excluded, [("HFO", "331", "3.114")])
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    projection = data["year_end_projection"]

    assert data["current_voyage"] is not None, "사전 조건: ⑵ 카드는 남는다 (#1085)"
    assert data["ytd"]["in_progress_voyage_count"] == 0, "사전 조건: ⑴에 없다"
    assert [item["key"] for item in projection["drivers"]] == [DRIVER_REMAINING_PLAN]
    assert _driver_sum(projection["drivers"]) == Decimal(projection["attained_cii"]) - Decimal(
        data["ytd"]["attained_cii"]
    )


@pytest.mark.asyncio
async def test_current_voyage_driver_is_the_whole_plan_when_the_clock_made_no_fuel(session):
    """소모율이 없어 ⑴에 경과분이 없으면 `CURRENT_VOYAGE`는 계획 전량의 효과 그 자체다.

    `reference_daily_foc_ton`이 없으면 시계가 연료를 만들지 못해 진행분이 ⑴에 들어가지
    않는다(`SIMULATION_NO_FUEL_RATE`). ⑶은 그 항차를 계획 전량으로 세므로 첫 단계는
    「없음 → 계획 전량」이고, 값이 실려야 한다. 합은 그대로다.
    """
    vessel_id = await _make_vessel(session, foc=None)
    await _add_actuals(session, await _make_voyage(session, vessel_id))
    await _add_current_voyage(session, vessel_id)
    await _add_plan(session, vessel_id)

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    projection = data["year_end_projection"]
    keys = [item["key"] for item in projection["drivers"]]

    assert WARNING_SIM_NO_FUEL_RATE in data["warnings"], "사전 조건: 경과분이 ⑴에 없다"
    assert keys == [DRIVER_CURRENT_VOYAGE, DRIVER_REMAINING_PLAN]
    assert Decimal(projection["drivers"][0]["delta_cii"]) != 0
    assert _driver_sum(projection["drivers"]) == Decimal(projection["attained_cii"]) - Decimal(
        data["ytd"]["attained_cii"]
    )


def test_basis_difference_is_carried_only_when_the_two_assemblies_disagree():
    """확정분 집합이 갈리면 `BASIS_DIFFERENCE`가 **맨 앞에** 실리고, 같으면 실리지 않는다.

    실측에서는 ⑴과 ⑶이 같은 저장소 함수·같은 절단으로 확정분을 읽어 늘 같다(위 합 검사가
    다섯 조합에서 부재를 단언한다). 그래서 갈리는 상태는 **엔진을 직접 불러** 만든다 —
    ⑴을 다른 값으로 넘기면 그 차이가 첫 단계로 드러나고 합은 그대로 ⑶ − ⑴이어야 한다.
    """
    from cii_platform.calc.annual_simulation import (
        CompletedTotals,
        RemainingVoyage,
        project_deterministic,
    )
    from cii_platform.calc.rating_engine import DVector
    from cii_platform.services.annual_simulation import VesselSnapshot
    from cii_platform.services.cii_current import _year_end_drivers
    from cii_platform.services.ytd_cii import InProgressContribution

    class _Context:
        vessel = VesselSnapshot(
            "BULK_CARRIER", Decimal("50000"), None, Decimal("14"), Decimal("30")
        )
        transport_capacity = Decimal("50000")
        required_cii = Decimal("5.045066")
        d_vector = DVector(Decimal("0.86"), Decimal("0.94"), Decimal("1.06"), Decimal("1.18"))

    class _Inputs:
        completed = CompletedTotals(co2_g=float(Decimal("1930680000")), distance_nm=4300.0)
        remaining = [RemainingVoyage(distance_nm=2300.0, fuel_ton=331.0, cf=3.114)]
        voyages_json = [
            {
                "voyage_id": "current",
                "kind": "PLAN",
                "planned_distance_nm": "2300",
                "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "331", "cf_used": "3.114"}],
            }
        ]

    deterministic = project_deterministic(
        completed=_Inputs.completed,
        remaining=_Inputs.remaining,
        transport_capacity=_Context.transport_capacity,
        required_cii=_Context.required_cii,
        d_vector=_Context.d_vector,
    )
    elapsed = InProgressContribution(
        distance_nm=Decimal("2300"), fuel_uses=(("HFO", Decimal("250.444")),)
    )
    # ⑴을 ⑶의 조립 그대로 다시 만든 값 — 확정분 + 경과분.
    same_basis = project_deterministic(
        completed=_Inputs.completed,
        remaining=[RemainingVoyage(distance_nm=2300.0, fuel_ton=250.444, cf=3.114)],
        transport_capacity=_Context.transport_capacity,
        required_cii=_Context.required_cii,
        d_vector=_Context.d_vector,
    ).attained_cii

    def drivers(ytd: Decimal):
        return _year_end_drivers(
            _Context,
            _Inputs,
            deterministic,
            ytd_attained_cii=ytd,
            current_voyage_id="current",  # type: ignore[arg-type]
            contribution=elapsed,
            cf_by_fuel={"HFO": Decimal("3.114")},
        )

    agree = drivers(same_basis)
    assert [item["key"] for item in agree] == [DRIVER_CURRENT_VOYAGE, DRIVER_REMAINING_PLAN]

    shifted = same_basis - Decimal("0.5")
    disagree = drivers(shifted)
    assert [item["key"] for item in disagree] == [
        DRIVER_BASIS_DIFFERENCE,
        DRIVER_CURRENT_VOYAGE,
        DRIVER_REMAINING_PLAN,
    ]
    assert disagree[0]["delta_cii"] == "0.500000"
    # 나머지 두 단계는 출발점과 무관하다 — 차이는 전부 첫 키에 실린다.
    assert disagree[1:] == agree
    assert _driver_sum(disagree) == Decimal(
        str(deterministic.attained_cii.quantize(Decimal("0.000001"), rounding="ROUND_DOWN"))
    ) - shifted.quantize(Decimal("0.000001"), rounding="ROUND_DOWN")
    # ⑴이 없으면 분해도 없다.
    assert drivers(None) == []


@pytest.mark.asyncio
async def test_demo_bulk_drivers_match_the_reference_values(session):
    """시드 벌크선 50k — 이슈 조사 때 순수 엔진으로 재계산한 기준값 (#1673).

    ``as_of = DEMO_ANCHOR + 3일``은 시계가 계획 거리(2,300 nm)에 닿은 뒤다 — 거리는 계획과
    같고 연료만 다르므로(시계 250.444 t vs 계획 331 t) `CURRENT_VOYAGE`가 연료 차이만 잰다.
    확정 `V1_2026` 620 t / 4,300 nm · 잔여 계획 4건(`V1_PLANNED` + `#1052` 3건).

    시드는 세션 시작 때 한 번 적재되고 이 검사는 읽기만 한다. 값이 바뀌면 시드가 바뀐
    것이거나 분해가 바뀐 것이다 — 둘 다 이 자리에서 드러나야 한다.
    """
    from datetime import timedelta
    from uuid import UUID

    from cii_platform.db.demo_seed import DEMO_ANCHOR, VESSEL_ID_BULK

    data, _ = await get_current_cii(
        session, UUID(VESSEL_ID_BULK), year=2026, as_of=DEMO_ANCHOR + timedelta(days=3)
    )
    projection = data["year_end_projection"]

    assert data["ytd"]["attained_cii"] == "8.213830"
    assert projection["attained_cii"] == "8.965893"
    assert projection["drivers"] == [
        {"key": DRIVER_CURRENT_VOYAGE, "delta_cii": "0.760151"},
        {"key": DRIVER_REMAINING_PLAN, "delta_cii": "-0.008088"},
    ]
    assert _driver_sum(projection["drivers"]) == Decimal("0.752063")
