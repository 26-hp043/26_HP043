"""데이터 점검 서비스 DB 실동작 검증 (`API_SPEC §2.16` · `PRD §17.4` · #513).

판정 수식은 ``tests/test_data_quality.py``가 본다. 여기는 **실제 DB 행에서 네 심각도가
맞게 갈리는가**와 **CII 영향·완결성이 선박 누적값과 같은 재료로 나오는가**를 본다.

선대 전체를 도는 서비스라 시드된 데모 선박도 결과에 섞인다 — 검사는 **이 파일이 넣은
선박으로 걸러** 단언한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import ensure_regulation_year, insert_returning_id

from cii_platform.services.data_quality import (
    IMPACT_ONLY_VOYAGE,
    SEVERITY_ANOMALY,
    SEVERITY_SUBSTITUTED,
    SEVERITY_UNAVAILABLE,
    SEVERITY_UNCONFIRMED,
    UNAVAILABLE_FUEL_UNFILLED,
    get_fleet_data_quality,
)
from cii_platform.services.ytd_cii import compute_ytd_cii

YEAR = 2026


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> str:
    """기준 속력 12kn · 기준 일일 연료 24t — 2,880nm를 12kn로 가면 기대 연료 240t."""
    await ensure_regulation_year(session, 2026)
    return await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
        " reference_speed_kn, reference_daily_foc_ton) "
        "VALUES ('9513001', 'DQ TEST', 'BULK_CARRIER', 30000, 50000, 12, 24) RETURNING id",
        {},
    )


async def _voyage(
    session,
    vessel_id: str,
    *,
    no: str,
    status: str = "CONFIRMED",
    actual_distance: float | None = 2880,
    speed: float | None = 12,
    hours: int | None = 240,
    planned_fuel: float | None = 240,
    actual_fuel: float | None = 240,
) -> str:
    departure = datetime.fromisoformat("2026-03-01T00:00:00+00:00")
    arrival = None if hours is None else departure + timedelta(hours=hours)
    voyage_id = await insert_returning_id(
        session,
        "INSERT INTO voyage "
        "(vessel_id, voyage_no, status, annual_inclusion_policy, regulation_year, "
        " departure_port_name, arrival_port_name, planned_distance_nm, actual_distance_nm, "
        " planned_speed_kn, actual_avg_speed_kn, actual_departure_at, actual_arrival_at) "
        "VALUES (:vid, :no, :st, 'INCLUDE_AS_ACTUAL', :yr, 'BUSAN', 'SINGAPORE', 2880, "
        " :dist, 12, :spd, :dep, :arr) RETURNING id",
        {
            "vid": vessel_id,
            "no": no,
            "st": status,
            "yr": YEAR,
            "dist": actual_distance,
            "spd": speed,
            "dep": None if hours is None else departure,
            "arr": arrival,
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'HFO', :pt, :at, 3.114, 'USER_INPUT')"
        ),
        {"vid": voyage_id, "pt": planned_fuel, "at": actual_fuel},
    )
    return voyage_id


async def _mine(session, vessel_id: str) -> tuple[dict, list[dict], dict]:
    result = await get_fleet_data_quality(session, regulation_year=YEAR)
    vessel = next(row for row in result["vessels"] if row["vessel_id"] == vessel_id)
    issues = [item for item in result["issues"] if item["vessel_id"] == vessel_id]
    return vessel, issues, result["summary"]


def _by(issues: list[dict], severity: str) -> list[dict]:
    return [item for item in issues if item["severity"] == severity]


@pytest.mark.asyncio
async def test_clean_confirmed_voyages_raise_no_issue(session, vessel_id):
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B")

    vessel, issues, _ = await _mine(session, vessel_id)

    assert issues == []
    assert vessel["completeness_ratio"] == "1.0000"


@pytest.mark.asyncio
async def test_missing_actual_fuel_is_a_substitution_with_its_cii_impact(session, vessel_id):
    """⚠️ **CII 영향은 그 항차를 뺀 누적 CII와의 차이다** (`PRD §17.4.2`).

    서비스의 값을 **같은 함수로 따로 구한 두 누적값의 차**와 대조한다 — 식을 옮겨 적으면
    부호가 뒤집혀도 그럴듯한 값이 나온다.
    """
    keep = await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=300)

    _, issues, _ = await _mine(session, vessel_id)
    substituted = _by(issues, SEVERITY_SUBSTITUTED)

    assert [item["voyage_id"] for item in substituted] == [target]
    assert substituted[0]["codes"] == ["FUEL:HFO"]

    base = await compute_ytd_cii(session, vessel_id=UUID(vessel_id), regulation_year=YEAR)
    without = await compute_ytd_cii(
        session,
        vessel_id=UUID(vessel_id),
        regulation_year=YEAR,
        exclude_voyage_ids=frozenset({UUID(target)}),
    )
    impact = substituted[0]["cii_impact"]
    assert Decimal(impact["delta"]) == pytest.approx(
        base.attained_cii - without.attained_cii, abs=Decimal("1e-4")
    )
    # 계획 300t이 섞여 누적이 나빠졌다 — 빼면 좋아진다.
    assert Decimal(impact["delta"]) > 0
    assert keep != target


@pytest.mark.asyncio
async def test_a_fuel_row_with_nothing_in_it_is_unavailable_not_substituted(session, vessel_id):
    """실적도 계획도 없는 행은 **아무것도 들어가지 않았다** — 대체로 세면 「추정이 들어갔다」다."""
    await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=None)

    _, issues, _ = await _mine(session, vessel_id)

    assert _by(issues, SEVERITY_SUBSTITUTED) == []
    unavailable = _by(issues, SEVERITY_UNAVAILABLE)
    assert [item["voyage_id"] for item in unavailable] == [target]
    assert unavailable[0]["codes"] == [f"{UNAVAILABLE_FUEL_UNFILLED}:HFO"]


@pytest.mark.asyncio
async def test_fuel_far_from_the_model_is_an_anomaly(session, vessel_id):
    """기대 240t에 480t(2배) — 이상치. **계산에서는 빼지 않는다**(`PRD §17.1`)."""
    await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", actual_fuel=480)

    _, issues, _ = await _mine(session, vessel_id)
    anomaly = _by(issues, SEVERITY_ANOMALY)

    assert [item["voyage_id"] for item in anomaly] == [target]
    assert anomaly[0]["codes"] == ["FUEL_VS_MODEL"]

    ytd = await compute_ytd_cii(session, vessel_id=UUID(vessel_id), regulation_year=YEAR)
    assert ytd.voyage_count == 2


@pytest.mark.asyncio
async def test_completed_but_not_confirmed_is_unconfirmed(session, vessel_id):
    await _voyage(session, vessel_id, no="A")
    target = await _voyage(session, vessel_id, no="B", status="COMPLETED")

    vessel, issues, _ = await _mine(session, vessel_id)

    assert [item["voyage_id"] for item in _by(issues, SEVERITY_UNCONFIRMED)] == [target]
    # 값 자체는 실측이다 — 완결성에서 빼지 않는다.
    assert vessel["completeness_ratio"] == "1.0000"


@pytest.mark.asyncio
async def test_completeness_is_the_measured_share_of_co2(session, vessel_id):
    """실측 240t + 대체 360t → 실측 CO₂ 비율 240 ÷ 600 = 0.4 (항차 수로 세면 0.5)."""
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=360)

    vessel, _, _ = await _mine(session, vessel_id)

    assert vessel["completeness_ratio"] == "0.4000"


@pytest.mark.asyncio
async def test_an_anomalous_voyage_is_not_counted_as_measured(session, vessel_id):
    """⚠️ 이상치 항차는 값이 들어가 있어도 **믿기 어려운 값**이다 — 완결성의 「실측」에서 뺀다.

    실측 240t + 이상치 480t → 240 ÷ 720 = 0.3333. 이상치를 실측으로 세면 1.0000이 되어
    **믿기 어려운 데이터가 많은 선박일수록 완결돼 보인다.** (첫 판 검사가 이 결함을 못 잡았다 —
    돌연변이로 확인.)
    """
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B", actual_fuel=480)

    vessel, _, _ = await _mine(session, vessel_id)

    assert vessel["completeness_ratio"] == "0.3333"


@pytest.mark.asyncio
async def test_a_single_voyage_has_no_impact_to_compare(session, vessel_id):
    """항차가 하나뿐이면 빼고 난 누적이 없다 — 0이 아니라 **사유**를 낸다."""
    await _voyage(session, vessel_id, no="A", status="COMPLETED")

    _, issues, _ = await _mine(session, vessel_id)
    unconfirmed = _by(issues, SEVERITY_UNCONFIRMED)

    assert unconfirmed[0]["cii_impact"] is None
    assert unconfirmed[0]["cii_impact_reason"] == IMPACT_ONLY_VOYAGE


@pytest.mark.asyncio
async def test_voyages_that_cannot_be_judged_are_counted_apart(session, vessel_id):
    """⚠️ **판정 못 함은 이상치 0건과 섞지 않는다** — 제원·시각이 없는 항차."""
    await session.execute(
        text(
            "UPDATE vessel SET reference_speed_kn = NULL, reference_daily_foc_ton = NULL "
            "WHERE id = :id"
        ),
        {"id": vessel_id},
    )
    before = (await get_fleet_data_quality(session, regulation_year=YEAR))["summary"]
    await _voyage(session, vessel_id, no="A", hours=None)

    _, issues, after = await _mine(session, vessel_id)

    assert _by(issues, SEVERITY_ANOMALY) == []
    assert after["anomaly_unjudged_count"] == before["anomaly_unjudged_count"] + 1


@pytest.mark.asyncio
async def test_a_vessel_that_cannot_be_calculated_is_unavailable(session, vessel_id):
    """선대 요약(`#419`)과 **같은 사유 어휘**를 쓴다 — 제원이 없으면 ``MISSING_SPEC``."""
    await _voyage(session, vessel_id, no="A")
    await session.execute(
        text("UPDATE vessel SET deadweight = NULL WHERE id = :id"), {"id": vessel_id}
    )

    vessel, issues, _ = await _mine(session, vessel_id)

    assert vessel["unavailable_reason"] == "MISSING_SPEC"
    vessel_level = [item for item in _by(issues, SEVERITY_UNAVAILABLE) if item["voyage_id"] is None]
    assert vessel_level[0]["codes"] == ["MISSING_SPEC"]
    assert vessel["completeness_ratio"] is None


@pytest.mark.asyncio
async def test_issues_are_grouped_in_design_system_order(session, vessel_id):
    """그룹 순서 = `DESIGN_SYSTEM §2.3.1` 표 순서(대체 → 계산 불가 → 이상치 → 미입력)."""
    await _voyage(session, vessel_id, no="A", status="COMPLETED")
    await _voyage(session, vessel_id, no="B", actual_fuel=480)
    await _voyage(session, vessel_id, no="C", actual_fuel=None, planned_fuel=300)

    _, issues, _ = await _mine(session, vessel_id)

    assert [item["severity"] for item in issues] == [
        SEVERITY_SUBSTITUTED,
        SEVERITY_ANOMALY,
        SEVERITY_UNCONFIRMED,
    ]


@pytest.mark.asyncio
async def test_response_shape_matches_api_spec(session, vessel_id):
    """`API_SPEC §2.16` 필드 집합 — 영향이 **있는** 행과 **없는** 행을 함께 본다.

    선대 계약표(`test_response_contract_db.py`)에 넣지 않은 이유: 이 응답의 `issues[]`는
    **DB에 어떤 항차가 있느냐에 따라** 영향 블록의 유무가 갈려, 공용 데이터로 비교하면
    다른 파일이 남긴 행에 따라 결과가 흔들린다. 여기서 만든 데이터로 **양쪽 모양을 다** 본다.
    """
    await _voyage(session, vessel_id, no="A")
    await _voyage(session, vessel_id, no="B", actual_fuel=None, planned_fuel=300)
    await _voyage(session, vessel_id, no="C", status="COMPLETED")

    result = await get_fleet_data_quality(session, regulation_year=YEAR)

    assert set(result) == {"regulation_year", "summary", "vessels", "issues"}
    assert set(result["summary"]) == {
        "substituted_count",
        "unavailable_count",
        "anomaly_count",
        "unconfirmed_count",
        "anomaly_unjudged_count",
        "completeness_ratio",
    }
    mine = next(row for row in result["vessels"] if row["vessel_id"] == vessel_id)
    assert set(mine) == {
        "vessel_id",
        "vessel_name",
        "data_available",
        "unavailable_reason",
        "ytd_attained_cii",
        "ytd_rating",
        "voyage_count",
        "completeness_ratio",
    }
    issues = [item for item in result["issues"] if item["vessel_id"] == vessel_id]
    for item in issues:
        assert set(item) == {
            "severity",
            "vessel_id",
            "vessel_name",
            "voyage_id",
            "voyage_no",
            "codes",
            "cii_impact",
            "cii_impact_reason",
        }
    with_impact = [item["cii_impact"] for item in issues if item["cii_impact"] is not None]
    assert with_impact, "영향 블록이 있는 행을 만들지 못했다 — 검사가 한쪽 모양만 본다"
    assert set(with_impact[0]) == {
        "attained_cii",
        "attained_cii_without",
        "delta",
        "rating",
        "rating_without",
    }


def test_the_route_answers_over_http(migrated_db, app_fresh_engine):
    """⚠️ **실제 HTTP 경로로 받아 본다** — 서비스 검사는 라우트 배선·봉투·인증을 보지 않는다.

    데모 시드 위라 ``issues[]`` 모양은 데이터에 따라 갈린다 — 여기서는 **데이터와 무관한
    키만** 단언하고, 행 모양은 위 ``test_response_shape_matches_api_spec``가 본다.
    """
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(f"{API_V1_PREFIX}/fleet/data-quality").status_code == 401

        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        response = client.get(f"{API_V1_PREFIX}/fleet/data-quality?regulation_year={YEAR}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"data", "meta"}
        assert body["data"]["regulation_year"] == YEAR
        assert set(body["data"]["summary"]) >= {"anomaly_unjudged_count", "completeness_ratio"}

        out_of_range = client.get(f"{API_V1_PREFIX}/fleet/data-quality?regulation_year=1999")
        assert out_of_range.status_code == 422
