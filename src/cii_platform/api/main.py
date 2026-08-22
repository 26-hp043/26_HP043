"""FastAPI 앱 진입점 (#49).

앱 인스턴스를 구성하고, 요청 컨텍스트 미들웨어, 오류 핸들러(#100/#107에서 정의),
라우터를 배선한다. 모든 업무 엔드포인트는 API_SPEC §1.1의 base URL ``/api/v1``
아래에 둔다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.api.rate_limit import (
    DEFAULT_RATE_LIMIT,
    RateLimiter,
    rate_limit_middleware,
)
from cii_platform.api.routes.annual_simulations import router as annual_simulations_router
from cii_platform.api.routes.auth import router as auth_router
from cii_platform.api.routes.auth_dev import router as auth_dev_router
from cii_platform.api.routes.auth_dev import should_register_dev_auth
from cii_platform.api.routes.auth_tokens import router as auth_tokens_router
from cii_platform.api.routes.calculations import router as calculations_router
from cii_platform.api.routes.fleet import router as fleet_router
from cii_platform.api.routes.health import router as health_router
from cii_platform.api.routes.not_underway import router as not_underway_router
from cii_platform.api.routes.parameters import router as parameters_router
from cii_platform.api.routes.reports import router as reports_router
from cii_platform.api.routes.scenarios import router as scenarios_router
from cii_platform.api.routes.vessels import router as vessels_router
from cii_platform.api.routes.voyages import router as voyages_router
from cii_platform.auth.middleware import auth_middleware
from cii_platform.config import should_expose_api_docs
from cii_platform.mail.config import load_mail_settings

# API_SPEC §1.1: 모든 API는 /api/v1 prefix 아래에 둔다.
API_V1_PREFIX = "/api/v1"

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """기동 시점 설정 검증 (#524).

    ## 왜 여기인가

    ``mail/config.py``의 가드는 **「프로덕션인데 메일이 로그로만 나가는」 상태**를
    막으려고 만들어졌다. 그런데 ``get_mailer()``가 ``lru_cache``로 **라우트 안에서
    처음 호출**되므로, 그 가드는 기동이 아니라 **첫 발송 시도**에서야 돈다.

    실제로 일어나는 일은 이랬다.

    * 앱이 정상 기동한다(health 200) → 아무도 이상을 눈치채지 못한다
    * 사용자가 「비밀번호를 잊었어요」를 누른다 → 그 요청이 500으로 떨어진다

    가드가 지키려던 것이 정확히 이 상황이다. 지금은 조용하지 않고 시끄럽게
    실패하지만, **드러나는 시점이 「배포 직후」가 아니라 「첫 사용자가 계정을 잃을
    뻔한 순간」**이다. 문서(`backends.py`·`.env.example`)는 줄곧 「기동을 막는다」고
    적어 왔다 — 구현을 그 문서에 맞춘다.

    ## 무엇을 하지 않는가

    **연결을 열지 않는다.** SMTP 서버에 실제로 붙어 보는 것은 기동을 외부 서비스
    가용성에 묶는 일이고, 그건 배포가 멈춰야 할 이유가 아니다. 여기서 보는 것은
    **설정이 앞뒤가 맞는가**뿐이다 — 프로덕션인데 console인지, smtp인데 호스트가
    비었는지.
    """
    settings = load_mail_settings()
    _log.info("메일 백엔드: %s", settings.backend)
    yield


def api_docs_kwargs(*, expose_docs: bool) -> dict[str, str | None]:
    """``FastAPI()``에 넘길 문서 라우트 설정 (#593).

    프로덕션이면 ``docs_url``·``redoc_url``·``openapi_url``을 **모두 ``None``**으로
    두어 라우트 자체를 등록하지 않는다. 셋을 함께 끄는 이유는 ``/docs``가 스펙 본문을
    ``/openapi.json``에서 받아 그리기 때문이다 — 하나만 남기면 UI만 사라지고
    **구조 정보는 그대로 열린다.**

    개발에서는 빈 dict을 돌려 **FastAPI 기본값을 그대로 쓴다.** 기본 경로를 여기에
    다시 적으면 FastAPI가 기본값을 바꿨을 때 두 곳이 갈린다.

    **인자를 받는 이유는 검증 때문이다** — ``build_public_paths()``와 같은 판단이다.
    """
    if expose_docs:
        return {}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


app = FastAPI(
    title="CII Platform API",
    lifespan=lifespan,
    # #593 프로덕션에서는 OpenAPI 문서를 열지 않는다. `auth/dependencies.py`의
    # 공개 경로 목록도 같은 판정을 쓴다 — 한쪽만 바뀌면 `/docs`가 401과 404 사이에서
    # 갈린다.
    **api_docs_kwargs(expose_docs=should_expose_api_docs()),
)

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
# #370 not under way 구간 CRUD — 정박 연료를 넣을 입구. 없으면 M이 늘지 않아
# 「정박해도 등급이 안 떨어지는」 상태가 된다(#353 분자 경로).
app.include_router(not_underway_router, prefix=API_V1_PREFIX)
# #64 기능③ 연간 시뮬레이션 — 스냅샷 격리로 실행 중 데이터 변경과 분리한다.
app.include_router(annual_simulations_router, prefix=API_V1_PREFIX)
# #444 규제 파라미터 조회 — 화면이 선택지를 자기 코드에 박아 두지 않게 한다.
# 읽기 전용이다. 개정 적재(§7.5)는 이력 보존·권한(#359)과 함께 정해야 한다.
app.include_router(parameters_router, prefix=API_V1_PREFIX)
# #361 리포트 — 응답이 JSON이 아니라 파일(PDF·CSV·HTML)이다.
app.include_router(reports_router, prefix=API_V1_PREFIX)
# #414 이메일·비밀번호 인증 — signup·login은 공개 경로(PUBLIC_PATHS)다.
app.include_router(auth_router, prefix=API_V1_PREFIX)
# #408 이메일 인증·비밀번호 재설정 — 메일 링크로 진입하므로 세션이 없다(공개 경로).
app.include_router(auth_tokens_router, prefix=API_V1_PREFIX)
# #276 개발 환경 스텁 인증 — production이면 라우트 자체를 등록하지 않는다.
# 인증 미들웨어가 공개 경로(/api/v1/auth/dev-login)로 취급한다 (#307).
if should_register_dev_auth():
    app.include_router(auth_dev_router, prefix=API_V1_PREFIX)
