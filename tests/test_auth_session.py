"""인증 미들웨어·세션·CSRF 테스트 (#275).

DB 없이 돈다 — 세션 토큰 생성·해싱·검증 로직과 미들웨어 게이트를 검증한다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
