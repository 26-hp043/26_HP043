"""감사 로그 인증 이벤트 실동작 검증 (#277).

완료 기준을 DB에서 직접 고정한다:

1. dev-login → ``LOGIN_SUCCESS`` 행 — ``user_id`` 채워짐, ``dev_login`` 플래그
2. logout → ``LOGOUT`` 행
3. OIDC state 불일치 → ``LOGIN_FAILURE`` 행 — **자격 증명 값이 details에 없음**

``app_fresh_engine``(NullPool) + 커밋 기반 — TestClient 포털 루프와 fixture 루프의
연결 충돌을 피한다(conftest 참조). audit_log에는 immutable 트리거가 없어(015)
정리 DELETE가 자유롭다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"


async def _fetch_events(session, action: str) -> list:
    rows = await session.execute(
        text(
            "SELECT user_id, details_json, ip_address FROM audit_log "
            'WHERE action = :action ORDER BY "timestamp" DESC'
        ),
        {"action": action},
    )
    return rows.mappings().all()


async def _cleanup() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(text("DELETE FROM audit_log"))
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
        await s.commit()
    await get_engine().dispose()


async def test_dev_login_records_login_success(migrated_db, app_fresh_engine):
    """LOGIN_SUCCESS — user_id 채워짐 + dev_login 플래그 (#277)."""
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200

        from cii_platform.db.session import get_sessionmaker

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as s:
            events = await _fetch_events(s, "LOGIN_SUCCESS")
            assert len(events) == 1
            event = events[0]
            # 완료 기준 — 주체가 기록된다.
            assert event["user_id"]
            assert event["details_json"] == {"dev_login": True}
            assert event["ip_address"]
    finally:
        await _cleanup()


async def test_logout_records_logout_event(migrated_db, app_fresh_engine):
    """LOGOUT — 실제 세션 무효화 시에만 기록 (#277)."""
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            # `#634` — logout도 CSRF를 검증한다. 화면(`auth/session.ts`)이 하는 것과
            # 같이 `csrf` 쿠키 값을 헤더로 옮겨 싣는다.
            csrf = {"X-CSRF-Token": client.cookies["csrf"]}
            assert client.post("/api/v1/auth/logout", headers=csrf).status_code == 204

        from cii_platform.db.session import get_sessionmaker

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as s:
            events = await _fetch_events(s, "LOGOUT")
            assert len(events) == 1
            assert events[0]["user_id"]
    finally:
        await _cleanup()


async def test_login_failure_records_no_credentials(migrated_db, app_fresh_engine):
    """LOGIN_FAILURE — 비밀번호가 로그에 없다 (완료 기준, #277 · #414 개정).

    종전에는 OIDC state 불일치로 실패를 유발했다. 자체 ID/PW 인증으로 바뀌면서
    **틀린 비밀번호**로 유발하며, 확인할 것은 같다 — 요청에 실린 자격 증명이
    감사 행에 나타나면 안 된다.
    """
    try:
        with TestClient(app, base_url=_BASE) as client:
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "super-secret-pw-42"},
            )
        assert resp.status_code == 401

        from cii_platform.db.session import get_sessionmaker

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as s:
            events = await _fetch_events(s, "LOGIN_FAILURE")
            assert len(events) == 1
            event = events[0]
            # 사유는 코드(열거값)만 — 원문 자격 증명 없음.
            assert event["details_json"] == {"reason": "unknown_email"}
            # 주체를 알 수 없으므로 NULL이다.
            assert event["user_id"] is None
            serialized = str(event["details_json"]) + str(event["user_id"] or "")
            assert "super-secret-pw-42" not in serialized
            assert "nobody@example.com" not in serialized
    finally:
        await _cleanup()
