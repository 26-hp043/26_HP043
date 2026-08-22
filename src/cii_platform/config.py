"""애플리케이션 설정.

``DATABASE_URL``이 없을 때의 동작은 ``APP_ENV``에 따라 갈린다 (#118).
프로덕션에서는 개발용 기본값으로 조용히 폴백하지 않고 즉시 실패한다.
환경변수 누락이 "연결 거부"로 뒤늦게 드러나는 것을 막고, 개발용 credential이
운영 traceback에 남지 않게 하기 위함이다.
"""

import logging
import os

#: 모듈 로거. ``warnings.warn``은 기본 필터에서 모듈당 1회만 출력되고 uvicorn 로그로
#: 잘 올라오지 않아 폴백이 눈에 띄지 않는다 (#231). 로거를 쓰면 매 import마다 남는다.
_log = logging.getLogger(__name__)

# 환경 구분. 미설정 시 개발 환경으로 본다.
_ENV = os.environ.get("APP_ENV", "development")

# 로컬 개발용 기본 접속 URL. docker-compose.yml · .env.example과 같은 값이다.
_DEFAULT_DATABASE_URL = "postgresql+asyncpg://cii:cii@localhost:5432/cii"

_url = os.environ.get("DATABASE_URL")

if _url is None:
    if _ENV == "production":
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다 (APP_ENV=production). "
            "프로덕션에서는 개발용 기본값으로 폴백하지 않습니다."
        )
    _log.warning(
        "DATABASE_URL이 없어 개발용 기본값을 사용합니다: %s",
        _DEFAULT_DATABASE_URL,
    )
    _url = _DEFAULT_DATABASE_URL

DATABASE_URL: str = _url


def is_production() -> bool:
    """``APP_ENV=production``인가 — 환경 분기의 단일 출처 (#648).

    아래 두 판정이 같은 말을 두 번 쓰지 않게 한다. ``routes/auth_dev.py``의
    ``should_register_dev_auth()``는 `#276`이 만든 것이라 그대로 두었다 — 그쪽까지
    옮기면 `#276`의 테스트를 함께 고쳐야 한다.
    """
    return _ENV == "production"


def should_expose_dev_auth() -> bool:
    """``routes/auth_dev.py``의 ``should_register_dev_auth()``와 **같은 판정**이다 (#648).

    ## 왜 같은 판정이 두 곳에 있는가

    ``auth/dependencies.py``의 공개 경로 목록이 이 값을 필요로 하는데, 거기서
    ``routes/auth_dev.py``를 import하면 **``TECH_SPEC §16`` 계층 규칙을 어긴다** —
    auth는 routes보다 아래층이다.

    ## 갈리면 무슨 일이 생기는가

    ``#276``이 프로덕션에서 dev-login **라우트를 등록하지 않는데** 공개 경로 목록에는
    그대로 남아 있었다. ``is_public_path()``가 완전일치 허용 목록이라 목록에 있으면
    미들웨어를 통과하고 → 라우트가 없어 **404**가 된다. 다른 미등록 경로는 전부
    **401**이므로 **그 경로만 응답이 달라진다** — `#593`이 ``/docs``에서 없앤 것과
    같은 신호다.

    **두 판정이 어긋나면 ``tests/test_docs_exposure.py``가 잡는다.**
    """
    return not is_production()


def should_expose_api_docs() -> bool:
    """``APP_ENV=production``이면 False — OpenAPI 문서를 열지 않는다 (#593).

    ## 무엇을 막는가

    ``/docs``·``/redoc``·``/openapi.json``은 FastAPI 기본값이 **항상 켜짐**이라,
    프로덕션에서도 **세션 없이 API 전체 구조**를 읽을 수 있었다 — 엔드포인트 50종,
    요청 스키마, 필드명, 검증 규칙. 인증이 필요한 엔드포인트는 그대로 보호되므로
    그 자체가 취약점은 아니지만, 노출할 이유도 없다. **스펙의 정본은 저장소의
    ``API_SPEC.md``**라 운영 중 조회가 필요하지 않다.

    ## 왜 이 함수가 ``config.py``에 있는가

    ``api/main.py``(문서 라우트 등록)와 ``auth/dependencies.py``(공개 경로 목록)가
    **둘 다** 이 판정을 쓴다. 어느 한쪽에 두면 다른 쪽이 import 순환을 만든다.
    ``APP_ENV``를 읽는 곳이 여기이므로 판정도 여기에 둔다.

    ``routes/auth_dev.py``의 ``should_register_dev_auth()``와 **같은 형태**다 —
    런타임 조건 분기가 아니라 **기동 시점에** 가른다. 요청마다 판정하면 환경변수를
    바꿔 켤 수 있는 것처럼 읽히고, 실제로는 프로세스 수명 동안 바뀌지 않는다.
    """
    return not is_production()


def public_base_url(fallback: str) -> str:
    """메일 링크의 기준 주소 (#429).

    ``/verify-email``·``/password-reset``은 **프론트엔드 라우트**다. API 서버에는
    그 경로가 없으므로, 메일 링크는 사용자가 실제로 화면을 여는 주소를 가리켜야 한다.

    ## 왜 폴백을 남기는가

    종전 구현은 ``request.base_url``만 썼고, 그 근거를 *"설정으로 따로 두면 그 값이
    실제 서비스 주소와 어긋났을 때 링크가 조용히 죽는다"* 라고 적었다. **그 우려는
    지금도 유효하다** — 다만 그것이 「설정을 두지 않을 이유」는 아니었다.

    운영은 nginx 뒤에서 프론트와 API가 **같은 origin**이라 요청 주소가 정확하다.
    개발은 Vite(5173)와 FastAPI(8000)가 **다른 origin**이라 요청 주소가 언제나 틀린다.
    그래서 **설정이 있으면 설정을, 없으면 요청 주소를** 쓴다 — 같은 origin 배포는
    설정 없이 지금 동작을 그대로 유지하고, 분리된 환경만 명시한다.

    :param fallback: 미설정 시 쓸 주소. 호출부가 ``str(request.base_url)``을 넘긴다.
        **설정을 읽지 못한 것과 요청 주소를 쓰기로 한 것을 구분**하기 위해 인자로
        받는다 — 이 함수가 ``Request``를 알면 레이어 방향이 뒤집힌다.
    """
    configured = os.environ.get("APP_PUBLIC_URL", "").strip()
    return (configured or fallback).rstrip("/")
