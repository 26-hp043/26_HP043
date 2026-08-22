"""배선 검증 — 실제 ``main.app`` 대상 (#307).

최소 ``FastAPI()`` 앱을 새로 만들지 않는다. 미들웨어를 최소 앱에 붙이면
"미들웨어를 붙이면 401"만 증명되고 "실제 앱에 붙어 있다"는 증명되지 않는다(#318).
아래 테스트는 ``main.app``을 그대로 쓰므로 배선이 없으면 레드로 떨어진다.

케이스: AT-AUTH-006 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

import pytest
from fakes import FAKE_SESSION_TOKEN, install_fake_auth
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.auth.session import SESSION_COOKIE_NAME


def test_protected_route_is_401_without_session() -> None:
    """미들웨어 미배선이면 200이 나와 실패한다 — 배선 존재를 증명하는 테스트."""
    with TestClient(app, base_url="https://testserver") as client:
        resp = client.get("/api/v1/vessels")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"
        # RequestContext가 auth보다 바깥 — 401에도 request_id가 채워진다.
        assert resp.json()["meta"]["request_id"]


def test_health_is_public() -> None:
    """/health는 인증 없이 통과한다 (PUBLIC_PATHS)."""
    with TestClient(app, base_url="https://testserver") as client:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200


def test_mutating_route_without_csrf_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """세션은 유효해도 CSRF 토큰이 없으면 상태 변경은 403 (#307)."""
    install_fake_auth(monkeypatch)
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, FAKE_SESSION_TOKEN)
        resp = client.post(
            "/api/v1/vessels",
            json={"imo_number": "1234567", "name": "T", "ship_type": "BULK_CARRIER"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "CSRF_ERROR"


def test_mutating_route_with_wrong_csrf_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """CSRF 토큰 불일치는 403 (#307)."""
    install_fake_auth(monkeypatch)
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, FAKE_SESSION_TOKEN)
        resp = client.post(
            "/api/v1/vessels",
            json={"imo_number": "1234567", "name": "T", "ship_type": "BULK_CARRIER"},
            headers={"X-CSRF-Token": "wrong"},
        )
        assert resp.status_code == 403


def _mutating_routes() -> list[tuple[str, str, bool]]:
    """``routes/*.py``를 **소스에서** 읽어 상태 변경 라우트를 모은다.

    FastAPI 객체를 훑지 않는다 — 이 버전은 ``include_router``가 라우트를 래퍼
    객체 안에 감춰 두어, 순진하게 ``app.routes``를 도는 코드는 **0개를 검사하고도
    통과한다.** 실제로 그렇게 썼다가 아래 `test_the_guard_can_actually_fail`에
    걸렸다. 소스는 그런 식으로 조용해지지 않는다.

    반환: ``(메서드, 전체 경로, require_csrf가 걸렸는가)``
    """
    import ast
    from pathlib import Path

    routes_dir = Path(__file__).resolve().parents[1] / "src" / "cii_platform" / "api" / "routes"
    found: list[tuple[str, str, bool]] = []

    for path in sorted(routes_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # ``router = APIRouter(prefix="/auth", ...)`` — 없으면 빈 접두사.
        prefix = ""
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "router" for t in node.targets
            ):
                for kw in getattr(node.value, "keywords", []):
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for deco in node.decorator_list:
                func = getattr(deco, "func", None)
                method = getattr(func, "attr", "").upper()
                if method not in {"POST", "PATCH", "PUT", "DELETE"}:
                    continue
                if not deco.args or not isinstance(deco.args[0], ast.Constant):
                    continue
                full = f"{API_V1_PREFIX}{prefix}{deco.args[0].value}"
                source = ast.unparse(node.args)
                found.append((method, full, "require_csrf" in source))

    return found


def test_no_session_route_skips_csrf() -> None:
    """**세션을 요구하는 상태 변경 라우트에 CSRF 예외가 없다** (`#634`).

    `POST /auth/logout` 하나만 예외였다 — 세션이 필요한데 `require_csrf`가 없어
    제3자 사이트가 사용자를 강제 로그아웃시킬 수 있었다. 그 예외를 없앴고, 여기서
    **다시 생기지 않도록 잠근다.**

    개별 라우트를 열거하지 않는다 — 라우트가 하나 늘 때 이 테스트가 알아야 하고,
    열거하면 새 라우트는 목록에 없어 검사되지 않는다(`#527`이 겪은 형태다).

    검증이 없어도 되는 것은 **세션이 없는 공개 경로**뿐이다. 검증할 세션이 없으므로
    예외가 아니라 적용 대상이 아니다 (`API_SPEC §1.2`).
    """
    from cii_platform.auth.dependencies import build_public_paths

    # 환경과 무관하게 판정한다 — dev-login·docs가 노출되는 환경에서도 같은 결론이어야
    # 한다. 넓은 쪽(둘 다 공개)을 쓰면 공개 경로를 놓치지 않는다.
    public = build_public_paths(expose_docs=True, expose_dev_auth=True)

    offenders = [
        f"{method} {path}"
        for method, path, has_csrf in _mutating_routes()
        if path not in public and not has_csrf
    ]

    assert not offenders, (
        f"세션이 필요한데 CSRF 검증이 없는 라우트 {len(offenders)}개: {offenders}\n"
        "→ `Depends(require_csrf)`를 걸거나, 공개 경로라면 PUBLIC_PATHS에 넣으세요."
    )


def test_the_guard_can_actually_fail() -> None:
    """위 단언이 **아무것도 검사하지 않는 상태**가 아닌지 확인한다.

    라우트 수집이 깨지면 `offenders`가 늘 비어 조용히 통과한다. **이 가드가 실제로
    한 번 잡았다** — 처음 구현은 `app.routes`를 돌았는데 이 FastAPI 버전은 라우트를
    래퍼에 감춰 두어 수집 결과가 0개였다.
    """
    routes = _mutating_routes()
    assert len(routes) >= 20, f"검사 대상이 {len(routes)}개뿐이다 — 수집이 깨졌는지 확인할 것"
    assert any(has_csrf for _, _, has_csrf in routes), "require_csrf를 하나도 찾지 못했다"


def test_public_mutating_routes_are_the_session_less_ones() -> None:
    """CSRF 검증이 없는 상태 변경 라우트는 **전부 공개 인증 경로**다 (`#634`).

    위 테스트의 반대 방향이다 — 「예외가 없다」만 보면 **전부 공개로 만들어** 통과시킬
    수 있다. 검증이 빠진 것들이 실제로 세션 없는 경로인지 여기서 확인한다.
    """
    from cii_platform.auth.dependencies import build_public_paths

    public = build_public_paths(expose_docs=True, expose_dev_auth=True)
    skipped = sorted({path for _, path, has_csrf in _mutating_routes() if not has_csrf})

    assert skipped, "검증이 없는 라우트를 하나도 찾지 못했다 — 수집이 깨졌는지 확인할 것"
    assert all(path in public for path in skipped), skipped
    # 로그아웃이 다시 이 목록에 들어오면 `#634`의 회귀다.
    assert f"{API_V1_PREFIX}/auth/logout" not in skipped


def test_middleware_stack_order() -> None:
    """스택 순서 — 바깥→안쪽: RequestContext → rate_limit → auth (#307)."""
    from cii_platform.api.middleware import RequestContextMiddleware

    stack = app.user_middleware  # 바깥 → 안쪽 순 저장(insert(0, …) 때문).
    assert stack[0].cls is RequestContextMiddleware
    dispatches = [m.kwargs.get("dispatch") for m in stack if m.cls is BaseHTTPMiddleware]
    names = [d.__name__ for d in dispatches if d is not None]
    assert names == ["rate_limit_middleware", "auth_middleware"]


# --- DB 필요 테스트 (CI에서 실행) ----------------------------------------------------
#
# app_fresh_engine(NullPool)로 포털 루프 충돌을 피한다(conftest 참조).
# dev-login은 실제로 커밋하므로 finally에서 스텁 사용자를 정리한다.


async def _cleanup_stub_user() -> None:
    from sqlalchemy import text

    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
        await s.commit()


async def test_dev_login_issues_session_cookie(migrated_db, app_fresh_engine):
    """dev-login이 실제 앱에서 세션 쿠키를 발급한다 — 배선 후에도 공개 경로."""
    try:
        with TestClient(app, base_url="https://testserver") as client:
            resp = client.post("/api/v1/auth/dev-login")
            assert resp.status_code == 200, resp.text
            assert SESSION_COOKIE_NAME in client.cookies
            assert client.cookies.get("csrf")

            # 발급받은 세션으로 보호 라우트가 열린다 (완료 기준: 쿠키 → 200).
            resp2 = client.get("/api/v1/vessels")
            assert resp2.status_code == 200, resp2.text
    finally:
        await _cleanup_stub_user()


async def test_dev_login_then_mutating_route_with_csrf(migrated_db, app_fresh_engine):
    """dev-login 발급 CSRF 토큰으로 상태 변경이 가능하다 (#307 완료 기준).

    항차 생성으로 검증한다 — 선박 등록은 reference line 시드(seed 스크립트)가
    필요하지만, CI의 마이그레이션 DB에는 없다. 항차 생성은 017이 시드하는
    연료(HFO)만 있으면 성립한다.
    """
    from uuid import UUID

    demo_vessel = UUID("00000000-0000-4000-8000-000000000001")  # 018 시드 선박
    payload = {
        "departure_port_name": "Busan",
        "arrival_port_name": "Rotterdam",
        "planned_distance_nm": 11000.0,
        "planned_speed_kn": 14.0,
        "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 800.0}],
    }
    voyage_id = None
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            csrf_token = client.cookies.get("csrf")

            resp = client.post(f"/api/v1/vessels/{demo_vessel}/voyages", json=payload)
            assert resp.status_code == 403

            resp2 = client.post(
                f"/api/v1/vessels/{demo_vessel}/voyages",
                json=payload,
                headers={"X-CSRF-Token": csrf_token},
            )
            assert resp2.status_code == 201, resp2.text
            voyage_id = resp2.json()["data"]["id"]
    finally:
        await _cleanup_stub_user()
        if voyage_id:
            from sqlalchemy import text

            from cii_platform.db.session import get_sessionmaker

            sessionmaker = get_sessionmaker()
            async with sessionmaker() as s:
                # 연료 내역은 FK CASCADE로 함께 사라진다.
                await s.execute(text("DELETE FROM voyage WHERE id = :id"), {"id": voyage_id})
                await s.commit()
