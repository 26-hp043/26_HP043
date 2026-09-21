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

import logging
import re
import uuid
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cii_platform.config import DATABASE_URL
from cii_platform.db.url import normalize_to_async

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


# db.url.normalize_to_async으로 통일 (#234 → #1058). alembic/seed/pytest/앱이 같은
# 정책을 공유한다.


#: ``CAST(? AS <타입>)`` — CUBRID가 받지 못하는 자리가 있는 캐스트 자리표시자.
#: ``IS 0`` / ``IS 1`` — CUBRID에서 ``IS``의 오른쪽은 ``NULL``·``TRUE``·``FALSE``만 온다.
#:
#: ⚠️ **감지만 하고 고쳐 쓰지 않는다** (#1316). 종전에는 두 모양을 정규식으로 치환했다.
#: 검사 스위트 전체를 세어 보니(2026-09-22 · 3114 passed) 운영 코드가 내는 것은
#: ``auth.py``의 ``.is_(False)`` 세 곳뿐이었고 — 저장소의 다른 자리는 이미 ``== 1``을
#: 쓰고 있었다 — CAST 71건은 전부 **테스트의 PostgreSQL 시절 생 SQL**이었다. 셋을
#: ``== 0``으로, 테스트 SQL을 고친 뒤 치환이 0건이 되어 걷어냈다.
#:
#: 치환을 남겨 두지 않는 이유는 정규식이 **문장이 무엇이든 모양만 맞으면 바꾸기** 때문이다.
#: 예상 밖 문장에 닿으면 오류가 아니라 **조용히 틀린 결과**가 난다. 고쳐 쓰지 않으면 같은
#: 문장이 CUBRID에서 문법 오류로 **시끄럽게** 실패한다 — 그쪽이 낫다. 소스에 다시 들어오는
#: 것은 ``tests/test_db_session_param_convert.py``의 소스 가드가 막는다.
_CAST_PLACEHOLDER = re.compile(r"CAST\(\? AS \w+\)")
_IS_BOOL_LITERAL = re.compile(r"\bIS [01]\b")

#: 감지 관측용 (#1246 · #1316). 두 모양이 보이면 문장 앞 120자를 남긴다 — 곧 CUBRID가
#: 거부할 문장이므로 오류 로그와 짝지어 원인을 바로 읽게 한다. DEBUG 레벨이라 운영
#: 로그가 문장으로 시끄러워지지 않는다(검사는 `tests/conftest.py`가 DEBUG로 받아 센다).
_LOG = logging.getLogger(__name__)


def cubrid_param_convert(
    conn: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> tuple[str, object]:
    """``before_cursor_execute`` 훅 — CUBRID가 받는 모양으로 문장과 파라미터를 고친다.

    ⚠️ **모듈 수준에 두는 이유** (`#1058` · `#955` 커버리지 하한).

    이 함수는 ``get_engine()`` 안의 클로저였다. 검사는 ``tests/conftest.py``가 **제
    변환기**를 붙인 엔진을 쓰므로 **이 함수는 전 검사에서 한 번도 돌지 않았고**,
    커버리지가 그것을 `db/session.py 78.6% (52-62 미커버)`로 가리키고 있었다.

    🔴 **그 갈라짐은 이미 한 번 결함을 냈다.** `conftest` 쪽 변환기가 모든 ``datetime``을
    초로 깎고 타임존을 떼고 있었는데, 운영에는 그 이벤트가 붙지 않아 **검사만 없는
    결함을 만들어 내고** 있었다(`2538271`). 두 변환기가 갈리면 **검사는 초록인데 운영이
    깨지거나, 그 반대**가 된다.

    모듈 수준으로 꺼내면 훅 자체를 **엔진 없이 직접 부를 수 있어** 규칙을 검사로 못
    박을 수 있다(`tests/test_db_session_param_convert.py`). 동작은 그대로다.
    """
    if parameters and isinstance(parameters, (tuple, list)):
        parameters = tuple(
            p.hex if isinstance(p, uuid.UUID) else str(p) if isinstance(p, Decimal) else p
            for p in parameters
        )
    n_cast = len(_CAST_PLACEHOLDER.findall(statement))
    n_bool = len(_IS_BOOL_LITERAL.findall(statement))
    if n_cast or n_bool:
        # 고쳐 쓰지 않고 남기기만 한다(#1316) — 이 문장은 CUBRID가 거부한다.
        _LOG.debug(
            "cubrid_param_convert 감지(치환 안 함): cast=%d bool=%d — %s",
            n_cast,
            n_bool,
            statement[:120],
        )
    return statement, parameters


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """프로세스당 하나의 async 엔진을 반환한다.

    ``lru_cache``로 단일 인스턴스를 보장한다. 엔진마다 커넥션 풀이 따로 생기므로
    요청마다 만들면 연결 수가 요청 수만큼 늘어난다.
    """
    engine = create_async_engine(normalize_to_async(DATABASE_URL), pool_pre_ping=True)
    # CUBRID 호환: UUID/Decimal 파라미터 자동 변환 (#1058)
    event.listen(engine.sync_engine, "before_cursor_execute", cubrid_param_convert, retval=True)
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
