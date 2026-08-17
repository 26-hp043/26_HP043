"""인증 라우트(signup·login·me) 계약 테스트 (#414) — **DB로 돈다**.

## 종전과 달라진 점

`#274` 시절 이 파일은 구글 OIDC 흐름을 대역(``FakeAuthSession``)으로 검증했다.
자체 ID/PW 인증으로 바뀌면서 **실제 DB를 쓴다** — 이메일 UNIQUE 제약과 소문자
정규화가 이 기능의 핵심이라 대역으로는 검증되지 않기 때문이다.

## 이 파일이 잡는 것

- **계정 존재 여부 비노출** — 없는 이메일과 틀린 비밀번호가 같은 응답을 낸다
- **회원가입 중복은 알린다** — 위와 반대 방향의 **의도된 비대칭** (`PRD §6.3`)
- 이메일 소문자 정규화
- 비밀번호 정책 위반 거부
- 응답에 비밀번호 해시가 실리지 않는 것

케이스: AT-AUTH-001 · AT-AUTH-002 · AT-AUTH-003 · AT-AUTH-004 · AT-AUTH-005 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.api.routes.auth import EMAIL_TAKEN_MESSAGE, LOGIN_FAILED_MESSAGE

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    """실제 앱 + 실제 DB."""
    with TestClient(app, base_url=_BASE) as c:
        yield c


async def _cleanup(emails: list[str]) -> None:
    """테스트가 만든 계정을 지운다. 세션은 FK CASCADE지만 명시적으로 지운다."""
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        for email in emails:
            await s.execute(
                text(
                    "DELETE FROM user_session WHERE user_id IN "
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": email},
            )
            await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


class TestSignup:
    async def test_signup_creates_account_and_issues_session(self, client):
        try:
            resp = client.post(
                "/api/v1/auth/signup",
                json={"email": "skipper@example.com", "password": PASSWORD},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()["data"]
            assert body["email"] == "skipper@example.com"
            # 가입 즉시 로그인 상태가 된다 — 이메일 인증 전에도 이용을 허용한다.
            assert "sid" in resp.cookies
            assert "csrf" in resp.cookies
        finally:
            await _cleanup(["skipper@example.com"])

    async def test_email_is_lowercased(self, client):
        """대소문자가 다른 같은 주소를 다른 계정으로 두지 않는다."""
        try:
            resp = client.post(
                "/api/v1/auth/signup",
                json={"email": "Skipper@Example.COM", "password": PASSWORD},
            )
            assert resp.status_code == 201, resp.text
            assert resp.json()["data"]["email"] == "skipper@example.com"
        finally:
            await _cleanup(["skipper@example.com"])

    async def test_duplicate_email_is_reported(self, client):
        """**중복은 알린다** — 감추면 사용자가 가입 성공으로 오해한다 (`PRD §6.3`)."""
        try:
            first = client.post(
                "/api/v1/auth/signup",
                json={"email": "dup@example.com", "password": PASSWORD},
            )
            assert first.status_code == 201
            client.cookies.clear()

            second = client.post(
                "/api/v1/auth/signup",
                json={"email": "dup@example.com", "password": PASSWORD},
            )
            assert second.status_code == 409
            assert second.json()["error"]["message"] == EMAIL_TAKEN_MESSAGE
        finally:
            await _cleanup(["dup@example.com"])

    def test_short_password_is_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/signup", json={"email": "x@example.com", "password": "short"}
        )
        assert resp.status_code == 422
        assert "10자" in resp.json()["error"]["message"]

    def test_malformed_email_is_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/signup", json={"email": "not-an-email", "password": PASSWORD}
        )
        assert resp.status_code == 422

    async def test_response_never_carries_the_hash(self, client):
        """응답 본문에 비밀번호 관련 값이 실리면 안 된다."""
        try:
            resp = client.post(
                "/api/v1/auth/signup",
                json={"email": "nohash@example.com", "password": PASSWORD},
            )
            assert "password" not in resp.text.lower()
            assert "argon2" not in resp.text.lower()
        finally:
            await _cleanup(["nohash@example.com"])


class TestLogin:
    async def test_login_succeeds_and_issues_session(self, client):
        try:
            client.post(
                "/api/v1/auth/signup",
                json={"email": "login@example.com", "password": PASSWORD},
            )
            client.cookies.clear()

            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "login@example.com", "password": PASSWORD},
            )
            assert resp.status_code == 200, resp.text
            assert "sid" in resp.cookies
        finally:
            await _cleanup(["login@example.com"])

    async def test_wrong_password_and_unknown_email_are_indistinguishable(self, client):
        """**이 파일에서 가장 중요한 검증이다.**

        「없는 이메일입니다」와 「비밀번호가 틀렸습니다」를 구분해 내면 **가입자
        목록을 캐낼 수 있다** (`API_SPEC §1.2`).
        """
        try:
            client.post(
                "/api/v1/auth/signup",
                json={"email": "secret@example.com", "password": PASSWORD},
            )
            client.cookies.clear()

            wrong_password = client.post(
                "/api/v1/auth/login",
                json={"email": "secret@example.com", "password": "totally-wrong-pw"},
            )
            unknown_email = client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "totally-wrong-pw"},
            )

            assert wrong_password.status_code == 401
            assert unknown_email.status_code == 401
            assert (
                wrong_password.json()["error"]["message"]
                == unknown_email.json()["error"]["message"]
                == LOGIN_FAILED_MESSAGE
            )
            assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]
        finally:
            await _cleanup(["secret@example.com"])

    async def test_login_is_case_insensitive_on_email(self, client):
        try:
            client.post(
                "/api/v1/auth/signup",
                json={"email": "case@example.com", "password": PASSWORD},
            )
            client.cookies.clear()

            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "CASE@Example.com", "password": PASSWORD},
            )
            assert resp.status_code == 200, resp.text
        finally:
            await _cleanup(["case@example.com"])

    def test_login_is_a_public_path(self, client):
        """로그인은 공개 경로다 — 미들웨어가 막으면 인증 자체를 할 수 없다."""
        client.cookies.clear()
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": PASSWORD},
        )
        # 인증 실패(401)이지 「인증이 필요합니다」(미들웨어 차단)가 아니다.
        assert resp.json()["error"]["message"] == LOGIN_FAILED_MESSAGE


class TestMe:
    async def test_me_returns_current_user_without_hash(self, client):
        try:
            client.post(
                "/api/v1/auth/signup",
                json={"email": "me@example.com", "password": PASSWORD},
            )
            resp = client.get("/api/v1/auth/me")
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            assert body["email"] == "me@example.com"
            assert "password_hash" not in body
            # 미인증 상태를 그대로 노출한다 — 화면이 배너를 띄울 근거다.
            assert body["email_verified_at"] is None
        finally:
            await _cleanup(["me@example.com"])

    def test_me_without_session_is_401(self, client):
        client.cookies.clear()
        assert client.get("/api/v1/auth/me").status_code == 401


class TestEnvExample:
    def test_env_example_documents_mail_settings_without_real_values(self):
        """메일 설정이 문서화돼 있고 실제 자격증명은 커밋되지 않아야 한다."""
        content = (_PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "MAIL_BACKEND" in content
        assert "SMTP_HOST" in content

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(("SMTP_PASSWORD=", "SMTP_USER=")):
                pytest.fail(f"실제 자격 증명이 .env.example에 커밋됨: {stripped}")

    def test_env_example_no_longer_mentions_google_oidc(self):
        """`#414`에서 구글 OIDC를 제거했으므로 예시에도 남아 있으면 안 된다."""
        content = (_PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "GOOGLE_CLIENT_ID" not in content
        assert "OIDC_REDIRECT_URI" not in content
