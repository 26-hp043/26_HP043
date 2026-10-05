"""인증 경로가 같은 대상을 같은 조건으로 다루는지 — HTTP 응답과 DB로 본다 (#2109).

세 곳이 서로 다른 조건을 쓰고 있었다.

1. **탈퇴한 계정의 토큰 확정** — 발급 경로와 세션 검증은 활성 계정만 보는데 확정 경로는
   PK로 그냥 읽었다. 재설정 메일을 받은 뒤 탈퇴한 계정의 링크가 200으로 확정돼 **탈퇴한
   계정의 비밀번호가 바뀌었다.**
2. **예약 주소** — 둘러보기·개발 스텁이 고정 PK로 쓰는 이메일을 가입이 막지 않아, 누가
   먼저 가입하면 그 경로가 500이 됐다.
3. **가입 표시 이름** — ``PATCH /auth/me``는 공백을 떼고 빈 값을 ``null``로 접는데 가입은
   받은 값을 그대로 저장했다.

``app_fresh_engine``(NullPool) + 커밋 기반이다 — `conn` fixture는 TestClient의 포털 루프와
연결을 공유해 쓸 수 없다(`test_tour_login_db.py`와 같은 이유).

케이스: (`TEST_PLAN §14.5` 정의 없음 — #2109의 회귀 검사다)
"""

from __future__ import annotations

import pytest
from conftest import insert_returning_id
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.api.routes.auth import _normalize_email
from cii_platform.api.routes.auth_dev import router as auth_dev_router
from cii_platform.api.routes.auth_tokens import TOKEN_INVALID_MESSAGE
from cii_platform.auth import tour_gate
from cii_platform.auth.reserved_emails import (
    DEV_STUB_EMAIL,
    RESERVED_EMAILS,
    TOUR_EMAIL,
    is_reserved_email,
)
from cii_platform.auth.session import SESSION_COOKIE_NAME
from cii_platform.auth.signup_gate import REJECTED_MESSAGE as SIGNUP_REJECTED_MESSAGE
from cii_platform.db.models.user_token import PURPOSE_EMAIL_VERIFY, PURPOSE_PASSWORD_RESET
from cii_platform.services.auth_token import issue_token

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "brand-new-passphrase"
_TOUR_CODE = "harbour-tour-9x"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


def _maker():
    from cii_platform.db.session import get_sessionmaker

    return get_sessionmaker()()


async def _cleanup(*emails: str) -> None:
    async with _maker() as s:
        for email in emails:
            owner = "(SELECT id FROM app_user WHERE email = :e)"
            await s.execute(text(f"DELETE FROM user_token WHERE user_id IN {owner}"), {"e": email})
            await s.execute(
                text(f"DELETE FROM user_session WHERE user_id IN {owner}"), {"e": email}
            )
            await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


async def _scalar(sql: str, email: str):
    async with _maker() as s:
        return (await s.execute(text(sql), {"e": email})).scalar_one()


async def _user_count(email: str) -> int:
    return await _scalar("SELECT COUNT(*) FROM app_user WHERE email = :e", email)


async def _unused_token_count(email: str) -> int:
    return await _scalar(
        "SELECT COUNT(*) FROM user_token WHERE used_at IS NULL "
        "AND user_id IN (SELECT id FROM app_user WHERE email = :e)",
        email,
    )


async def _issue(email: str, purpose: str) -> str:
    """토큰 원문을 얻는다 — 메일을 보내지 않고 서비스로 직접 발급한다."""
    async with _maker() as s:
        user_id = (
            await s.execute(text("SELECT id FROM app_user WHERE email = :e"), {"e": email})
        ).scalar_one()
        raw = await issue_token(s, user_id=user_id, purpose=purpose)
        await s.commit()
    return raw


async def _soft_delete(email: str) -> None:
    """``is_deleted``만 세운다 — **토큰은 살려 둔다.**

    탈퇴 라우트는 토큰도 함께 무효화하므로, 그 경로로는 확정 쪽의 활성 계정 판정이
    혼자 막는지 볼 수 없다(토큰이 먼저 죽는다). 두 방어를 따로 본다.
    """
    async with _maker() as s:
        await s.execute(text("UPDATE app_user SET is_deleted = 1 WHERE email = :e"), {"e": email})
        await s.commit()


def _signup(client: TestClient, email: str, **extra):
    return client.post(
        f"{API_V1_PREFIX}/auth/signup", json={"email": email, "password": PASSWORD, **extra}
    )


def _withdraw(client: TestClient) -> None:
    resp = client.delete(
        f"{API_V1_PREFIX}/auth/me", headers={"X-CSRF-Token": client.cookies["csrf"]}
    )
    assert resp.status_code == 204, resp.text


def _reset_confirm(client: TestClient, token: str):
    return client.post(
        f"{API_V1_PREFIX}/auth/password-reset/confirm",
        json={"token": token, "password": NEW_PASSWORD},
    )


def _verify_confirm(client: TestClient, token: str):
    return client.post(f"{API_V1_PREFIX}/auth/verify-email/confirm", json={"token": token})


def _error_of(resp) -> tuple[int, dict]:
    """상태 코드와 `error` 객체 — `meta`(요청 ID·시각)는 요청마다 달라 뺀다."""
    return resp.status_code, resp.json()["error"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. 탈퇴한 계정의 토큰 확정
# ─────────────────────────────────────────────────────────────────────────────


class TestTokenConfirmAfterWithdrawal:
    async def test_password_reset_is_rejected_and_the_password_does_not_change(self, client):
        """🔴 종전에는 200이었고 **탈퇴한 계정의 비밀번호가 바뀌었다.**"""
        email = "gone-reset@example.com"
        try:
            assert _signup(client, email).status_code == 201
            raw = await _issue(email, PURPOSE_PASSWORD_RESET)
            before = await _scalar("SELECT password_hash FROM app_user WHERE email = :e", email)
            _withdraw(client)

            resp = _reset_confirm(client, raw)

            assert resp.status_code == 422, resp.text
            assert resp.json()["error"]["message"] == TOKEN_INVALID_MESSAGE
            after = await _scalar("SELECT password_hash FROM app_user WHERE email = :e", email)
            assert after == before, "탈퇴한 계정의 비밀번호가 바뀌었다"
        finally:
            await _cleanup(email)

    async def test_email_verification_is_rejected(self, client):
        email = "gone-verify@example.com"
        try:
            assert _signup(client, email).status_code == 201
            raw = await _issue(email, PURPOSE_EMAIL_VERIFY)
            _withdraw(client)

            resp = _verify_confirm(client, raw)

            assert resp.status_code == 422, resp.text
            assert resp.json()["error"]["message"] == TOKEN_INVALID_MESSAGE
            verified = await _scalar(
                "SELECT email_verified_at FROM app_user WHERE email = :e", email
            )
            assert verified is None, "탈퇴한 계정이 인증 완료로 기록됐다"
        finally:
            await _cleanup(email)

    async def test_withdrawal_invalidates_every_unused_token(self, client):
        """탈퇴가 **용도와 무관하게** 미사용 토큰을 죽인다 — 가입 때 나간 인증 토큰도."""
        email = "gone-tokens@example.com"
        try:
            assert _signup(client, email).status_code == 201
            await _issue(email, PURPOSE_PASSWORD_RESET)
            assert await _unused_token_count(email) == 2, "전제 — 인증·재설정 토큰이 살아 있다"

            _withdraw(client)

            assert await _unused_token_count(email) == 0
        finally:
            await _cleanup(email)

    @pytest.mark.parametrize(
        ("purpose", "confirm"),
        [(PURPOSE_PASSWORD_RESET, _reset_confirm), (PURPOSE_EMAIL_VERIFY, _verify_confirm)],
    )
    async def test_live_token_of_a_withdrawn_account_looks_like_a_forged_one(
        self, client, purpose, confirm
    ):
        """🔴 토큰이 **살아 있어도** 탈퇴한 계정이면 없는 토큰과 같은 응답이다.

        탈퇴 라우트의 토큰 무효화를 거치지 않은 상태를 만든다(`_soft_delete`) — 확정
        쪽의 활성 계정 판정이 **혼자서도** 막는지 본다. 응답이 갈리면 토큰 하나로
        「그 계정은 탈퇴했다」가 확인된다.
        """
        email = f"gone-live-{purpose.lower().replace('_', '-')}@example.com"
        try:
            assert _signup(client, email).status_code == 201
            raw = await _issue(email, purpose)
            before = await _scalar("SELECT password_hash FROM app_user WHERE email = :e", email)
            await _soft_delete(email)

            withdrawn = confirm(client, raw)
            forged = confirm(client, "no-such-token-at-all")

            assert withdrawn.status_code == 422, withdrawn.text
            assert _error_of(withdrawn) == _error_of(forged)
            after = await _scalar("SELECT password_hash FROM app_user WHERE email = :e", email)
            assert after == before
            assert (
                await _scalar("SELECT email_verified_at FROM app_user WHERE email = :e", email)
                is None
            )
        finally:
            await _cleanup(email)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 예약 주소
# ─────────────────────────────────────────────────────────────────────────────


def test_reserved_addresses_are_the_two_stub_accounts():
    """목록은 한 곳이고, 두 스텁 경로가 그 상수를 쓴다."""
    from cii_platform.api.routes import auth, auth_dev

    assert frozenset({TOUR_EMAIL, DEV_STUB_EMAIL}) == RESERVED_EMAILS
    assert auth._TOUR_EMAIL is TOUR_EMAIL
    assert auth_dev._STUB_EMAIL is DEV_STUB_EMAIL
    # 목록은 정규화된 형태로 적는다 — 가입이 정규화한 값과 그대로 비교되게.
    assert all(_normalize_email(item) == item for item in RESERVED_EMAILS)


@pytest.mark.parametrize(
    "variant", ["Tour@BlueLog.Local", "  TOUR@bluelog.local ", "DEV@LocalHost"]
)
def test_reserved_check_runs_after_signup_normalization(variant):
    assert is_reserved_email(_normalize_email(variant))


class TestReservedAddressSignup:
    @pytest.mark.parametrize(
        ("sent", "stored"),
        [
            (TOUR_EMAIL, TOUR_EMAIL),
            ("Tour@BlueLog.Local", TOUR_EMAIL),
            (DEV_STUB_EMAIL, DEV_STUB_EMAIL),
            ("DEV@LocalHost", DEV_STUB_EMAIL),
        ],
    )
    async def test_signup_is_refused_like_a_gate_rejection(self, client, sent, stored):
        """🔴 종전에는 201이었다 — 그 뒤 둘러보기·개발 로그인이 500이 됐다."""
        try:
            resp = _signup(client, sent)

            assert resp.status_code == 422, resp.text
            error = resp.json()["error"]
            assert error["code"] == "VALIDATION_ERROR"
            assert error["message"] == SIGNUP_REJECTED_MESSAGE
            assert await _user_count(stored) == 0, "거부된 가입이 계정을 만들었다"
            assert SESSION_COOKIE_NAME not in client.cookies
        finally:
            await _cleanup(stored)

    async def test_whitespace_padded_address_creates_no_account(self, client):
        """앞뒤 공백은 스키마의 이메일 형식 검사가 먼저 422로 끊는다 — 계정은 생기지 않는다."""
        try:
            resp = _signup(client, f"  {TOUR_EMAIL} ")
            assert resp.status_code == 422, resp.text
            assert await _user_count(TOUR_EMAIL) == 0
        finally:
            await _cleanup(TOUR_EMAIL)


async def _squat(email: str) -> None:
    """예약 주소를 **다른 PK**로 먼저 차지한 상태 — 가입이 막기 전에 만들어진 계정이다."""
    async with _maker() as s:
        await insert_returning_id(
            s,
            "INSERT INTO app_user (email, password_hash) VALUES (:e, 'x') RETURNING id",
            {"e": email},
        )
        await s.commit()


class TestReservedAddressAlreadyTaken:
    async def test_tour_login_answers_conflict_instead_of_500(self, client, monkeypatch):
        """🔴 종전에는 예외를 다시 올려 500이었다."""
        monkeypatch.setenv(tour_gate.ENV_NAME, _TOUR_CODE)
        try:
            await _squat(TOUR_EMAIL)

            resp = client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": _TOUR_CODE})

            assert resp.status_code == 409, resp.text
            error = resp.json()["error"]
            assert error["code"] == "CONFLICT"
            # 내부 값을 싣지 않는다 — 원인은 서버 로그에만 남는다.
            assert TOUR_EMAIL not in resp.text
            assert str(tour_gate.TOUR_USER_ID) not in resp.text
            # 코드가 맞은 사람에게 「링크를 다시 확인」을 시키지 않는다.
            assert error["message"] != tour_gate.REJECTED_MESSAGE
            assert SESSION_COOKIE_NAME not in client.cookies
            assert await _user_count(TOUR_EMAIL) == 1, "선점한 계정을 건드리지 않는다"
        finally:
            await _cleanup(TOUR_EMAIL)

    async def test_dev_login_answers_conflict_instead_of_500(self, migrated_db, app_fresh_engine):
        dev_app = FastAPI()
        dev_app.include_router(auth_dev_router, prefix=API_V1_PREFIX)
        try:
            await _squat(DEV_STUB_EMAIL)
            with TestClient(dev_app, base_url=_BASE, raise_server_exceptions=False) as c:
                resp = c.post(f"{API_V1_PREFIX}/auth/dev-login")

                assert resp.status_code == 409, resp.text
                assert resp.json()["error"]["code"] == "CONFLICT"
                assert DEV_STUB_EMAIL not in resp.text
                assert SESSION_COOKIE_NAME not in c.cookies
        finally:
            await _cleanup(DEV_STUB_EMAIL)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 가입 표시 이름
# ─────────────────────────────────────────────────────────────────────────────


class TestSignupDisplayName:
    @pytest.mark.parametrize(
        ("sent", "stored"),
        [("   ", None), ("", None), ("  홍길동  ", "홍길동"), ("홍 길동", "홍 길동")],
    )
    async def test_signup_normalizes_like_patch_me(self, client, sent, stored):
        """🔴 종전에는 받은 값이 그대로 저장됐다 — 공백뿐인 이름이 `null`과 갈렸다.

        **PATCH와 같은 결과**인지를 함께 본다. 리터럴만 단언하면 두 경로가 다시
        갈려도(한쪽 규칙만 바뀌어도) 잡지 못한다.
        """
        email = "name-normalize@example.com"
        try:
            resp = _signup(client, email, display_name=sent)

            assert resp.status_code == 201, resp.text
            assert resp.json()["data"]["display_name"] == stored
            in_db = await _scalar("SELECT display_name FROM app_user WHERE email = :e", email)
            assert in_db == stored

            patched = client.patch(
                f"{API_V1_PREFIX}/auth/me",
                headers={"X-CSRF-Token": client.cookies["csrf"]},
                json={"display_name": sent},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["data"]["display_name"] == stored
        finally:
            await _cleanup(email)

    async def test_length_limit_counts_the_untrimmed_value_on_both_routes(self, client):
        """상한 100자는 **떼기 전의 값**으로 센다 — 가입과 PATCH가 같다."""
        email = "name-length@example.com"
        padded = "가" * 100 + " "
        try:
            assert _signup(client, email, display_name=padded).status_code == 422
            assert _signup(client, email).status_code == 201
            patched = client.patch(
                f"{API_V1_PREFIX}/auth/me",
                headers={"X-CSRF-Token": client.cookies["csrf"]},
                json={"display_name": padded},
            )
            assert patched.status_code == 422, patched.text
        finally:
            await _cleanup(email)
