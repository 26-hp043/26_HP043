"""개발 환경 스텁 인증 테스트 (#276).
케이스: AT-AUTH-013 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

from cii_platform.api.routes.auth_dev import should_register_dev_auth


def test_should_register_dev_returns_true_in_development():
    """APP_ENV=development → True (#276).

    ``config._ENV``를 갈아 끼운다 — `#810`부터 이 함수가 자기 값을 들고 있지 않고
    ``config.should_expose_dev_auth()``에 위임하기 때문이다. 종전에는
    ``auth_dev._ENV``를 갈아야 했고, **그 이름이 존재한다는 것 자체가** 판정이
    두 곳이라는 뜻이었다.
    """
    import cii_platform.config as config

    original = config._ENV
    config._ENV = "development"
    try:
        assert should_register_dev_auth() is True
    finally:
        config._ENV = original


def test_should_register_dev_returns_false_in_production():
    """APP_ENV=production → False (#276)."""
    import cii_platform.config as config

    original = config._ENV
    config._ENV = "production"
    try:
        assert should_register_dev_auth() is False
    finally:
        config._ENV = original


def test_dev_auth_does_not_hold_its_own_copy_of_app_env():
    """``routes/auth_dev.py``가 ``APP_ENV``를 따로 들고 있지 않다 (#810).

    종전 구현은 ``from cii_platform.config import _ENV``로 **import 시점에 값을
    복사**했다. 그러면 ``config._ENV``만 바꿔도 이 함수의 답이 바뀌지 않는다 —
    두 판정이 갈릴 수 있다는 뜻이고, 갈리면 dev-login이 401이 아니라 **404**가 되어
    「여기에 무언가 있다」는 신호가 남는다(`#276`·`#593`).

    이 테스트는 위임을 되돌리면 즉시 실패한다.
    """
    import cii_platform.api.routes.auth_dev as auth_dev
    import cii_platform.config as config

    assert not hasattr(auth_dev, "_ENV"), (
        "auth_dev가 APP_ENV 사본을 갖고 있다 — config의 판정과 갈릴 수 있다 (#810)"
    )

    original = config._ENV
    try:
        config._ENV = "production"
        assert should_register_dev_auth() is False
        config._ENV = "development"
        assert should_register_dev_auth() is True
    finally:
        config._ENV = original


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
        _STUB_EMAIL,
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
            text("SELECT id FROM app_user WHERE email = :email"),
            {"email": _STUB_EMAIL},
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

    고정 UUID 이전에는 재기동마다 PK가 달라져 INSERT를 시도 → ``email``
    UNIQUE 위반 → 500이었다. 재기동 = 별도 커밋이므로 행을 실제 커밋으로 심는다.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from cii_platform.api.routes.auth_dev import (
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
                "INSERT INTO app_user (id, email, password_hash) VALUES (:id, 'dev@localhost', 'x')"
            ),
            {"id": str(_STUB_USER_ID)},
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
