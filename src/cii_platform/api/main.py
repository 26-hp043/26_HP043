"""FastAPI 앱 진입점 (#49).

앱 인스턴스를 구성하고, 요청 컨텍스트 미들웨어, 오류 핸들러(#100/#107에서 정의),
라우터를 배선한다. 모든 업무 엔드포인트는 API_SPEC §1.1의 base URL ``/api/v1``
아래에 둔다.
"""

from __future__ import annotations

from fastapi import FastAPI

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.api.rate_limit import (
    DEFAULT_RATE_LIMIT,
    RateLimiter,
    rate_limit_middleware,
)
from cii_platform.api.routes.auth import router as auth_router
from cii_platform.api.routes.auth_dev import router as auth_dev_router
from cii_platform.api.routes.auth_dev import should_register_dev_auth
from cii_platform.api.routes.calculations import router as calculations_router
from cii_platform.api.routes.fleet import router as fleet_router
from cii_platform.api.routes.health import router as health_router
from cii_platform.api.routes.scenarios import router as scenarios_router
from cii_platform.api.routes.vessels import router as vessels_router
from cii_platform.api.routes.voyages import router as voyages_router
from cii_platform.auth.middleware import auth_middleware

# API_SPEC §1.1: 모든 API는 /api/v1 prefix 아래에 둔다.
API_V1_PREFIX = "/api/v1"

app = FastAPI(title="CII Platform API")

# 미들웨어 스택 (#238 · #275 · #307) — 바깥 → 안쪽 순서:
#   RequestContext → rate_limit → auth → 라우트
# Starlette의 add_middleware는 user_middleware.insert(0, …)라 **나중에 등록한
# 미들웨어가 바깥**에서 실행된다 (등록 방식과 무관 — middleware("http") 데코레이터도
# 내부적으로 add_middleware를 쓴다). 따라서 아래는 안쪽 것부터 등록한다.
#
# - RequestContext가 가장 바깥: request_id/timestamp를 먼저 주입해야 401·429 응답의
#   meta.request_id가 채워진다 (API_SPEC §1.3.2).
# - rate_limit이 auth보다 바깥: 미인증 트래픽(로그인 무차별 대입 포함)도 한도에
#   포함된다.
# - auth가 가장 안쪽: 세션을 검증하고 request.state에 사용자·세션을 주입한다.
#   공개 경로(health · auth/*)는 통과한다 (auth/dependencies.py PUBLIC_PATHS).
app.middleware("http")(auth_middleware)
app.state.rate_limiter = RateLimiter(DEFAULT_RATE_LIMIT)
app.middleware("http")(rate_limit_middleware)
app.add_middleware(RequestContextMiddleware)

# AppError(및 하위 클래스) → API_SPEC §1.3.2 표준 오류 응답.
# #116이 RequestValidationError(Pydantic 검증 실패)와 catch-all을 함께 등록한다.
register_exception_handlers(app)

app.include_router(health_router, prefix=API_V1_PREFIX)
# #51 선박 조회 · #55 기능① 계산 · #57 기능② 시나리오 비교.
app.include_router(vessels_router, prefix=API_V1_PREFIX)
app.include_router(voyages_router, prefix=API_V1_PREFIX)
app.include_router(calculations_router, prefix=API_V1_PREFIX)
app.include_router(scenarios_router, prefix=API_V1_PREFIX)
# #350 선대 요약 — 대시보드가 한 번의 호출로 선대 전체 현황을 받는다.
app.include_router(fleet_router, prefix=API_V1_PREFIX)
# #414 이메일·비밀번호 인증 — signup·login은 공개 경로(PUBLIC_PATHS)다.
app.include_router(auth_router, prefix=API_V1_PREFIX)
# #276 개발 환경 스텁 인증 — production이면 라우트 자체를 등록하지 않는다.
# 인증 미들웨어가 공개 경로(/api/v1/auth/dev-login)로 취급한다 (#307).
if should_register_dev_auth():
    app.include_router(auth_dev_router, prefix=API_V1_PREFIX)
