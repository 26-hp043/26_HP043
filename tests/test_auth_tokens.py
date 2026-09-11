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
from cii_platform.mail import MailDeliveryError
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


# ─────────────────────────────────────────────────────────────────────────────
# 성공 경로 — `#871`
#
# `#871`이 「테스트가 통과하는데 라우트 본문이 실행되지 않는다」를 보고했고, 원인의
# **대부분은 커버리지 계측**이었다(`pyproject.toml`의 `concurrency` 참조). 다만 계측을
# 고친 뒤에도 `auth_tokens.py`가 80%였고, 남은 구멍은 **진짜 미검사**였다.
#
#   136-150  인증 메일 재발송의 성공 경로와 메일 실패 502
#   166-176  인증 확인의 성공 경로
#   206-207  재설정 메일 실패 502
#   232-233  재설정 확인에서 토큰은 유효한데 사용자가 없는 경우
#
# 종전 검사는 **거부 경로만** 보고 있었다 — 위조 토큰·모르는 주소·약한 비밀번호.
# 「막아야 할 것을 막는가」만 보고 **「해야 할 일을 하는가」를 보지 않은** 상태다.
# ─────────────────────────────────────────────────────────────────────────────


class _FailingMailer:
    """발송이 실패하는 메일러. `MailDeliveryError`는 백엔드가 감싸 던지는 예외다."""

    async def send(self, _message) -> None:
        raise MailDeliveryError("테스트 강제 실패")


async def _user_id(email: str):
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = await s.execute(text("SELECT id FROM app_user WHERE email = :e"), {"e": email})
        return row.scalar_one()


async def _verified_at(email: str):
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = await s.execute(
            text("SELECT email_verified_at FROM app_user WHERE email = :e"), {"e": email}
        )
        return row.scalar_one()


class TestEmailVerificationSucceeds:
    async def test_resend_issues_a_new_token_for_an_unverified_account(self, client):
        """재발송이 **실제로 새 토큰을 낸다.**

        종전에는 「모르는 주소도 같은 응답」만 검사했다 — 그 검사는 `user is None`
        갈래만 지나므로, 재발송이 아무 일도 하지 않아도 통과한다.
        """
        email = "resend@example.com"
        try:
            assert (
                client.post(
                    "/api/v1/auth/signup", json={"email": email, "password": PASSWORD}
                ).status_code
                == 201
            )
            first = await _latest_token_hash(email, PURPOSE_EMAIL_VERIFY)
            assert first is not None

            resp = client.post("/api/v1/auth/verify-email/request", json={"email": email})
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["message"] == RESET_REQUESTED_MESSAGE

            # 재발송이면 **다른 토큰**이어야 한다 — 같으면 이전 것이 그대로 살아 있다.
            assert await _latest_token_hash(email, PURPOSE_EMAIL_VERIFY) != first
        finally:
            await _cleanup(email)

    async def test_confirming_marks_the_account_verified(self, client):
        """인증 확인이 **실제로 `email_verified_at`을 기록한다.**

        종전에는 위조 토큰 거부만 검사했다. 성공 경로가 비어 있으면 「인증했는데
        인증되지 않은」 상태를 아무도 잡지 못한다.
        """
        from cii_platform.db.session import get_sessionmaker
        from cii_platform.services.auth_token import issue_token as issue

        email = "confirm@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            assert await _verified_at(email) is None

            async with get_sessionmaker()() as s:
                raw = await issue(s, user_id=await _user_id(email), purpose=PURPOSE_EMAIL_VERIFY)
                await s.commit()

            resp = client.post("/api/v1/auth/verify-email/confirm", json={"token": raw})
            assert resp.status_code == 200, resp.text
            assert await _verified_at(email) is not None
        finally:
            await _cleanup(email)

    async def test_already_verified_account_gets_no_new_token(self, client):
        """이미 인증된 계정은 **토큰을 더 만들지 않되 응답은 같다.**

        응답을 다르게 하면 「이 주소는 이미 인증됨」이 밖에서 확인된다.
        """
        from cii_platform.db.session import get_sessionmaker
        from cii_platform.services.auth_token import issue_token as issue

        email = "already@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            async with get_sessionmaker()() as s:
                raw = await issue(s, user_id=await _user_id(email), purpose=PURPOSE_EMAIL_VERIFY)
                await s.commit()
            client.post("/api/v1/auth/verify-email/confirm", json={"token": raw})
            settled = await _latest_token_hash(email, PURPOSE_EMAIL_VERIFY)

            resp = client.post("/api/v1/auth/verify-email/request", json={"email": email})
            assert resp.status_code == 200
            assert resp.json()["data"]["message"] == RESET_REQUESTED_MESSAGE
            assert await _latest_token_hash(email, PURPOSE_EMAIL_VERIFY) == settled
        finally:
            await _cleanup(email)

    async def test_mail_failure_is_reported_but_the_token_survives(
        self, client, monkeypatch: pytest.MonkeyPatch
    ):
        """발송이 실패하면 502를 내되 **토큰은 되돌리지 않는다** (`#407` 경계).

        되돌리면 사용자는 오류를 본 뒤 그 토큰으로 아무것도 할 수 없다. 라우트 주석이
        *「토큰은 이미 커밋됐다 — 되돌리지 않는다」*로 그 판단을 적어 두었다.
        """
        from cii_platform.api.routes import auth_tokens as module

        email = "mailfail@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            monkeypatch.setattr(module, "get_mailer", _FailingMailer)

            resp = client.post("/api/v1/auth/verify-email/request", json={"email": email})
            assert resp.status_code == 502, resp.text
            assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
            # 커밋된 토큰이 남아 있다.
            assert await _latest_token_hash(email, PURPOSE_EMAIL_VERIFY) is not None
        finally:
            await _cleanup(email)


class TestPasswordResetEdges:
    async def test_mail_failure_is_reported(self, client, monkeypatch: pytest.MonkeyPatch):
        """재설정 메일 발송 실패도 502다 — 조용히 성공한 척하지 않는다."""
        from cii_platform.api.routes import auth_tokens as module

        email = "resetmail@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            monkeypatch.setattr(module, "get_mailer", _FailingMailer)

            resp = client.post("/api/v1/auth/password-reset/request", json={"email": email})
            assert resp.status_code == 502, resp.text
        finally:
            await _cleanup(email)

    async def test_token_for_a_deleted_account_is_rejected_generically(self, client):
        """계정이 사라진 뒤의 토큰도 **같은 문구**로 거부한다.

        구분하면 「그 계정은 지워졌다」가 밖에서 확인된다.

        ⚠️ **어느 갈래로 거부되는지는 이 검사가 규정하지 않는다.** `user_token`의 FK가
        `ON DELETE CASCADE`(`fk_user_token_user`)라 사용자를 지우면 토큰 행도 함께
        사라지고, 그래서 `consume_token`이 먼저 `TokenError`를 낸다 — 라우트의
        「토큰은 유효한데 사용자가 없다」 분기(`auth_tokens.py:168-169`·`232-233`)는
        **API로 도달할 수 없는 방어 코드**다. 그 4문장이 커버리지에 남는 이유이며,
        도달시키려면 `session.get`을 갈아 끼워야 하는데 그것은 **구현을 검사하는 것이지
        동작을 검사하는 것이 아니다.** 여기서 지키는 것은 **밖에서 보이는 계약**이다.
        """
        from cii_platform.db.session import get_sessionmaker
        from cii_platform.services.auth_token import issue_token as issue

        email = "gone@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            user_id = await _user_id(email)
            async with get_sessionmaker()() as s:
                raw = await issue(s, user_id=user_id, purpose=PURPOSE_PASSWORD_RESET)
                await s.commit()

            # 행을 지운다 — soft delete가 아니라 물리 삭제여야 `session.get`이 None이다.
            async with get_sessionmaker()() as s:
                await s.execute(text("DELETE FROM user_session WHERE user_id = :i"), {"i": user_id})
                await s.execute(text("DELETE FROM app_user WHERE id = :i"), {"i": user_id})
                await s.commit()

            resp = client.post(
                "/api/v1/auth/password-reset/confirm",
                json={"token": raw, "password": NEW_PASSWORD},
            )
            assert resp.status_code == 400, resp.text
            assert resp.json()["error"]["message"] == TOKEN_INVALID_MESSAGE
        finally:
            await _cleanup(email)


# ─────────────────────────────────────────────────────────────────────────────
# 메일 실패의 원인이 로그에 남는다 (#819)
#
# 백엔드(`mail/backends.py`)는 SMTP 예외를 `MailDeliveryError(..., cause=exc) from exc`로
# 감싸 원인을 보존하는데, **소비자 세 곳이 전부 버리고 있었다** — 두 곳은 로그 0줄,
# 한 곳은 `warning`이라 `__cause__`가 빠졌다. SMTP 비밀번호가 만료되면 모든 재설정
# 요청이 502를 내는데 `535`가 어디에도 남지 않는다.
# ─────────────────────────────────────────────────────────────────────────────


class _SmtpAuthError(Exception):
    """SMTP 인증 실패를 흉내 낸다. 로그에 **이 이름과 문구**가 남아야 한다."""


_CAUSE_TEXT = "535 5.7.8 authentication credentials invalid"


class _CausedFailingMailer:
    """실제 백엔드처럼 원인을 달아 던지는 메일러."""

    async def send(self, _message) -> None:
        try:
            raise _SmtpAuthError(_CAUSE_TEXT)
        except _SmtpAuthError as exc:
            raise MailDeliveryError("메일을 보내지 못했습니다: smtp:587", cause=exc) from exc


def _cause_logged(caplog: pytest.LogCaptureFixture, logger: str) -> bool:
    """그 로거의 레코드 중 **원인 예외까지** 담은 것이 있는가.

    메시지 문자열이 아니라 `exc_info`의 `__cause__`를 본다 — 「실패했다」 한 줄은 종전
    `warning`도 남겼다. 빠졌던 것은 **왜**다.
    """
    for record in caplog.records:
        if record.name != logger or not record.exc_info:
            continue
        cause = record.exc_info[1].__cause__
        if isinstance(cause, _SmtpAuthError) and _CAUSE_TEXT in str(cause):
            return True
    return False


class TestMailFailureCauseIsLogged:
    async def test_verification_resend(self, client, monkeypatch, caplog):
        from cii_platform.api.routes import auth_tokens as module

        email = "cause-verify@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            monkeypatch.setattr(module, "get_mailer", _CausedFailingMailer)
            caplog.set_level("ERROR", logger=module.__name__)

            resp = client.post("/api/v1/auth/verify-email/request", json={"email": email})

            assert resp.status_code == 502, resp.text
            assert _cause_logged(caplog, module.__name__)
        finally:
            await _cleanup(email)

    async def test_password_reset(self, client, monkeypatch, caplog):
        from cii_platform.api.routes import auth_tokens as module

        email = "cause-reset@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
            monkeypatch.setattr(module, "get_mailer", _CausedFailingMailer)
            caplog.set_level("ERROR", logger=module.__name__)

            resp = client.post("/api/v1/auth/password-reset/request", json={"email": email})

            assert resp.status_code == 502, resp.text
            assert _cause_logged(caplog, module.__name__)
        finally:
            await _cleanup(email)

    async def test_signup(self, client, monkeypatch, caplog):
        """가입은 메일이 실패해도 201이다 — 그래서 로그가 **유일한** 흔적이다."""
        from cii_platform.api.routes import auth as module

        email = "cause-signup@example.com"
        try:
            monkeypatch.setattr(module, "get_mailer", _CausedFailingMailer)
            caplog.set_level("ERROR", logger=module.__name__)

            resp = client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})

            assert resp.status_code == 201, resp.text
            assert _cause_logged(caplog, module.__name__)
        finally:
            await _cleanup(email)


# ─────────────────────────────────────────────────────────────────────────────
# 응답 계약 — 토큰 경로 네 개의 필드 집합 (#753)
#
# `test_response_contract_db.py`의 누락 감지가 이 테스트를 이름으로 가리킨다.
# ─────────────────────────────────────────────────────────────────────────────


def _flatten(value, prefix: str = "") -> set[str]:
    """`test_response_contract_db.flatten`과 같은 규칙 — 테스트 파일끼리 import하지 않는다."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for name, child in value.items():
            path = f"{prefix}{name}"
            keys.add(path)
            keys |= _flatten(child, f"{path}.")
    elif isinstance(value, list):
        for item in value:
            keys |= _flatten(item, f"{prefix[:-1]}[].")
    return keys


#: 네 경로가 같은 모양이다. 요청 두 경로는 **가입 여부와 무관하게 같은 문구**를 내므로
#: 모양이 갈리면 그 차이로 가입 여부가 드러난다.
MESSAGE_CONTRACT = frozenset({"data", "data.message", "meta", "meta.request_id", "meta.timestamp"})


class TestTokenRouteContract:
    async def test_token_routes_match_the_contract(self, client):
        from cii_platform.db.session import get_sessionmaker
        from cii_platform.services.auth_token import issue_token as issue

        email = "contract-token@example.com"
        try:
            client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})

            requests = ("/api/v1/auth/verify-email/request", "/api/v1/auth/password-reset/request")
            for path in requests:
                resp = client.post(path, json={"email": email})
                assert resp.status_code == 200, f"{path}: {resp.text}"
                assert _flatten(resp.json()) == MESSAGE_CONTRACT, path

            user_id = await _user_id(email)
            async with get_sessionmaker()() as s:
                verify = await issue(s, user_id=user_id, purpose=PURPOSE_EMAIL_VERIFY)
                reset = await issue(s, user_id=user_id, purpose=PURPOSE_PASSWORD_RESET)
                await s.commit()

            confirmed = client.post("/api/v1/auth/verify-email/confirm", json={"token": verify})
            assert confirmed.status_code == 200, confirmed.text
            assert _flatten(confirmed.json()) == MESSAGE_CONTRACT

            done = client.post(
                "/api/v1/auth/password-reset/confirm",
                json={"token": reset, "password": NEW_PASSWORD},
            )
            assert done.status_code == 200, done.text
            assert _flatten(done.json()) == MESSAGE_CONTRACT
        finally:
            await _cleanup(email)
