"""개발 환경 스텁 인증 테스트 (#276)."""

from __future__ import annotations

from cii_platform.api.routes.auth_dev import should_register_dev_auth


def test_should_register_dev_returns_true_in_development():
    """APP_ENV=development → True (#276)."""
    import cii_platform.api.routes.auth_dev as mod

    original = mod._ENV
    mod._ENV = "development"
    try:
        assert should_register_dev_auth() is True
    finally:
        mod._ENV = original


def test_should_register_dev_returns_false_in_production():
    """APP_ENV=production → False (#276)."""
    import cii_platform.api.routes.auth_dev as mod

    original = mod._ENV
    mod._ENV = "production"
    try:
        assert should_register_dev_auth() is False
    finally:
        mod._ENV = original


def test_stub_user_id_is_fixed_constant():
    """_STUB_USER_ID가 고정 UUID다 — uuid4()로 되돌리면 재기동 시 500 (#308)."""
    from uuid import UUID

    from cii_platform.api.routes.auth_dev import _STUB_USER_ID

    assert UUID("00000000-0000-4000-8000-000000000deb") == _STUB_USER_ID


# --- #308: dev-login 실제 호출 (DB 필요 — CI에서 실행) -------------------------------
#
# conn fixture 세션을 TestClient 안에서 쓰면 요청의 포털 루프와 fixture 루프가
# 엔진 연결을 공유해 "attached to a different loop"로 실패한다 — app_fresh_engine
# (NullPool) + 커밋 기반으로 검증한다.


async def test_dev_login_first_boot_creates_user_and_issues_cookie(migrated_db, app_fresh_engine):
    """첫 기동 — 사용자 행을 만들고 세션 쿠키를 발급한다 (#308)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from cii_platform.api.routes.auth_dev import (
        _STUB_GOOGLE_SUB,
        _STUB_USER_ID,
    )
    from cii_platform.api.routes.auth_dev import (
        router as auth_dev_router,
    )
    from cii_platform.auth.session import SESSION_COOKIE_NAME
    from cii_platform.db.session import get_sessionmaker

    app = FastAPI()
    app.include_router(auth_dev_router, prefix="/api/v1")
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/dev-login")
        assert resp.status_code == 200, resp.text
        assert SESSION_COOKIE_NAME in client.cookies

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        row = await s.execute(
            text("SELECT id FROM app_user WHERE google_sub = :sub"),
            {"sub": _STUB_GOOGLE_SUB},
        )
        assert row.scalar_one() == _STUB_USER_ID
        await s.execute(
            text("DELETE FROM user_session WHERE user_id = :id"),
            {"id": str(_STUB_USER_ID)},
        )
        await s.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": str(_STUB_USER_ID)})
        await s.commit()


async def test_dev_login_restart_finds_existing_user(migrated_db, app_fresh_engine):
    """재기동 시나리오 — 이전 기동이 만든 행이 있으면 조회 경로로 200 (#308).

    고정 UUID 이전에는 재기동마다 PK가 달라져 INSERT를 시도 → ``google_sub``
    UNIQUE 위반 → 500이었다. 재기동 = 별도 커밋이므로 행을 실제 커밋으로 심는다.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from cii_platform.api.routes.auth_dev import (
        _STUB_GOOGLE_SUB,
        _STUB_USER_ID,
    )
    from cii_platform.api.routes.auth_dev import (
        router as auth_dev_router,
    )
    from cii_platform.auth.session import SESSION_COOKIE_NAME
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(
            text(
                "INSERT INTO app_user (id, google_sub, email) VALUES (:id, :sub, 'dev@localhost')"
            ),
            {"id": str(_STUB_USER_ID), "sub": _STUB_GOOGLE_SUB},
        )
        await s.commit()

    app = FastAPI()
    app.include_router(auth_dev_router, prefix="/api/v1")
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/dev-login")
        assert resp.status_code == 200, resp.text
        assert SESSION_COOKIE_NAME in client.cookies

    async with sessionmaker() as s:
        row = await s.execute(
            text("SELECT last_login_at FROM app_user WHERE id = :id"),
            {"id": str(_STUB_USER_ID)},
        )
        assert row.scalar_one() is not None
        await s.execute(
            text("DELETE FROM user_session WHERE user_id = :id"),
            {"id": str(_STUB_USER_ID)},
        )
        await s.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": str(_STUB_USER_ID)})
        await s.commit()
