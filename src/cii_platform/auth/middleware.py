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
    AuthenticationError,
    is_public_path,
    resolve_session,
)

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response


async def auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """요청마다 세션을 검증한다. 공개 경로는 통과.

    판정은 ``resolve_session`` **한 벌**이다 (#1050). 종전에는 쿠키 → 해시 → 세션 → 만료 →
    사용자 조회가 여기와 ``get_current_user``에 따로 있었고, 이쪽이 항상 먼저 돌아 저쪽은
    운영에서 실행되지 않았다. 갈려도 증상이 없는 중복이라 한 벌로 합쳤다.

    미들웨어는 예외 핸들러 **바깥**에서 돌므로 ``AuthenticationError``를 여기서 잡아
    `API_SPEC §1.3.2` 401 봉투로 바꾼다 — 문구는 예외가 들고 온 것을 그대로 쓴다.
    """
    # 공개 경로는 통과
    if is_public_path(request.url.path):
        return await call_next(request)

    try:
        await resolve_session(request)
    except AuthenticationError as exc:
        return _unauthorized_response(request, exc.message)

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
