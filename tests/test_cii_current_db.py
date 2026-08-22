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

from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.services.cii_current import (
    REASON_NO_BASIS,
    REASON_YEAR_COMPLETE,
    WARNING_SIM_NO_FUEL_RATE,
    get_current_cii,
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
    """`PRD §3.3` ⑶ — 화면이 「⑶만 크게 표시하지 않는다」를 지키려면 근거가 필요하다."""
    vessel_id = await _make_vessel(session)
    await _add_actuals(session, await _make_voyage(session, vessel_id))

    data, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    assumptions = data["year_end_projection"]["assumptions"]

    assert assumptions["method"] == "YTD_DAILY_AVERAGE"
    for key in ("elapsed_days", "remaining_days", "daily_distance_nm", "daily_fuel_ton"):
        assert assumptions[key] is not None


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
