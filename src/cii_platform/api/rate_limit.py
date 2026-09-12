"""요청 한도 미들웨어 — 경로 버킷별·IP별 분당 요청 수 제한 (#238 · #811).

``API_SPEC §13.2``가 **두 행**을 규정한다 — **계산 API 분당 60회**, **CRUD API 분당
300회**. 종전 구현은 아래 행(300)만 인용해 **계산 경로에도 300을 적용**했다. 계산 1건은
``prec=50`` 컨텍스트라 요청당 CPU가 CRUD보다 크다는 것이 `#238` 자신의 근거였는데,
가져온 수치가 반대쪽이었다.

여기에 **인증 경로 분당 10회**를 더한다(`#811`). 로그인 300회/분은 무차별 대입 방어가
아니고, ``/password-reset/request``·``/verify-email/request``는 같은 한도 아래에서
**메일 발송 증폭기**로 쓰인다. 이 정책은 `API_SPEC §13.2` 표에 함께 등재했다 — 429는
사용자가 보는 계약이므로 구현만 두면 정본이 틀린 상태가 된다.

## 버킷은 서로 독립이다

카운터 키가 ``(버킷, IP)``다. 인증 한도를 다 써도 CRUD·계산은 막히지 않는다.
``API_SPEC §13.2``가 계산과 CRUD를 **별도 행**으로 규정하는 것과 같은 해석이다.
따라서 한 IP의 분당 상한은 네 버킷의 합(기본 380)이며, 어느 한 버킷의 값이 아니다.

## 구현은 고정 윈도 in-memory 카운터다

uvicorn 워커마다 카운터가 따로 생기지만, 이 프로젝트는 `#232`가 ``workers=1``을
기본으로 삼으므로 MVP에선 유효하다. 멀티 워커·멀티 인스턴스 배포에선 Redis 같은
공유 저장소가 필요하다 — 그 이전 없이 **계정 잠금 같은 상태**를 여기 얹으면 워커마다
잠금이 따로 생겨 「잠긴 줄 알았는데 다른 워커로는 열려 있는」 상태가 된다 (`#811` 판단).

한도 값이 ``0``이면 그 버킷은 통과만 한다 — 테스트 환경이나 한도를 끄고 싶을 때 쓴다.

**``X-Forwarded-For`` 신뢰 정책** — 기본적으로 ``X-Forwarded-For``를 **무시하고**
``request.client.host``를 쓴다. 클라이언트가 이 헤더를 임의로 바꿔 한도를 우회하는
것을 막기 위함이다. 역방향 프록시(nginx · Cloudflare) 뒤에서 원 클라이언트 IP로
한도를 걸어야 한다면 ``USE_FORWARDED_FOR=true``로 설정한다 — 이때는 **신뢰할 수
있는 프록시만 앞에 있는 환경**이 전제다. `#811`이 ``docker-compose.prod.yml``의
``app.ports``를 없앤 것이 그 전제의 절반이다(호스트에서 ``:8000``에 직접 붙어 헤더를
위조할 수 없어야 한다). 나머지 절반은 `#786`이 맡는다.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request
from starlette.responses import JSONResponse, Response

from cii_platform.errors import RateLimitError

#: 인증 경로 — 비밀번호 추측과 메일 발송 증폭을 막는다.
BUCKET_AUTH = "auth"
#: 계산 경로 — ``API_SPEC §13.2``의 「계산 API」 행.
BUCKET_CALCULATION = "calculation"
#: 챗봇 경로 — ``API_SPEC §13.2``의 「챗봇 API」 행 (`#120`).
#:
#: ⚠️ **계산 버킷(60)을 함께 쓰지 않는 이유가 둘이다.** ⑴ 사람이 채팅을 치는 속도로
#: 분당 10이면 넉넉하다 — 분당 60은 사람이 낼 수 없는 속도다 ⑵ **챗봇은 호출마다
#: 외부 LLM 비용이 붙는다.** 다른 API는 초과 호출이 서버 부하로 끝나지만 챗봇은
#: **금액**으로 끝난다.
BUCKET_CHAT = "chat"
#: 그 밖의 전부 — ``API_SPEC §13.2``의 「CRUD API」 행.
BUCKET_DEFAULT = "default"

_API_V1 = "/api/v1"

#: 분당 10회를 거는 경로 (#811). **완전 일치**로 본다 — 접두사로 매칭하면
#: ``/auth/logout``·``/auth/me`` 같은 정상 경로까지 잡힌다.
#:
#: ``/auth/password-change``는 이슈 `#811`의 목록에 없지만 넣었다. **현재 비밀번호를
#: 받는 유일한 다른 경로**이고, 세션을 훔친 공격자가 종전에는 분당 300회 시도할 수
#: 있었다. 정당한 사용자는 평생 몇 번 부르지 않으므로 10회/분에 비용이 없다.
#:
#: ``/auth/verify-email/confirm``·``/auth/password-reset/confirm``은 **넣지 않았다**.
#: 토큰이 ``secrets.token_urlsafe(32)``(256비트)라 추측이 불가능하므로
#: (`services/auth_token.py`) 한도를 걸어도 얻는 것이 없다.
#:
#: ``/auth/dev-login``도 넣지 않았다 — 프로덕션에는 등록되지 않고(`#276`),
#: 개발에서는 ``scripts/demo_up.sh``가 쓰는 편의 경로다.
AUTH_PATHS = frozenset(
    {
        f"{_API_V1}/auth/login",
        f"{_API_V1}/auth/signup",
        f"{_API_V1}/auth/password-change",
        f"{_API_V1}/auth/password-reset/request",
        f"{_API_V1}/auth/verify-email/request",
    }
)

#: 분당 10회를 거는 챗봇 경로 (``API_SPEC §13.2`` 「챗봇 API」 · `#120`).
#:
#: `#121`이 라우트를 열면서 채웠다. 버킷과 한도를 **라우트보다 먼저** 둔 덕에
#: 한도 없는 경로가 열려 있던 시간이 없다.
CHAT_PATHS: frozenset[str] = frozenset({f"{_API_V1}/chat"})

#: 분당 60회를 거는 경로 (``API_SPEC §13.2`` 「계산 API」).
#:
#: 명단은 ``API_SPEC §13.1`` 성능 목표표가 확정해 준다 — 그 표가 열거하는
#: ``voyage-cii``·``scenarios/compare``·``annual-simulations``(결정론·Monte Carlo)가
#: 곧 계산 엔진을 도는 요청이다.
#:
#: ``POST /scenarios/{id}/adopt``는 **넣지 않았다** — 계산이 아니라 「이 시나리오를
#: 채택한다」는 선언이다(`API_SPEC §5.2`). ``GET /calculations``·
#: ``GET /annual-simulations/{id}``도 조회라 CRUD 행에 속한다.
CALCULATION_ROUTES = frozenset(
    {
        ("POST", f"{_API_V1}/calculations/voyage-cii"),
        ("POST", f"{_API_V1}/scenarios/compare"),
        ("POST", f"{_API_V1}/annual-simulations"),
    }
)

#: ``POST /annual-simulations/{id}/reproduce`` — 경로에 UUID가 들어 있어 완전 일치로
#: 잡을 수 없다. 재현은 같은 Monte Carlo 엔진을 다시 도는 요청이므로 계산 버킷이다.
_REPRODUCE_PREFIX = f"{_API_V1}/annual-simulations/"
_REPRODUCE_SUFFIX = "/reproduce"

#: ``X-Forwarded-For`` 헤더 신뢰 여부. **기본 false** — 클라이언트가 헤더를 바꿔
#: 한도를 우회하는 것을 막는다. 역방향 프록시 뒤에서만 true로 설정한다.
_USE_FORWARDED_FOR = os.environ.get("USE_FORWARDED_FOR", "false").lower() == "true"

_WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class RateLimits:
    """버킷별 분당 한도 (#811). ``0``이면 그 버킷은 한도를 걸지 않는다."""

    default: int
    auth: int
    calculation: int
    chat: int

    @classmethod
    def from_env(cls) -> RateLimits:
        """환경변수에서 읽는다. 기본값은 ``API_SPEC §13.2`` + `#811` + `#120`."""
        return cls(
            default=int(os.environ.get("RATE_LIMIT_PER_MINUTE", "300")),
            auth=int(os.environ.get("RATE_LIMIT_AUTH_PER_MINUTE", "10")),
            calculation=int(os.environ.get("RATE_LIMIT_CALC_PER_MINUTE", "60")),
            chat=int(os.environ.get("RATE_LIMIT_CHAT_PER_MINUTE", "10")),
        )

    @classmethod
    def uniform(cls, limit: int) -> RateLimits:
        """네 버킷을 같은 한도로 (테스트용).

        버킷 경계가 아니라 **카운터 자체**를 검증하는 테스트가 쓴다 — 그런 테스트에
        버킷별 값을 따로 주면 무엇을 재는 검사인지 흐려진다.
        """
        return cls(default=limit, auth=limit, calculation=limit, chat=limit)

    def for_bucket(self, bucket: str) -> int:
        if bucket == BUCKET_AUTH:
            return self.auth
        if bucket == BUCKET_CALCULATION:
            return self.calculation
        if bucket == BUCKET_CHAT:
            return self.chat
        return self.default


def resolve_bucket(method: str, path: str) -> str:
    """요청 경로가 어느 버킷인지 (#811).

    **미들웨어가 요청마다 부르므로 DB도 라우트 테이블도 보지 않는다** — 상수 집합
    조회뿐이다. 경로 목록이 실제 라우트와 어긋나면 한도가 **조용히** 풀리므로,
    ``tests/test_rate_limit.py``가 두 집합의 모든 경로가 앱에 실재하는지 대조한다.
    """
    if path in AUTH_PATHS:
        return BUCKET_AUTH
    if path in CHAT_PATHS:
        return BUCKET_CHAT
    if (method, path) in CALCULATION_ROUTES:
        return BUCKET_CALCULATION
    if method == "POST" and path.startswith(_REPRODUCE_PREFIX) and path.endswith(_REPRODUCE_SUFFIX):
        return BUCKET_CALCULATION
    return BUCKET_DEFAULT


def _client_ip(request: Request) -> str:
    """클라이언트 IP를 판별한다.

    **기본적으로 ``X-Forwarded-For``를 무시한다.** 클라이언트가 이 헤더를 임의로
    바꿔 매 요청 다른 IP로 위장하면 한도가 완전히 우회된다 (#rate-limit-security).

    ``USE_FORWARDED_FOR=true``일 때만 헤더를 읽는다 — 이때는 **신뢰할 수 있는
    역방향 프록시가 앞에 있는 환경**이 전제다. 프록시가 없는 직접 노출 환경에서는
    ``request.client.host``가 곧 클라이언트 IP이므로 그대로 쓴다.
    """
    if _USE_FORWARDED_FOR:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # 콤마로 연결된 값에서 첫 항이 원 클라이언트. 뒤는 중간 프록시 체인이다.
            return forwarded.split(",", 1)[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


class RateLimiter:
    """``(버킷, IP)``별 고정-윈도 카운터. 윈도우가 끝나면 통째로 리셋.

    **sliding window가 아닌 fixed window인 이유** — 구현이 단순하고 MVP 한도에서
    윈도 경계의 순간적 스파이크(최대 2x)가 서비스에 영향을 주지 않는다. 정밀한 한도가
    필요하면 sliding window 또는 토큰 버킷을 도입한다.

    **버킷을 나눈 카운터를 하나의 윈도로 두는 이유** — 윈도를 버킷마다 따로 두면
    리셋 시점이 갈려, 어느 버킷이 언제 비는지 설명할 수 없게 된다. 한도는 버킷별로
    다르지만 **시간 축은 하나**다.
    """

    def __init__(self, limits: RateLimits) -> None:
        self.limits = limits
        self._counts: dict[tuple[str, str], int] = defaultdict(int)
        self._window_start = time.monotonic()

    @property
    def limit(self) -> int:
        """기본(CRUD) 버킷 한도. `#238` 시절의 이름을 유지한다."""
        return self.limits.default

    def consume(self, ip: str, bucket: str = BUCKET_DEFAULT) -> None:
        """``(버킷, IP)`` 카운터를 1 증가. 한도 초과 시 ``RateLimitError``.

        윈도가 끝났으면 먼저 리셋한다 — 그래야 카운트가 누적되지 않는다.
        """
        limit = self.limits.for_bucket(bucket)
        if limit <= 0:
            return
        now = time.monotonic()
        if now - self._window_start >= _WINDOW_SECONDS:
            self._counts.clear()
            self._window_start = now
        key = (bucket, ip)
        self._counts[key] += 1
        if self._counts[key] > limit:
            raise RateLimitError(
                f"분당 요청 한도({limit})를 초과했습니다. 잠시 후 다시 시도해 주세요."
            )


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """요청마다 ``(버킷, IP)`` 카운터를 1 증가. 한도 초과 시 429 응답을 직접 만든다.

    **여기서 직접 JSONResponse를 반환하는 이유** — Starlette/FastAPI의 exception
    handler는 **라우트 핸들러에서 raise된 예외만** 잡는다. 미들웨어에서 raise된
    ``RateLimitError``는 500으로 떨어진다. ``app_error_handler``가 ``AppError``를
    잡는 것과 같은 응답 포맷을 직접 만들어 반환한다 (API_SPEC §1.3.2).

    **미들웨어 순서** — ``RequestContextMiddleware``보다 **안쪽**에 등록돼야 한다.
    ``RequestContext``가 ``request.state.request_id``를 먼저 주입해야 429 응답의
    ``meta.request_id``가 채워진다 (API_SPEC §1.3.2). ``main.py``에서 등록 순서를
    보장한다.

    **``auth_middleware``보다 바깥이어야 한다** (`#307`). 그래야 미인증 트래픽 —
    로그인 무차별 대입이 정확히 그것이다 — 도 한도에 든다.
    """
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return await call_next(request)
    bucket = resolve_bucket(request.method, request.url.path)
    try:
        limiter.consume(_client_ip(request), bucket)
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
