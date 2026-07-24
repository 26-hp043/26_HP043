"""FastAPI 앱 진입점 (#49).

앱 인스턴스를 구성하고, 요청 컨텍스트 미들웨어, 오류 핸들러(#100/#107에서 정의),
라우터를 배선한다. 모든 업무 엔드포인트는 API_SPEC §1.1의 base URL ``/api/v1``
아래에 둔다.

실행 진입점은 ``cii_platform.api.main:app``이다(Dockerfile CMD와 일치).
"""

from __future__ import annotations

from fastapi import FastAPI

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.api.routes.health import router as health_router

# API_SPEC §1.1: 모든 API는 /api/v1 prefix 아래에 둔다.
API_V1_PREFIX = "/api/v1"

app = FastAPI(title="CII Platform API")

# 요청마다 request_id/timestamp를 state에 주입(미들웨어) → 오류 응답 meta에서 사용.
app.add_middleware(RequestContextMiddleware)

# AppError(및 하위 클래스) → API_SPEC §1.3.2 표준 오류 응답. (RequestValidationError·
# catch-all 핸들러는 #116에서 추가한다.)
register_exception_handlers(app)

app.include_router(health_router, prefix=API_V1_PREFIX)
