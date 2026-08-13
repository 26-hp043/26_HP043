"""인증 라우트(login·callback) 계약 테스트 (#274) — **DB 없이 돈다**.

httpx(구글 토큰 교환)와 id_token 검증을 monkeypatch로 대체하고, 세션 의존성을
``FakeAuthSession``으로 바꿔 **라우트 → 오류 응답 → 쿠키** 전 구간을 실제 HTTP
요청으로 통과시킨다.

이 방식으로 잡는 것: nonce 발급·검증, state 불일치 401, ``meta`` 누락, 사용자
식별이 ``email``이 아닌 ``sub``로 되는지 (완료 기준).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.db.session import get_session

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 로그인 시 쿠키로 내려가는 OIDC 임시 값 이름.
OIDC_COOKIES = ("oidc_state", "oidc_verifier", "oidc_nonce")


class _FakeResult:
    """``execute``가 돌려주는 Result 대역 — scalar_one_or_none만 지원."""

    def __init__(self, value: Any):
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeAuthSession:
    """``AsyncSession`` 대역 — google_sub별 사용자를 메모리에 보관한다.

    라우트가 실행하는 ``select(AppUser).where(google_sub == ...)``의 바인드 파라미터를
    읽어 사용자를 찾는다. 두 번의 콜백에서 같은 ``google_sub``면 같은 객체(같은 id)를
    돌려줘야 완료 기준(이메일이 바뀌어도 같은 ``app_user.id``)이 성립한다.
    """

    def __init__(self) -> None:
        self.users: dict[str, Any] = {}
        self.committed = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        params = stmt.compile().params
        sub = next(v for k, v in params.items() if "google_sub" in k)
        return _FakeResult(self.users.get(sub))

    def add(self, obj: Any) -> None:
        # AppUser만 index에 담고, UserSession(google_sub 없음)은 무시한다.
        sub = getattr(obj, "google_sub", None)
        if sub:
            self.users[sub] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1


@pytest.fixture
def auth_session() -> FakeAuthSession:
    return FakeAuthSession()


@pytest.fixture
def auth_client(
    monkeypatch: pytest.MonkeyPatch,
    auth_session: FakeAuthSession,
) -> Iterator[TestClient]:
    """토큰 교환·id_token 검증을 대역으로 바꾸고 세션을 대체한 클라이언트."""
    from cii_platform.api.routes import auth as auth_routes

    async def fake_exchange(_code: str, _verifier: str) -> dict[str, str]:
        return {"id_token": "fake-id-token"}

    async def fake_verify(_token: str, *, expected_nonce: str | None = None) -> dict[str, Any]:
        return {
            "sub": "google-sub-123",
            "email": "first@example.com",
            "email_verified": True,
            "name": "Test User",
            "nonce": expected_nonce,
        }

    monkeypatch.setattr(auth_routes, "exchange_code", fake_exchange)
    monkeypatch.setattr(auth_routes, "verify_id_token", fake_verify)

    async def override_session():
        yield auth_session

    app.dependency_overrides[get_session] = override_session
    # 302를 따라가면 구글 외부 URL로 재요청되므로(기본 follow_redirects=True) 끈다.
    with TestClient(app, follow_redirects=False) as client:
        yield client
    app.dependency_overrides.clear()


def _login_cookies(client: TestClient) -> dict[str, str]:
    """``/auth/login``을 호출해 쿠키 3종을 뽑는다."""
    resp = client.get("/api/v1/auth/login")
    assert resp.status_code == 302
    return {name: resp.cookies.get(name, "") for name in OIDC_COOKIES}


class TestLogin:
    """GET /auth/login — 302 + state·verifier·nonce 쿠키."""

    def test_login_redirects_to_google_with_cookies(self, auth_client: TestClient):
        cookies = _login_cookies(auth_client)
        for name in OIDC_COOKIES:
            assert cookies[name], f"{name} 쿠키가 없습니다"

    def test_login_nonce_goes_to_auth_url(self, auth_client: TestClient):
        resp = auth_client.get("/api/v1/auth/login")
        location = resp.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        # nonce가 인증 URL에 실려야 콜백에서 대조할 수 있다.
        assert "nonce=" in location
        assert resp.cookies.get("oidc_nonce") in location

    def test_login_rejects_external_redirect_to(self, auth_client: TestClient):
        # 절대 URL redirect_to는 버려진다 — state에 담기지 않는다.
        resp = auth_client.get(
            "/api/v1/auth/login", params={"redirect_to": "https://evil.example.com"}
        )
        location = resp.headers["location"]
        assert "evil.example.com" not in location

    def test_login_allows_internal_redirect_to(self, auth_client: TestClient):
        resp = auth_client.get("/api/v1/auth/login", params={"redirect_to": "/dashboard"})
        location = resp.headers["location"]
        # 내부 경로는 state에 "state:/dashboard" 형태로 실린다.
        assert "/dashboard" in location


class TestCallback:
    """GET /auth/callback — state 검증 · nonce 검증 · 사용자 upsert."""

    def test_callback_requires_code_and_state(self, auth_client: TestClient):
        resp = auth_client.get("/api/v1/auth/callback")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "BAD_REQUEST"
        assert "meta" in resp.json()

    def test_callback_state_mismatch_is_401(self, auth_client: TestClient):
        # 쿠키의 state와 콜백으로 돌아온 state가 다르면 재생으로 보고 거부.
        resp = auth_client.get(
            "/api/v1/auth/callback",
            params={"code": "c", "state": "attacker-state"},
            cookies={"oidc_state": "real-state", "oidc_verifier": "v"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_callback_missing_verifier_is_401(self, auth_client: TestClient):
        resp = auth_client.get(
            "/api/v1/auth/callback",
            params={"code": "c", "state": "state-1"},
            cookies={"oidc_state": "state-1"},
        )
        assert resp.status_code == 401

    def test_callback_success_sets_session_cookies(self, auth_client: TestClient):
        cookies = _login_cookies(auth_client)
        resp = auth_client.get(
            "/api/v1/auth/callback",
            params={"code": "c", "state": cookies["oidc_state"]},
            cookies=cookies,
        )
        assert resp.status_code == 302
        assert resp.cookies.get("sid")
        assert resp.cookies.get("csrf")

    def test_callback_clears_oidc_cookies(self, auth_client: TestClient):
        cookies = _login_cookies(auth_client)
        resp = auth_client.get(
            "/api/v1/auth/callback",
            params={"code": "c", "state": cookies["oidc_state"]},
            cookies=cookies,
        )
        for name in OIDC_COOKIES:
            assert name not in resp.cookies

    def test_callback_identifies_user_by_sub_not_email(
        self, auth_client: TestClient, auth_session: FakeAuthSession
    ):
        """완료 기준 — 이메일이 바뀌어도 같은 ``app_user.id``가 유지된다."""
        from cii_platform.api.routes import auth as auth_routes

        # 첫 로그인: 이메일 first@example.com
        cookies = _login_cookies(auth_client)
        resp = auth_client.get(
            "/api/v1/auth/callback",
            params={"code": "c", "state": cookies["oidc_state"]},
            cookies=cookies,
        )
        assert resp.status_code == 302
        first_user = auth_session.users["google-sub-123"]

        # 두 번째 로그인: 같은 sub, 다른 이메일
        async def fake_verify_changed_email(
            _token: str, *, expected_nonce: str | None = None
        ) -> dict[str, Any]:
            return {
                "sub": "google-sub-123",
                "email": "changed@example.com",
                "email_verified": True,
                "name": "Test User",
                "nonce": expected_nonce,
            }

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(auth_routes, "verify_id_token", fake_verify_changed_email)
        try:
            cookies2 = _login_cookies(auth_client)
            resp2 = auth_client.get(
                "/api/v1/auth/callback",
                params={"code": "c", "state": cookies2["oidc_state"]},
                cookies=cookies2,
            )
            assert resp2.status_code == 302
        finally:
            monkeypatch.undo()

        second_user = auth_session.users["google-sub-123"]
        # 같은 사용자 — id가 유지되고 이메일만 갱신된다.
        assert second_user.id == first_user.id
        assert second_user.email == "changed@example.com"


class TestEnvExample:
    """완료 기준 — .env.example에 자격 증명 항목이 있고 실제 값은 없다."""

    def test_env_example_has_oidc_entries_without_real_values(self):
        text = (_PROJECT_ROOT / ".env.example").read_text()
        assert "GOOGLE_CLIENT_ID" in text
        assert "GOOGLE_CLIENT_SECRET" in text
        # 실제 값(주석 없는 할당)이 없어야 한다.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("GOOGLE_CLIENT_ID=", "GOOGLE_CLIENT_SECRET=")):
                pytest.fail(f"실제 자격 증명이 .env.example에 커밋됨: {stripped}")
