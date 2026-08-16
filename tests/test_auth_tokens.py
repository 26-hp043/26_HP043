"""이메일 인증 · 비밀번호 재설정 검증 (#408).

## 이 파일이 잡는 것

- **토큰 재사용·위조·만료가 구분되지 않는 것** — 구분하면 공격자가 추측 결과를 좁힌다
- **재설정 성공 시 기존 세션이 전부 끊기는 것** — 이 기능의 존재 이유
- **재설정 요청이 가입 여부를 노출하지 않는 것**
- 재발송 시 이전 토큰이 무효화되는 것

메일은 `console` 백엔드가 로그로만 출력하므로 발송 실패가 테스트를 막지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.api.routes.auth_tokens import (
    RESET_REQUESTED_MESSAGE,
    TOKEN_INVALID_MESSAGE,
)
from cii_platform.db.models.user_token import (
    PURPOSE_EMAIL_VERIFY,
    PURPOSE_PASSWORD_RESET,
)
from cii_platform.services.auth_token import (
    TokenError,
    consume_token,
    hash_token,
    issue_token,
)

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "brand-new-passphrase"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


async def _cleanup(email: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "DELETE FROM user_token WHERE user_id IN (SELECT id FROM app_user WHERE email = :e)"
            ),
            {"e": email},
        )
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = :e)"
            ),
            {"e": email},
        )
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


async def _latest_token_hash(email: str, purpose: str) -> str | None:
    """DB에 남은 최신 토큰 해시. **원문은 조회할 수 없다** — 그것이 설계다."""
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = await s.execute(
            text(
                "SELECT token_hash FROM user_token t JOIN app_user u ON u.id = t.user_id "
                "WHERE u.email = :e AND t.purpose = :p ORDER BY t.created_at DESC LIMIT 1"
            ),
            {"e": email, "p": purpose},
        )
        return row.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# 서비스 계층 — 토큰 발급·소비
# ─────────────────────────────────────────────────────────────────────────────


class TestTokenService:
    async def test_issued_token_is_stored_as_hash_only(self, conn):
        """DB에 원문이 남으면 안 된다 — 유출 시 그대로 쓸 수 있는 증명이 된다."""
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            row = await s.execute(
                text(
                    "INSERT INTO app_user (email, password_hash) "
                    "VALUES ('tok@example.com', 'x') RETURNING id"
                )
            )
            user_id = row.scalar_one()

            raw = await issue_token(s, user_id=user_id, purpose=PURPOSE_EMAIL_VERIFY)
            await s.flush()

            # 이 사용자의 토큰만 본다 — DB에 다른 토큰이 있어도 영향받지 않게.
            stored = await s.execute(
                text("SELECT token_hash FROM user_token WHERE user_id = :u"),
                {"u": user_id},
            )
            digest = stored.scalar_one()

            assert digest != raw
            assert digest == hash_token(raw)

    async def test_consuming_twice_fails(self, conn):
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            row = await s.execute(
                text(
                    "INSERT INTO app_user (email, password_hash) "
                    "VALUES ('twice@example.com', 'x') RETURNING id"
                )
            )
            user_id = row.scalar_one()
            raw = await issue_token(s, user_id=user_id, purpose=PURPOSE_EMAIL_VERIFY)
            await s.flush()

            assert await consume_token(s, raw=raw, purpose=PURPOSE_EMAIL_VERIFY) == user_id
            await s.flush()

            with pytest.raises(TokenError):
                await consume_token(s, raw=raw, purpose=PURPOSE_EMAIL_VERIFY)

    async def test_expired_token_fails(self, conn):
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            row = await s.execute(
                text(
                    "INSERT INTO app_user (email, password_hash) "
                    "VALUES ('exp@example.com', 'x') RETURNING id"
                )
            )
            user_id = row.scalar_one()
            raw = await issue_token(s, user_id=user_id, purpose=PURPOSE_PASSWORD_RESET)
            await s.flush()

            # 만료 이후 시점으로 검증한다.
            future = datetime.now(UTC) + timedelta(hours=2)
            with pytest.raises(TokenError):
                await consume_token(s, raw=raw, purpose=PURPOSE_PASSWORD_RESET, now=future)

    async def test_purpose_mismatch_fails(self, conn):
        """인증 토큰으로 비밀번호를 바꿀 수 없어야 한다."""
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            row = await s.execute(
                text(
                    "INSERT INTO app_user (email, password_hash) "
                    "VALUES ('mix@example.com', 'x') RETURNING id"
                )
            )
            user_id = row.scalar_one()
            raw = await issue_token(s, user_id=user_id, purpose=PURPOSE_EMAIL_VERIFY)
            await s.flush()

            with pytest.raises(TokenError):
                await consume_token(s, raw=raw, purpose=PURPOSE_PASSWORD_RESET)

    async def test_reissue_invalidates_the_previous_token(self, conn):
        """재발송 때마다 유효한 링크가 늘어나면, 오래된 메일이 계속 살아 있다."""
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            row = await s.execute(
                text(
                    "INSERT INTO app_user (email, password_hash) "
                    "VALUES ('re@example.com', 'x') RETURNING id"
                )
            )
            user_id = row.scalar_one()

            old = await issue_token(s, user_id=user_id, purpose=PURPOSE_EMAIL_VERIFY)
            await s.flush()
            new = await issue_token(s, user_id=user_id, purpose=PURPOSE_EMAIL_VERIFY)
            await s.flush()

            with pytest.raises(TokenError):
                await consume_token(s, raw=old, purpose=PURPOSE_EMAIL_VERIFY)
            assert await consume_token(s, raw=new, purpose=PURPOSE_EMAIL_VERIFY) == user_id


# ─────────────────────────────────────────────────────────────────────────────
# API — 이메일 인증
# ─────────────────────────────────────────────────────────────────────────────


class TestEmailVerification:
    async def test_signup_issues_a_verification_token(self, client):
        try:
            resp = client.post(
                "/api/v1/auth/signup",
                json={"email": "verify@example.com", "password": PASSWORD},
            )
            assert resp.status_code == 201
            # 가입 즉시 인증 메일용 토큰이 발급된다.
            assert await _latest_token_hash("verify@example.com", PURPOSE_EMAIL_VERIFY)
        finally:
            await _cleanup("verify@example.com")

    def test_forged_token_is_rejected_with_the_generic_message(self, client):
        """위조·만료·사용됨을 구분하지 않는다 — 구분하면 추측 결과를 좁힐 수 있다."""
        resp = client.post("/api/v1/auth/verify-email/confirm", json={"token": "forged-token"})
        assert resp.status_code == 400
        assert resp.json()["error"]["message"] == TOKEN_INVALID_MESSAGE

    async def test_request_for_unknown_email_looks_the_same(self, client):
        """존재 확인 수단이 되면 안 된다."""
        resp = client.post(
            "/api/v1/auth/verify-email/request", json={"email": "nobody@example.com"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["message"] == RESET_REQUESTED_MESSAGE


# ─────────────────────────────────────────────────────────────────────────────
# API — 비밀번호 재설정
# ─────────────────────────────────────────────────────────────────────────────


class TestPasswordReset:
    async def test_request_response_is_identical_regardless_of_registration(self, client):
        """**가입 여부를 노출하지 않는다** — 노출하면 가입자 목록이 캐진다."""
        try:
            client.post(
                "/api/v1/auth/signup",
                json={"email": "known@example.com", "password": PASSWORD},
            )
            client.cookies.clear()

            known = client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "known@example.com"},
            )
            unknown = client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "unknown@example.com"},
            )

            assert known.status_code == unknown.status_code == 200
            assert known.json()["data"] == unknown.json()["data"]
        finally:
            await _cleanup("known@example.com")

    async def test_reset_revokes_all_existing_sessions(self, client):
        """**이 기능의 존재 이유다.**

        탈취된 상태에서 비밀번호만 바꾸면 공격자 세션이 그대로 살아 있다.
        """
        from cii_platform.db.session import get_sessionmaker
        from cii_platform.services.auth_token import issue_token as issue

        email = "revoke@example.com"
        try:
            signup = client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            assert signup.status_code == 201
            # 이 시점에 세션이 살아 있다.
            assert client.get("/api/v1/auth/me").status_code == 200

            # 재설정 토큰을 직접 발급한다 — 메일 원문을 테스트가 알 수 없기 때문이다.
            async with get_sessionmaker()() as s:
                row = await s.execute(
                    text("SELECT id FROM app_user WHERE email = :e"), {"e": email}
                )
                user_id = row.scalar_one()
                raw = await issue(s, user_id=user_id, purpose=PURPOSE_PASSWORD_RESET)
                await s.commit()

            resp = client.post(
                "/api/v1/auth/password-reset/confirm",
                json={"token": raw, "password": NEW_PASSWORD},
            )
            assert resp.status_code == 200, resp.text

            # 기존 세션 쿠키가 더 이상 통하지 않는다.
            assert client.get("/api/v1/auth/me").status_code == 401
        finally:
            await _cleanup(email)

    async def test_old_password_stops_working_and_new_one_works(self, client):
        from cii_platform.db.session import get_sessionmaker
        from cii_platform.services.auth_token import issue_token as issue

        email = "swap@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            async with get_sessionmaker()() as s:
                row = await s.execute(
                    text("SELECT id FROM app_user WHERE email = :e"), {"e": email}
                )
                raw = await issue(s, user_id=row.scalar_one(), purpose=PURPOSE_PASSWORD_RESET)
                await s.commit()

            client.post(
                "/api/v1/auth/password-reset/confirm",
                json={"token": raw, "password": NEW_PASSWORD},
            )
            client.cookies.clear()

            old = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
            new = client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
            assert old.status_code == 401
            assert new.status_code == 200
        finally:
            await _cleanup(email)

    def test_weak_new_password_is_rejected(self, client):
        """정책 검사가 재설정 경로에도 적용된다."""
        resp = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": "whatever", "password": "short"},
        )
        assert resp.status_code == 422
        assert "10자" in resp.json()["error"]["message"]

    def test_forged_reset_token_is_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": "forged", "password": NEW_PASSWORD},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["message"] == TOKEN_INVALID_MESSAGE
