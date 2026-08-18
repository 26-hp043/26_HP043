"""인증 미들웨어·세션·CSRF 테스트 (#275).

DB 없이 돈다 — 세션 토큰 생성·해싱·검증 로직과 미들웨어 게이트를 검증한다.

케이스: AT-AUTH-009 · AT-AUTH-010 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.auth.dependencies import get_current_user
from cii_platform.auth.session import (
    COOKIE_ATTRIBUTES,
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_TTL_DAYS,
    create_session_fields,
    generate_csrf_token,
    generate_session_token,
    hash_token,
    is_expired,
    is_revoked,
    is_valid,
    verify_csrf,
)
from cii_platform.db.models.app_user import AppUser


class TestTokenGeneration:
    """토큰 생성·해싱."""

    def test_session_token_is_unique(self):
        a = generate_session_token()
        b = generate_session_token()
        assert a != b

    def test_csrf_token_is_unique(self):
        a = generate_csrf_token()
        b = generate_csrf_token()
        assert a != b

    def test_hash_is_sha256_hex(self):
        token = "test-token"
        h = hash_token(token)
        assert len(h) == 64
        assert h == hashlib.sha256(b"test-token").hexdigest()


class TestSessionValidity:
    """세션 만료·무효 판정."""

    def test_fresh_session_is_valid(self):
        now = datetime.now(UTC)
        expires = now + timedelta(days=7)
        assert is_valid(expires, None)

    def test_expired_session_is_invalid(self):
        now = datetime.now(UTC)
        expires = now - timedelta(seconds=1)
        assert not is_valid(expires, None)

    def test_revoked_session_is_invalid(self):
        now = datetime.now(UTC)
        expires = now + timedelta(days=7)
        assert not is_valid(expires, now)

    def test_is_expired(self):
        now = datetime.now(UTC)
        assert is_expired(now - timedelta(seconds=1), now)
        assert not is_expired(now + timedelta(days=1), now)

    def test_is_revoked(self):
        assert is_revoked(datetime.now(UTC))
        assert not is_revoked(None)


class TestCsrfVerification:
    """CSRF 토큰 검증."""

    def test_matching_token_passes(self):
        csrf = generate_csrf_token()
        h = hash_token(csrf)
        assert verify_csrf(csrf, h)

    def test_mismatched_token_fails(self):
        csrf = generate_csrf_token()
        h = hash_token("different")
        assert not verify_csrf(csrf, h)

    def test_empty_token_fails(self):
        h = hash_token(generate_csrf_token())
        assert not verify_csrf("", h)


class TestCreateSessionFields:
    """세션 INSERT 필드 생성."""

    def test_fields_contain_hashes_not_plaintext(self):
        from uuid import uuid4

        fields, session_token, csrf_token = create_session_fields(uuid4())
        # DB에는 해시만.
        assert fields["session_token_hash"] != session_token
        assert fields["csrf_token_hash"] != csrf_token
        assert fields["session_token_hash"] == hash_token(session_token)
        assert fields["csrf_token_hash"] == hash_token(csrf_token)

    def test_expires_at_is_ttl_days_ahead(self):
        from uuid import uuid4

        fields, _, _ = create_session_fields(uuid4())
        now = datetime.now(UTC)
        delta = fields["expires_at"] - now
        # TTL ± 1분 오차 허용 (테스트 실행 시간)
        assert abs(delta.total_seconds() - SESSION_TTL_DAYS * 86400) < 60

    def test_revoked_at_is_none_on_creation(self):
        from uuid import uuid4

        fields, _, _ = create_session_fields(uuid4())
        assert fields["revoked_at"] is None

    def test_returned_tokens_are_different(self):
        from uuid import uuid4

        _, session_token, csrf_token = create_session_fields(uuid4())
        assert session_token != csrf_token


class TestCookieConfig:
    """쿠키 속성이 API_SPEC §1.2와 일치하는지."""

    def test_session_cookie_name(self):
        assert SESSION_COOKIE_NAME == "sid"

    def test_csrf_cookie_name(self):
        assert CSRF_COOKIE_NAME == "csrf"

    def test_cookie_attributes(self):
        assert COOKIE_ATTRIBUTES["httponly"] is True
        assert COOKIE_ATTRIBUTES["secure"] is True
        assert COOKIE_ATTRIBUTES["samesite"] == "lax"
        assert COOKIE_ATTRIBUTES["path"] == "/"


class TestAuthMiddlewareGate:
    """인증 미들웨어가 공개/보호 경로를 올바르게 가른다."""

    @pytest.fixture
    def auth_app(self) -> FastAPI:
        """인증 미들웨어가 붙은 최소 app."""
        from starlette.responses import JSONResponse

        from cii_platform.auth.middleware import auth_middleware

        app = FastAPI()

        @app.get("/health")
        async def health():
            return JSONResponse({"data": {"status": "ok"}})

        @app.get("/api/v1/vessels")
        async def vessels():
            return JSONResponse({"data": []})

        app.middleware("http")(auth_middleware)
        return app

    def test_public_path_passes_without_session(self, auth_app):
        with TestClient(auth_app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_protected_path_without_cookie_is_401(self, auth_app):
        with TestClient(auth_app) as client:
            resp = client.get("/api/v1/vessels")
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "UNAUTHORIZED"


class TestPublicPaths:
    """공개 경로 판정 — 명시적 목록만 허용 (#308)."""

    def test_dev_login_path_is_public(self):
        from cii_platform.auth.dependencies import is_public_path

        assert is_public_path("/api/v1/auth/dev-login")

    def test_auth_prefix_alone_is_not_public(self):
        from cii_platform.auth.dependencies import is_public_path

        # 접두사 규칙 제거 — auth 하위라도 목록에 없으면 보호된다.
        assert not is_public_path("/api/v1/auth/logout")
        assert not is_public_path("/auth/anything")


class TestRequireCsrfFailClosed:
    """``require_csrf``는 session_row가 없으면 막는다 — fail-closed (#311)."""

    CSRF_TOKEN = "csrf-plaintext-for-test"

    @pytest.fixture
    def csrf_app(self) -> FastAPI:
        """``Depends(require_csrf)``가 건 라우트가 붙은 최소 app."""
        from types import SimpleNamespace

        from starlette.responses import JSONResponse

        from cii_platform.auth.dependencies import require_csrf

        app = FastAPI()
        register_exception_handlers(app)

        @app.middleware("http")
        async def seed_session_row(request, call_next):
            # 인증 미들웨어가 session_row를 주입한 상황을 흉내낸다.
            request.state.session_row = SimpleNamespace(csrf_token_hash=hash_token(self.CSRF_TOKEN))
            return await call_next(request)

        @app.post("/api/v1/thing")
        async def thing(_csrf: None = Depends(require_csrf)):
            return JSONResponse({"data": {}})

        return app

    def test_without_middleware_state_is_401(self):
        """session_row가 없으면 조용히 통과하지 않고 401 (#311)."""
        from starlette.responses import JSONResponse

        from cii_platform.auth.dependencies import require_csrf

        app = FastAPI()
        register_exception_handlers(app)

        @app.post("/api/v1/thing")
        async def thing(_csrf: None = Depends(require_csrf)):
            return JSONResponse({"data": {}})

        with TestClient(app) as client:
            resp = client.post("/api/v1/thing")
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_missing_csrf_header_is_403(self, csrf_app):
        with TestClient(csrf_app) as client:
            resp = client.post("/api/v1/thing")
            assert resp.status_code == 403
            assert resp.json()["error"]["code"] == "CSRF_ERROR"

    def test_wrong_csrf_token_is_403(self, csrf_app):
        with TestClient(csrf_app) as client:
            resp = client.post("/api/v1/thing", headers={"X-CSRF-Token": "wrong"})
            assert resp.status_code == 403

    def test_correct_csrf_token_passes(self, csrf_app):
        with TestClient(csrf_app) as client:
            resp = client.post("/api/v1/thing", headers={"X-CSRF-Token": self.CSRF_TOKEN})
            assert resp.status_code == 200


class TestGetCurrentUserDependsSafe:
    """``get_current_user``를 Depends로 안전하게 걸 수 있다 (#315)."""

    def test_depends_route_without_cookie_returns_401(self):
        # 주의: 라우트 어노테이션의 이름(AppUser·get_current_user)은 모듈 네임스페이스에서
        # 평가된다(from __future__ import annotations) — 함수 안에서 import하면 안 풀린다.
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/api/v1/me")
        async def me(user: Annotated[AppUser, Depends(get_current_user)]):
            return {"data": {"id": str(user.id)}}

        # 예전 시그니처(session: AsyncSession = None)였다면 라우트 등록 단계에서
        # FastAPI가 AsyncSession을 요청 본문으로 해석하다 실패한다 (#315).
        with TestClient(app) as client:
            resp = client.get("/api/v1/me")
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "UNAUTHORIZED"
