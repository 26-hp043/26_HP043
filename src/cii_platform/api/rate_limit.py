"""요청 한도 미들웨어 — IP별 분당 요청 수 제한 (#238).

API_SPEC §13.2가 **분당 300회 / 사용자**를 규정. MVP에는 인증(#104)이 없어 IP 기반으로
적용한다. 인증 도입 시 user_id 기반으로 전환한다 — 그때까지는 X-Forwarded-For 의
첫 값을 클라이언트 IP로 본다(역방향 프록시 뒤의 배포 전제).

구현은 **고정 윈도 in-memory 카운터**다. uvicorn 워커마다 카운터가 따로 생기지만,
이 프로젝트는 #232가 workers=1을 기본으로 삼으므로 MVP에선 유효하다. 멀티 워커·멀티
인스턴스 배포에선 Redis 같은 공유 저장소가 필요하다(#238 후속).

``RATE_LIMIT_PER_MINUTE=0``이면 미들웨어가 통과만 한다 — 테스트 환경이나 한도를
끄고 싶을 때 쓴다.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from cii_platform.errors import RateLimitError

#: API_SPEC §13.2 — 분당 요청 한도 기본값. 환경변수로 override.
#: ``0``이면 비활성(미들웨어가 통과만 한다).
DEFAULT_RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "300"))

_WINDOW_SECONDS = 60.0


def _client_ip(request: Request) -> str:
    """클라이언트 IP — ``X-Forwarded-For`` 첫 값, 없으면 ``client.host``.

    역방향 프록시(nginx · Cloudflare · App Gateway) 뒤의 배포에선 ``X-Forwarded-For``
    가 원 클라이언트를 담는다. uvicorn을 ``--proxy-headers``로 띄우는 것이 전제.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # 콤마로 연결된 값에서 첫 항이 원 클라이언트. 뒤는 중간 프록시 체인이다.
        return forwarded.split(",", 1)[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


class RateLimiter:
    """IP별 고정-윈도 카운터. 윈도우가 끝나면 통째로 리셋.

    **sliding window가 아닌 fixed window인 이유** — 구현이 단순하고 MVP 한도(300)에서
    윈도 경계의 순간적 스파이크(최대 2x)가 서비스에 영향을 주지 않는다. 정밀한 한도가
    필요하면 sliding window 또는 토큰 버킷을 도입한다.
    """

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._counts: dict[str, int] = defaultdict(int)
        self._window_start = time.monotonic()

    def consume(self, ip: str) -> None:
        """IP 카운터를 1 증가. 한도 초과 시 ``RateLimitError``.

        윈도가 끝났으면 먼저 리셋한다 — 그래야 카운트가 누적되지 않는다.
        """
        if self.limit <= 0:
            return
        now = time.monotonic()
        if now - self._window_start >= _WINDOW_SECONDS:
            self._counts.clear()
            self._window_start = now
        self._counts[ip] += 1
        if self._counts[ip] > self.limit:
            raise RateLimitError(
                f"분당 요청 한도({self.limit})를 초과했습니다. 잠시 후 다시 시도해 주세요."
            )


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """요청마다 IP 카운터를 1 증가. 한도 초과 시 429 응답을 직접 만든다.

    **여기서 직접 JSONResponse를 반환하는 이유** — Starlette/FastAPI의 exception
    handler는 **라우트 핸들러에서 raise된 예외만** 잡는다. 미들웨어에서 raise된
    ``RateLimitError``는 500으로 떨어진다. ``app_error_handler``가 ``AppError``를
    잡는 것과 같은 응답 포맷을 직접 만들어 반환한다 (API_SPEC §1.3.2).
    """
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return await call_next(request)
    try:
        limiter.consume(_client_ip(request))
    except RateLimitError as exc:
        from cii_platform.api.timefmt import iso_utc_now

        state = getattr(request, "state", None)
        body = {
            "error": {"code": exc.code, "message": exc.message},
            "meta": {
                "request_id": getattr(state, "request_id", None),
                "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
            },
        }
        return JSONResponse(status_code=exc.http_status, content=body)
    return await call_next(request)
    limiter.consume(_client_ip(request))
    return await call_next(request)
