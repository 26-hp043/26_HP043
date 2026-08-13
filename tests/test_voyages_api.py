"""항차 API 계약 테스트 (#53) — DB 없이 돈다."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.routes.voyages import router as voyages_router
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session

VESSEL_ID = UUID("00000000-0000-4000-8000-000000000001")
LIST_URL = f"/api/v1/vessels/{VESSEL_ID}/voyages"
CREATE_URL = LIST_URL


class _FakeFuelUse:
    def __init__(self, **kw):
        self.id = uuid4()
        self.fuel_type = kw.get("fuel_type", "HFO")
        self.planned_fuel_ton = kw.get("planned_fuel_ton", Decimal("100"))
        self.actual_fuel_ton = kw.get("actual_fuel_ton")
        self.cf_used = kw.get("cf_used", Decimal("3.114"))
        self.source = kw.get("source", "USER_INPUT")


class _FakeVoyage:
    def __init__(self, **kw):
        self.id = kw.get("id", uuid4())
        self.vessel_id = kw.get("vessel_id", VESSEL_ID)
        self.voyage_no = kw.get("voyage_no", "V-2026-001")
        self.status = kw.get("status", "DRAFT")
        self.departure_port_name = kw.get("departure_port_name", "Busan")
        self.departure_lat = kw.get("departure_lat")
        self.departure_lon = kw.get("departure_lon")
        self.arrival_port_name = kw.get("arrival_port_name", "Rotterdam")
        self.arrival_lat = kw.get("arrival_lat")
        self.arrival_lon = kw.get("arrival_lon")
        self.planned_distance_nm = kw.get("planned_distance_nm", Decimal("11000"))
        self.actual_distance_nm = kw.get("actual_distance_nm")
        self.planned_speed_kn = kw.get("planned_speed_kn", Decimal("14"))
        self.actual_avg_speed_kn = kw.get("actual_avg_speed_kn")
        self.planned_departure_at = kw.get("planned_departure_at")
        self.planned_arrival_at = kw.get("planned_arrival_at")
        self.actual_departure_at = kw.get("actual_departure_at")
        self.actual_arrival_at = kw.get("actual_arrival_at")
        self.annual_inclusion_policy = kw.get("annual_inclusion_policy", "EXCLUDE")
        self.regulation_year = kw.get("regulation_year", 2026)
        self.created_from = kw.get("created_from", "MANUAL")
        self.notes = kw.get("notes")
        self.is_deleted = False
        self.created_at = kw.get("created_at", dt.datetime(2026, 8, 13, tzinfo=dt.UTC))


class _FakeSession:
    async def commit(self):
        pass

    async def flush(self):
        pass

    def add(self, obj):
        pass


class _FakeFuelRow:
    def __init__(self, code="HFO", cf="3.114"):
        self.code = code
        self.cf = cf


@pytest.fixture
def voyage_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from cii_platform.services import voyage as svc

    voyage_store: list[_FakeVoyage] = [_FakeVoyage(), _FakeVoyage(voyage_no="V-2026-002")]
    fuel_store: dict[UUID, list[_FakeFuelUse]] = {
        voyage_store[0].id: [_FakeFuelUse()],
        voyage_store[1].id: [_FakeFuelUse()],
    }

    async def fake_insert(session, **fields):
        v = _FakeVoyage(**fields)
        voyage_store.append(v)
        fuel_store[v.id] = []
        return v

    async def fake_insert_fuel_use(session, **fields):
        fu = _FakeFuelUse(**fields)
        fuel_store.setdefault(fields.get("voyage_id"), []).append(fu)
        return fu

    async def fake_list_fuel_uses(session, voyage_id):
        return fuel_store.get(voyage_id, [])

    async def fake_list_active(
        session, *, vessel_id, limit, cursor=None, status=None, regulation_year=None
    ):
        return voyage_store[: limit + 1]

    async def fake_get_by_id(session, voyage_id):
        return next((v for v in voyage_store if v.id == voyage_id), None)

    async def fake_get_fuel_types_by_codes(session, codes):
        return {code: _FakeFuelRow(code=code) for code in codes}

    monkeypatch.setattr(svc.voyage_repo, "insert", fake_insert)
    monkeypatch.setattr(svc.voyage_repo, "insert_fuel_use", fake_insert_fuel_use)
    monkeypatch.setattr(svc.voyage_repo, "list_fuel_uses", fake_list_fuel_uses)
    monkeypatch.setattr(svc.voyage_repo, "list_active", fake_list_active)
    monkeypatch.setattr(svc.voyage_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(svc.param_repo, "get_fuel_types_by_codes", fake_get_fuel_types_by_codes)

    async def override_session():
        yield _FakeSession()

    # 항차 의미론 테스트 — CSRF 검증은 의존성 override로 격리한다.
    # (fail-closed 전환 후 미들웨어 없는 최소 앱은 session_row가 없어 401이 된다.
    #  CSRF 자체는 test_auth_session.py·test_auth_wiring.py가 잠근다.)
    async def override_csrf() -> None:
        return None

    app = FastAPI()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_csrf] = override_csrf
    register_exception_handlers(app)
    app.include_router(voyages_router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


PAYLOAD = {
    "departure_port_name": "Busan",
    "arrival_port_name": "Rotterdam",
    "planned_distance_nm": 11000.0,
    "planned_speed_kn": 14.0,
    "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 800.0}],
}


def test_create_voyage_returns_201(voyage_app):
    resp = voyage_app.post(CREATE_URL, json=PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert "data" in body and "meta" in body
    assert body["data"]["status"] == "DRAFT"
    assert body["data"]["annual_inclusion_policy"] == "EXCLUDE"
    assert len(body["data"]["fuel_uses"]) == 1
    assert body["data"]["fuel_uses"][0]["fuel_type"] == "HFO"


def test_list_voyages_envelope(voyage_app):
    body = voyage_app.get(LIST_URL).json()
    assert set(body) == {"data", "meta"}
    assert "has_more" in body["meta"]
    assert len(body["data"]) == 2


def test_get_voyage_by_id(voyage_app):
    body = voyage_app.get(LIST_URL).json()
    voyage_id = body["data"][0]["id"]
    resp = voyage_app.get(f"/api/v1/voyages/{voyage_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == voyage_id


def test_get_voyage_not_found(voyage_app):
    missing = "00000000-0000-4000-8000-00000000ffff"
    resp = voyage_app.get(f"/api/v1/voyages/{missing}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_create_with_empty_fuel_uses_is_422(voyage_app):
    resp = voyage_app.post(CREATE_URL, json={**PAYLOAD, "fuel_uses": []})
    assert resp.status_code == 422


def test_create_with_negative_distance_is_422(voyage_app):
    resp = voyage_app.post(CREATE_URL, json={**PAYLOAD, "planned_distance_nm": -1})
    assert resp.status_code == 422


# --- 상태 전환 policy (#310) · PATCH null 의미론 (#312) ------------------------------


class TestTransitionPolicy:
    """전환에서 annual_inclusion_policy 미지정 = 현행 유지 (#310)."""

    @pytest.fixture
    def transition_app(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
        """PLANNED·INCLUDE_AS_PLAN 항차 하나를 가진 앱."""
        from cii_platform.services import voyage as svc

        voyage = _FakeVoyage(
            status="PLANNED",
            annual_inclusion_policy="INCLUDE_AS_PLAN",
            regulation_year=2026,
        )
        store: dict[UUID, _FakeVoyage] = {voyage.id: voyage}

        async def fake_get_by_id(_session, voyage_id):
            return store.get(voyage_id)

        async def fake_list_fuel_uses(_session, voyage_id):
            return []

        monkeypatch.setattr(svc.voyage_repo, "get_by_id", fake_get_by_id)
        monkeypatch.setattr(svc.voyage_repo, "list_fuel_uses", fake_list_fuel_uses)

        async def override_session():
            yield _FakeSession()

        # CSRF 검증 격리 — voyage_app과 같은 맥락 (test_auth_*가 CSRF를 잠근다).
        async def override_csrf() -> None:
            return None

        app = FastAPI()
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[require_csrf] = override_csrf
        register_exception_handlers(app)
        app.include_router(voyages_router, prefix="/api/v1")
        with TestClient(app) as client:
            yield client, store
        app.dependency_overrides.clear()

    def test_omitted_policy_is_preserved(self, transition_app):
        """PLANNED(INCLUDE_AS_PLAN) → IN_PROGRESS 미지정: policy 유지 (#310)."""
        client, store = transition_app
        voyage_id = next(iter(store))
        resp = client.post(
            f"/api/v1/voyages/{voyage_id}/transition", json={"to_status": "IN_PROGRESS"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["annual_inclusion_policy"] == "INCLUDE_AS_PLAN"

    def test_incompatible_target_requires_explicit_policy(self, transition_app):
        """PLANNED(INCLUDE_AS_PLAN) → COMPLETED 미지정: 자동 보정 없이 422 (#310)."""
        client, store = transition_app
        voyage_id = next(iter(store))
        resp = client.post(
            f"/api/v1/voyages/{voyage_id}/transition", json={"to_status": "COMPLETED"}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "STATE_TRANSITION_ERROR"

    def test_exclude_only_status_auto_sets_exclude(self, transition_app):
        """→ CANCELLED 미지정: EXCLUDE-only 상태는 자동 설정 (API_SPEC §3.5)."""
        client, store = transition_app
        voyage_id = next(iter(store))
        resp = client.post(
            f"/api/v1/voyages/{voyage_id}/transition", json={"to_status": "CANCELLED"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["annual_inclusion_policy"] == "EXCLUDE"

    def test_explicit_policy_still_validated(self, transition_app):
        """명시적 지정은 종전대로 검증 — COMPLETED에 INCLUDE_AS_PLAN은 422."""
        client, store = transition_app
        voyage_id = next(iter(store))
        resp = client.post(
            f"/api/v1/voyages/{voyage_id}/transition",
            json={"to_status": "COMPLETED", "annual_inclusion_policy": "INCLUDE_AS_PLAN"},
        )
        assert resp.status_code == 422


class TestUpdateNullSemantics:
    """PATCH의 null 의미론 — 생략=변경 없음, 명시적 null=클리어 (#312)."""

    @pytest.fixture
    def update_app(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
        from cii_platform.services import voyage as svc

        voyage = _FakeVoyage(
            status="PLANNED",
            annual_inclusion_policy="EXCLUDE",
            regulation_year=2026,
        )
        store: dict[UUID, _FakeVoyage] = {voyage.id: voyage}

        async def fake_get_by_id(_session, voyage_id):
            return store.get(voyage_id)

        async def fake_list_fuel_uses(_session, voyage_id):
            return []

        monkeypatch.setattr(svc.voyage_repo, "get_by_id", fake_get_by_id)
        monkeypatch.setattr(svc.voyage_repo, "list_fuel_uses", fake_list_fuel_uses)

        async def override_session():
            yield _FakeSession()

        # CSRF 검증 격리 — voyage_app과 같은 맥락 (test_auth_*가 CSRF를 잠근다).
        async def override_csrf() -> None:
            return None

        app = FastAPI()
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[require_csrf] = override_csrf
        register_exception_handlers(app)
        app.include_router(voyages_router, prefix="/api/v1")
        with TestClient(app) as client:
            yield client, store
        app.dependency_overrides.clear()

    def test_explicit_null_clears_regulation_year(self, update_app):
        """EXCLUDE 항차의 regulation_year=null → 클리어 (#312)."""
        client, store = update_app
        voyage_id = next(iter(store))
        resp = client.patch(f"/api/v1/voyages/{voyage_id}", json={"regulation_year": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["regulation_year"] is None
        assert store[voyage_id].regulation_year is None

    def test_omitted_field_leaves_value(self, update_app):
        """regulation_year 생략 → 값 유지 (#312)."""
        client, store = update_app
        voyage_id = next(iter(store))
        resp = client.patch(f"/api/v1/voyages/{voyage_id}", json={"notes": "메모만 변경"})
        assert resp.status_code == 200
        assert resp.json()["data"]["regulation_year"] == 2026

    def test_null_clear_rejected_when_policy_requires_year(self, update_app):
        """INCLUDE_AS_PLAN 항차의 null 클리어 → 422 (#150 가드 도달)."""
        client, store = update_app
        voyage_id = next(iter(store))
        store[voyage_id].annual_inclusion_policy = "INCLUDE_AS_PLAN"
        resp = client.patch(f"/api/v1/voyages/{voyage_id}", json={"regulation_year": None})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "data" not in resp.json()
