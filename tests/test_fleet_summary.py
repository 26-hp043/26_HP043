"""선대 요약 서비스 검증 (#350).

이 이슈의 위험은 **계산이 아니라 판정과 경계**에 있다. YTD 수치는 ``#353``의
``compute_ytd_cii``가 이미 계산하고 그 테스트가 따로 있으므로, 여기서는
아래 넷을 본다.

* ``PRD §3.3.7`` 규제 트리거 판정 — E 1년 / D 3년 연속
* 「D등급 진입까지 n일」 경계 4종 (이슈 #350이 필수로 지목)
* KPI 집계가 선박 목록과 어긋나지 않는 것
* 선박 0척이 **오류가 아닌 것**

순수 함수(판정·경계)는 DB 없이 보고, 집계·조회는 DB로 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.calc.rating_engine import DVector, determine_rating
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import ValidationError
from cii_platform.services import fleet_summary
from cii_platform.services.cii_current import resolve_in_progress_state
from cii_platform.services.fleet_summary import (
    REASON_ALREADY_AT_OR_BELOW,
    REASON_NO_DATA,
    REASON_NO_RECENT_DATA,
    REASON_NOT_THIS_YEAR,
    REASON_NOT_UNDER_WAY,
    REASON_NOT_WORSENING,
    UNAVAILABLE_CALCULATION_ERROR,
    UNAVAILABLE_MISSING_SPEC,
    UNAVAILABLE_NO_DATA,
    UNAVAILABLE_NO_PARAMETERS,
    compute_days_to_target,
    evaluate_risk_reasons,
    get_fleet_summary,
)
from cii_platform.services.ytd_cii import YtdCiiOutput, compute_ytd_cii

YEAR = 2026
HFO_CF = Decimal("3.114")


# ─────────────────────────────────────────────────────────────────────────────
# PRD §3.3.7 — 규제 트리거 판정
# ─────────────────────────────────────────────────────────────────────────────


def test_e_this_year_is_a_trigger():
    assert evaluate_risk_reasons(ytd_rating="E", prior_ratings=[]) == ["E_THIS_YEAR"]


def test_d_three_years_running_is_a_trigger():
    assert evaluate_risk_reasons(ytd_rating="D", prior_ratings=["D", "D"]) == ["D_THIRD_YEAR"]


def test_d_alone_is_not_a_trigger():
    """등급만으로 판정하지 않는다 — Reg 28.7의 트리거는 연속 연수를 포함한다."""
    assert evaluate_risk_reasons(ytd_rating="D", prior_ratings=["C", "D"]) == []


def test_d_with_missing_history_is_not_a_trigger():
    """확정 등급이 없는 해는 D로 치지 않는다. 모르는 것을 나쁜 쪽으로 단정하지 않는다."""
    assert evaluate_risk_reasons(ytd_rating="D", prior_ratings=["D", None]) == []


def test_d_with_only_one_prior_year_is_not_a_trigger():
    """직전 2개 연도가 다 있어야 3년 연속이 성립한다."""
    assert evaluate_risk_reasons(ytd_rating="D", prior_ratings=["D"]) == []


def test_no_rating_yields_no_reason():
    assert evaluate_risk_reasons(ytd_rating=None, prior_ratings=["D", "D"]) == []


def test_c_never_triggers():
    assert evaluate_risk_reasons(ytd_rating="C", prior_ratings=["D", "D"]) == []


# ─────────────────────────────────────────────────────────────────────────────
# 「D등급 진입까지 n일」 — 이슈 #350이 지목한 경계 4종
# ─────────────────────────────────────────────────────────────────────────────


#: 픽스처가 쓰는 required CII와 d-vector (#814).
#:
#: 실제 IMO 값이 아니라 **경계가 읽기 쉬운 값으로 떨어지도록** 고른 것이다.
#: ``attained = 5.0``과 짝지으면 아래가 된다.
#:
#: .. code-block:: text
#:
#:     superior = 6.0 × 0.70 = 4.2      lower    = 6.0 × 0.80 = 4.8
#:     upper    = 6.0 × 1.00 = 6.0      inferior = 6.0 × 1.10 = 6.6
#:     4.8 < 5.0 <= 6.0  →  등급 C · D 진입 경계(upper_boundary) = 6.0
_FIXTURE_REQUIRED_CII = Decimal("6.0")
_FIXTURE_D_VECTOR = DVector(
    d1=Decimal("0.70"), d2=Decimal("0.80"), d3=Decimal("1.00"), d4=Decimal("1.10")
)


def _rating_of(attained: Decimal, required: Decimal = _FIXTURE_REQUIRED_CII):
    """**실제 엔진**으로 등급과 경계를 만든다 (#814).

    ## 왜 손으로 dict를 쓰지 않는가

    종전 픽스처는 ``{"d": Decimal("6.0")}``이었다. ``determine_rating``은 **그런 키를
    만들지 않는다** — 넷뿐이고 전부 ``*_boundary`` 형태다. 그래서 구현이 없는 키를
    조회해 「D등급 진입까지 n일」이 **항상 `null`**이었는데도, 테스트는 자기가 만든
    가짜 키를 자기가 읽어 **전부 통과**했다(`#814`).

    엔진 출력을 쓰면 키 오타가 곧 테스트 실패가 된다.
    """
    return determine_rating(
        attained_cii=attained,
        required_cii=required,
        d_vector=_FIXTURE_D_VECTOR,
    )


def _ytd(*, required_cii: Decimal = _FIXTURE_REQUIRED_CII, **over) -> YtdCiiOutput:
    """검사용 YTD 결과.

    ``attained_cii``를 주면 등급과 경계를 **엔진이 그 값으로 다시 만든다** —
    손으로 적으면 둘이 어긋난 조합이 생기고, 그 조합에서만 통과하는 검사가 남는다.

    ``required_cii``를 올리면 경계가 통째로 멀어진다(경계 = required × d). 「경계까지
    여유가 매우 큰」 상황을 만들 때 쓴다.
    """
    attained = over.pop("attained_cii", Decimal("5.0"))
    if attained is None:
        # 「YTD를 낼 수 없는 선박」 — 등급도 경계도 없다. 엔진을 부를 수 없다.
        rating, boundaries = None, None
    else:
        result = _rating_of(attained, required_cii)
        rating, boundaries = result.rating, result.boundaries

    base = {
        "data_available": True,
        "regulation_year": YEAR,
        "capacity_axis": "DWT",
        "transport_capacity": Decimal("50000"),
        "attained_cii": attained,
        "rating": rating,
        "boundaries": boundaries,
        "required_cii": required_cii,
        "underway_distance_nm": Decimal("1000"),
        # `#431` 산식이 누적 거리를 쓴다 — 정박 거리가 없는 선박이라 둘이 같다.
        "total_distance_nm": Decimal("1000"),
    }
    base.update(over)
    return YtdCiiOutput(**base)


AS_OF = datetime(YEAR, 3, 1, tzinfo=UTC)


def _past(*, recent_cii: str, now: YtdCiiOutput | None = None) -> YtdCiiOutput:
    """최근 창의 시작 시점 누적 — **최근 구간의 강도**로부터 역산해 만든다 (`#431`).

    테스트가 정하고 싶은 것은 「최근 30일을 얼마나 나쁘게 뛰었나」이지 그 시점의
    누적값이 아니다. 강도를 주면 누적을 맞춰 주는 편이 의도가 드러난다.

        A = attained × Dt  ·  A_past = A_now − 강도 × ΔD
    """
    current = now if now is not None else _ytd()
    distance_now = current.total_distance_nm
    distance_past = distance_now * Decimal("0.5")
    area_now = current.attained_cii * distance_now
    area_past = area_now - Decimal(recent_cii) * (distance_now - distance_past)
    return _ytd(
        attained_cii=area_past / distance_past,
        total_distance_nm=distance_past,
        underway_distance_nm=distance_past,
    )


def test_days_no_data_when_ytd_unavailable():
    result = compute_days_to_target(
        _ytd(data_available=False, attained_cii=None, rating=None),
        past=None,
        underway_state="UNDER_WAY",
        as_of=AS_OF,
    )
    assert result.days is None
    assert result.reason == REASON_NO_DATA


def test_days_already_at_or_below_for_d():
    result = compute_days_to_target(
        _ytd(rating="D"), past=None, underway_state="UNDER_WAY", as_of=AS_OF
    )
    assert result.reason == REASON_ALREADY_AT_OR_BELOW


def test_days_already_at_or_below_for_e():
    result = compute_days_to_target(
        _ytd(rating="E"), past=None, underway_state="UNDER_WAY", as_of=AS_OF
    )
    assert result.reason == REASON_ALREADY_AT_OR_BELOW


def test_days_not_computed_while_not_under_way():
    """정박 중에는 산정하지 않는다.

    거리가 늘지 않고 연료만 늘어 CII가 단조 악화하므로, n일이 하루가 다르게
    짧아졌다가 **출항하는 순간 되돌아간다.** 요동치는 숫자 대신 사유를 준다.
    """
    result = compute_days_to_target(_ytd(), past=None, underway_state="NOT_UNDER_WAY", as_of=AS_OF)
    assert result.days is None
    assert result.reason == REASON_NOT_UNDER_WAY


def test_days_not_this_year_when_far_away():
    """올해 안에 도달하지 않으면 숫자 대신 사유를 준다."""
    # 경계까지 여유가 매우 커서 외삽 결과가 연말을 넘는 경우.
    #
    # `#814` — 종전에는 `boundaries={"d": ...}`를 손으로 넣었다. 그 키는 엔진이 만들지
    # 않는 것이라 **구현이 그것을 못 읽는다는 사실을 이 검사가 가렸다.** 지금은
    # `required_cii`를 올려 경계 자체를 멀리 민다(경계 = required × d).
    far = _ytd(attained_cii=Decimal("1.0"), required_cii=Decimal("99.0"))
    result = compute_days_to_target(
        far,
        past=_past(recent_cii="99.5", now=far),
        underway_state="UNDER_WAY",
        as_of=datetime(YEAR, 12, 20, tzinfo=UTC),
    )
    assert result.days is None
    assert result.reason == REASON_NOT_THIS_YEAR


def test_days_returns_a_number_in_the_normal_case():
    # 최근 30일을 경계보다 나쁘게 뛴 경우 — 그때만 「진입까지 n일」이 존재한다.
    result = compute_days_to_target(
        _ytd(), past=_past(recent_cii="8.0"), underway_state="UNDER_WAY", as_of=AS_OF
    )
    assert result.reason is None
    assert isinstance(result.days, int)
    assert result.days >= 0


def test_days_shrink_as_the_margin_shrinks():
    """**이 이슈의 본체**다 (`#431`).

    종전 구현은 분자가 약분돼 **경계까지의 여유와 무관하게 언제나 경과일수**를 냈다.
    같은 운항 강도라면 경계에 가까울수록 남은 일수가 짧아져야 한다.
    """
    wide = _ytd(attained_cii=Decimal("5.0"))
    narrow = _ytd(attained_cii=Decimal("5.9"))

    far = compute_days_to_target(
        wide,
        past=_past(recent_cii="8.0", now=wide),
        underway_state="UNDER_WAY",
        as_of=AS_OF,
    )
    near = compute_days_to_target(
        narrow,
        past=_past(recent_cii="8.0", now=narrow),
        underway_state="UNDER_WAY",
        as_of=AS_OF,
    )

    assert far.days is not None and near.days is not None
    assert near.days < far.days


def test_days_is_not_just_the_elapsed_day_count():
    """회귀 방지 — 종전 값은 언제나 `as_of`의 연중 일수였다."""
    now = _ytd(attained_cii=Decimal("5.9"))
    result = compute_days_to_target(
        now, past=_past(recent_cii="8.0", now=now), underway_state="UNDER_WAY", as_of=AS_OF
    )
    assert result.days != AS_OF.timetuple().tm_yday


def test_steady_operation_never_reaches_the_boundary():
    """일정한 강도로 운항하면 누적 CII는 **평평하다 — 커지지 않는다.**

    `attained_cii`가 누적 분자/분모의 비이기 때문이다. 이 경우 「n일」은 존재하지
    않으며, 0일이 아니라 사유로 표기해야 한다 — 숫자를 만들면 「곧 진입한다」로 읽힌다.
    """
    result = compute_days_to_target(
        _ytd(), past=_past(recent_cii="5.0"), underway_state="UNDER_WAY", as_of=AS_OF
    )
    assert result.days is None
    assert result.reason == REASON_NOT_WORSENING


def test_improving_operation_does_not_produce_a_countdown():
    """최근 운항이 경계보다 효율적이면 진입하지 않는다."""
    result = compute_days_to_target(
        _ytd(), past=_past(recent_cii="3.0"), underway_state="UNDER_WAY", as_of=AS_OF
    )
    assert result.reason == REASON_NOT_WORSENING


def test_ytd_average_alone_cannot_produce_a_number():
    """`past`가 없으면(창이 연초 이전) 최근 강도가 곧 YTD 평균이다.

    그때 분모는 정의상 0이 되므로 값을 낼 수 없다 — 연초 몇 주 동안은
    「아직 판단할 수 없다」가 정직한 답이다.
    """
    result = compute_days_to_target(_ytd(), past=None, underway_state="UNDER_WAY", as_of=AS_OF)
    assert result.days is None
    assert result.reason == REASON_NOT_WORSENING


def test_no_sailing_in_the_window_is_reported():
    """창 안에 항해가 없으면 소비율을 낼 근거가 없다."""
    result = compute_days_to_target(
        _ytd(),
        past=_ytd(),  # 누적이 그대로 — 그 사이 움직이지 않았다
        underway_state="UNDER_WAY",
        as_of=AS_OF,
    )
    assert result.days is None
    assert result.reason == REASON_NO_RECENT_DATA


def test_days_no_data_without_boundary():
    result = compute_days_to_target(
        _ytd(boundaries=None), past=None, underway_state="UNDER_WAY", as_of=AS_OF
    )
    assert result.reason == REASON_NO_DATA


# ─────────────────────────────────────────────────────────────────────────────
# DB — 집계와 응답 형태
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    """규정 파라미터를 멱등하게 심는다 (test_ytd_cii_service_db.py와 같은 방식)."""
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


async def _hide_seeded_vessels(session) -> None:
    """마이그레이션 018이 심은 샘플 선박을 이 테스트 안에서만 감춘다.

    ``list_active``는 ``is_deleted = false``만 본다. 트랜잭션이 끝나면 롤백되므로
    실제 데이터는 그대로다. **이렇게 하지 않으면 선대 구성을 테스트가 통제할 수
    없어** 「0척일 때」·「정확히 3척일 때」를 검증할 수 없다.
    """
    await session.execute(text("UPDATE vessel SET is_deleted = true"))


async def _insert_vessel(
    session,
    *,
    imo: str,
    name: str,
    underway_state: str | None = None,
    detail_status: str | None = None,
    ship_type: str = "BULK_CARRIER",
    deadweight: int | None = 50000,
    gross_tonnage: int | None = 30000,
) -> str:
    # `is_cii_applicable_hint`는 서비스가 등록 시 산정하는 값이라(`API_SPEC §2.3`)
    # 직접 INSERT하는 이 헬퍼가 대신 계산해 넣는다 — 컬럼 기본값에 맡기면 GT가
    # 30,000인 선박도 「미해당」으로 앉는다.
    hint = gross_tonnage is not None and gross_tonnage >= 5000
    row = await session.execute(
        text(
            "INSERT INTO vessel "
            "(imo_number, name, ship_type, gross_tonnage, deadweight, "
            " is_cii_applicable_hint, underway_state, detail_status) "
            "VALUES (:imo, :name, :ship_type, :gt, :dwt, :hint, :st, :ds) "
            "RETURNING id"
        ),
        {
            "imo": imo,
            "name": name,
            "ship_type": ship_type,
            "gt": gross_tonnage,
            "dwt": deadweight,
            "hint": hint,
            "st": underway_state,
            "ds": detail_status,
        },
    )
    return str(row.scalar_one())


async def _insert_voyage_with_fuel(session, vessel_id: str) -> None:
    """실적 한 건. 이 선박이 「실적 없음」이 아니게 만드는 것이 목적이다."""
    row = await session.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, "
            " actual_distance_nm, planned_speed_kn, actual_arrival_at) "
            "VALUES (:vid, 'COMPLETED', 'INCLUDE_AS_ACTUAL', :yr, 'BUSAN', 'SINGAPORE', "
            " 1000, 1000, 12, :arr) RETURNING id"
        ),
        {"vid": vessel_id, "yr": YEAR, "arr": datetime(YEAR, 3, 1, tzinfo=UTC)},
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'HFO', 80, 80, 3.114, 'USER_INPUT')"
        ),
        {"vid": str(row.scalar_one())},
    )


async def _insert_voyage(
    session, vessel_id: str, *, arrived: datetime, distance: int, fuel: int
) -> None:
    """도착 시각·거리·연료를 지정한 실적 한 건 (#814).

    `_insert_voyage_with_fuel`은 값이 고정이라 **구간별 강도 차이**를 만들 수 없다.
    `#431` 산식은 「최근 창의 강도 − 경계」로 소비율을 내므로, 창 안팎의 강도가 같으면
    분모가 0 이하가 되어 `NOT_WORSENING`이 나온다.
    """
    row = await session.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, "
            " actual_distance_nm, planned_speed_kn, actual_arrival_at) "
            "VALUES (:vid, 'COMPLETED', 'INCLUDE_AS_ACTUAL', :yr, 'BUSAN', 'SINGAPORE', "
            " :d, :d, 12, :arr) RETURNING id"
        ),
        {"vid": vessel_id, "yr": YEAR, "d": distance, "arr": arrived},
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'HFO', :f, :f, 3.114, 'USER_INPUT')"
        ),
        {"vid": str(row.scalar_one()), "f": fuel},
    )


@pytest.mark.asyncio
async def test_empty_fleet_is_not_an_error(session):
    """선박 0척은 정상 상태다.

    아직 등록하지 않은 선사가 처음 보는 화면이므로 예외로 만들면 안 된다.
    화면은 이 응답으로 「등록된 선박이 없습니다」를 그린다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    result = await get_fleet_summary(session, regulation_year=YEAR)

    assert result["vessels"] == []
    assert result["actions"] == []
    assert result["summary"]["total"] == 0
    assert result["summary"]["at_risk"] == 0


@pytest.mark.asyncio
async def test_as_of_is_echoed(session):
    """`as_of` 계약 ⑵ — 서버가 확정한 값을 응답에 반드시 싣는다."""
    await _seed_parameters(session)
    fixed = datetime(YEAR, 6, 1, 12, 0, tzinfo=UTC)
    result = await get_fleet_summary(session, regulation_year=YEAR, as_of=fixed)
    assert result["as_of"] == fixed.isoformat()


@pytest.mark.asyncio
async def test_counts_match_the_vessel_rows(session):
    """KPI 집계가 목록과 어긋나지 않는다.

    화면과 서버가 각자 세면 필터가 붙었을 때 달라지고, 그 차이는 눈으로 발견되지
    않는다. 그래서 서버가 확정한다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(
        session, imo="9200001", name="A", underway_state="UNDER_WAY", detail_status="SAILING"
    )
    await _insert_vessel(
        session,
        imo="9200002",
        name="B",
        underway_state="NOT_UNDER_WAY",
        detail_status="AT_ANCHOR",
    )
    await _insert_vessel(session, imo="9200003", name="C")  # 상태 미기록

    result = await get_fleet_summary(session, regulation_year=YEAR)
    summary = result["summary"]

    assert summary["total"] == len(result["vessels"]) == 3
    assert summary["under_way"] == 1
    assert summary["not_under_way"] == 1
    # 상태를 모르는 선박을 운항/정박 어느 쪽에도 넣지 않는다 — 넣으면 없는 사실을
    # 만들어 내는 것이다.
    assert summary["unknown_state"] == 1
    assert summary["under_way"] + summary["not_under_way"] + summary["unknown_state"] == 3


@pytest.mark.asyncio
async def test_vessel_without_voyages_reports_no_data(session):
    """항차가 없는 선박은 오류가 아니라 ``data_available=False``다."""
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9200010", name="NO VOYAGE")

    result = await get_fleet_summary(session, regulation_year=YEAR)
    row = result["vessels"][0]

    assert row["data_available"] is False
    assert row["ytd_rating"] is None
    assert row["risk_reasons"] == []
    assert row["days_to_d"] is None
    assert result["summary"]["no_data"] == 1


@pytest.mark.asyncio
async def test_actions_are_derived_from_risk_reasons(session):
    """조치 목록을 따로 만들지 않는다.

    손으로 적으면 KPI 「규제 조치 대상」 수와 목록 항목 수가 어긋날 수 있다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9200020", name="PLAIN")

    result = await get_fleet_summary(session, regulation_year=YEAR)

    assert len(result["actions"]) == result["summary"]["at_risk"]


@pytest.mark.asyncio
async def test_numbers_are_strings(session):
    """`API_SPEC §1.7` — 수치는 문자열로 직렬화한다.

    float으로 되돌리면 Layer 1이 지킨 정밀도가 그 순간 사라진다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(
        session, imo="9200030", name="STR", underway_state="UNDER_WAY", detail_status="SAILING"
    )

    result = await get_fleet_summary(session, regulation_year=YEAR)
    row = result["vessels"][0]

    for key in ("ytd_attained_cii", "ytd_required_cii", "current_lat", "current_lon"):
        assert row[key] is None or isinstance(row[key], str)


# ─────────────────────────────────────────────────────────────────────────────
# CII 적용 대상 표시 (#653)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_applicable_vessel_reports_the_server_judgement(session):
    """선대 행이 **서버 판정을 그대로** 싣는다 (`API_SPEC §2.8`).

    종전에는 이 두 필드가 없어, 대시보드가 등급과 값만 보이고 **그 값이 규제상
    의미가 있는지는 말하지 않았다.**
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9200060", name="BIG", gross_tonnage=30000)

    row = (await get_fleet_summary(session, regulation_year=YEAR))["vessels"][0]

    assert row["is_cii_applicable_hint"] is True
    assert row["gross_tonnage"] == 30000.0


@pytest.mark.asyncio
async def test_small_vessel_and_unknown_gt_are_distinguishable(session):
    """**「미해당」과 「GT가 없어 판정 불가」를 화면이 가를 수 있어야 한다.**

    둘 다 `is_cii_applicable_hint = false`라 그 필드만으로는 구분되지 않는다.
    `gross_tonnage`를 함께 싣는 이유가 이것이다 — 합쳐 보이면 총톤수를 넣지 않은
    사용자가 「이 배는 규제 대상이 아니다」로 읽는다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9200061", name="SMALL", gross_tonnage=4999)
    await _insert_vessel(session, imo="9200062", name="NOGT", gross_tonnage=None)

    rows = {
        r["name"]: r for r in (await get_fleet_summary(session, regulation_year=YEAR))["vessels"]
    }

    assert rows["SMALL"]["is_cii_applicable_hint"] is False
    assert rows["SMALL"]["gross_tonnage"] == 4999.0

    assert rows["NOGT"]["is_cii_applicable_hint"] is False
    assert rows["NOGT"]["gross_tonnage"] is None


@pytest.mark.asyncio
async def test_gross_tonnage_is_a_number_not_a_layer1_string(session):
    """`gross_tonnage`는 계산 **결과**가 아니라 입력 제원이다.

    `API_SPEC §1.7`의 문자열 직렬화는 Layer 1 값에만 적용되고, `§2.1` 선박 객체
    예시는 총톤수를 `25000.0`처럼 숫자로 적는다. 같은 필드가 엔드포인트마다 다른
    형으로 나가면 화면이 매번 형을 확인해야 한다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9200063", name="NUM", gross_tonnage=30000)

    row = (await get_fleet_summary(session, regulation_year=YEAR))["vessels"][0]

    assert isinstance(row["gross_tonnage"], float)


# ─────────────────────────────────────────────────────────────────────────────
# 제원 미비 선박이 선대 전체를 무너뜨리지 않는다 (#419)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vessel_without_capacity_does_not_break_the_fleet(session):
    """**이 이슈의 본체**다.

    `vessel.deadweight`는 nullable이고(`DB_SCHEMA §2.1`) `PRD §20 O-11`이 수동 입력
    경로를 열어 두어, **제원을 나중에 채우려고 등록한 선박**이 실제로 생긴다.
    종전에는 그 한 척이 `GET /fleet/summary` 전체를 500으로 만들었다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9204001", name="정상선")
    await _insert_vessel(session, imo="9204002", name="제원미비선", deadweight=None)

    summary = await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF)

    names = {row["name"] for row in summary["vessels"]}
    assert names == {"정상선", "제원미비선"}, "한 척이 실패해도 나머지가 보여야 한다"


@pytest.mark.asyncio
async def test_healthy_vessel_keeps_its_numbers_next_to_a_broken_one(session):
    """이슈 완료 기준 3항 — **나머지 선박의 값이 정상이어야 한다.**

    목록에 남는 것만으로는 부족하다. 실적이 있어 등급까지 나오는 선박이 옆 선박의
    실패에 휩쓸려 값을 잃으면, 「전체가 죽던 것」이 「전부 빈칸이 되는 것」으로 바뀔
    뿐이다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    healthy = await _insert_vessel(session, imo="9204001", name="정상선")
    await _insert_voyage_with_fuel(session, healthy)
    await _insert_vessel(session, imo="9204002", name="제원미비선", deadweight=None)

    rows = {
        r["name"]: r
        for r in (await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF))["vessels"]
    }

    assert rows["정상선"]["data_available"] is True
    assert rows["정상선"]["ytd_attained_cii"] is not None
    assert rows["정상선"]["ytd_rating"] is not None
    assert rows["정상선"]["unavailable_reason"] is None
    assert rows["제원미비선"]["unavailable_reason"] == UNAVAILABLE_MISSING_SPEC


@pytest.mark.asyncio
async def test_history_failure_does_not_erase_this_years_value(session, monkeypatch):
    """**계산에 성공한 값을 뒤의 조회 실패가 버리지 않는다.**

    이 선박을 계산하는 경로가 셋인데(현재 시점 · 직전 2개 연도 이력 · 최근 구간
    시작점) 셋을 한 try로 묶으면, 이력 조회가 창 규칙 위반 같은 **제원과 무관한
    이유**로 실패해도 이미 나온 올해 값까지 버려진다. 그러면 제원이 멀쩡한 선박에
    「제원을 입력하세요」가 뜬다 — 사용자가 해도 아무것도 바뀌지 않는 안내다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    vessel_id = await _insert_vessel(session, imo="9204001", name="정상선")
    await _insert_voyage_with_fuel(session, vessel_id)

    async def _boom(*args, **kwargs):
        raise ValidationError("from은 2019 이상이어야 합니다", field="from_year")

    monkeypatch.setattr(fleet_summary, "_prior_confirmed_ratings", _boom)

    row = (await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF))["vessels"][0]

    assert row["data_available"] is True
    assert row["ytd_rating"] is not None
    assert row["unavailable_reason"] is None
    # 이력을 못 읽었으므로 「직전 등급을 모른다」 — 모르는 것을 D로 단정하지 않는다.
    assert row["risk_reasons"] == []


@pytest.mark.asyncio
async def test_unexplained_failure_is_not_called_a_spec_problem(session, monkeypatch):
    """제원으로 설명되지 않는 실패에 「제원을 입력하세요」라고 하지 않는다.

    `ValidationError`는 이력 창 규칙·파라미터 seed 손상 등 **선박과 무관한 이유**로도
    난다. 예외의 종류만 보고 사유를 정하면 그것들이 전부 「제원 미비」로 위장된다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9204001", name="정상선")

    async def _boom(*args, **kwargs):
        raise ValidationError("파라미터 seed가 손상됐습니다", field="capacity_rule")

    monkeypatch.setattr(fleet_summary, "compute_ytd_cii", _boom)

    row = (await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF))["vessels"][0]

    assert row["unavailable_reason"] == UNAVAILABLE_CALCULATION_ERROR


@pytest.mark.asyncio
async def test_unsupported_ship_type_is_a_spec_problem(session):
    """미지원 선종은 **선박 정보에서 고칠 수 있으므로** 제원 문제로 묶는다.

    `vessel.ship_type`은 `String(50)`이고 DB에 enum 제약이 없어(`calc/capacity.py`)
    오타 선종이 실제로 저장된다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9204004", name="오타선종", ship_type="BULK_CARRIRE")

    row = (await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF))["vessels"][0]

    assert row["unavailable_reason"] == UNAVAILABLE_MISSING_SPEC


@pytest.mark.asyncio
async def test_missing_spec_is_distinguished_from_no_data(session):
    """「실적 없음」과 「제원 미비」는 **사용자가 할 일이 다르다.**

    전자는 항차를 등록해야 하고 후자는 제원을 입력해야 한다. 같은 빈칸으로 그리면
    화면이 무엇을 하라고 말할 수 없다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9204001", name="정상선")
    await _insert_vessel(session, imo="9204002", name="제원미비선", deadweight=None)

    rows = {
        r["name"]: r
        for r in (await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF))["vessels"]
    }

    # 제원은 있으나 항차가 없다 → NO_DATA
    assert rows["정상선"]["unavailable_reason"] == UNAVAILABLE_NO_DATA
    # 제원 자체가 없다 → MISSING_SPEC
    assert rows["제원미비선"]["unavailable_reason"] == UNAVAILABLE_MISSING_SPEC


@pytest.mark.asyncio
async def test_unavailable_vessel_reports_no_numbers(session):
    """계산하지 못한 선박에 수치를 지어내지 않는다."""
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9204002", name="제원미비선", deadweight=None)

    row = (await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF))["vessels"][0]

    assert row["data_available"] is False
    assert row["ytd_attained_cii"] is None
    assert row["ytd_rating"] is None
    # 등급이 없으므로 위험 판정도 없다 — 「모름」을 「위험 아님」으로도 「위험」으로도 읽지 않는다.
    assert row["risk_reasons"] == []


@pytest.mark.asyncio
async def test_missing_ship_type_parameters_is_per_vessel_not_fleet_wide(session):
    """선종별 기준선이 없는 선박도 **그 선박만** 값이 비어야 한다.

    연도 파라미터와 달리 기준선·등급경계는 **선종별**이라 선대 공통이 아니다. 한
    선종의 seed가 빠져도(가이드라인 개정으로 선종이 추가된 직후 등) 나머지 선박은
    정상으로 보여야 한다.

    기준선 조회는 실적이 있어야 일어나므로(항차가 없으면 그 전에 「실적 없음」으로
    끝난다) 항차를 하나 넣어 실제로 파라미터 조회까지 가게 한다. 삭제는 이 트랜잭션
    안에서만 유효하며 끝나면 롤백된다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9204001", name="정상선")
    tanker = await _insert_vessel(session, imo="9204003", name="미지원선종", ship_type="TANKER")
    await _insert_voyage_with_fuel(session, tanker)
    await session.execute(text("DELETE FROM cii_reference_line WHERE ship_type = 'TANKER'"))
    await session.execute(text("DELETE FROM cii_rating_boundary WHERE ship_type = 'TANKER'"))

    rows = {
        r["name"]: r
        for r in (await get_fleet_summary(session, regulation_year=YEAR, as_of=AS_OF))["vessels"]
    }

    assert len(rows) == 2
    assert rows["미지원선종"]["unavailable_reason"] == UNAVAILABLE_NO_PARAMETERS


@pytest.mark.asyncio
async def test_missing_regulation_year_still_fails_the_whole_request(session):
    """**연도 파라미터 부재는 선대 공통이라 요청 전체가 실패해야 한다.**

    루프 안에서 잡으면 「전 선박이 파라미터 없음」으로 표시되어, 실제 원인(그 해의
    규정 seed가 없다)이 선박 문제로 위장된다. `API_SPEC §2.8`도 409로 규정한다.
    """
    from cii_platform.errors import ParameterError

    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    await _insert_vessel(session, imo="9204001", name="정상선")

    with pytest.raises(ParameterError):
        await get_fleet_summary(session, regulation_year=1999, as_of=AS_OF)


@pytest.mark.asyncio
async def test_empty_fleet_is_not_an_error_even_without_parameters(session):
    """**선박 0척이 오류가 아니라는 계약이 파라미터 확인보다 우선한다.**

    아직 아무것도 등록하지 않은 선사가 처음 보는 화면이다. 계산할 대상이 없으므로
    파라미터도 필요 없는데, 여기서 409를 내면 사용자는 「기능이 고장났다」로 읽는다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)

    result = await get_fleet_summary(session, regulation_year=1999, as_of=AS_OF)

    assert result["vessels"] == []
    assert result["summary"]["total"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 「D등급 진입까지 n일」이 실제로 숫자를 낸다 (#814)
#
# `fleet_summary`가 `boundaries.get("d")`를 조회했는데 `determine_rating`은 그 키를
# 만들지 않는다(넷뿐이고 전부 `*_boundary`). `boundary is None`이 **항상 참**이라
# `#431`이 만든 산식 33줄이 한 줄도 실행되지 않았고, 사유는 언제나 `NO_DATA`였다.
# 대시보드의 「D등급 진입까지 n일」은 **한 번도 숫자를 낸 적이 없다.**
# ─────────────────────────────────────────────────────────────────────────────


def test_the_d_entry_boundary_key_exists_in_the_engine_output():
    """`fleet_summary`가 찾는 키가 **엔진이 실제로 만드는 키**다 (#814).

    이 검사가 없으면 키를 다시 오타 내도 아무 데서도 드러나지 않는다 —
    `dict.get()`은 없는 키에 `None`을 돌려주고, 그 `None`은 정상적인 사유
    (`NO_DATA`)로 흡수된다. **오류도 로그도 남지 않는다.**
    """
    boundaries = _rating_of(Decimal("5.0")).boundaries

    assert fleet_summary._D_ENTRY_BOUNDARY_KEY in boundaries, (
        f"fleet_summary가 찾는 키 {fleet_summary._D_ENTRY_BOUNDARY_KEY!r}를 "
        f"determine_rating이 만들지 않는다. 실제 키: {sorted(boundaries)}"
    )
    # C를 벗어나는 지점이 곧 D 진입점이다 — 판정 부등식(`attained <= upper` → C)과 짝.
    assert fleet_summary._D_ENTRY_BOUNDARY_KEY == "upper_boundary"


def test_every_boundary_key_used_in_src_exists_in_the_engine_output():
    """``src/``가 참조하는 boundary 키가 **전부 실재한다** (#814).

    ## 왜 문자열을 훑는가

    `boundaries`는 dict이고 **API 응답과 `calculation_run.result_json`에 그 키 이름
    그대로 실린다**(`API_SPEC §2.14`). 저장된 JSON을 다시 읽는 경로는 dataclass로
    바꿔도 타입 검사가 닿지 않는다 — 그래서 타입이 아니라 **참조 전수 대조**로 막는다.

    ## 무엇을 보지 않는가

    반대 방향(「엔진이 만드는 키를 아무도 안 쓴다」)은 보지 않는다. 쓰지 않는 경계가
    있는 것은 결함이 아니다.
    """
    import re
    from pathlib import Path

    boundaries = set(_rating_of(Decimal("5.0")).boundaries)
    referenced: dict[str, set[str]] = {}
    # 접근 대상 이름을 고정하지 않는다 — `annual_simulation`은 `decimal_bounds[...]`로
    # 받는다. `*_boundary`로 끝나는 문자열 리터럴 조회를 전부 본다.
    pattern = re.compile(r'(?:\.get\(\s*|\[\s*)"(\w*_boundary)"')

    src = Path(__file__).resolve().parents[1] / "src"
    for py in src.rglob("*.py"):
        for key in pattern.findall(py.read_text(encoding="utf-8")):
            referenced.setdefault(key, set()).add(py.name)

    assert referenced, "boundary 키 참조를 하나도 찾지 못했다 — 패턴이 낡았는지 확인할 것"

    unknown = {k: sorted(v) for k, v in referenced.items() if k not in boundaries}
    assert not unknown, (
        f"determine_rating이 만들지 않는 boundary 키를 참조한다: {unknown}. "
        f"실제 키: {sorted(boundaries)} (#814)"
    )


@pytest.mark.asyncio
async def test_days_to_d_is_a_number_for_a_worsening_vessel(session):
    """운항 중이고 D보다 나은 선박에서 `days_to_d`에 **숫자**가 들어간다 (#814).

    `#814`의 완료 기준 1이다. 순수 함수 검사(`compute_days_to_target`)는 종전에도
    있었지만 **가짜 경계 dict**로 돌아 실제 배선을 보지 못했다 — 이 검사는
    `get_fleet_summary` 응답까지 지나간다.

    최근 30일이 그 이전보다 나빠야 소비율이 양수가 되므로, 항차를 **두 구간**으로
    나눠 뒤 구간의 연료 강도를 높인다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    vessel_id = await _insert_vessel(
        session,
        imo="9000814",
        name="DAYS TO D",
        # `chk_vessel_state_pair`(마이그레이션 026) — 둘은 함께 있거나 함께 없어야 한다.
        underway_state="UNDER_WAY",
        detail_status="SAILING",
    )

    # 초반: 효율이 좋은 구간 (강도 낮음).
    await _insert_voyage(
        session, vessel_id, arrived=datetime(YEAR, 1, 20, tzinfo=UTC), distance=5000, fuel=200
    )
    # 최근 30일: 강도를 크게 올린다 — 이게 없으면 NOT_WORSENING이다.
    await _insert_voyage(
        session, vessel_id, arrived=datetime(YEAR, 6, 20, tzinfo=UTC), distance=1000, fuel=300
    )

    result = await get_fleet_summary(
        session, regulation_year=YEAR, as_of=datetime(YEAR, 6, 25, tzinfo=UTC)
    )
    vessel = next(v for v in result["vessels"] if v["vessel_id"] == vessel_id)

    assert vessel["days_to_d_reason"] != REASON_NO_DATA, (
        f"사유가 NO_DATA다 — 경계값을 못 읽고 있다(#814의 결함이 되살아났다). 응답: {vessel}"
    )
    assert isinstance(vessel["days_to_d"], int), (
        f"days_to_d가 숫자가 아니다: {vessel['days_to_d']!r} / 사유 {vessel['days_to_d_reason']!r}"
    )
    assert vessel["days_to_d"] >= 0
    assert vessel["days_to_d_reason"] is None


@pytest.mark.asyncio
async def test_days_to_d_baseline_counts_the_in_progress_contribution(session):
    """「D등급까지 n일」의 30일 전 기준선에도 **그 시점의 진행분**이 들어간다 (#864).

    현재값에는 진행 중 항차의 연초부터 누적이 들어 있는데 기준선에 빠지면 그
    전체가 30일 창의 증가분으로 계상되어 n일이 실제보다 몇 배 짧아진다. 서비스의
    `days_to_d`가 **올바른 기준선으로 직접 계산한 값**과 같은지, 그리고 결함
    기준선(진행분 누락)의 값과 실제로 갈리는지를 나란히 본다 — 둘 중 하나만 보면
    「같은 잘못을 같이 하면 통과한다」에 걸린다.
    """
    await _seed_parameters(session)
    await _hide_seeded_vessels(session)
    vessel_id = await _insert_vessel(
        session,
        imo="9000864",
        name="DAYS BASELINE",
        # `chk_vessel_state_pair`(마이그레이션 026) — 둘은 함께 있거나 함께 없어야 한다.
        underway_state="UNDER_WAY",
        detail_status="SAILING",
    )
    # 시뮬레이션 시계(#368)가 진행분 연료를 내려면 소모율·유종 제원이 필요하다.
    # foc 30t/일 × 14kn의 소비율은 D 진입 경계보다 나빠야 소비율이 양수가 된다.
    await session.execute(
        text(
            "UPDATE vessel SET reference_speed_kn = 14, reference_daily_foc_ton = 30, "
            "default_fuel_type = 'HFO' WHERE id = :id"
        ),
        {"id": UUID(vessel_id)},
    )
    # 확정 실적 — 등급을 D보다 좋은 밴드로 띄우되 attained가 경계 근처에 붙게 한다.
    # 경계에서 멀면 외삽 일수가 연말을 넘어 `NOT_THIS_YEAR`(None)가 되어 버리니,
    # 올바른 기준선의 n일이 연말 안에 들어오도록 확정 연료를 잡는다.
    await _insert_voyage(
        session, vessel_id, arrived=datetime(YEAR, 3, 20, tzinfo=UTC), distance=5000, fuel=300
    )
    # 진행 중 항차 — 창 시작보다 앞서 출항해 기준선 기여분이 실재하게 만든다.
    # foc와 경과일이 attained를 D 진입 경계 너머로 밀면 `ALREADY_AT_OR_BELOW`가
    # 되어 n일이 사라지므로, 확정 실적을 낮게 잡아 B 밴드에 둔다.
    await session.execute(
        text(
            "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
            " actual_departure_at, planned_arrival_at, created_from) "
            "VALUES (:vid, 'IN_PROGRESS', 'INCLUDE_AS_PLAN', :yr, 'BUSAN', 'SINGAPORE', "
            " 3000, 14, :departed, NULL, 'MANUAL')"
        ),
        {"vid": vessel_id, "yr": YEAR, "departed": datetime(YEAR, 7, 20, tzinfo=UTC)},
    )

    as_of = datetime(YEAR, 9, 1, tzinfo=UTC)
    window_start = as_of - timedelta(days=30)
    vessel_row = await vessel_repo.get_by_id(session, UUID(vessel_id))

    in_progress_now = (
        (await resolve_in_progress_state(session, vessel=vessel_row, as_of=as_of))
        .for_year(YEAR)
        .contribution
    )
    now = await compute_ytd_cii(
        session,
        vessel_id=vessel_id,
        regulation_year=YEAR,
        as_of=as_of,
        in_progress=in_progress_now,
    )
    in_progress_past = (
        (await resolve_in_progress_state(session, vessel=vessel_row, as_of=window_start))
        .for_year(YEAR)
        .contribution
    )
    past_fixed = await compute_ytd_cii(
        session,
        vessel_id=vessel_id,
        regulation_year=YEAR,
        as_of=window_start,
        in_progress=in_progress_past,
    )
    past_buggy = await compute_ytd_cii(
        session, vessel_id=vessel_id, regulation_year=YEAR, as_of=window_start
    )

    days_fixed = compute_days_to_target(
        now, past=past_fixed, underway_state="UNDER_WAY", as_of=as_of
    )
    days_buggy = compute_days_to_target(
        now, past=past_buggy, underway_state="UNDER_WAY", as_of=as_of
    )

    assert days_fixed.days is not None, (
        f"올바른 기준선에서도 값을 못 냈다: fixed={days_fixed!r} buggy={days_buggy!r}"
    )
    # 결함 기준선의 증상은 둘 중 하나다 — 겉소비율이 경계 아래로 내려가 값이
    # 소실되거나(NOT_WORSENING), 남는 증가분이 전부 진행분으로 계상되어 과대
    # 짧은 n일이 나온다.
    assert days_buggy.days is None or days_fixed.days > days_buggy.days, (
        f"기준선의 진행분이 값을 바꾸지 못했다 — 재현 데이터가 결함을 덮는다: "
        f"fixed={days_fixed!r} buggy={days_buggy!r}"
    )

    fleet = await get_fleet_summary(session, regulation_year=YEAR, as_of=as_of)
    vessel = next(v for v in fleet["vessels"] if v["vessel_id"] == vessel_id)
    assert vessel["days_to_d"] == days_fixed.days, (
        f"서비스 days_to_d({vessel['days_to_d']!r})가 올바른 기준선 값({days_fixed.days!r})과 "
        f"다르다 — 결함 기준선 결과는 {days_buggy!r} (#864)"
    )


def test_days_to_d_reasons_match_the_api_spec_table():
    """코드의 사유 상수와 `API_SPEC §2.8` 표가 같다 (#814).

    ## 왜 어긋나 있었나

    `#431`이 산식을 넣으며 `NO_RECENT_DATA`·`NOT_WORSENING` 둘을 추가했으나 정본에
    옮기지 못했다. 그런데 **같은 시기에 경계 키 오타로 그 산식이 한 줄도 실행되지
    않아**, 두 사유가 응답에 나온 적이 없었다 — 문서에 빠진 사실이 드러날 자리가
    없었다. 결함 둘이 서로를 가린 형태다.

    ## 무엇을 보는가

    표에 있는 것이 코드에 있고, 코드에 있는 것이 표에 있는지 **양방향**으로 본다.
    한 방향만 보면 「문서에만 있는 사유」나 「코드에만 있는 사유」 중 하나가 남는다
    (`#591`이 엔드포인트 표에서 양방향 6종을 찾아낸 뒤의 관례다).
    """
    import re
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[1] / "API_SPEC.md").read_text(encoding="utf-8")
    section = spec.split("#### `days_to_d`")[1].split("#### `unavailable_reason`")[0]
    documented = set(re.findall(r"^\| `([A-Z_]+)` \|", section, re.M))

    in_code = {
        REASON_ALREADY_AT_OR_BELOW,
        REASON_NOT_THIS_YEAR,
        REASON_NOT_UNDER_WAY,
        REASON_NO_DATA,
        REASON_NO_RECENT_DATA,
        REASON_NOT_WORSENING,
    }

    assert documented, "§2.8의 사유 표를 읽지 못했다 — 형식이 바뀌었는지 확인할 것"
    assert documented == in_code, (
        f"문서에만 있는 사유: {sorted(documented - in_code)} / "
        f"코드에만 있는 사유: {sorted(in_code - documented)}"
    )


def test_every_reason_constant_is_covered_by_the_contract_test():
    """위 검사의 `in_code` 집합이 모듈의 `REASON_*` **전부**다 (#814).

    이 검사가 없으면 새 사유를 추가하면서 위 집합에 넣는 것을 잊을 수 있고, 그러면
    문서 대조가 **그 사유를 모르는 채로 통과**한다.
    """
    declared = {
        value
        for name, value in vars(fleet_summary).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }

    assert declared == {
        REASON_ALREADY_AT_OR_BELOW,
        REASON_NOT_THIS_YEAR,
        REASON_NOT_UNDER_WAY,
        REASON_NO_DATA,
        REASON_NO_RECENT_DATA,
        REASON_NOT_WORSENING,
    }, f"모듈의 REASON_* 상수: {sorted(declared)}"
