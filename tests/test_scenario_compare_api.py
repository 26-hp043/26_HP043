"""기능② API 계약 테스트 (#57) — **DB 없이 돈다.**

``test_voyage_cii_api``와 같은 방식: 저장소를 대역으로 갈아 끼워 라우트 → 서비스 →
직렬화 → JSON 전 구간을 실제 HTTP 요청으로 통과시킨다.

기대값(앵커)은 서비스 조립이 아니라 ``calc`` 엔진 직접 호출로 산출했다 —
PRD §11.2 시나리오 생성 + §11.4.1 cubic speed model을 시나리오별로 적용한 값이다.
입력: 50,000 DWT 벌크선(기준속도 14.0kn) · FOC 35.0t/day · HFO · 직항 11,000nm.

DIRECT와 DETOUR의 ``attained_cii``가 같은 것은 오류가 아니라 수학적 필연이다 —
같은 속도에서 cubic 모델의 연료는 거리에 정비례하고 ``W = capacity × distance``도
거리에 정비례하므로 CII는 거리와 무관해진다. §5.1 예시의 4.982/5.231이 같은 속도에서
다른 CII를 보이는 것은 그 예시값이 재현 불가능하다는 뜻이다 (#151).

케이스: AT-SC-001 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fakes import (
    DEMO_VESSEL_ID,
    DEMO_YEAR,
    FakeCalculationRun,
    FakeFuelType,
    FakeRatingBoundary,
    FakeReferenceLine,
    FakeRegulationYear,
    FakeSession,
    FakeVessel,
    FakeVoyageScenario,
)
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.db.session import get_session

ENDPOINT = "/api/v1/scenarios/compare"

VALID_PAYLOAD: dict[str, Any] = {
    "vessel_id": str(DEMO_VESSEL_ID),
    "regulation_year": DEMO_YEAR,
    "current_speed_kn": 14.0,
    "fuel_type": "HFO",
    "base_daily_foc_ton": 35.0,
    "direct_distance_nm": 11000.0,
}

#: 앵커 — calc 엔진 직접 산출. 시나리오 생성 규칙(PRD §11.2)이 적용된 값.
ANCHOR: dict[str, dict[str, Any]] = {
    "DIRECT": {
        "distance_nm": 11000.0,
        "speed_kn": 14.0,
        "duration_hours": "785.7143",
        "fuel_ton": "1145.83",
        "co2_emission_ton": "3568.13",
        "attained_cii": "6.487500",
        "ratio_to_required": "1.28591",
        "estimated_rating": "E",
        "risk_level": "CRITICAL",
        "next_worse_boundary_margin": None,
        "next_worse_boundary_margin_ratio": None,
    },
    "DETOUR": {
        "distance_nm": 11550.0,
        "speed_kn": 14.0,
        "duration_hours": "825.0000",
        "fuel_ton": "1203.13",
        "co2_emission_ton": "3746.53",
        "attained_cii": "6.487500",
        "ratio_to_required": "1.28591",
        "estimated_rating": "E",
        "risk_level": "CRITICAL",
        "next_worse_boundary_margin": None,
        "next_worse_boundary_margin_ratio": None,
    },
    "SLOW_STEAMING": {
        "distance_nm": 11000.0,
        "speed_kn": 13.0,
        "duration_hours": "846.1538",
        "fuel_ton": "987.99",
        "co2_emission_ton": "3076.60",
        "attained_cii": "5.593814",
        "ratio_to_required": "1.10877",
        "estimated_rating": "D",
        "risk_level": "HIGH",
        "next_worse_boundary_margin": "0.359364",
        "next_worse_boundary_margin_ratio": "0.0712",
    },
}

SCENARIO_ORDER = ["DIRECT", "DETOUR", "SLOW_STEAMING"]


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> Iterator[TestClient]:
    """저장소를 대역으로 바꾸고 클라이언트를 준비한다 (기능① 패턴)."""
    from cii_platform.services import scenario_compare as svc

    async def fake_get_by_id(_session, vessel_id):
        return (
            FakeVessel(reference_speed_kn=Decimal("14.0")) if vessel_id == DEMO_VESSEL_ID else None
        )

    async def fake_regulation_year(_session, year):
        return FakeRegulationYear() if year == DEMO_YEAR else None

    async def fake_reference_lines(_session, ship_type):
        return [FakeReferenceLine()] if ship_type == "BULK_CARRIER" else []

    async def fake_rating_boundaries(_session, ship_type):
        return [FakeRatingBoundary()] if ship_type == "BULK_CARRIER" else []

    async def fake_fuel_types(_session, codes):
        known = {"HFO": FakeFuelType()}
        return {code: known[code] for code in codes if code in known}

    async def fake_insert_run(_session, **_kwargs):
        return FakeCalculationRun()

    inserted_scenarios: list[dict[str, Any]] = []

    async def fake_insert_scenario(_session, **kwargs):
        inserted_scenarios.append(kwargs)
        return FakeVoyageScenario()

    monkeypatch.setattr(svc.vessel_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(svc.param_repo, "get_regulation_year", fake_regulation_year)
    monkeypatch.setattr(svc.param_repo, "list_reference_lines", fake_reference_lines)
    monkeypatch.setattr(svc.param_repo, "list_rating_boundaries", fake_rating_boundaries)
    monkeypatch.setattr(svc.param_repo, "get_fuel_types_by_codes", fake_fuel_types)
    monkeypatch.setattr(svc.calc_run_repo, "insert_scenario", fake_insert_run)
    monkeypatch.setattr(svc.scenario_repo, "insert", fake_insert_scenario)

    # 삽입 기록을 테스트가 읽을 수 있게 세션에 붙인다 — 모듈 속성은 teardown 순서에
    # 좌우되지 않는 곳에 둔다.
    session.inserted_scenarios = inserted_scenarios  # type: ignore[attr-defined]

    async def override_session():
        yield session

    from fakes import FAKE_CSRF_TOKEN, FAKE_SESSION_TOKEN, install_fake_auth

    from cii_platform.auth.session import SESSION_COOKIE_NAME

    install_fake_auth(monkeypatch)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, FAKE_SESSION_TOKEN)
        client.headers.update({"X-CSRF-Token": FAKE_CSRF_TOKEN})
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def ok_body(wired: TestClient) -> dict[str, Any]:
    resp = wired.post(ENDPOINT, json=VALID_PAYLOAD)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- 계약값 --------------------------------------------------------------------------


class TestContractValues:
    """응답 수치가 앵커와 같다."""

    @pytest.mark.parametrize("scenario_type", SCENARIO_ORDER)
    def test_scenario_fields(self, ok_body, scenario_type):
        scenarios = ok_body["data"]["scenarios"]
        actual = next(s for s in scenarios if s["scenario_type"] == scenario_type)
        for field, expected in ANCHOR[scenario_type].items():
            assert actual[field] == expected, f"{scenario_type}.{field}"

    def test_scenario_order(self, ok_body):
        """PRD §11.2 표 순서 — DIRECT · DETOUR · SLOW_STEAMING."""
        types = [s["scenario_type"] for s in ok_body["data"]["scenarios"]]
        assert types == SCENARIO_ORDER

    def test_scenario_name_korean(self, ok_body):
        names = {s["scenario_type"]: s["scenario_name"] for s in ok_body["data"]["scenarios"]}
        assert names == {"DIRECT": "직항", "DETOUR": "우회", "SLOW_STEAMING": "감속"}

    def test_scenario_id_is_uuid_and_distinct(self, ok_body):
        ids = [s["scenario_id"] for s in ok_body["data"]["scenarios"]]
        assert len(set(ids)) == 3
        for scenario_id in ids:
            UUID(scenario_id)

    def test_required_cii_shared_across_scenarios(self, ok_body):
        """required_cii는 시나리오와 무관하다 — 같은 선박·연도 파라미터다."""
        required = {s["required_cii"] for s in ok_body["data"]["scenarios"]}
        assert required == {"5.045066"}

    def test_calculation_basis_capacity_fields(self, ok_body):
        """AT-SC-003 — calculation_basis에 capacity 필드가 있다."""
        basis = ok_body["data"]["scenarios"][0]["calculation_basis"]
        assert basis["transport_capacity"] == "50000"
        assert basis["transport_capacity_basis"] == "DWT"
        assert basis["reference_capacity"] == "50000"
        assert basis["reference_capacity_rule"] == "DWT"
        assert basis["z_factor_percent"] == "11.0"
        assert basis["a_decimal"] == "4745"
        assert basis["c"] == "0.622"

    def test_summary_neutral_minima(self, ok_body):
        """AT-SC-002 — 추천 문구 없이 지표별 최소값만."""
        assert ok_body["data"]["summary"] == {
            "lowest_cii_scenario": "SLOW_STEAMING",
            "shortest_duration_scenario": "DIRECT",
            "lowest_fuel_scenario": "SLOW_STEAMING",
        }

    def test_weather_defaults_to_none(self, ok_body):
        for s in ok_body["data"]["scenarios"]:
            assert s["weather_model_used"] == "NONE"
            assert s["weather_factor"] == 1.0

    def test_parameters_used_schema(self, ok_body):
        used = ok_body["parameters_used"]
        assert used["regulation_year"] == {"year": "2026", "z_factor_percent": "11.0"}
        assert used["fuel_types"] == [{"code": "HFO", "cf": "3.114"}]
        assert used["rating_boundary"] == {
            "d1": "0.86",
            "d2": "0.94",
            "d3": "1.06",
            "d4": "1.18",
        }


class TestEnvelope:
    """AT-SC-004 — warnings·disclaimer·hash·meta·이력 저장."""

    def test_warnings_and_disclaimer(self, ok_body):
        assert ok_body["warnings"] == ["REFERENCE_ONLY"]
        assert ok_body["disclaimer"] == "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다."

    def test_hash_format(self, ok_body):
        import re

        pattern = re.compile(r"^sha256:[0-9a-f]{64}$")
        assert pattern.match(ok_body["input_hash"])
        assert pattern.match(ok_body["parameter_hash"])

    def test_meta(self, ok_body):
        meta = ok_body["meta"]
        assert set(meta) == {"request_id", "timestamp", "duration_ms"}
        assert isinstance(meta["duration_ms"], int)

    def test_calculation_run_id_present(self, ok_body):
        UUID(ok_body["calculation_run_id"])

    def test_transaction_is_committed(self, wired, session):
        wired.post(ENDPOINT, json=VALID_PAYLOAD)
        assert session.committed == 2

    def test_audit_records_scenario_type(self, wired, session):
        """감사 로그에 SCENARIO 타입으로 남는다 (#277)."""
        wired.post(ENDPOINT, json=VALID_PAYLOAD)
        audits = [obj for obj in session.added if type(obj).__name__ == "AuditLog"]
        assert len(audits) == 1
        assert audits[0].details_json["calculation_type"] == "SCENARIO"
        assert audits[0].details_json["status"] == "SUCCESS"

    def test_voyage_scenario_rows_inserted(self, wired, session):
        """시나리오 3행이 저장되고 독립 시나리오(voyage_id NULL)다."""
        wired.post(ENDPOINT, json=VALID_PAYLOAD)
        recorded = session.inserted_scenarios  # type: ignore[attr-defined]
        assert [row["scenario_type"] for row in recorded] == SCENARIO_ORDER
        assert all(row["scenario_name"] in ("직항", "우회", "감속") for row in recorded)


# --- 시나리오 생성 규칙 ----------------------------------------------------------------


class TestScenarioGeneration:
    """PRD §11.2 — 기본값·floor·좌표 경로."""

    def test_explicit_detour_distance_wins(self, wired):
        payload = {**VALID_PAYLOAD, "detour_distance_nm": 12000.0}
        resp = wired.post(ENDPOINT, json=payload)
        detour = next(s for s in resp.json()["data"]["scenarios"] if s["scenario_type"] == "DETOUR")
        assert detour["distance_nm"] == 12000.0

    def test_explicit_slow_speed_wins(self, wired):
        payload = {**VALID_PAYLOAD, "slow_speed_kn": 12.5}
        resp = wired.post(ENDPOINT, json=payload)
        slow = next(
            s for s in resp.json()["data"]["scenarios"] if s["scenario_type"] == "SLOW_STEAMING"
        )
        assert slow["speed_kn"] == 12.5

    def test_slow_speed_floor_warning(self, wired):
        """current 1.5kn → 감속 0.5kn이 아니라 floor 1.0kn + 경고 (PRD §11.2)."""
        payload = {**VALID_PAYLOAD, "current_speed_kn": 1.5}
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        slow = next(s for s in body["data"]["scenarios"] if s["scenario_type"] == "SLOW_STEAMING")
        assert slow["speed_kn"] == 1.0
        assert "SLOW_SPEED_FLOOR" in body["warnings"]

    def test_explicit_slow_speed_at_floor_still_warns(self, wired):
        """명시적 slow_speed_kn=1.0도 floor 경고를 낸다.

        경고의 의미는 「감속 시나리오가 최소 속도에서 운항한다」는 사실 자체다 —
        기본값 산출 경로에서 floor에 걸렸는지와 무관하게, 1.0kn에서의 cubic 모델
        외삽은 신뢰도가 낮아 사용자가 알아야 한다 (PRD §11.2 「floor 도달 시 경고」).
        """
        payload = {**VALID_PAYLOAD, "slow_speed_kn": 1.0}
        resp = wired.post(ENDPOINT, json=payload)
        assert "SLOW_SPEED_FLOOR" in resp.json()["warnings"]

    def test_slow_speed_above_floor_no_warning(self, wired):
        """명시적 slow_speed_kn이 floor 위면 경고가 없다."""
        payload = {**VALID_PAYLOAD, "slow_speed_kn": 12.5}
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.json()["warnings"] == ["REFERENCE_ONLY"]

    def test_coordinates_resolve_direct_distance(self, wired):
        """거리 대신 좌표 → 대권거리(§5.1 예시 좌표 = 4832.64nm)."""
        payload = {
            key: value for key, value in VALID_PAYLOAD.items() if key != "direct_distance_nm"
        } | {
            "current_lat": 35.0,
            "current_lon": 129.0,
            "destination_lat": 51.9244,
            "destination_lon": 4.4778,
        }
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.status_code == 200, resp.text
        direct = next(s for s in resp.json()["data"]["scenarios"] if s["scenario_type"] == "DIRECT")
        assert direct["distance_nm"] == 4832.64

    def test_weather_model_falls_back_with_warning(self, wired):
        """#61 전까지 NONE이 아닌 모델은 fallback + WEATHER_NONE_FALLBACK."""
        payload = {**VALID_PAYLOAD, "weather_model": "SIMPLE_RULE"}
        body = wired.post(ENDPOINT, json=payload).json()
        assert "WEATHER_NONE_FALLBACK" in body["warnings"]
        assert body["data"]["scenarios"][0]["weather_model_used"] == "NONE"

    def test_base_daily_foc_from_vessel(self, wired, monkeypatch):
        """요청에 없으면 선박 기준값(FakeVessel.reference_daily_foc_ton)을 쓴다."""
        from cii_platform.services import scenario_compare as svc

        async def fake_get_by_id(_session, vessel_id):
            return FakeVessel(
                reference_speed_kn=Decimal("14.0"),
                reference_daily_foc_ton=Decimal("30.0"),
            )

        monkeypatch.setattr(svc.vessel_repo, "get_by_id", fake_get_by_id)
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "base_daily_foc_ton"}
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.status_code == 200, resp.text

    def test_non_cii_vessel_warning(self, wired, monkeypatch):
        from cii_platform.services import scenario_compare as svc

        async def fake_get_by_id(_session, vessel_id):
            return FakeVessel(
                reference_speed_kn=Decimal("14.0"),
                gross_tonnage=Decimal("4999.00"),
            )

        monkeypatch.setattr(svc.vessel_repo, "get_by_id", fake_get_by_id)
        body = wired.post(ENDPOINT, json=VALID_PAYLOAD).json()
        assert "NON_CII_VESSEL" in body["warnings"]


# --- 검증·도메인 오류 ------------------------------------------------------------------


class TestValidationErrors:
    def test_missing_reference_speed_on_vessel(self, wired, monkeypatch):
        """선박에 reference_speed_kn이 없으면 cubic 모델 분모가 없다 → 422."""
        from cii_platform.services import scenario_compare as svc

        async def fake_get_by_id(_session, vessel_id):
            return FakeVessel() if vessel_id == DEMO_VESSEL_ID else None

        monkeypatch.setattr(svc.vessel_repo, "get_by_id", fake_get_by_id)
        resp = wired.post(ENDPOINT, json=VALID_PAYLOAD)
        assert resp.status_code == 422
        fields = [d["field"] for d in resp.json()["error"]["details"]]
        assert "vessel_id" in fields

    def test_missing_base_daily_foc(self, wired, monkeypatch):
        from cii_platform.services import scenario_compare as svc

        async def fake_get_by_id(_session, vessel_id):
            return FakeVessel(reference_speed_kn=Decimal("14.0"))

        monkeypatch.setattr(svc.vessel_repo, "get_by_id", fake_get_by_id)
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "base_daily_foc_ton"}
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.status_code == 422
        fields = [d["field"] for d in resp.json()["error"]["details"]]
        assert "base_daily_foc_ton" in fields

    def test_no_distance_no_coordinates(self, wired):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "direct_distance_nm"}
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.status_code == 422
        fields = [d["field"] for d in resp.json()["error"]["details"]]
        assert "direct_distance_nm" in fields

    def test_same_point_coordinates_rejected(self, wired):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "direct_distance_nm"} | {
            "current_lat": 35.0,
            "current_lon": 129.0,
            "destination_lat": 35.0,
            "destination_lon": 129.0,
        }
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.status_code == 422

    def test_unknown_fuel_type(self, wired):
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "fuel_type": "UNKNOWN"})
        assert resp.status_code == 422
        fields = [d["field"] for d in resp.json()["error"]["details"]]
        assert "fuel_type" in fields

    @pytest.mark.parametrize(
        ("patch", "field"),
        [
            ({"current_speed_kn": 0.9}, "current_speed_kn"),
            ({"slow_speed_kn": 0.9}, "slow_speed_kn"),
            ({"direct_distance_nm": -1}, "direct_distance_nm"),
            ({"current_lat": 91}, "current_lat"),
        ],
    )
    def test_schema_rejections(self, wired, patch, field):
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, **patch})
        assert resp.status_code == 422
        fields = [d["field"] for d in resp.json()["error"]["details"]]
        assert field in fields

    def test_unknown_field_rejected(self, wired):
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "speed_knots": 12.0})
        assert resp.status_code == 422

    def test_unknown_vessel_404(self, wired):
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "vessel_id": str(UUID(int=1))})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_missing_regulation_year_409(self, wired):
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "regulation_year": 2031})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PARAMETER_ERROR"
