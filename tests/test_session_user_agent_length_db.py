"""칸(255자)보다 긴 User-Agent로도 로그인·가입이 성공하는가 — HTTP 응답과 DB 값으로 본다 (#2520).

``user_session.user_agent``는 ``VARCHAR(255)``인데 ``create_session_fields``가 받은 값을
그대로 넣어, 256자 이상이면 INSERT가 실패해 로그인·가입·개발 로그인이 500이었다.
세션을 발급하는 한 곳(``create_session_fields``)에서 자르므로 세 경로를 모두 본다.

``app_fresh_engine``(NullPool) + 커밋 기반이다 — `test_auth_path_consistency_db.py`와 같은 이유.

케이스: (`TEST_PLAN §14.5` 정의 없음 — #2520의 회귀 검사다)
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.api.routes.auth_dev import router as auth_dev_router
from cii_platform.auth.reserved_emails import DEV_STUB_EMAIL
from cii_platform.auth.session import USER_AGENT_MAX_LENGTH, create_session_fields

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE, raise_server_exceptions=False) as c:
        yield c


def _maker():
    from cii_platform.db.session import get_sessionmaker

    return get_sessionmaker()()


async def _cleanup(email: str) -> None:
    async with _maker() as s:
        owner = "(SELECT id FROM app_user WHERE email = :e)"
        await s.execute(text(f"DELETE FROM user_token WHERE user_id IN {owner}"), {"e": email})
        await s.execute(
            text(f"DELETE FROM audit_log WHERE entity_type = 'app_user' AND entity_id IN {owner}"),
            {"e": email},
        )
        await s.execute(text(f"DELETE FROM user_session WHERE user_id IN {owner}"), {"e": email})
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


async def _stored_agents(email: str) -> list[str]:
    async with _maker() as s:
        rows = await s.execute(
            text(
                "SELECT user_agent FROM user_session "
                "WHERE user_id IN (SELECT id FROM app_user WHERE email = :e)"
            ),
            {"e": email},
        )
        return [r[0] for r in rows]


def test_create_session_fields_truncates_to_column_length():
    over = "a" * (USER_AGENT_MAX_LENGTH + 145)
    fields, _, _ = create_session_fields(uuid.uuid4(), user_agent=over)
    assert fields["user_agent"] == over[:USER_AGENT_MAX_LENGTH]
    assert USER_AGENT_MAX_LENGTH == 255


@pytest.mark.parametrize("length", [256, 400])
async def test_signup_and_login_succeed_with_long_user_agent(client, length):
    email = f"ua-{uuid.uuid4().hex[:10]}@example.com"
    ua = {"User-Agent": "a" * length}
    try:
        resp = client.post(
            f"{API_V1_PREFIX}/auth/signup",
            json={"email": email, "password": PASSWORD},
            headers=ua,
        )
        assert resp.status_code == 201, resp.text
        client.cookies.clear()

        resp = client.post(
            f"{API_V1_PREFIX}/auth/login",
            json={"email": email, "password": PASSWORD},
            headers=ua,
        )
        assert resp.status_code == 200, resp.text

        stored = await _stored_agents(email)
        assert len(stored) == 2
        assert all(len(v) <= USER_AGENT_MAX_LENGTH for v in stored)
    finally:
        await _cleanup(email)


async def test_dev_login_succeeds_with_long_user_agent(migrated_db, app_fresh_engine):
    dev_app = FastAPI()
    dev_app.include_router(auth_dev_router, prefix=API_V1_PREFIX)
    try:
        with TestClient(dev_app, base_url=_BASE, raise_server_exceptions=False) as c:
            resp = c.post(f"{API_V1_PREFIX}/auth/dev-login", headers={"User-Agent": "b" * 400})
            assert resp.status_code == 200, resp.text
        stored = await _stored_agents(DEV_STUB_EMAIL)
        assert stored
        assert all(len(v) <= USER_AGENT_MAX_LENGTH for v in stored)
    finally:
        await _cleanup(DEV_STUB_EMAIL)


async def test_dev_login_succeeds_with_long_non_ascii_user_agent(migrated_db, app_fresh_engine):
    """한글 UA — 헤더는 latin-1로, DB로는 UTF-8로 가므로 바이트로 잘라야 한다."""
    dev_app = FastAPI()
    dev_app.include_router(auth_dev_router, prefix=API_V1_PREFIX)
    try:
        with TestClient(dev_app, base_url=_BASE, raise_server_exceptions=False) as c:
            resp = c.post(
                f"{API_V1_PREFIX}/auth/dev-login",
                headers={"User-Agent": ("한" * 300).encode("utf-8")},
            )
            assert resp.status_code == 200, resp.text
        stored = await _stored_agents(DEV_STUB_EMAIL)
        assert stored
        assert all(len(v.encode("utf-8")) <= USER_AGENT_MAX_LENGTH for v in stored)
    finally:
        await _cleanup(DEV_STUB_EMAIL)
