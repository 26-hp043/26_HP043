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

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.fleet_summary import (
    REASON_ALREADY_AT_OR_BELOW,
    REASON_NO_DATA,
    REASON_NOT_THIS_YEAR,
    REASON_NOT_UNDER_WAY,
    compute_days_to_target,
    evaluate_risk_reasons,
    get_fleet_summary,
)
from cii_platform.services.ytd_cii import YtdCiiOutput

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


def _ytd(**over) -> YtdCiiOutput:
    base = {
        "data_available": True,
        "regulation_year": YEAR,
        "capacity_axis": "DWT",
        "transport_capacity": Decimal("50000"),
        "attained_cii": Decimal("5.0"),
        "rating": "C",
        "boundaries": {"d": Decimal("6.0")},
        "underway_distance_nm": Decimal("1000"),
    }
    base.update(over)
    return YtdCiiOutput(**base)


AS_OF = datetime(YEAR, 3, 1, tzinfo=UTC)


def test_days_no_data_when_ytd_unavailable():
    result = compute_days_to_target(
        _ytd(data_available=False, attained_cii=None, rating=None),
        underway_state="UNDER_WAY",
        as_of=AS_OF,
    )
    assert result.days is None
    assert result.reason == REASON_NO_DATA


def test_days_already_at_or_below_for_d():
    result = compute_days_to_target(_ytd(rating="D"), underway_state="UNDER_WAY", as_of=AS_OF)
    assert result.reason == REASON_ALREADY_AT_OR_BELOW


def test_days_already_at_or_below_for_e():
    result = compute_days_to_target(_ytd(rating="E"), underway_state="UNDER_WAY", as_of=AS_OF)
    assert result.reason == REASON_ALREADY_AT_OR_BELOW


def test_days_not_computed_while_not_under_way():
    """정박 중에는 산정하지 않는다.

    거리가 늘지 않고 연료만 늘어 CII가 단조 악화하므로, n일이 하루가 다르게
    짧아졌다가 **출항하는 순간 되돌아간다.** 요동치는 숫자 대신 사유를 준다.
    """
    result = compute_days_to_target(_ytd(), underway_state="NOT_UNDER_WAY", as_of=AS_OF)
    assert result.days is None
    assert result.reason == REASON_NOT_UNDER_WAY


def test_days_not_this_year_when_far_away():
    """올해 안에 도달하지 않으면 숫자 대신 사유를 준다."""
    # 경계까지 여유가 매우 커서 외삽 결과가 연말을 넘는 경우.
    result = compute_days_to_target(
        _ytd(attained_cii=Decimal("1.0"), boundaries={"d": Decimal("99.0")}),
        underway_state="UNDER_WAY",
        as_of=datetime(YEAR, 12, 20, tzinfo=UTC),
    )
    assert result.days is None
    assert result.reason == REASON_NOT_THIS_YEAR


def test_days_returns_a_number_in_the_normal_case():
    result = compute_days_to_target(_ytd(), underway_state="UNDER_WAY", as_of=AS_OF)
    assert result.reason is None
    assert isinstance(result.days, int)
    assert result.days >= 0


def test_days_no_data_without_boundary():
    result = compute_days_to_target(_ytd(boundaries=None), underway_state="UNDER_WAY", as_of=AS_OF)
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
) -> str:
    row = await session.execute(
        text(
            "INSERT INTO vessel "
            "(imo_number, name, ship_type, gross_tonnage, deadweight, "
            " underway_state, detail_status) "
            "VALUES (:imo, :name, 'BULK_CARRIER', 30000, 50000, :st, :ds) "
            "RETURNING id"
        ),
        {"imo": imo, "name": name, "st": underway_state, "ds": detail_status},
    )
    return str(row.scalar_one())


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
