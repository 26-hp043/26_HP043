"""FastAPI 앱 진입점 (#49).

앱 인스턴스를 구성하고, 요청 컨텍스트 미들웨어, 오류 핸들러(#100/#107에서 정의),
라우터를 배선한다. 모든 업무 엔드포인트는 API_SPEC §1.1의 base URL ``/api/v1``
아래에 둔다.
"""

from __future__ import annotations

from fastapi import FastAPI

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.api.rate_limit import DEFAULT_RATE_LIMIT, RateLimiter, rate_limit_middleware
from cii_platform.api.routes.calculations import router as calculations_router
from cii_platform.api.routes.health import router as health_router
from cii_platform.api.routes.vessels import router as vessels_router
from cii_platform.api.routes.voyages import router as voyages_router

# API_SPEC §1.1: 모든 API는 /api/v1 prefix 아래에 둔다.
API_V1_PREFIX = "/api/v1"

app = FastAPI(title="CII Platform API")

# #238 — IP별 분당 요청 한도. API_SPEC §13.2 (300/min). 환경변수 RATE_LIMIT_PER_MINUTE=0이면 비활성.
# **등록 순서가 중요** — Starlette의 add_middleware는 user_middleware.insert(0, …)라
# **나중에 등록한 미들웨어가 바깥**에서 실행된다 (등록 방식과 무관하다 — middleware("http")
# 데코레이터도 내부적으로 add_middleware를 쓴다). rate_limit_middleware는
# RequestContextMiddleware보다 **안쪽**이어야 한다. RequestContext가 먼저
# request.state.request_id를 주입해야 429 응답의 meta.request_id가 채워진다 (API_SPEC §1.3.2).
# 따라서 rate_limit을 먼저 등록하고 RequestContext를 **나중에** 등록하면 RequestContext가
# 바깥이 돼 의도한 순서가 된다.
app.state.rate_limiter = RateLimiter(DEFAULT_RATE_LIMIT)
app.middleware("http")(rate_limit_middleware)
app.add_middleware(RequestContextMiddleware)

# AppError(및 하위 클래스) → API_SPEC §1.3.2 표준 오류 응답.
# #116이 RequestValidationError(Pydantic 검증 실패)와 catch-all을 함께 등록한다.
register_exception_handlers(app)

app.include_router(health_router, prefix=API_V1_PREFIX)
# #51 선박 조회 · #55 기능① 계산.
app.include_router(vessels_router, prefix=API_V1_PREFIX)
app.include_router(voyages_router, prefix=API_V1_PREFIX)
app.include_router(calculations_router, prefix=API_V1_PREFIX)
