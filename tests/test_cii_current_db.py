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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.services.cii_current import (
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
        "policy": "EXCLUDE",
        "year": YEAR,
    }
    fields.update(over)
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_departure_at, planned_arrival_at, annual_inclusion_policy, "
            "regulation_year, created_from) "
            "VALUES (:id, :vessel_id, :status, 'Busan', 'Singapore', "
            "3000, 14, :departed, :planned_arrival, :policy, :year, 'MANUAL')"
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
    await _make_voyage(session, vessel_id, departed_at=datetime(YEAR, 6, 1, tzinfo=UTC))

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
