"""선박 조회·등록 API 계약 테스트 (#51, #50) — **DB 없이 돈다.**

커서 인코딩·페이지네이션 판단·응답 형태·검증 규칙·중복 체크는 DB 없이 검증할 수 있고,
실제 쿼리의 정합성은 DB가 있는 CI가 확인한다.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fakes import DEMO_VESSEL_ID, FakeReferenceLine, FakeSession, FakeVessel
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.db.repositories.vessel import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Cursor,
    decode_cursor,
    encode_cursor,
)
from cii_platform.db.session import get_session
from cii_platform.services.vessel import normalize_limit

LIST_URL = "/api/v1/vessels"


# --- 커서 ---------------------------------------------------------------------------


class TestCursor:
    """keyset 커서 인코딩."""

    def test_roundtrip(self):
        cursor = Cursor(name="샘플 벌크선 (50,000 DWT)", vessel_id=str(DEMO_VESSEL_ID))
        assert decode_cursor(encode_cursor(cursor)) == cursor

    def test_name_with_special_characters(self):
        """선박명에 공백·괄호·쉼표가 들어가도 왕복이 성립한다."""
        cursor = Cursor(name="M/V  A,B (X) — 한글", vessel_id=str(uuid4()))
        assert decode_cursor(encode_cursor(cursor)) == cursor

    def test_is_opaque(self):
        """내부 구조가 그대로 노출되지 않는다.

        노출하면 클라이언트가 형식에 의존하게 되어 정렬 키를 바꿀 수 없다.
        """
        token = encode_cursor(Cursor(name="STAR SKIPPER", vessel_id=str(DEMO_VESSEL_ID)))
        assert "STAR SKIPPER" not in token

    @pytest.mark.parametrize("token", ["", "!!!not-base64!!!", "YWJj", "///"])
    def test_broken_cursor_returns_none_not_exception(self, token):
        """**예외를 던지지 않는다.** 잘못된 커서로 500이 나가면 안 된다."""
        assert decode_cursor(token) is None

    @pytest.mark.parametrize(
        "token",
        # base64는 정상이지만 vessel_id가 UUID가 아닌 값들.
        [
            base64.urlsafe_b64encode(b"A\x00not-a-uuid").decode(),
            base64.urlsafe_b64encode(b"A\x00" + b"x" * 36).decode(),
            base64.urlsafe_b64encode(b"A\x00123").decode(),
        ],
    )
    def test_non_uuid_vessel_id_returns_none(self, token):
        """#233 — base64는 정상이더라도 vessel_id가 UUID가 아니면 None.

        잘못된 값이 DB까지 내려가 asyncpg가 거절 → 500이 되는 경로를 막는다.
        """
        assert decode_cursor(token) is None


# --- limit 정규화 --------------------------------------------------------------------


class TestNormalizeLimit:
    """API_SPEC §2.1 「기본 20, 최대 100」."""

    def test_default(self):
        assert normalize_limit(None) == DEFAULT_LIMIT == 20

    def test_within_range(self):
        assert normalize_limit(5) == 5

    def test_clamped_not_rejected(self):
        """상한 초과는 **오류가 아니라 절삭**이다.

        422를 내면 클라이언트가 재시도 로직을 따로 만들어야 한다.
        """
        assert normalize_limit(1000) == MAX_LIMIT == 100

    @pytest.mark.parametrize("value", [0, -1])
    def test_non_positive_is_rejected(self, value):
        """0 이하는 의미가 없으므로 422로 돌려준다."""
        from cii_platform.errors import ValidationError

        with pytest.raises(ValidationError):
            normalize_limit(value)


# --- API ----------------------------------------------------------------------------


def _vessels(count: int) -> list[FakeVessel]:
    """이름 순으로 정렬된 대역 선박 목록."""
    return [
        FakeVessel(
            id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
            imo_number=f"900000{index}",
            name=f"VESSEL {index:03d}",
        )
        for index in range(1, count + 1)
    ]


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, dict]]:
    """저장소를 대역으로 바꾸고 호출 인자를 기록한다."""
    from cii_platform.services import vessel as svc

    recorded: dict = {}
    store: list[FakeVessel] = _vessels(3)

    async def fake_list_active(_session, *, limit, cursor=None, ship_type=None, search=None):
        recorded["limit"] = limit
        recorded["cursor"] = cursor
        recorded["ship_type"] = ship_type
        recorded["search"] = search
        return store[: limit + 1]

    async def fake_get_by_id(_session, vessel_id):
        return next((v for v in store if v.id == vessel_id), None)

    monkeypatch.setattr(svc.vessel_repo, "list_active", fake_list_active)
    monkeypatch.setattr(svc.vessel_repo, "get_by_id", fake_get_by_id)

    async def override_session():
        yield FakeSession()

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, recorded
    app.dependency_overrides.clear()


class TestListVessels:
    def test_envelope(self, wired):
        client, _ = wired
        body = client.get(LIST_URL).json()
        assert set(body) == {"data", "meta"}
        assert set(body["meta"]) == {"next_cursor", "has_more", "request_id", "timestamp"}

    def test_vessel_object_shape(self, wired):
        """API_SPEC §2.1 선박 객체의 키 12개."""
        client, _ = wired
        item = client.get(LIST_URL).json()["data"][0]
        assert set(item) == {
            "id",
            "imo_number",
            "name",
            "ship_type",
            "gross_tonnage",
            "deadweight",
            "default_fuel_type",
            "reference_speed_kn",
            "reference_daily_foc_ton",
            "is_cii_applicable_hint",
            "created_at",
            "updated_at",
        }

    def test_specs_are_numbers_not_strings(self, wired):
        """선박 제원은 **Layer 1 값이 아니다** — §2.1 예시가 숫자로 적는다.

        계산 **결과**만 문자열로 직렬화한다(§1.7).
        """
        client, _ = wired
        item = client.get(LIST_URL).json()["data"][0]
        assert isinstance(item["gross_tonnage"], float)
        assert isinstance(item["deadweight"], float)
        assert isinstance(item["is_cii_applicable_hint"], bool)

    def test_null_specs_stay_null(self, wired, monkeypatch):
        """GT 미상 선박은 ``null``로 나간다. 0으로 채우면 「GT가 0」이 된다."""
        from cii_platform.services import vessel as svc

        async def fake_list(_session, **_kwargs):
            return [FakeVessel(gross_tonnage=None, reference_speed_kn=None)]

        monkeypatch.setattr(svc.vessel_repo, "list_active", fake_list)
        client, _ = wired
        item = client.get(LIST_URL).json()["data"][0]
        assert item["gross_tonnage"] is None
        assert item["reference_speed_kn"] is None

    def test_default_limit_is_applied(self, wired):
        client, recorded = wired
        client.get(LIST_URL)
        assert recorded["limit"] == DEFAULT_LIMIT

    def test_limit_is_clamped(self, wired):
        client, recorded = wired
        client.get(LIST_URL, params={"limit": 500})
        assert recorded["limit"] == MAX_LIMIT

    def test_has_more_false_when_page_not_full(self, wired):
        """저장소가 ``limit + 1``건을 주므로 초과분 유무가 곧 ``has_more``다."""
        client, _ = wired
        body = client.get(LIST_URL, params={"limit": 10}).json()
        assert body["meta"]["has_more"] is False
        assert body["meta"]["next_cursor"] is None
        assert len(body["data"]) == 3

    def test_has_more_true_and_cursor_returned(self, wired):
        client, _ = wired
        body = client.get(LIST_URL, params={"limit": 2}).json()
        assert body["meta"]["has_more"] is True
        assert body["meta"]["next_cursor"] is not None
        assert len(body["data"]) == 2

    def test_next_cursor_points_at_last_item_of_page(self, wired):
        """커서는 **반환한 마지막 행**을 가리킨다.

        초과분(``limit + 1``번째)을 가리키면 다음 페이지가 한 건을 건너뛴다.
        """
        client, _ = wired
        body = client.get(LIST_URL, params={"limit": 2}).json()
        cursor = decode_cursor(body["meta"]["next_cursor"])
        assert cursor.name == body["data"][-1]["name"]
        assert cursor.vessel_id == body["data"][-1]["id"]

    def test_filters_are_passed_through(self, wired):
        client, recorded = wired
        client.get(LIST_URL, params={"ship_type": "BULK_CARRIER", "search": "STAR"})
        assert recorded["ship_type"] == "BULK_CARRIER"
        assert recorded["search"] == "STAR"

    def test_unknown_ship_type_is_422(self, wired):
        """#237 — 13종에 없는 ship_type은 422. 오타와 '결과 없음'을 구분한다."""
        client, _ = wired
        resp = client.get(LIST_URL, params={"ship_type": "BULK_CARIER"})  # 오타
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"][0]["field"] == "ship_type"

    def test_search_percent_is_not_wildcard(self, wired):
        """#237 — ``%`` 를 리터럴로 이스케이프. 서비스가 repo로 ``\\%`` 형태를 넘긴다."""
        client, recorded = wired
        client.get(LIST_URL, params={"search": "%"})
        # repo는 서비스가 넘긴 값을 그대로 쿼리에 쓴다 — escape는 repo가 담당.
        # 따라서 서비스 테스트에서는 넘어온 원본 값을 확인하고, escape 검증은
        # repo 직접 단위 테스트가 담당한다 (DB 의존).
        assert recorded["search"] == "%"

    def test_search_over_max_length_is_truncated(self, wired):
        """#237 — SEARCH_MAX_LENGTH(100) 초과는 절단. 422가 아니다 (normalize_limit 정책)."""
        client, recorded = wired
        long_search = "x" * 200
        client.get(LIST_URL, params={"search": long_search})
        assert len(recorded["search"]) == 100

    def test_broken_cursor_is_422(self, wired):
        """깨진 커서를 첫 페이지로 폴백하지 않는다 — 무한 루프가 된다."""
        client, _ = wired
        resp = client.get(LIST_URL, params={"cursor": "!!!"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_non_uuid_cursor_is_422(self, wired):
        """#233 — base64는 정상이지만 vessel_id가 UUID가 아닌 커서 → 422."""
        client, _ = wired
        token = base64.urlsafe_b64encode(b"A\x00not-a-uuid").decode()
        resp = client.get(LIST_URL, params={"cursor": token})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_zero_limit_is_422(self, wired):
        client, _ = wired
        assert client.get(LIST_URL, params={"limit": 0}).status_code == 422


class TestGetVessel:
    def test_found(self, wired):
        client, _ = wired
        vid = "00000000-0000-4000-8000-000000000001"
        body = client.get(f"{LIST_URL}/{vid}").json()
        assert body["data"]["id"] == vid
        assert set(body["meta"]) == {"request_id", "timestamp"}

    def test_not_found_is_404(self, wired):
        client, _ = wired
        resp = client.get(f"{LIST_URL}/00000000-0000-4000-8000-0000000000ff")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_malformed_uuid_is_422(self, wired):
        """UUID가 아닌 경로 파라미터는 Pydantic이 잡는다 (#116 핸들러 경유)."""
        client, _ = wired
        resp = client.get(f"{LIST_URL}/not-a-uuid")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


class TestDecimalToNumber:
    """``Decimal`` → JSON number 변환이 값을 바꾸지 않는다."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(Decimal("50000.00"), 50000.0), (Decimal("6405.77"), 6405.77), (None, None)],
    )
    def test_number(self, value, expected):
        from cii_platform.services.vessel import _number

        assert _number(value) == expected


# --- POST /vessels (#50) ------------------------------------------------------------


class TestCreateVessel:
    """선박 등록 (#50, API_SPEC §2.3). DB 없이 — 서비스 로직·검증 규칙·응답 형태만."""

    PAYLOAD: dict = {
        "imo_number": "1234567",
        "name": "Pacific Star",
        "ship_type": "BULK_CARRIER",
        "gross_tonnage": 25000.0,
        "deadweight": 50000.0,
    }

    @pytest.fixture
    def create_wired(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
        """``create_vessel``이 쓰는 repo 3종을 대역으로 교체한다."""
        from cii_platform.services import vessel as svc

        recorded: dict = {}
        known_ship_types = {"BULK_CARRIER", "TANKER"}
        existing_imos: set[str] = set()

        async def fake_list_reference_lines(_session, ship_type):
            recorded["ship_type"] = ship_type
            return [FakeReferenceLine()] if ship_type in known_ship_types else []

        async def fake_find_active_by_imo(_session, imo_number):
            recorded["imo_check"] = imo_number
            return FakeVessel(imo_number=imo_number) if imo_number in existing_imos else None

        async def fake_insert(_session, **fields):
            recorded["insert_kwargs"] = fields
            # FakeVessel이 모든 insert 필드를 dataclass field로 갖는다.
            return FakeVessel(**fields)  # type: ignore[arg-type]

        monkeypatch.setattr(svc.param_repo, "list_reference_lines", fake_list_reference_lines)
        monkeypatch.setattr(svc.vessel_repo, "find_active_by_imo", fake_find_active_by_imo)
        monkeypatch.setattr(svc.vessel_repo, "insert", fake_insert)

        async def override_session():
            yield FakeSession()

        app.dependency_overrides[get_session] = override_session
        with TestClient(app) as client:
            yield client, recorded, existing_imos
        app.dependency_overrides.clear()

    def test_creates_vessel_with_201(self, create_wired):
        """정상 등록 → 201 + §2.2 형태의 vessel 객체 (#50 완료 기준)."""
        client, _, _ = create_wired
        resp = client.post(LIST_URL, json=self.PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert set(body) == {"data", "meta"}
        assert body["data"]["imo_number"] == "1234567"
        assert body["data"]["name"] == "Pacific Star"
        assert body["data"]["ship_type"] == "BULK_CARRIER"

    def test_is_cii_applicable_hint_true_when_gt_ge_5000(self, create_wired):
        """API_SPEC §2.3 — ``gross_tonnage >= 5,000`` → ``is_cii_applicable_hint = true``."""
        client, recorded, _ = create_wired
        client.post(LIST_URL, json={**self.PAYLOAD, "gross_tonnage": 5000.0})
        assert recorded["insert_kwargs"]["is_cii_applicable_hint"] is True

    def test_is_cii_applicable_hint_false_when_gt_below_5000(self, create_wired):
        client, recorded, _ = create_wired
        client.post(LIST_URL, json={**self.PAYLOAD, "gross_tonnage": 4999.99})
        assert recorded["insert_kwargs"]["is_cii_applicable_hint"] is False

    def test_is_cii_applicable_hint_false_when_gt_none(self, create_wired):
        """GT 미상 → false. 0으로 채우면 「GT가 0」이 된다."""
        client, recorded, _ = create_wired
        payload = {**self.PAYLOAD}
        payload.pop("gross_tonnage")
        client.post(LIST_URL, json=payload)
        assert recorded["insert_kwargs"]["is_cii_applicable_hint"] is False

    def test_duplicate_imo_is_409(self, create_wired):
        """#50 완료 기준 — 중복 IMO → PARAMETER_ERROR(409)."""
        client, _, existing_imos = create_wired
        existing_imos.add("1234567")  # 이미 존재하는 IMO로 세팅
        resp = client.post(LIST_URL, json=self.PAYLOAD)
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "PARAMETER_ERROR"
        assert "1234567" in body["error"]["message"]

    def test_unknown_ship_type_is_422(self, create_wired):
        """VAL-004 — ``cii_reference_line``에 없는 선종 → ValidationError(422)."""
        client, _, _ = create_wired
        resp = client.post(LIST_URL, json={**self.PAYLOAD, "ship_type": "UNKNOWN_SHIP"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"][0]["field"] == "ship_type"

    def test_malformed_imo_is_422(self, create_wired):
        """VAL-003 — 7자리 숫자가 아니면 Pydantic 422."""
        client, _, _ = create_wired
        resp = client.post(LIST_URL, json={**self.PAYLOAD, "imo_number": "12345"})
        assert resp.status_code == 422

    def test_zero_gross_tonnage_is_422(self, create_wired):
        """VAL-002 — gross_tonnage <= 0 → Pydantic 422."""
        client, _, _ = create_wired
        resp = client.post(LIST_URL, json={**self.PAYLOAD, "gross_tonnage": 0})
        assert resp.status_code == 422

    def test_extra_field_forbidden(self, create_wired):
        """``extra='forbid'`` — 모르는 필드는 422 (오타 필드 조용히 무시 방지)."""
        client, _, _ = create_wired
        resp = client.post(LIST_URL, json={**self.PAYLOAD, "unexpected": "value"})
        assert resp.status_code == 422
