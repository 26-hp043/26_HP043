"""요청 컨텍스트 미들웨어 (#49).

모든 요청에 대해 추적용 ``request_id``(UUID4)와 요청 수신 시각 ``timestamp``(응답
``meta``에 사용)를 생성해 ``request.state``에 주입한다. 값은 ``call_next`` 이전,
즉 요청 수신 시점에 만들어진다. :mod:`cii_platform.api.error_handlers`가 오류 응답의
``meta``(API_SPEC §1.3.2)를 채울 때 이 값을 읽는다.

범위(#49): ``request.state`` 주입까지만 담당한다. 응답 헤더(``X-Request-ID`` 등)는
API_SPEC에 근거가 없어 추가하지 않는다. Pydantic 검증 오류/일반 예외 핸들러는 #116,
config 경고는 #118이 별도로 다룬다.

## 접근 로그 (#827 ⑵ · 구조화 로그)

같은 자리에서 접근 요약 한 줄을 남긴다 — **쿼리스트링 없이 path만**. uvicorn 기본
접근 로그는 쿼리스트링을 남겨 ``verify-email?token=…``이 로그로 새는 결함이 있었다
(#827 실측). 5xx는 ERROR, 나머지는 INFO.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.log_config import ACCESS_LOGGER

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

_access_log = logging.getLogger(ACCESS_LOGGER)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """요청마다 ``request_id``·``timestamp``를 ``request.state``에 주입한다."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = str(uuid4())
        request.state.timestamp = iso_utc_now()
        started = time.perf_counter()

        def _log_access(status: int) -> None:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            # 요약만 남긴다 — 본문·쿼리스트링은 절대 로그에 들어가지 않는다(log_config 참조).
            _access_log.log(
                logging.ERROR if status >= 500 else logging.INFO,
                "%s %s → %s",
                request.method,
                request.url.path,
                status,
                extra={
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": duration_ms,
                    "client": request.client.host if request.client else None,
                },
            )

        try:
            response = await call_next(request)
        except Exception:
            # 처리되지 않은 예외는 **최외곽**(ServerErrorMiddleware)에서 500 응답으로
            # 바뀐다 — Starlette의 Exception 핸들러는 사용자 미들웨어 바깥에 있다.
            # 여기서 올리며 접근 한 줄을 남기지 않으면 500에 접근 기록이 없다(#827 ⑵).
            _log_access(500)
            raise
        _log_access(response.status_code)
        return response
