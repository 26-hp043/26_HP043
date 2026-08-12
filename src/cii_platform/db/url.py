"""PostgreSQL 접속 URL 정규화 — asyncpg 드라이버로 단일화 (#234).

alembic · seed · pytest · 앱 세션의 4곳이 각각 사본을 갖고 있어 분기가 갈린다.
앱만 ``postgresql+<다른 드라이버>`` 분기가 빠져, 배포 환경이 동기 드라이버 URL을
주면 alembic/seed/pytest는 통과하고 **앱만 기동에 실패하는** 조합이 된다 (#234).
한 곳으로 모아 그 정책을 4곳이 공유한다.

계층 (TECH_SPEC §16): 이 모듈은 db 하위 패키지의 일부이며, alembic · scripts · tests
모두 이미 ``cii_platform.config``를 import한다 (``DATABASE_URL``). 레이어 중립
위치에서 URL을 다루는 것이므로 계층 위반이 아니다.
"""

from __future__ import annotations

#: asyncpg 드라이버 접두사 — 본 프로젝트가 사용하는 유일한 PostgreSQL 드라이버.
_ASYNC_PREFIX = "postgresql+asyncpg://"
_POSTGRES_PREFIX = "postgresql://"
_POSTGRES_PLUS_PREFIX = "postgresql+"


def normalize_to_asyncpg(url: str) -> str:
    """PostgreSQL 접속 URL을 ``postgresql+asyncpg://``로 정규화한다.

    분기 순서:

    1. 이미 asyncpg이면 그대로.
    2. ``postgresql://``(드라이버 생략)이면 asyncpg 접두사로 교체.
    3. ``postgresql+<다른 드라이버>://``이면 asyncpg으로 교체 — 배포 환경이
       동기 드라이버(psycopg 등)를 지정하는 경우가 흔하다.
    4. 그 외(비 PostgreSQL URL)는 손대지 않는다 — 에러 메시지가 드라이버
       mismatch로 가려지는 것을 막는다.

    **역은 수행하지 않는다.** asyncpg URL이 들어오면 그대로 반환하므로 역방향
    정규화(예: 동기 엔진용으로 psycopg로 되돌리기)가 필요하면 별도 함수를 둬야 한다.
    """
    if url.startswith(_ASYNC_PREFIX):
        return url
    if url.startswith(_POSTGRES_PREFIX):
        return _ASYNC_PREFIX + url.split("://", 1)[1]
    if url.startswith(_POSTGRES_PLUS_PREFIX):
        return _ASYNC_PREFIX + url.split("://", 1)[1]
    return url
