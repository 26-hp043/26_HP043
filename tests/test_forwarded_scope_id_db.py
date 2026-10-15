"""``X-Forwarded-For``·서명 헤더의 IPv6 스코프 ID가 ``ip_address`` 칸을 넘기지 않는다 (#2522).

``ipaddress.ip_address("fe80::1%" + 긴 문자열)``이 스코프 ID를 그대로 돌려줘, 감사 로그·세션의
``VARCHAR(45)`` 칸을 넘기면 INSERT가 실패해 500이었다. 두 파싱 자리(XFF · 서명 헤더)가 스코프를
버린 주소를 쓰는지 단위로, 실제 응답과 저장값은 DB로 본다 (`#1889`의 형식 검증은 그대로다).

케이스: (`TEST_PLAN §14.5` 정의 없음 — #2522의 회귀 검사다)
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

import cii_platform.api.rate_limit as rl
from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.api.routes.auth_dev import router as auth_dev_router
from cii_platform.auth.reserved_emails import DEV_STUB_EMAIL

_BASE = "https://testserver"
_SECRET = "s3cret-for-tests"
_LONG_SCOPE = "fe80::1%" + "a" * 60


class _Client:
    host = "127.0.0.1"


class _Req:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.client = _Client()


@pytest.mark.parametrize("scope", ["eth0", "a" * 60, "1"])
def test_scope_id_is_dropped_on_both_parsing_paths(monkeypatch, scope) -> None:
    monkeypatch.setattr(rl, "_PROXY_CLIENT_IP_SECRET", _SECRET)
    monkeypatch.setattr(rl, "_USE_FORWARDED_FOR", True)
    raw = f"fe80::1%{scope}"

    signed = {"x-bluelog-client-ip": raw, "x-bluelog-proxy-secret": _SECRET}
    assert rl.client_ip(_Req(signed)) == "fe80::1"

    monkeypatch.setattr(rl, "_PROXY_CLIENT_IP_SECRET", "")
    assert rl.client_ip(_Req({"x-forwarded-for": f"{raw}, 10.0.0.1"})) == "fe80::1"
    # 스코프가 없는 주소는 그대로다.
    assert rl.client_ip(_Req({"x-forwarded-for": "2001:DB8::1"})) == "2001:db8::1"


def _maker():
    from cii_platform.db.session import get_sessionmaker

    return get_sessionmaker()()


async def _cleanup(email: str) -> None:
    async with _maker() as s:
        owner = "(SELECT id FROM app_user WHERE email = :e)"
        await s.execute(
            text(f"DELETE FROM audit_log WHERE entity_type = 'app_user' AND entity_id IN {owner}"),
            {"e": email},
        )
        await s.execute(text(f"DELETE FROM user_session WHERE user_id IN {owner}"), {"e": email})
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


async def test_dev_login_and_failed_login_do_not_500_on_long_scope_id(
    migrated_db, app_fresh_engine, monkeypatch
):
    monkeypatch.setattr(rl, "_PROXY_CLIENT_IP_SECRET", "")
    monkeypatch.setattr(rl, "_USE_FORWARDED_FOR", True)
    headers = {"X-Forwarded-For": _LONG_SCOPE}
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@example.com"

    dev_app = FastAPI()
    dev_app.include_router(auth_dev_router, prefix=API_V1_PREFIX)
    try:
        with TestClient(dev_app, base_url=_BASE, raise_server_exceptions=False) as c:
            resp = c.post(f"{API_V1_PREFIX}/auth/dev-login", headers=headers)
            assert resp.status_code == 200, resp.text
        async with _maker() as s:
            rows = await s.execute(
                text(
                    "SELECT ip_address FROM user_session WHERE user_id IN "
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": DEV_STUB_EMAIL},
            )
            stored = [r[0] for r in rows]
        assert stored
        # 같은 개발 계정의 앞선 세션(다른 검사가 다른 IP로 만든 것)이 남아 있을 수 있다 — CI에서
        # 실제로 그랬다. 방금 만든 세션이 스코프를 버린 주소인가와 칸 길이만 본다.
        assert "fe80::1" in stored
        assert all(v is None or len(v) <= 45 for v in stored)

        # 로그인 실패 감사 로그도 같은 칸에 적는다.
        with TestClient(app, base_url=_BASE, raise_server_exceptions=False) as c:
            resp = c.post(
                f"{API_V1_PREFIX}/auth/login",
                json={"email": unknown, "password": "wrong-password-123"},
                headers=headers,
            )
            assert resp.status_code != 500, resp.text
            async with _maker() as s:
                rows = await s.execute(
                    text("SELECT ip_address FROM audit_log WHERE ip_address LIKE 'fe80::1%'")
                )
                assert all(len(r[0]) <= 45 for r in rows)
    finally:
        await _cleanup(DEV_STUB_EMAIL)
