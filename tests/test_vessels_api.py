"""선박 조회 API 계약 테스트 (#51) — **DB 없이 돈다.**

커서 인코딩·페이지네이션 판단·응답 형태는 DB 없이 검증할 수 있고, 실제 쿼리의
정합성은 DB가 있는 CI가 확인한다.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fakes import DEMO_VESSEL_ID, FakeSession, FakeVessel
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
