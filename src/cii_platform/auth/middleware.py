"""인증 미들웨어 — 요청마다 세션을 검증하고 request.state에 사용자를 주입한다 (#275).

이 미들웨어는 **인증 게이트** 역할을 한다:
1. 공개 경로(health, auth/*)는 통과
2. 그 외 경로는 세션 쿠키를 검증 → request.state에 사용자·세션을 주입
3. CSRF 검증은 ``require_csrf`` 의존성이 라우트 단에서 수행

**미들웨어 순서** — ``RequestContextMiddleware``보다 **안쪽**에 등록돼야 한다
(request_id가 먼저 채워져야 401 응답의 meta.request_id가 채워지기 때문).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from cii_platform.auth.dependencies import (
    is_public_path,
)
from cii_platform.auth.session import SESSION_COOKIE_NAME, hash_token, is_valid

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response


async def auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """요청마다 세션을 검증한다. 공개 경로는 통과."""
    from sqlalchemy import select

    from cii_platform.db.models.app_user import AppUser
    from cii_platform.db.models.user_session import UserSession
    from cii_platform.db.session import get_sessionmaker

    # 공개 경로는 통과
    if is_public_path(request.url.path):
        return await call_next(request)

    # 세션 쿠키 확인
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        return _unauthorized_response(request, "인증이 필요합니다.")

    token_hash = hash_token(token)

    # DB 조회 — 미들웨어 안에서 직접 세션을 만든다 (의존성 주입이 안 되므로)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        stmt = select(UserSession).where(
            UserSession.session_token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
        result = await db_session.execute(stmt)
        user_session = result.scalar_one_or_none()

        if user_session is None:
            return _unauthorized_response(request, "세션을 찾을 수 없습니다.")

        if not is_valid(user_session.expires_at, user_session.revoked_at):
            return _unauthorized_response(
                request, "로그인 세션이 만료되었습니다. 다시 로그인하세요."
            )

        user_stmt = select(AppUser).where(
            AppUser.id == user_session.user_id,
            AppUser.is_deleted.is_(False),
        )
        user_result = await db_session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if user is None:
            return _unauthorized_response(request, "사용자 계정을 찾을 수 없습니다.")

        # request.state에 캐시 — 라우트 의존성에서 재조회하지 않는다
        request.state.session_user = user
        request.state.session_row = user_session

    return await call_next(request)


def _unauthorized_response(request: Request, message: str) -> Response:
    """401 응답을 API_SPEC §1.3.2 포맷으로 만든다."""
    from starlette.responses import JSONResponse

    from cii_platform.api.timefmt import iso_utc_now

    state = getattr(request, "state", None)
    body = {
        "error": {"code": "UNAUTHORIZED", "message": message},
        "meta": {
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }
    return JSONResponse(status_code=401, content=body)
