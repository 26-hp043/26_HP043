"""요청 컨텍스트 미들웨어 (#49).

모든 요청에 대해 추적용 ``request_id``(UUID4)와 요청 수신 시각 ``timestamp``(응답
``meta``에 사용)를 생성해 ``request.state``에 주입한다. 값은 ``call_next`` 이전,
즉 요청 수신 시점에 만들어진다. :mod:`cii_platform.api.error_handlers`가 오류 응답의
``meta``(API_SPEC §1.3.2)를 채울 때 이 값을 읽는다.

범위(#49): ``request.state`` 주입까지만 담당한다. 응답 헤더(``X-Request-ID`` 등)는
API_SPEC에 근거가 없어 추가하지 않는다. Pydantic 검증 오류/일반 예외 핸들러는 #116,
config 경고는 #118이 별도로 다룬다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware

from cii_platform.api.timefmt import iso_utc_now

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """요청마다 ``request_id``·``timestamp``를 ``request.state``에 주입한다."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = str(uuid4())
        request.state.timestamp = iso_utc_now()
        return await call_next(request)
