"""not under way 구간 CRUD API 실동작 (#370) — 입력 경로의 규칙을 잠근다.

완료 기준(이슈 #370)을 그대로 검증한다:

* 시드 없이 등록·수정·삭제 — ``POST/PATCH/DELETE`` 실동작
* 등록한 구간의 연료가 **YTD CII 분자에 반영** — ``compute_ytd_cii`` 직접 호출로
  종단 확인 (#353 엔진과의 결합)
* 같은 선박의 구간 겹침 → 409 (``#368`` ``_overlap_hours``의 전제 강제)
* 인증 게이트 — 실제 앱에서 CSRF 없는 POST는 403 (#307 배선 확인 선례)

패턴은 ``test_voyage_delete_db.py`` — 서비스가 ``commit``하므로 ``conn`` 롤백
격리가 아니라 ``app_fresh_engine``(NullPool) + 실제 커밋 + 종료 정리를 쓴다.
규제 파라미터는 마이그레이션 032(#127)가 심으므로 별도 시딩이 없다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.routes.not_underway import router as not_underway_router
from cii_platform.auth.dependencies import require_csrf

_BASE = "https://testserver"

# IMO 뒷자리 — 테스트마다 고유 선박을 만들어 충돌·간섭을 원천 차단한다.
_counter = iter(range(1, 9999))


def _imo() -> str:
    return f"7300{next(_counter):03d}"


def _ts(day: int, hour: int = 8) -> str:
    return datetime(2026, 1, day, hour, tzinfo=UTC).isoformat()


async def _create_vessel(imo: str) -> str:
    from cii_platform.db.session import get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as s:
        row = await s.execute(
            text(
                "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight) "
                "VALUES (:imo, 'NUW CRUD TEST', 'BULK_CARRIER', 30000, 50000) RETURNING id"
            ),
            {"imo": imo},
        )
        await s.commit()
        return str(row.scalar_one())


async def _cleanup(imo: str) -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as s:
        await s.execute(
            text(
                "DELETE FROM not_underway_fuel_use WHERE period_id IN "
                "(SELECT id FROM not_underway_period WHERE vessel_id IN "
                "(SELECT id FROM vessel WHERE imo_number = :imo))"
            ),
            {"imo": imo},
        )
        await s.execute(
            text(
                "DELETE FROM not_underway_period WHERE vessel_id IN "
                "(SELECT id FROM vessel WHERE imo_number = :imo)"
            ),
            {"imo": imo},
        )
        await s.execute(text("DELETE FROM vessel WHERE imo_number = :imo"), {"imo": imo})
        await s.commit()
    await get_engine().dispose()


def _app() -> FastAPI:
    """CSRF는 의존성 override로 격리 — 이 파일은 CRUD 의미론만 본다.

    배선(실제 CSRF 게이트)은 ``test_csrf_required_for_create``가 실앱으로 잠근다.
    """

    async def override_csrf() -> None:
        return None

    app = FastAPI()
    app.dependency_overrides[require_csrf] = override_csrf
    register_exception_handlers(app)
    app.include_router(not_underway_router, prefix="/api/v1")
    return app


def _payload(**overrides: object) -> dict:
    base: dict = {
        "period_type": "AT_ANCHOR",
        "started_at": _ts(10),
        "ended_at": _ts(12),
        "regulation_year": 2026,
        "port_name": "BUSAN",
        "distance_nm": 0,
        "fuel_uses": [{"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "12.50"}],
    }
    base.update(overrides)
    return base


class _Ctx:
    """테스트 하나의 세계 — 선박 1척 + 그 선박을 가리키는 클라이언트."""

    def __init__(self, client: TestClient, vessel_id: str, imo: str):
        self.client = client
        self.vessel_id = vessel_id
        self.imo = imo

    def create(self, **overrides: object):
        return self.client.post(
            f"/api/v1/vessels/{self.vessel_id}/not-underway-periods",
            json=_payload(**overrides),
        )


@pytest_asyncio.fixture
async def ctx(migrated_db, app_fresh_engine):
    imo = _imo()
    vessel_id = await _create_vessel(imo)
    with TestClient(_app(), base_url=_BASE) as client:
        yield _Ctx(client, vessel_id, imo)
    await _cleanup(imo)


# --- 생성 ------------------------------------------------------------------------


async def test_create_returns_201_with_cf_snapshot(ctx):
    """생성 — 자식 연료에 기록 시점 CF snapshot이 확정된다 (030 · PRD §8.4)."""
    resp = ctx.create(
        period_type="CANAL_TRANSIT",
        started_at=_ts(10),
        ended_at=_ts(11),
        distance_nm="200.00",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["period_type"] == "CANAL_TRANSIT"
    assert body["distance_nm"] == 200.0
    assert body["voyage_id"] is None
    assert len(body["fuel_uses"]) == 1
    fuel = body["fuel_uses"][0]
    assert fuel["consumer_type"] == "AUX_ENGINE"
    assert fuel["fuel_type"] == "HFO"
    # 017 seed의 HFO CF — 마이그레이션 032 파라미터와 동일한 정본값.
    assert fuel["cf_used"] == 3.114


async def test_create_ongoing_period_with_null_ended_at(ctx):
    """진행 중 구간(ended_at NULL) — 묘박 시작 후 아직 안 끝난 상태."""
    resp = ctx.create(ended_at=None)
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["ended_at"] is None


async def test_create_rejects_reversed_time_order(ctx):
    """ended_at ≤ started_at → 422 (DB CHECK를 앞서 스키마·서비스가 걸러준다)."""
    assert ctx.create(started_at=_ts(12), ended_at=_ts(10)).status_code == 422


async def test_create_rejects_year_mismatch(ctx):
    """귀속 연도 ≠ 시작 연도 → 422. YTD가 (vessel, year)로 묶고 started_at으로
    절단하므로, 어긋난 구간은 조회에서 사라지거나 두 번 잡힌다."""
    assert ctx.create(regulation_year=2025).status_code == 422


async def test_create_rejects_naive_datetime(ctx):
    """타임존 없는 시각 → 422. aware/naive 혼합 비교는 TypeError로 500이 된다."""
    assert ctx.create(started_at="2026-01-10T08:00:00").status_code == 422


async def test_create_rejects_unknown_fuel(ctx):
    assert (
        ctx.create(
            fuel_uses=[{"consumer_type": "AUX_ENGINE", "fuel_type": "NO_SUCH", "fuel_ton": "1"}]
        ).status_code
        == 422
    )


async def test_create_rejects_invalid_period_type(ctx):
    """period_type 6값 밖 → 422 (스키마 Literal이 CHECK와 같은 집합을 유지)."""
    assert ctx.create(period_type="SAILING").status_code == 422


async def test_create_rejects_duplicate_consumer_fuel_pair(ctx):
    """(consumer_type, fuel_type) 중복 → 422. 029 UNIQUE를 선제 검증해
    DB 무결성 오류(500)를 사용자가 고칠 수 있는 입력 오류로 바꾼다."""
    dup = [
        {"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "1"},
        {"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "2"},
    ]
    assert ctx.create(fuel_uses=dup).status_code == 422


async def test_create_rejects_overlapping_period(ctx):
    """같은 선박 구간 겹침 → 409 — 종료·진행 중 모두 (#368 전제 강제)."""
    assert ctx.create().status_code == 201

    # 종료 시각이 기존 구간 내부로 들어감.
    assert ctx.create(started_at=_ts(11), ended_at=_ts(13)).status_code == 409
    # 기존 종료 구간을 완전히 덮음.
    assert ctx.create(started_at=_ts(9), ended_at=_ts(13)).status_code == 409
    # 진행 중 구간은 시작 이후의 모든 구간과 겹친다 — 종료된 새 구간도 걸린다.
    assert ctx.create(started_at=_ts(20), ended_at=None).status_code == 201
    assert ctx.create(started_at=_ts(25), ended_at=_ts(26)).status_code == 409


async def test_create_allows_back_to_back_period(ctx):
    """끝점이 만나는 배치는 허용 — [8,12] 다음 [12,16]은 겹침이 아니다."""
    assert ctx.create().status_code == 201
    resp = ctx.create(started_at=_ts(12), ended_at=_ts(16))
    assert resp.status_code == 201, resp.text


# --- 조회 ------------------------------------------------------------------------


async def test_get_period_and_404(ctx):
    created = ctx.create().json()["data"]
    period_id = created["id"]

    got = ctx.client.get(f"/api/v1/not-underway-periods/{period_id}")
    assert got.status_code == 200
    assert got.json()["data"]["id"] == period_id

    missing = ctx.client.get(f"/api/v1/not-underway-periods/{uuid4()}")
    assert missing.status_code == 404


async def test_list_filters_and_pagination(ctx):
    """ongoing 필터 + 최근 시작 순 + keyset 페이지네이션."""
    assert ctx.create(started_at=_ts(10), ended_at=_ts(11)).status_code == 201
    assert ctx.create(started_at=_ts(12), ended_at=_ts(13)).status_code == 201
    assert ctx.create(started_at=_ts(14), ended_at=None).status_code == 201

    base = f"/api/v1/vessels/{ctx.vessel_id}/not-underway-periods"

    ongoing = ctx.client.get(base, params={"ongoing": True}).json()
    assert len(ongoing["data"]) == 1
    assert ongoing["data"][0]["ended_at"] is None

    year = ctx.client.get(base, params={"regulation_year": 2025}).json()
    assert year["data"] == []

    page1 = ctx.client.get(base, params={"limit": 2}).json()
    assert [p["started_at"][:13] for p in page1["data"]] == [
        "2026-01-14T",
        "2026-01-12T",
    ]
    assert page1["meta"]["has_more"] is True

    page2 = ctx.client.get(base, params={"limit": 2, "cursor": page1["meta"]["next_cursor"]}).json()
    assert len(page2["data"]) == 1
    assert page2["meta"]["has_more"] is False
    # 두 페이지를 합치면 중복이 없다 (keyset의 핵심 보장).
    ids1 = {p["id"] for p in page1["data"]}
    ids2 = {p["id"] for p in page2["data"]}
    assert ids1 & ids2 == set()


# --- 수정 ------------------------------------------------------------------------


async def test_patch_ends_and_reopens_ongoing_period(ctx):
    """진행 중 구간의 ended_at 확정 → 다시 null로 되돌리기 (#312 의미론)."""
    period_id = ctx.create(ended_at=None).json()["data"]["id"]

    ended = ctx.client.patch(
        f"/api/v1/not-underway-periods/{period_id}",
        json={"ended_at": _ts(15)},
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["data"]["ended_at"] is not None

    reopened = ctx.client.patch(
        f"/api/v1/not-underway-periods/{period_id}", json={"ended_at": None}
    )
    assert reopened.status_code == 200
    assert reopened.json()["data"]["ended_at"] is None


async def test_patch_replaces_fuel_uses(ctx):
    """fuel_uses 제공 = 목록 전체 교체 — CF는 교체 시점의 현재 CF로."""
    period_id = ctx.create().json()["data"]["id"]

    resp = ctx.client.patch(
        f"/api/v1/not-underway-periods/{period_id}",
        json={
            "fuel_uses": [
                {"consumer_type": "MAIN_ENGINE", "fuel_type": "DIESEL_GAS_OIL", "fuel_ton": "2.0"}
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    fuels = resp.json()["data"]["fuel_uses"]
    assert len(fuels) == 1
    assert fuels[0]["consumer_type"] == "MAIN_ENGINE"
    assert fuels[0]["fuel_type"] == "DIESEL_GAS_OIL"
    # DIESEL_GAS_OIL CF — 017 seed 정본값.
    assert fuels[0]["cf_used"] == 3.206


async def test_patch_rejects_overlap_with_other_period(ctx):
    """수정으로 시간을 옮겨 다른 구간과 겹치면 409 (자기 자신은 제외)."""
    first = ctx.create(started_at=_ts(10), ended_at=_ts(12)).json()["data"]
    second = ctx.create(started_at=_ts(14), ended_at=_ts(16)).json()["data"]

    moved = ctx.client.patch(
        f"/api/v1/not-underway-periods/{second['id']}",
        json={"started_at": _ts(11)},
    )
    assert moved.status_code == 409

    # 자기 자신과의 겹침은 판정하지 않는다 — 시작만 앞으로 당겨도 자기 창 안이면 OK.
    shrink = ctx.client.patch(
        f"/api/v1/not-underway-periods/{first['id']}",
        json={"started_at": _ts(11)},
    )
    assert shrink.status_code == 200


async def test_patch_404_and_delete(ctx):
    period_id = ctx.create().json()["data"]["id"]

    assert ctx.client.patch(f"/api/v1/not-underway-periods/{uuid4()}", json={}).status_code == 404

    deleted = ctx.client.delete(f"/api/v1/not-underway-periods/{period_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"id": period_id, "deleted": True}

    # soft delete — 조회에서 사라진다.
    assert ctx.client.get(f"/api/v1/not-underway-periods/{period_id}").status_code == 404


# --- YTD 분자 반영 (완료 기준 2) ----------------------------------------------------


async def test_created_fuel_reaches_ytd_numerator(ctx, migrated_db):
    """등록한 구간의 연료가 YTD CII 분자에 들어간다 — #353 엔진과의 종단 결합.

    운하 통과 200nm + HFO 5t → not_underway CO₂ = 5×10⁶×3.114 = 15,570,000 g.
    항차 실적이 없으므로 전체 CO₂가 곧 not under way 기여다.
    """
    resp = ctx.create(
        period_type="CANAL_TRANSIT",
        started_at=_ts(10),
        ended_at=_ts(11),
        distance_nm="200.00",
        fuel_uses=[{"consumer_type": "MAIN_ENGINE", "fuel_type": "HFO", "fuel_ton": "5.0"}],
    )
    assert resp.status_code == 201, resp.text

    from cii_platform.db.session import get_sessionmaker
    from cii_platform.services.ytd_cii import compute_ytd_cii

    maker = get_sessionmaker()
    async with maker() as s:
        result = await compute_ytd_cii(s, vessel_id=ctx.vessel_id, regulation_year=2026)
    assert result.data_available is True
    assert result.not_underway_period_count == 1
    assert result.total_distance_nm == Decimal("200.00")
    assert result.not_underway_co2_g == Decimal("15570000")
    assert result.total_co2_g == result.not_underway_co2_g


# --- 인증 게이트 (완료 기준 4 — 실앱 배선) --------------------------------------------


async def test_csrf_required_for_create(migrated_db, app_fresh_engine):
    """실제 앱 — CSRF 헤더 없는 POST는 403, 세션 csrf 쿠키로 보내면 통과한다.

    #307 선례: 새 변경 엔드포인트는 배선을 테스트로 확인한다.
    """
    from cii_platform.api.main import app

    imo = _imo()
    vessel_id = await _create_vessel(imo)
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200

            url = f"/api/v1/vessels/{vessel_id}/not-underway-periods"
            blocked = client.post(url, json=_payload())
            assert blocked.status_code == 403, blocked.text
            assert blocked.json()["error"]["code"] == "CSRF_ERROR"

            allowed = client.post(
                url, json=_payload(), headers={"X-CSRF-Token": client.cookies.get("csrf")}
            )
            assert allowed.status_code == 201, allowed.text
    finally:
        await _cleanup(imo)
