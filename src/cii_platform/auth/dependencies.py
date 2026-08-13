"""FastAPI 인증 의존성 — 현재 사용자 주입 + CSRF 검증 (#275).

라우트는 이 모듈만 참조한다 (TECH_SPEC §16 계층 규칙).
``auth/session.py``의 세션 로직과 ``db/repositories``를 경유해 DB에 접근한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy import select

from cii_platform.auth.session import (
    SESSION_COOKIE_NAME,
    is_valid,
    verify_csrf,
)
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.models.user_session import UserSession
from cii_platform.errors import AppError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class AuthenticationError(AppError):
    """세션 없음·만료·무효 (API_SPEC §1.4). HTTP 401."""

    def __init__(self, message: str = "인증이 필요합니다."):
        super().__init__("UNAUTHORIZED", message)


class CsrfError(AppError):
    """CSRF 토큰 누락·불일치 (API_SPEC §1.4). HTTP 403."""

    def __init__(self, message: str = "CSRF 토큰이 올바르지 않습니다."):
        super().__init__("CSRF_ERROR", message)


#: 인증이 필요 없는 경로 (API_SPEC §1.2). dev-login은 세션 발급 자체가 목적이므로
#: 공개 경로에 둔다 (#308).
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/health",
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/callback",
        "/api/v1/auth/dev-login",
        "/auth/login",
        "/auth/callback",
        "/auth/dev-login",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)

#: CSRF 검증이 필요 없는 메서드.
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})


def is_public_path(path: str) -> bool:
    """경로가 인증 예외인지 확인한다 — **명시적 목록만** 쓴다 (#308).

    ``startswith("/auth/")`` 같은 접두사 규칙을 쓰지 않는다: 실제 요청 경로는
    항상 ``/api/v1`` prefix를 달고 나오므로 접두사가 실효 없었고, 향후 auth 하위에
    보호가 필요한 엔드포인트가 추가될 때 실수로 공개될 위험만 남는다.
    """
    return path in PUBLIC_PATHS


async def get_current_user(
    request: Request,
    session: AsyncSession = None,  # Depends로 주입됨 — main.py에서 override
) -> AppUser:
    """현재 인증된 사용자를 반환한다. 미인증 시 ``AuthenticationError``.

    ``request.state.session_user``에 캐시한다 — 같은 요청에서 두 번째 호출은
    DB 조회 없이 캐시된 값을 돌려준다.
    """
    cached = getattr(request.state, "session_user", None)
    if cached is not None:
        return cached

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        raise AuthenticationError()

    from cii_platform.auth.session import hash_token

    token_hash = hash_token(token)
    stmt = select(UserSession).where(
        UserSession.session_token_hash == token_hash,
        UserSession.revoked_at.is_(None),
    )
    result = await session.execute(stmt)
    user_session = result.scalar_one_or_none()

    if user_session is None:
        raise AuthenticationError("세션을 찾을 수 없습니다.")
    if not is_valid(user_session.expires_at, user_session.revoked_at):
        raise AuthenticationError("로그인 세션이 만료되었습니다. 다시 로그인하세요.")

    user_stmt = select(AppUser).where(
        AppUser.id == user_session.user_id,
        AppUser.is_deleted.is_(False),
    )
    user_result = await session.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    if user is None:
        raise AuthenticationError("사용자 계정을 찾을 수 없습니다.")

    request.state.session_user = user
    request.state.session_row = user_session
    return user


def require_csrf(
    request: Request,
) -> None:
    """상태 변경 요청(POST·PATCH·DELETE)에서 CSRF 토큰을 검증한다.

    ``X-CSRF-Token`` 헤더와 세션에 저장된 ``csrf_token_hash``를 비교한다.
    CSRF 토큰 원문은 쿠키로도 전달되지만, **헤더로만** 검증한다 —
    쿠키는 자동으로 전송되므로 공격자가 임의의 값을 넣을 수 있다.
    """
    if request.method in SAFE_METHODS:
        return

    user_session = getattr(request.state, "session_row", None)
    if user_session is None:
        # 인증 미들웨어가 먼저 실행돼야 session_row가 있다. 없으면 인증 실패.
        return

    csrf_header = request.headers.get("x-csrf-token")
    if csrf_header is None:
        raise CsrfError("CSRF 토큰이 누락되었습니다.")
    if not verify_csrf(csrf_header, user_session.csrf_token_hash):
        raise CsrfError("CSRF 토큰이 올바르지 않습니다.")
