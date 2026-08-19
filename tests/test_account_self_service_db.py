"""계정 관리 — 비밀번호 변경 · 표시 이름 변경 · 탈퇴 (#506) — **DB로 돈다**.

인증은 가입에서 로그인까지만 있었고 **로그인한 사용자가 자기 계정을 관리하는 경로가
하나도 없었다.** 비밀번호를 바꾸려면 로그아웃하고 「비밀번호를 잊었어요」로 메일을
받는 수밖에 없었는데, 개발 환경은 메일이 컨테이너 로그로만 나가므로 **로그를 볼 수
있는 사람만 비밀번호를 바꿀 수 있는 상태**였다.

## 이 파일이 잡는 것

- **현재 비밀번호 확인 없이는 못 바꾼다** — 세션이 탈취됐을 수 있다
- **바꾸면 세션이 전부 끊긴다** — 재설정(`API_SPEC §1.2`)과 같은 규칙. 본인도 포함
- **`email`은 받지 않는다** — 로그인 ID이므로 잘못 바꾸면 계정에 접근할 수 없다
- **「보내지 않음」과 「`null`을 보냄」을 구분한다** — 표시 이름을 지울 수 있어야 한다
- **탈퇴는 행을 지우지 않는다** — 계산·감사 기록이 보존 대상이다(`DB_SCHEMA §7.1`·`§7.3`)
- **탈퇴 후 같은 이메일로 재가입할 수 있다** — 이메일 변경 경로를 두지 않는 대신 여는 길

## detached 객체 함정 (#279 · #506)

미들웨어는 자기 세션으로 사용자를 조회한 뒤 그 세션을 닫는다. 그 객체를 그대로
고치고 라우트 세션으로 commit하면 **아무것도 쓰이지 않는데 200이 나간다.** 아래
테스트들은 **응답이 아니라 DB를 다시 읽어** 확인한다 — 응답만 보면 그 함정을 못 잡는다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 계정 관리는 `#506`에서 신설된 기능이다)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-correct-horse"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


async def _cleanup(emails: list[str]) -> None:
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


async def _fetch_user(email: str) -> dict | None:
    """DB를 직접 읽는다 — 응답만 보면 detached 함정을 못 잡는다."""
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = (
            await s.execute(
                text(
                    "SELECT password_hash, display_name, is_deleted FROM app_user WHERE email = :e"
                ),
                {"e": email},
            )
        ).first()
    return None if row is None else dict(row._mapping)


async def _live_session_count(email: str) -> int:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        return (
            await s.execute(
                text(
                    "SELECT count(*) FROM user_session WHERE revoked_at IS NULL "
                    "AND user_id IN (SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": email},
            )
        ).scalar_one()


def _signup(client: TestClient, email: str) -> None:
    resp = client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text


def _csrf_headers(client: TestClient) -> dict[str, str]:
    """쿠키의 csrf 원문을 헤더로 옮긴다 (`API_SPEC §1.2`)."""
    return {"X-CSRF-Token": client.cookies["csrf"]}


class TestPasswordChange:
    async def test_changes_password_in_the_database(self, client):
        """**DB를 다시 읽어** 해시가 실제로 바뀐 것을 확인한다."""
        email = "pw-change@example.com"
        try:
            _signup(client, email)
            before = await _fetch_user(email)

            resp = client.post(
                "/api/v1/auth/password-change",
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                headers=_csrf_headers(client),
            )
            assert resp.status_code == 200, resp.text

            after = await _fetch_user(email)
            assert after["password_hash"] != before["password_hash"], (
                "해시가 그대로다 — detached 객체를 고치고 commit하면 이렇게 된다 (#279)"
            )
        finally:
            await _cleanup([email])

    async def test_new_password_actually_works(self, client):
        """바뀐 비밀번호로 로그인되고 **옛 비밀번호로는 안 된다.**"""
        email = "pw-works@example.com"
        try:
            _signup(client, email)
            client.post(
                "/api/v1/auth/password-change",
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                headers=_csrf_headers(client),
            )
            client.cookies.clear()

            old = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
            assert old.status_code == 401

            new = client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
            assert new.status_code == 200, new.text
        finally:
            await _cleanup([email])

    async def test_wrong_current_password_is_rejected(self, client):
        """세션이 탈취됐을 수 있으므로 현재 비밀번호를 한 번 더 확인한다."""
        email = "pw-wrong@example.com"
        try:
            _signup(client, email)
            before = await _fetch_user(email)

            resp = client.post(
                "/api/v1/auth/password-change",
                json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
                headers=_csrf_headers(client),
            )
            assert resp.status_code == 401, resp.text

            after = await _fetch_user(email)
            assert after["password_hash"] == before["password_hash"]
        finally:
            await _cleanup([email])

    async def test_current_password_is_checked_before_policy(self, client):
        """현재 비밀번호가 틀리면 **새 비밀번호 규칙을 알려 주지 않는다.**

        순서가 반대면 「현재 비밀번호는 틀렸는데 정책은 알려 주는」 응답이 난다.
        """
        email = "pw-order@example.com"
        try:
            _signup(client, email)
            resp = client.post(
                "/api/v1/auth/password-change",
                json={"current_password": "wrong", "new_password": "short"},
                headers=_csrf_headers(client),
            )
            assert resp.status_code == 401, resp.text
        finally:
            await _cleanup([email])

    async def test_weak_new_password_is_rejected(self, client):
        email = "pw-weak@example.com"
        try:
            _signup(client, email)
            resp = client.post(
                "/api/v1/auth/password-change",
                json={"current_password": PASSWORD, "new_password": "short"},
                headers=_csrf_headers(client),
            )
            assert resp.status_code == 422, resp.text
        finally:
            await _cleanup([email])

    async def test_all_sessions_are_revoked(self, client):
        """**본인 세션도 끊긴다** — 재설정과 같은 규칙 (`API_SPEC §1.2`)."""
        email = "pw-revoke@example.com"
        try:
            _signup(client, email)
            assert await _live_session_count(email) == 1

            resp = client.post(
                "/api/v1/auth/password-change",
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                headers=_csrf_headers(client),
            )
            assert resp.json()["data"]["revoked_sessions"] >= 1
            assert await _live_session_count(email) == 0
        finally:
            await _cleanup([email])

    async def test_requires_authentication(self, client):
        resp = client.post(
            "/api/v1/auth/password-change",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401


class TestUpdateMe:
    async def test_updates_display_name_in_the_database(self, client):
        email = "name-set@example.com"
        try:
            _signup(client, email)
            resp = client.patch(
                "/api/v1/auth/me",
                json={"display_name": "김선장"},
                headers=_csrf_headers(client),
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["display_name"] == "김선장"
            assert (await _fetch_user(email))["display_name"] == "김선장"
        finally:
            await _cleanup([email])

    async def test_explicit_null_clears_the_name(self, client):
        """**「보내지 않음」과 「`null`을 보냄」을 구분한다** (`API_SPEC §3.4`)."""
        email = "name-clear@example.com"
        try:
            _signup(client, email)
            client.patch(
                "/api/v1/auth/me",
                json={"display_name": "김선장"},
                headers=_csrf_headers(client),
            )
            resp = client.patch(
                "/api/v1/auth/me",
                json={"display_name": None},
                headers=_csrf_headers(client),
            )
            assert resp.status_code == 200, resp.text
            assert (await _fetch_user(email))["display_name"] is None
        finally:
            await _cleanup([email])

    async def test_omitted_field_keeps_the_name(self, client):
        """빈 본문은 아무것도 바꾸지 않는다 — 생략은 「변경 없음」이다."""
        email = "name-keep@example.com"
        try:
            _signup(client, email)
            client.patch(
                "/api/v1/auth/me",
                json={"display_name": "김선장"},
                headers=_csrf_headers(client),
            )
            resp = client.patch("/api/v1/auth/me", json={}, headers=_csrf_headers(client))
            assert resp.status_code == 200, resp.text
            assert (await _fetch_user(email))["display_name"] == "김선장"
        finally:
            await _cleanup([email])

    async def test_whitespace_only_name_is_cleared(self, client):
        """공백뿐인 이름은 화면에서 이름 없음과 구분되지 않는다."""
        email = "name-space@example.com"
        try:
            _signup(client, email)
            client.patch(
                "/api/v1/auth/me",
                json={"display_name": "김선장"},
                headers=_csrf_headers(client),
            )
            client.patch(
                "/api/v1/auth/me",
                json={"display_name": "   "},
                headers=_csrf_headers(client),
            )
            assert (await _fetch_user(email))["display_name"] is None
        finally:
            await _cleanup([email])

    async def test_email_change_is_rejected(self, client):
        """**이메일은 받지 않는다** — 로그인 ID라 잘못 바꾸면 계정에 못 들어간다."""
        email = "name-email@example.com"
        try:
            _signup(client, email)
            resp = client.patch(
                "/api/v1/auth/me",
                json={"email": "other@example.com"},
                headers=_csrf_headers(client),
            )
            assert resp.status_code == 422, resp.text
            assert (await _fetch_user(email)) is not None, "이메일이 바뀌면 안 된다"
        finally:
            await _cleanup([email])

    async def test_requires_authentication(self, client):
        resp = client.patch("/api/v1/auth/me", json={"display_name": "x"})
        assert resp.status_code == 401


class TestDeleteMe:
    async def test_soft_deletes_without_removing_the_row(self, client):
        """**행을 지우지 않는다** — 계산·감사 기록이 보존 대상이다."""
        email = "del-soft@example.com"
        try:
            _signup(client, email)
            resp = client.delete("/api/v1/auth/me", headers=_csrf_headers(client))
            assert resp.status_code == 204, resp.text

            row = await _fetch_user(email)
            assert row is not None, "행이 사라졌다 — soft delete여야 한다"
            assert row["is_deleted"] is True
        finally:
            await _cleanup([email])

    async def test_sessions_are_revoked(self, client):
        email = "del-session@example.com"
        try:
            _signup(client, email)
            client.delete("/api/v1/auth/me", headers=_csrf_headers(client))
            assert await _live_session_count(email) == 0
        finally:
            await _cleanup([email])

    async def test_cannot_log_in_after_deletion(self, client):
        email = "del-login@example.com"
        try:
            _signup(client, email)
            client.delete("/api/v1/auth/me", headers=_csrf_headers(client))
            client.cookies.clear()

            resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
            assert resp.status_code == 401
        finally:
            await _cleanup([email])

    async def test_same_email_can_sign_up_again(self, client):
        """**이메일 변경 경로를 두지 않는 대신 여는 길**이다.

        `idx_app_user_email`이 `WHERE is_deleted = false`인 부분 유일 인덱스라
        성립한다(마이그레이션 033). 이 성질이 깨지면 `PRD §6.3`의 고지 문구가
        **거짓말이 된다.**
        """
        email = "del-reuse@example.com"
        try:
            _signup(client, email)
            client.delete("/api/v1/auth/me", headers=_csrf_headers(client))
            client.cookies.clear()

            again = client.post(
                "/api/v1/auth/signup",
                json={"email": email, "password": NEW_PASSWORD},
            )
            assert again.status_code == 201, again.text
        finally:
            await _cleanup([email])

    async def test_requires_authentication(self, client):
        resp = client.delete("/api/v1/auth/me")
        assert resp.status_code == 401
