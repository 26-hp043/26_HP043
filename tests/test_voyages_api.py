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
    def __init__(self) -> None:
        self.deleted: list = []

    async def commit(self):
        pass

    async def flush(self):
        pass

    def add(self, obj):
        pass

    async def delete(self, obj):
        self.deleted.append(obj)


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

    calls: dict[str, int] = {"list_fuel_uses": 0, "list_by_ids": 0}

    async def fake_list_fuel_uses(session, voyage_id):
        calls["list_fuel_uses"] += 1
        return fuel_store.get(voyage_id, [])

    async def fake_list_fuel_uses_by_ids(session, voyage_ids):
        calls["list_by_ids"] += 1
        return {vid: fuel_store.get(vid, []) for vid in voyage_ids}

    async def fake_has_calc_run_refs(session, voyage_id):
        return False

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
    monkeypatch.setattr(svc.voyage_repo, "list_fuel_uses_by_voyage_ids", fake_list_fuel_uses_by_ids)
    monkeypatch.setattr(svc.voyage_repo, "has_calculation_run_refs", fake_has_calc_run_refs)
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
        client.calls = calls  # type: ignore[attr-defined]  # N+1 검증용 호출 카운터
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


def test_create_with_duplicate_fuel_type_is_422(voyage_app):
    """같은 유종을 두 번 보내면 **422이지 500이 아니다** (`#636`).

    ``idx_fuel_use_unique``가 (항차, 유종) 중복을 막는데(`DB_SCHEMA §2.3` [S-2]),
    서비스가 걸러 내지 않으면 ``IntegrityError``가 그대로 올라와 500이 된다.
    실적 갱신(`_upsert_fuel_actuals`)은 같은 가드를 갖고 있었고 **생성 경로만
    빠져 있었다** — 화면 폼이 연료를 한 종만 보내 도달할 수 없는 경로였기 때문이다.
    `#636`이 폼을 다연료로 넓히면서 이 경로가 처음으로 열린다.
    """
    resp = voyage_app.post(
        CREATE_URL,
        json={
            **PAYLOAD,
            "fuel_uses": [
                {"fuel_type": "HFO", "planned_fuel_ton": 800.0},
                {"fuel_type": "HFO", "planned_fuel_ton": 200.0},
            ],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_accepts_multiple_fuel_types(voyage_app):
    """서로 다른 유종은 여러 줄로 받는다 (`API_SPEC §3.3` · `#636`).

    위 테스트만 있으면 **전부 거부해도 통과한다.** 정상 경로를 함께 박는다.
    """
    resp = voyage_app.post(
        CREATE_URL,
        json={
            **PAYLOAD,
            "voyage_no": "V-MULTI",
            "fuel_uses": [
                {"fuel_type": "HFO", "planned_fuel_ton": 800.0},
                {"fuel_type": "DIESEL_GAS_OIL", "planned_fuel_ton": 40.0},
            ],
        },
    )
    assert resp.status_code == 201
    codes = [fu["fuel_type"] for fu in resp.json()["data"]["fuel_uses"]]
    assert sorted(codes) == ["DIESEL_GAS_OIL", "HFO"]


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


def test_list_uses_single_batched_fuel_query(voyage_app):
    """목록의 fuel_uses가 IN 쿼리 1회로 모인다 — 항차별 조회 없음 (#314)."""
    resp = voyage_app.get(LIST_URL)
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2
    calls: dict = voyage_app.calls  # type: ignore[attr-defined]
    assert calls["list_by_ids"] == 1
    assert calls["list_fuel_uses"] == 0


# --- 삭제 (#313) --------------------------------------------------------------------


class TestDeleteVoyage:
    """hard delete의 계산 이력 참조 검사 (#313)."""

    @pytest.fixture
    def delete_app(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
        from cii_platform.services import voyage as svc

        voyage = _FakeVoyage(status="DRAFT")
        store: dict[UUID, _FakeVoyage] = {voyage.id: voyage}
        refs: set[UUID] = set()

        async def fake_get_by_id(_session, voyage_id):
            return store.get(voyage_id)

        async def fake_list_fuel_uses(_session, voyage_id):
            return []

        async def fake_has_refs(_session, voyage_id):
            return voyage_id in refs

        monkeypatch.setattr(svc.voyage_repo, "get_by_id", fake_get_by_id)
        monkeypatch.setattr(svc.voyage_repo, "list_fuel_uses", fake_list_fuel_uses)
        monkeypatch.setattr(svc.voyage_repo, "has_calculation_run_refs", fake_has_refs)

        session = _FakeSession()

        async def override_session():
            yield session

        # CSRF 검증 격리 — voyage_app과 같은 맥락 (test_auth_*가 CSRF를 잠근다).
        async def override_csrf() -> None:
            return None

        app = FastAPI()
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[require_csrf] = override_csrf
        register_exception_handlers(app)
        app.include_router(voyages_router, prefix="/api/v1")
        with TestClient(app) as client:
            yield client, store, refs, session
        app.dependency_overrides.clear()

    def test_hard_delete_without_refs_is_200(self, delete_app):
        """참조 없는 DRAFT → hard delete 200 (#313)."""
        client, store, refs, session = delete_app
        voyage_id = next(iter(store))
        resp = client.delete(f"/api/v1/voyages/{voyage_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["hard_delete"] is True
        # session.delete()가 호출됐다 — 대역 세션이 기록한다.
        assert [v.id for v in session.deleted] == [voyage_id]

    def test_hard_delete_with_refs_is_409(self, delete_app):
        """계산 이력 참조가 있는 DRAFT → 409 CONFLICT (500 아님, #313)."""
        client, store, refs, session = delete_app
        voyage_id = next(iter(store))
        refs.add(voyage_id)
        resp = client.delete(f"/api/v1/voyages/{voyage_id}")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"
        assert not session.deleted  # 삭제 시도 없음

    def test_soft_delete_skips_ref_check(self, delete_app):
        """COMPLETED → soft delete — FK 위반이 없으므로 참조 검사 없이 진행."""
        client, store, refs, _ = delete_app
        voyage_id = next(iter(store))
        store[voyage_id].status = "COMPLETED"
        refs.add(voyage_id)  # 참조가 있어도 soft delete은 200
        resp = client.delete(f"/api/v1/voyages/{voyage_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["hard_delete"] is False

    def test_planned_delete_is_422(self, delete_app):
        """PLANNED → 422 — 먼저 CANCELLED로 전환 필요 (기존 규칙 유지)."""
        client, store, _, _ = delete_app
        voyage_id = next(iter(store))
        store[voyage_id].status = "PLANNED"
        resp = client.delete(f"/api/v1/voyages/{voyage_id}")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "STATE_TRANSITION_ERROR"


class TestActualsRoute:
    """`PUT /voyages/{id}/actuals` — 라우트 계약 (`API_SPEC §3.6`, #440)."""

    @pytest.fixture
    def actuals_app(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
        from cii_platform.services import voyage as svc

        voyage = _FakeVoyage(
            status="COMPLETED",
            annual_inclusion_policy="INCLUDE_AS_ACTUAL",
            regulation_year=2026,
        )
        store: dict[UUID, _FakeVoyage] = {voyage.id: voyage}

        async def fake_get_by_id(_session, voyage_id):
            return store.get(voyage_id)

        async def fake_list_fuel_uses(_session, _voyage_id):
            return []

        monkeypatch.setattr(svc.voyage_repo, "get_by_id", fake_get_by_id)
        monkeypatch.setattr(svc.voyage_repo, "list_fuel_uses", fake_list_fuel_uses)

        async def override_session():
            yield _FakeSession()

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

    def test_distance_is_stored(self, actuals_app):
        client, store = actuals_app
        voyage_id = next(iter(store))

        resp = client.put(
            f"/api/v1/voyages/{voyage_id}/actuals",
            json={"actual_distance_nm": 1100.0},
        )

        assert resp.status_code == 200, resp.text
        assert store[voyage_id].actual_distance_nm == Decimal("1100.0")

    def test_status_is_not_touched(self, actuals_app):
        """전환은 별도 호출이다 — 함께 처리하면 전환 가드가 자기 입력을 보고 통과한다."""
        client, store = actuals_app
        voyage_id = next(iter(store))

        client.put(f"/api/v1/voyages/{voyage_id}/actuals", json={"actual_distance_nm": 1100.0})

        assert store[voyage_id].status == "COMPLETED"

    def test_unknown_field_is_rejected(self, actuals_app):
        """`extra="forbid"` — 오타 필드가 조용히 무시되면 사용자는 입력이 반영된 줄 안다."""
        client, store = actuals_app
        voyage_id = next(iter(store))

        resp = client.put(
            f"/api/v1/voyages/{voyage_id}/actuals",
            json={"actual_distance": 1100.0},
        )

        assert resp.status_code == 422

    def test_zero_fuel_is_rejected(self, actuals_app):
        """`chk_actual_fuel_positive`와 같은 조건. 0을 「안 썼다」로 쓰려면 행을 넣지 않는다."""
        client, store = actuals_app
        voyage_id = next(iter(store))

        resp = client.put(
            f"/api/v1/voyages/{voyage_id}/actuals",
            json={"fuel_uses": [{"fuel_type": "HFO", "actual_fuel_ton": 0}]},
        )

        assert resp.status_code == 422

    def test_speed_below_db_minimum_is_rejected_as_422(self, actuals_app):
        """스키마가 DB보다 느슨하면 사용자는 422가 아니라 500(제약 위반)을 받는다."""
        client, store = actuals_app
        voyage_id = next(iter(store))

        resp = client.put(
            f"/api/v1/voyages/{voyage_id}/actuals",
            json={"actual_avg_speed_kn": 0.5},
        )

        assert resp.status_code == 422
