"""비동기 DB 세션 관리 (#55).

FastAPI 라우트가 요청마다 세션을 받도록 엔진과 세션 팩토리를 한 곳에서 만든다.

**엔진을 모듈 임포트 시점에 만들지 않는다.** ``create_async_engine``은 URL을 파싱만
하고 연결은 첫 사용 시점에 열지만, 그래도 지연 생성으로 두는 이유가 있다 — 테스트가
``DATABASE_URL``을 바꿔 가며 import하는 경우와, DB 없이 앱을 import하는 경우
(``tests/test_health.py``가 그렇다)에 부작용을 남기지 않기 위해서다.

계층 규칙은 TECH_SPEC §16 참조. 이 모듈은 ``db`` 레이어에 속하며 ``services``·``api``를
import하지 않는다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cii_platform.config import DATABASE_URL
from cii_platform.db.url import normalize_to_async

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


# db.url.normalize_to_async으로 통일 (#234 → #1058). alembic/seed/pytest/앱이 같은
# 정책을 공유한다.


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """프로세스당 하나의 async 엔진을 반환한다.

    ``lru_cache``로 단일 인스턴스를 보장한다. 엔진마다 커넥션 풀이 따로 생기므로
    요청마다 만들면 연결 수가 요청 수만큼 늘어난다.
    """
    engine = create_async_engine(normalize_to_async(DATABASE_URL), pool_pre_ping=True)

    # CUBRID 호환: UUID/Decimal 파라미터 자동 변환 (#1058)
    import re
    import uuid
    from decimal import Decimal as _Decimal

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def _cubrid_param_convert(conn, cursor, statement, parameters, context, executemany):
        if parameters and isinstance(parameters, (tuple, list)):
            parameters = tuple(
                p.hex if isinstance(p, uuid.UUID)
                else str(p) if isinstance(p, _Decimal)
                else p
                for p in parameters
            )
        # CAST(? AS type) → ?
        statement = re.sub(r"CAST\(\? AS \w+\)", "?", statement)
        # IS 0/1 → = 0/1
        statement = re.sub(r"\bIS 0\b", "= 0", statement)
        statement = re.sub(r"\bIS 1\b", "= 1", statement)
        return statement, parameters

    return engine


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """세션 팩토리를 반환한다.

    ``expire_on_commit=False``인 이유: commit 후에도 ORM 객체의 속성을 읽어야 하는데,
    기본값(True)이면 commit 시점에 전부 만료되어 다음 접근이 **비동기 컨텍스트 밖에서
    lazy load를 시도**하고 ``MissingGreenlet``으로 터진다.
    """
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 의존성 — 요청 단위 세션.

    **commit은 하지 않는다.** 트랜잭션 경계를 정하는 것은 서비스 계층의 판단이며,
    의존성이 무조건 commit하면 실패한 요청의 부분 결과가 남을 수 있다.
    예외가 나면 세션이 닫히며 롤백된다.
    """
    async with get_sessionmaker()() as session:
        yield session
