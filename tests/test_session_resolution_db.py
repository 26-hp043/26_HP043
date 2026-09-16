"""세션 검증 한 벌 (#1050) — **DB로 돈다**.

종전에는 쿠키 → 해시 → 세션 → 만료·폐기 → 사용자 조회가 ``auth_middleware``와
``get_current_user``에 **두 벌** 있었고, 미들웨어가 항상 먼저 돌아 의존성 쪽 본문은 운영에서
실행되지 않았다(`#955` 커버리지 하한이 드러냈다). 여기서 잠그는 것은 셋이다.

1. **다섯 분기가 실제 쿠키로 지나간다** — 쿠키 없음 · 세션 없음 · 만료 · 폐기 · 삭제된 계정.
   ``resolve_session``을 직접 부른다(미들웨어 없이) — 운영에서는 미들웨어가 그것을 부른다
2. **미들웨어와 의존성이 같은 문구를 낸다** — 한 벌이라는 것을 응답으로 확인한다
3. **소스에 검증이 한 벌뿐이다** — ``UserSession.session_token_hash ==`` 조회가 `auth/` 아래
   한 곳에만 있다. 두 벌로 되돌아가면 여기서 걸린다

케이스: AT-AUTH-018 (`TEST_PLAN §4.7`)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.requests import Request

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.auth.dependencies import (
    SESSION_EXPIRED_MESSAGE,
    SESSION_NOT_FOUND_MESSAGE,
    USER_NOT_FOUND_MESSAGE,
    AuthenticationError,
    get_current_user,
    resolve_session,
)
from cii_platform.auth.session import SESSION_COOKIE_NAME

_BASE = "https://testserver"
_ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


async def _cleanup(email: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = :e)"
            ),
            {"e": email},
        )
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


async def _sql(statement: str, email: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text(statement), {"e": email})
        await s.commit()


def _signup(client: TestClient, email: str) -> str:
    resp = client.post(f"{API_V1_PREFIX}/auth/signup", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return client.cookies[SESSION_COOKIE_NAME]


def _request(token: str | None) -> Request:
    """미들웨어를 거치지 않은 맨 요청 — `request.state`가 비어 있어 캐시가 없다."""
    headers = [] if token is None else [(b"cookie", f"{SESSION_COOKIE_NAME}={token}".encode())]
    return Request({"type": "http", "method": "GET", "path": "/x", "headers": headers})


async def _resolve_message(token: str | None) -> str:
    with pytest.raises(AuthenticationError) as caught:
        await resolve_session(_request(token))
    return caught.value.message


# --- 1. 다섯 분기 --------------------------------------------------------------------


async def test_resolve_session_walks_all_five_branches_with_real_cookies(client):
    """의존성 본문이 **실제로** 실행된다 — 종전에는 캐시에서 돌아와 한 줄도 돌지 않았다."""
    email = "resolve-branches@example.com"
    try:
        token = _signup(client, email)

        # ⓪ 정상 — 사용자와 세션 행이 캐시된다
        request = _request(token)
        user = await resolve_session(request)
        assert user.email == email
        assert request.state.session_user is user
        assert request.state.session_row.user_id == user.id
        # 같은 요청의 두 번째 호출은 캐시다 — `get_current_user`도 같은 답
        assert await get_current_user(request) is user

        # ① 쿠키 없음
        assert await _resolve_message(None) == "인증이 필요합니다."
        # ② 세션 없음 — 모르는 토큰
        assert await _resolve_message("no-such-token") == SESSION_NOT_FOUND_MESSAGE
        # ③ 만료
        await _sql(
            "UPDATE user_session SET expires_at = DATE_SUB(now(), INTERVAL 1 HOUR) "
            "WHERE user_id IN (SELECT id FROM app_user WHERE email = :e)",
            email,
        )
        assert await _resolve_message(token) == SESSION_EXPIRED_MESSAGE
        # ④ 폐기 — 조회 조건(`revoked_at IS NULL`)에서 걸러져 「없음」과 같은 답이다
        await _sql(
            "UPDATE user_session SET expires_at = DATE_ADD(now(), INTERVAL 1 DAY), "
            "revoked_at = now() "
            "WHERE user_id IN (SELECT id FROM app_user WHERE email = :e)",
            email,
        )
        assert await _resolve_message(token) == SESSION_NOT_FOUND_MESSAGE
        # ⑤ 삭제된 계정 — 세션은 살아 있어도 사용자가 없다
        await _sql(
            "UPDATE user_session SET revoked_at = NULL "
            "WHERE user_id IN (SELECT id FROM app_user WHERE email = :e)",
            email,
        )
        await _sql("UPDATE app_user SET is_deleted = true WHERE email = :e", email)
        assert await _resolve_message(token) == USER_NOT_FOUND_MESSAGE
    finally:
        await _cleanup(email)


# --- 2. 미들웨어 = 의존성 --------------------------------------------------------------


async def test_middleware_answers_with_the_same_messages(client):
    """HTTP로 지나가는 401의 문구가 `resolve_session`의 문구와 같다 — 한 벌의 증거."""
    email = "resolve-middleware@example.com"
    try:
        token = _signup(client, email)

        bare = TestClient(app, base_url=_BASE)
        no_cookie = bare.get(f"{API_V1_PREFIX}/vessels").json()["error"]["message"]
        assert no_cookie == "인증이 필요합니다."

        bare.cookies.set(SESSION_COOKIE_NAME, "no-such-token")
        unknown = bare.get(f"{API_V1_PREFIX}/vessels").json()["error"]["message"]
        assert unknown == SESSION_NOT_FOUND_MESSAGE

        await _sql(
            "UPDATE user_session SET expires_at = DATE_SUB(now(), INTERVAL 1 HOUR) "
            "WHERE user_id IN (SELECT id FROM app_user WHERE email = :e)",
            email,
        )
        resp = client.get(f"{API_V1_PREFIX}/vessels")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"
        assert resp.json()["error"]["message"] == SESSION_EXPIRED_MESSAGE
        assert resp.json()["meta"]["request_id"], "RequestContext가 auth보다 바깥이다"
        del token
    finally:
        await _cleanup(email)


# --- 3. 소스에 한 벌 -------------------------------------------------------------------


def test_session_lookup_exists_in_exactly_one_place():
    """`auth/` 아래에서 세션 토큰 해시로 조회하는 코드는 `resolve_session` 하나다.

    두 벌로 되돌아가면 갈려도 증상이 없다 — 여기서만 걸린다.
    """
    auth_dir = _ROOT / "src" / "cii_platform" / "auth"
    hits = [
        f"{path.name}:{n}"
        for path in sorted(auth_dir.glob("*.py"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "UserSession.session_token_hash ==" in line
    ]
    assert len(hits) == 1 and hits[0].startswith("dependencies.py:"), hits
    middleware = (auth_dir / "middleware.py").read_text(encoding="utf-8")
    assert "resolve_session(" in middleware, "미들웨어가 한 벌을 부르지 않는다"
    assert "hash_token(" not in middleware, "미들웨어가 다시 자기 검증을 갖고 있다"
