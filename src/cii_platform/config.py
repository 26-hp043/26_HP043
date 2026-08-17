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
