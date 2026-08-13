"""배선 검증 — 실제 ``main.app`` 대상 (#307).

최소 ``FastAPI()`` 앱을 새로 만들지 않는다. 미들웨어를 최소 앱에 붙이면
"미들웨어를 붙이면 401"만 증명되고 "실제 앱에 붙어 있다"는 증명되지 않는다(#318).
아래 테스트는 ``main.app``을 그대로 쓰므로 배선이 없으면 레드로 떨어진다.
"""

from __future__ import annotations

import pytest
from fakes import FAKE_SESSION_TOKEN, install_fake_auth
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from cii_platform.api.main import app
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
                "(SELECT id FROM app_user WHERE google_sub = 'stub-dev-user-00000000')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE google_sub = 'stub-dev-user-00000000'"))
        # 상태 변경 테스트가 커밋한 선박도 정리 — 같은 IMO를 쓰는 다른 DB 테스트와
        # 충돌하지 않게 한다.
        await s.execute(text("DELETE FROM vessel WHERE imo_number = '7654321'"))
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
    """dev-login 발급 CSRF 토큰으로 상태 변경이 가능하다 (#307 완료 기준)."""
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            csrf_token = client.cookies.get("csrf")

            resp = client.post(
                "/api/v1/vessels",
                json={
                    "imo_number": "7654321",
                    "name": "CSRF T",
                    "ship_type": "BULK_CARRIER",
                },
            )
            assert resp.status_code == 403

            resp2 = client.post(
                "/api/v1/vessels",
                json={
                    "imo_number": "7654321",
                    "name": "CSRF T",
                    "ship_type": "BULK_CARRIER",
                },
                headers={"X-CSRF-Token": csrf_token},
            )
            assert resp2.status_code == 201, resp2.text
            assert resp2.json()["data"]["imo_number"] == "7654321"
    finally:
        await _cleanup_stub_user()
