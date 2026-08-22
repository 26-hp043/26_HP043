"""인증 실패 경로 테스트 (#279).

성공 경로만 검증하면 인증이 실제로 막고 있는지 알 수 없다 — 만료·무효화·
미등록 경로를 잠근다. id_token 검증 실패 전종(``test_oidc.py``)·state 불일치와
open redirect(``test_auth_api.py``)·CSRF 403(``test_auth_session.py``·
``test_auth_wiring.py``)는 각자의 파일이 담당한다.

케이스: AT-AUTH-007 · AT-AUTH-008 · AT-AUTH-011 · AT-AUTH-012 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

import subprocess
import sys

from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.auth.dependencies import PUBLIC_PATHS
from cii_platform.auth.session import SESSION_COOKIE_NAME

_BASE = "https://testserver"


async def _expire_current_session() -> None:
    """발급된 세션을 만료 상태로 만든다 — expires_at을 과거로."""
    from sqlalchemy import text

    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(
            text(
                "UPDATE user_session SET expires_at = now() - interval '1 hour' "
                "WHERE revoked_at IS NULL"
            )
        )
        await s.commit()


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


async def test_expired_session_is_401(migrated_db, app_fresh_engine):
    """세션 만료 후 같은 쿠키로 보호 경로 → 401 (#279)."""
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            assert client.get("/api/v1/vessels").status_code == 200

            await _expire_current_session()

            resp = client.get("/api/v1/vessels")
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "UNAUTHORIZED"
            assert "만료" in resp.json()["error"]["message"]
    finally:
        await _cleanup_stub_user()


async def test_logout_revokes_session_cookie(migrated_db, app_fresh_engine):
    """로그아웃 후 같은 쿠키로 보호 경로 → 401 (#279)."""
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            assert client.get("/api/v1/vessels").status_code == 200

            # 로그아웃 — 세션 쿠키는 지워지지만, 공격 시나리오를 위해
            # 만료된 쿠키 값을 다시 심어 동일 토큰으로 재시도한다.
            token = client.cookies.get(SESSION_COOKIE_NAME)
            # `#634` — logout도 CSRF를 검증한다.
            csrf = {"X-CSRF-Token": client.cookies["csrf"]}
            assert client.post("/api/v1/auth/logout", headers=csrf).status_code == 204

            client.cookies.set(SESSION_COOKIE_NAME, token)
            resp = client.get("/api/v1/vessels")
            assert resp.status_code == 401
    finally:
        await _cleanup_stub_user()


async def test_logout_without_csrf_header_is_403(migrated_db, app_fresh_engine):
    """세션이 유효해도 CSRF 헤더가 없으면 로그아웃되지 않는다 (`#634`).

    종전에는 이 요청이 **204를 내고 세션을 무효화**했다 — 제3자 사이트가 사용자를
    강제 로그아웃시킬 수 있었다. 데이터가 바뀌지 않아 심각도는 낮지만, 세션을
    요구하는 상태 변경 라우트 중 **이 하나만 규칙의 예외**였고 사유가 없었다.
    """
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200

            resp = client.post("/api/v1/auth/logout")
            assert resp.status_code == 403
            assert resp.json()["error"]["code"] == "CSRF_ERROR"

            # 막혔으면 세션도 살아 있어야 한다 — 「막았는데 로그아웃은 됐다」가
            # 되면 보호가 아무 일도 하지 않은 것이다.
            assert client.get("/api/v1/vessels").status_code == 200
    finally:
        await _cleanup_stub_user()


async def test_logout_is_not_idempotent_without_a_session(migrated_db, app_fresh_engine):
    """**「세션 없어도 204」가 아니다** (`#634`).

    `API_SPEC §1.2`가 그렇게 적고 있었으나 같은 행의 「인증: 필요」와 모순이었고,
    그 문구는 `#272`(PR `#297`)에서 사유 없이 들어왔다. 구현·테스트는 처음부터
    보호 경로로 다뤄 왔다 — 정본을 구현에 맞췄다.
    """
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            token = client.cookies.get(SESSION_COOKIE_NAME)
            csrf = {"X-CSRF-Token": client.cookies["csrf"]}

            assert client.post("/api/v1/auth/logout", headers=csrf).status_code == 204

            # 같은 쿠키로 다시 — 세션이 이미 무효화됐으므로 401이다.
            client.cookies.set(SESSION_COOKIE_NAME, token)
            resp = client.post("/api/v1/auth/logout", headers=csrf)
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "UNAUTHORIZED"

            # 쿠키가 아예 없는 경우도 401이다.
            client.cookies.clear()
            assert client.post("/api/v1/auth/logout").status_code == 401
    finally:
        await _cleanup_stub_user()


def test_protected_paths_are_not_public() -> None:
    """공개 경로는 열거된 것뿐 — 나머지 대표 경로는 전부 보호 (#279)."""
    assert "/api/v1/health" in PUBLIC_PATHS
    assert "/api/v1/auth/login" in PUBLIC_PATHS
    assert "/api/v1/auth/signup" in PUBLIC_PATHS
    assert "/api/v1/auth/dev-login" in PUBLIC_PATHS

    protected = [
        "/api/v1/vessels",
        "/api/v1/voyages",
        "/api/v1/calculations/voyage-cii",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/annual-simulations",
    ]
    for path in protected:
        assert path not in PUBLIC_PATHS, path


def test_dev_login_not_registered_in_production(tmp_path) -> None:
    """APP_ENV=production이면 dev-login 라우트가 앱에 없다 (#279).

    등록은 import 시점에 갈리므로 별도 프로세스에서 검증한다.
    """
    # FastAPI의 지연 라우터 등록(lazy include) 때문에 app.routes 나열은 믿을 수
    # 없다 — openapi() 생성으로 라우트를 확정 짓고 경로 집합을 검사한다.
    # (HTTP 요청 방식은 login의 구글 리다이렉트를 따라가 외부 네트워크에 의존한다.)
    code = (
        "from cii_platform.api.main import app\n"
        "paths = set(app.openapi()['paths'])\n"
        "assert '/api/v1/auth/dev-login' not in paths, sorted(paths)\n"
        "assert '/api/v1/auth/login' in paths\n"
        "assert '/api/v1/auth/signup' in paths\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        # config가 production에서 DATABASE_URL을 요구하므로 더미 URL을 준다 —
        # import 시점에 연결은 열지 않는다.
        env={
            "APP_ENV": "production",
            "DATABASE_URL": "postgresql+asyncpg://cii:cii@localhost:5432/cii",
            "PATH": "/usr/bin:/bin",
        },
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# GET이 CSRF 없이 통과하는 것은 test_auth_wiring.py의
# test_dev_login_issues_session_cookie가 증명한다 (dev-login 후 헤더 없이 GET → 200).
