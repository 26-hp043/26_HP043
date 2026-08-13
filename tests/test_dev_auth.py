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


def _dev_login_app(conn):
    """dev-login 라우트만 붙이고 get_session을 테스트 커넥션으로 override한 app."""
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.api.routes.auth_dev import router as auth_dev_router
    from cii_platform.db.session import get_session

    async def override_session():
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = override_session
    app.include_router(auth_dev_router, prefix="/api/v1")
    return app


async def test_dev_login_first_boot_creates_user_and_issues_cookie(conn):
    """첫 기동 — 사용자 행을 만들고 세션 쿠키를 발급한다 (#308)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from cii_platform.api.routes.auth_dev import _STUB_USER_ID
    from cii_platform.auth.session import SESSION_COOKIE_NAME

    app = _dev_login_app(conn)
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/dev-login")
        assert resp.status_code == 200
        assert SESSION_COOKIE_NAME in client.cookies

    row = await conn.execute(
        text("SELECT id FROM app_user WHERE id = :id"),
        {"id": str(_STUB_USER_ID)},
    )
    assert row.scalar_one() == _STUB_USER_ID


async def test_dev_login_restart_finds_existing_user(conn):
    """재기동 시나리오 — 이전 기동이 만든 행이 있으면 조회 경로로 200 (#308).

    고정 UUID 이전에는 재기동마다 PK가 달라져 INSERT를 시도 → ``google_sub``
    UNIQUE 위반 → 500이었다.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from cii_platform.api.routes.auth_dev import (
        _STUB_GOOGLE_SUB,
        _STUB_USER_ID,
    )
    from cii_platform.auth.session import SESSION_COOKIE_NAME

    # 이전 기동이 고정 UUID로 만든 행이 이미 있다.
    # (test_auth_wiring.py가 커밋한 스텁 사용자가 잔여할 경우를 대비해 먼저 정리한다.)
    await conn.execute(
        text("DELETE FROM user_session WHERE user_id = :id"),
        {"id": str(_STUB_USER_ID)},
    )
    await conn.execute(
        text("DELETE FROM app_user WHERE id = :id"),
        {"id": str(_STUB_USER_ID)},
    )
    await conn.execute(
        text("INSERT INTO app_user (id, google_sub, email) VALUES (:id, :sub, 'dev@localhost')"),
        {"id": str(_STUB_USER_ID), "sub": _STUB_GOOGLE_SUB},
    )

    app = _dev_login_app(conn)
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/dev-login")
        assert resp.status_code == 200
        assert SESSION_COOKIE_NAME in client.cookies

    # last_login_at이 채워진다 (#317 연계).
    row = await conn.execute(
        text("SELECT last_login_at FROM app_user WHERE id = :id"),
        {"id": str(_STUB_USER_ID)},
    )
    assert row.scalar_one() is not None
