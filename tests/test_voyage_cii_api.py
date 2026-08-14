"""기능① API 계약 테스트 (#55) — **DB 없이 돈다.**

저장소 함수를 monkeypatch로 갈아 끼우고 세션 의존성을 대역으로 바꿔, **라우트 →
서비스 → 직렬화 → JSON** 전 구간을 실제 HTTP 요청으로 통과시킨다.

이 방식으로 잡는 것: 필드명 오타, JSON 타입 위반(Layer 1이 숫자로 나감), 오류 코드·
HTTP status 불일치, ``meta`` 누락, 계약 예시와 다른 자릿수.

이 방식으로 못 잡는 것: 실제 쿼리의 정합성, 제약 위반, 트랜잭션 경계. 그건 DB가 있는
CI에서 별도 테스트가 확인한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

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
)
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.db.session import get_session

ENDPOINT = "/api/v1/calculations/voyage-cii"

#: 정본 픽스처와 같은 조건. 이 요청의 응답이 #132 계약 기대값과 같아야 한다.
VALID_PAYLOAD: dict[str, Any] = {
    "vessel_id": str(DEMO_VESSEL_ID),
    "regulation_year": DEMO_YEAR,
    "distance_nm": 1000.0,
    "speed_kn": 12.0,
    "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 80.0}],
    "weather_model": "NONE",
}


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> Iterator[TestClient]:
    """저장소를 전부 대역으로 바꾸고 클라이언트를 준다.

    **서비스 모듈이 import한 이름을 바꾼다.** ``from ... import X`` 형태로 들여온
    이름은 원본 모듈을 patch해도 바뀌지 않으므로, 서비스가 실제로 참조하는 모듈
    객체(``param_repo`` 등)의 속성을 갈아 끼운다.
    """
    from cii_platform.services import voyage_cii as svc

    async def fake_get_by_id(_session, vessel_id):
        return FakeVessel() if vessel_id == DEMO_VESSEL_ID else None

    async def fake_regulation_year(_session, year):
        return FakeRegulationYear() if year == DEMO_YEAR else None

    async def fake_reference_lines(_session, ship_type):
        return [FakeReferenceLine()] if ship_type == "BULK_CARRIER" else []

    async def fake_rating_boundaries(_session, ship_type):
        return [FakeRatingBoundary()] if ship_type == "BULK_CARRIER" else []

    async def fake_fuel_types(_session, codes):
        known = {"HFO": FakeFuelType()}
        return {code: known[code] for code in codes if code in known}

    async def fake_insert(_session, **_kwargs):
        return FakeCalculationRun()

    monkeypatch.setattr(svc.vessel_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(svc.param_repo, "get_regulation_year", fake_regulation_year)
    monkeypatch.setattr(svc.param_repo, "list_reference_lines", fake_reference_lines)
    monkeypatch.setattr(svc.param_repo, "list_rating_boundaries", fake_rating_boundaries)
    monkeypatch.setattr(svc.param_repo, "get_fuel_types_by_codes", fake_fuel_types)
    monkeypatch.setattr(svc.calc_run_repo, "insert_voyage_estimate", fake_insert)

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
    """정상 응답 본문. 여러 테스트가 같은 응답을 본다."""
    resp = wired.post(ENDPOINT, json=VALID_PAYLOAD)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- 계약값 --------------------------------------------------------------------------


class TestContractValues:
    """응답 수치가 #132 계약·정본 픽스처와 같다."""

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("attained_cii", "4.982400"),
            ("required_cii", "5.045066"),
            ("ratio_to_required", "0.98758"),
            ("estimated_rating", "C"),
            ("next_worse_boundary_margin", "0.365370"),
            ("next_worse_boundary_margin_ratio", "0.0724"),
            ("co2_emission_ton", "249.12"),
            ("fuel_consumption_ton", "80.00"),
            ("risk_level", "MEDIUM"),
            ("transport_capacity", "50000"),
            ("transport_capacity_basis", "DWT"),
            ("reference_capacity", "50000"),
            ("reference_capacity_rule", "DWT"),
        ],
    )
    def test_data_field(self, ok_body, field, expected):
        assert ok_body["data"][field] == expected

    def test_calculation_basis(self, ok_body):
        basis = ok_body["data"]["calculation_basis"]
        assert basis["ship_type"] == "BULK_CARRIER"
        assert basis["z_factor_percent"] == "11.0"
        assert basis["a_decimal"] == "4745"
        assert basis["c"] == "0.622"
        assert basis["fuel_cf_details"] == [{"fuel_type": "HFO", "cf": "3.114", "fuel_ton": "80.0"}]


# --- JSON 타입 -----------------------------------------------------------------------


class TestJsonTypes:
    """API_SPEC §1.7 — Layer 1 값은 **문자열**, 입력 에코는 숫자."""

    @pytest.mark.parametrize(
        "field",
        [
            "attained_cii",
            "required_cii",
            "ratio_to_required",
            "next_worse_boundary_margin",
            "next_worse_boundary_margin_ratio",
            "co2_emission_ton",
            "fuel_consumption_ton",
            "transport_capacity",
            "reference_capacity",
        ],
    )
    def test_layer1_is_string(self, ok_body, field):
        """숫자로 나가면 클라이언트의 JSON 파서가 배정밀도로 잘라 버린다.

        문자열로 직렬화하는 이유가 그것이므로(§1.7 `[ORACLE-C-1]`) 타입 자체를 잠근다.
        """
        assert isinstance(ok_body["data"][field], str), field

    def test_distance_is_number(self, ok_body):
        """``distance_nm``은 입력 에코라 **숫자**다 (§4.1 응답 타입 표)."""
        assert isinstance(ok_body["data"]["distance_nm"], (int, float))
        assert ok_body["data"]["distance_nm"] == 1000.0

    def test_model_version_is_mixed(self, ok_body):
        """``model_version``은 혼합 타입 — ``decimal_precision``만 number다."""
        mv = ok_body["model_version"]
        assert isinstance(mv["decimal_precision"], int)
        for key in (
            "engine",
            "decimal_rounding",
            "rng_algorithm",
            "numpy_version",
            "python_version",
        ):
            assert isinstance(mv[key], str), key

    def test_decimal_precision_is_canonical_not_working(self, ok_body):
        """공표 자릿수(30)를 싣는다. **작업 정밀도(50)가 아니다.**

        #179가 두 값을 분리했고, 클라이언트가 알아야 하는 것은 「응답 값이 몇 자리로
        확정됐는가」다.
        """
        assert ok_body["model_version"]["decimal_precision"] == 30


# --- envelope ------------------------------------------------------------------------


class TestEnvelope:
    """최상위 구조 (API_SPEC §4.1)."""

    def test_top_level_keys(self, ok_body):
        assert set(ok_body) == {
            "data",
            "parameters_used",
            "calculation_run_id",
            "model_version",
            "input_hash",
            "parameter_hash",
            "warnings",
            "disclaimer",
            "meta",
        }

    def test_internal_key_is_not_leaked(self, ok_body):
        """서비스가 쓰는 내부 키(``_duration_ms``)가 응답에 남지 않는다."""
        assert "_duration_ms" not in ok_body

    def test_hashes_match_db_constraint_format(self, ok_body):
        """``sha256:`` + 64 hex — DB_SCHEMA §2.5 ``chk_input_hash_format``와 같은 형식.

        형식이 어긋나면 저장 단계에서 CHECK 제약에 걸려 500이 된다.
        """
        import re

        pattern = re.compile(r"^sha256:[0-9a-f]{64}$")
        assert pattern.match(ok_body["input_hash"])
        assert pattern.match(ok_body["parameter_hash"])

    def test_warnings_and_disclaimer(self, ok_body):
        assert ok_body["warnings"] == ["REFERENCE_ONLY"]
        assert ok_body["disclaimer"] == "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다."

    def test_meta(self, ok_body):
        meta = ok_body["meta"]
        assert set(meta) == {"request_id", "timestamp", "duration_ms"}
        assert isinstance(meta["request_id"], str)
        assert isinstance(meta["duration_ms"], int)

    def test_parameters_used(self, ok_body):
        used = ok_body["parameters_used"]
        assert used["regulation_year"] == {"year": "2026", "z_factor_percent": "11.0"}
        assert used["fuel_types"] == [{"code": "HFO", "cf": "3.114"}]
        assert used["reference_line"]["ship_type"] == "BULK_CARRIER"
        assert used["rating_boundary"] == {
            "d1": "0.86",
            "d2": "0.94",
            "d3": "1.06",
            "d4": "1.18",
        }

    def test_transaction_is_committed(self, wired, session):
        """서비스가 트랜잭션을 닫는다. 열어 두면 이력이 저장되지 않는다."""
        wired.post(ENDPOINT, json=VALID_PAYLOAD)
        assert session.committed == 1


# --- 검증 오류 -----------------------------------------------------------------------


class TestValidationErrors:
    """Pydantic 검증 실패가 API_SPEC §1.3.2 형태로 나간다 (#116)."""

    @pytest.mark.parametrize(
        ("patch", "field"),
        [
            ({"distance_nm": 0}, "distance_nm"),
            ({"distance_nm": -1}, "distance_nm"),
            ({"speed_kn": 0.9}, "speed_kn"),
            ({"fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 0}]}, "fuel_uses[0].fuel_ton"),
            ({"fuel_uses": []}, "fuel_uses"),
        ],
    )
    def test_returns_422_with_field_path(self, wired, patch, field):
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, **patch})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        fields = [detail["field"] for detail in body["error"]["details"]]
        assert field in fields, fields

    def test_speed_exactly_one_knot_is_accepted(self, wired):
        """VAL-009는 **≥ 1.0**이다. 경계값이 거부되면 안 된다."""
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "speed_kn": 1.0})
        assert resp.status_code == 200

    def test_unknown_field_is_rejected(self, wired):
        """``speed_knots`` 같은 오타를 조용히 무시하지 않는다.

        무시하면 사용자가 보낸 값이 반영되지 않은 결과가 나가고, 화면에서는
        정상으로 보인다. #55 이슈 본문이 이 혼동을 명시적으로 경고한다.
        """
        payload = {**VALID_PAYLOAD}
        payload["speed_knots"] = 12.0
        resp = wired.post(ENDPOINT, json=payload)
        assert resp.status_code == 422

    def test_error_envelope_has_meta(self, wired):
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "distance_nm": 0})
        body = resp.json()
        assert set(body) == {"error", "meta"}
        assert "request_id" in body["meta"]
        assert "timestamp" in body["meta"]

    def test_field_label_is_attached(self, wired):
        """``field_label``이 한글 라벨로 채워진다 (API_SPEC §1.3.2 · §11)."""
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "distance_nm": 0})
        detail = next(d for d in resp.json()["error"]["details"] if d["field"] == "distance_nm")
        assert detail["field_label"] == "운항 거리"


# --- 도메인 오류 ---------------------------------------------------------------------


class TestDomainErrors:
    """서비스가 던지는 오류의 코드·status가 API_SPEC §1.4와 같다."""

    def test_unknown_vessel_is_404(self, wired):
        resp = wired.post(
            ENDPOINT,
            json={**VALID_PAYLOAD, "vessel_id": "00000000-0000-4000-8000-0000000000ff"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_unknown_regulation_year_is_409(self, wired):
        """**422가 아니라 409다.** 사용자가 요청을 고쳐도 해결되지 않고 서버에 그
        연도의 Z계수 행이 없는 상태다 (TECH_SPEC §12.1 ``ParameterError``).
        """
        resp = wired.post(ENDPOINT, json={**VALID_PAYLOAD, "regulation_year": 2099})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PARAMETER_ERROR"

    def test_unknown_fuel_type_is_422_with_field(self, wired):
        """VAL-006 — **입력 문제라 422**이며 필드 경로가 붙는다."""
        resp = wired.post(
            ENDPOINT,
            json={**VALID_PAYLOAD, "fuel_uses": [{"fuel_type": "ETHANE", "fuel_ton": 80.0}]},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"][0]["field"] == "fuel_uses[0].fuel_type"


# --- 동일 연료 합산 -------------------------------------------------------------------


class TestDuplicateFuelRows:
    """API_SPEC §4.1 — 「동일 ``fuel_type``이 여러 행이면 Decimal로 합산한다」."""

    @pytest.fixture
    def split_body(self, wired):
        resp = wired.post(
            ENDPOINT,
            json={
                **VALID_PAYLOAD,
                "fuel_uses": [
                    {"fuel_type": "HFO", "fuel_ton": 30.0},
                    {"fuel_type": "HFO", "fuel_ton": 50.0},
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_result_equals_single_row(self, split_body, ok_body):
        """30 + 50과 80이 같은 결과를 낸다."""
        assert split_body["data"]["attained_cii"] == ok_body["data"]["attained_cii"]
        assert split_body["data"]["co2_emission_ton"] == ok_body["data"]["co2_emission_ton"]

    def test_details_normalized_to_one_row(self, split_body):
        """``fuel_cf_details``는 **연료 종류당 한 행**으로 정규화된다."""
        details = split_body["data"]["calculation_basis"]["fuel_cf_details"]
        assert len(details) == 1
        assert details[0]["fuel_ton"] == "80.0"

    def test_input_hash_differs_from_single_row(self, split_body, ok_body):
        """**입력이 다르므로 해시는 달라야 한다.**

        결과가 같다고 해시까지 같으면 재현성 추적이 「무엇을 넣었는가」를 잃는다.
        """
        assert split_body["input_hash"] != ok_body["input_hash"]

    def test_parameter_hash_is_identical(self, split_body, ok_body):
        """반대로 **파라미터는 같으므로 parameter_hash는 같아야 한다.**"""
        assert split_body["parameter_hash"] == ok_body["parameter_hash"]


# --- 결정성 --------------------------------------------------------------------------


class TestDeterminism:
    def test_same_request_gives_same_values_and_hashes(self, wired):
        """TECH_SPEC §5.4 재현성 — 같은 입력에 같은 값·같은 해시."""
        first = wired.post(ENDPOINT, json=VALID_PAYLOAD).json()
        second = wired.post(ENDPOINT, json=VALID_PAYLOAD).json()
        assert first["data"] == second["data"]
        assert first["input_hash"] == second["input_hash"]
        assert first["parameter_hash"] == second["parameter_hash"]

    def test_calculation_run_id_differs(self, wired):
        """**이력은 매번 새로 생긴다** — 멱등하지 않다 (#55 「항상 새로 생성」)."""
        first = wired.post(ENDPOINT, json=VALID_PAYLOAD).json()
        second = wired.post(ENDPOINT, json=VALID_PAYLOAD).json()
        assert first["calculation_run_id"] != second["calculation_run_id"]


# --- 등급 E --------------------------------------------------------------------------


class TestGradeEResponse:
    def test_margin_fields_are_null(self, wired):
        """등급 E는 악화 방향 경계가 없어 ``null``이 나간다 (#171 결론)."""
        resp = wired.post(
            ENDPOINT,
            json={**VALID_PAYLOAD, "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 200.0}]},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["estimated_rating"] == "E"
        assert data["next_worse_boundary_margin"] is None
        assert data["next_worse_boundary_margin_ratio"] is None
        assert data["risk_level"] == "CRITICAL"


# --- 입력 변화 -----------------------------------------------------------------------


class TestInputEffects:
    """무엇이 무엇을 바꾸는가 — 데모 체크리스트가 확인하는 성질."""

    def _post(self, client, **patch):
        resp = client.post(ENDPOINT, json={**VALID_PAYLOAD, **patch})
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    def test_speed_does_not_change_anything(self, wired):
        """``speed_kn``은 Layer 1 계산의 피연산자가 아니다 (§4.1 각주)."""
        slow = self._post(wired, speed_kn=1.0)
        fast = self._post(wired, speed_kn=25.0)
        assert slow["attained_cii"] == fast["attained_cii"]
        assert slow["co2_emission_ton"] == fast["co2_emission_ton"]
        assert slow["estimated_rating"] == fast["estimated_rating"]

    def test_distance_changes_cii_but_not_co2(self, wired):
        """**거리를 바꿔도 CO₂는 그대로다.** 오류로 오인하기 쉬운 정상 동작이다."""
        base = self._post(wired)
        longer = self._post(wired, distance_nm=1200.0)
        assert longer["co2_emission_ton"] == base["co2_emission_ton"]
        assert Decimal(longer["attained_cii"]) < Decimal(base["attained_cii"])

    def test_fuel_moves_both(self, wired):
        base = self._post(wired)
        more = self._post(wired, fuel_uses=[{"fuel_type": "HFO", "fuel_ton": 90.0}])
        assert Decimal(more["co2_emission_ton"]) > Decimal(base["co2_emission_ton"])
        assert Decimal(more["attained_cii"]) > Decimal(base["attained_cii"])
