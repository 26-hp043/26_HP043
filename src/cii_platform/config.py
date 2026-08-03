"""애플리케이션 설정.

``DATABASE_URL``이 없을 때의 동작은 ``APP_ENV``에 따라 갈린다 (#118).
프로덕션에서는 개발용 기본값으로 조용히 폴백하지 않고 즉시 실패한다.
환경변수 누락이 "연결 거부"로 뒤늦게 드러나는 것을 막고, 개발용 credential이
운영 traceback에 남지 않게 하기 위함이다.
"""

import os
import warnings

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
    warnings.warn(
        f"DATABASE_URL이 없어 개발용 기본값을 사용합니다: {_DEFAULT_DATABASE_URL}",
        stacklevel=2,
    )
    _url = _DEFAULT_DATABASE_URL

DATABASE_URL: str = _url
