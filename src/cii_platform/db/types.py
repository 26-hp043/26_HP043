"""CUBRID 호환 커스텀 SQLAlchemy 타입 (#1058).

PostgreSQL JSONB 대체 — CUBRID에 JSONB가 없으므로 TEXT에 JSON 직렬화한다.
UUID 대체 — CUBRID에 네이티브 UUID가 없어 ``CHAR(32)``에 담되 ``str``도 받는다.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import sqlalchemy as sa


class JSONText(sa.TypeDecorator[Any]):
    """TEXT 컬럼에 JSON을 투명하게 직렬/역직렬화한다.

    PostgreSQL JSONB 대체. 쓰기 시 ``json.dumps``, 읽기 시 ``json.loads``.
    """

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: sa.Dialect) -> str | None:
        if value is not None:
            return json.dumps(value, ensure_ascii=False)
        return value

    def process_result_value(self, value: str | None, dialect: sa.Dialect) -> Any:
        if value is not None:
            return json.loads(value)
        return value


class Base64Bytes(sa.TypeDecorator[bytes]):
    """``TEXT`` 컬럼에 바이트를 base64로 투명하게 담는다 (`#2080`).

    ## 왜 BLOB이 아닌가

    ``sqlalchemy-cubrid``가 **자기 테스트 요건 파일에** 이렇게 적고 그 검사를 꺼 뒀다::

        @property
        def binary_comparisons(self) -> compound:
            \"\"\"CUBRID BLOB roundtrip has driver-level issues.\"\"\"
            return _CLOSED

    드라이버가 스스로 못 한다고 적은 길로 제품의 **첫 이진 열**을 내지 않는다.
    :class:`JSONText`가 CUBRID에 JSONB가 없어 택한 길과 같은 모양이다 — 없는 타입을
    흉내 내는 대신, **있는 타입 위에 변환을 얹는다**.

    ## 대가

    바이트가 약 4/3로 커진다. 쓰는 쪽이 **고정 크기로 다시 그린 뒤** 넣으므로
    (``services/avatar.py``) 그 4/3이 열린 값이 아니다 — 이 타입을 다른 데 쓸 때는
    **크기 상한이 어디에 있는지 먼저 확인한다.**
    """

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value: bytes | None, dialect: sa.Dialect) -> str | None:
        if value is None:
            return None
        return base64.b64encode(value).decode("ascii")

    def process_result_value(self, value: str | None, dialect: sa.Dialect) -> bytes | None:
        if value is None:
            return None
        return base64.b64decode(value)


class UuidText(sa.TypeDecorator[Any]):
    """``CHAR(32)``에 UUID를 담는다 — **``str``도 받는다** (#1058).

    ## 왜 필요한가

    전환 전 컬럼은 ``postgresql.UUID(as_uuid=True)``였고 **psycopg가 문자열을 받아
    줬다.** CUBRID 전환이 그것을 :class:`sqlalchemy.Uuid`로 바꾸면서 입력이 **조용히
    좁아졌다** — 이 타입의 bind processor는 ``value.hex``를 부르므로 문자열이 오면
    그 자리에서 선다.

    ::

        sa.Uuid().bind_processor(dialect)('6a8b3660…')
        → AttributeError: 'str' object has no attribute 'hex'

    2026-09-15 전체 pytest에서 **59건**이 이 한 줄로 떨어졌다
    (``sqlalchemy/sql/sqltypes.py:3738``). 부르는 쪽 수십 곳을 고치는 대신 **타입
    한 곳**에서 종전 계약을 되돌린다 — 넓히는 것이 아니라 **좁아진 것을 되돌리는**
    것이다.

    ## 무엇을 하지 않는가

    **아무 문자열이나 통과시키지 않는다.** :class:`uuid.UUID`가 파싱하지 못하면
    ``ValueError``를 낸다 — 대시 형식과 hex 32자를 모두 받고, 그 밖의 값은 거부한다.
    ``AttributeError``보다 **틀렸다는 신호가 분명하다.**

    ## 저장 모양은 바뀌지 않는다

    ``impl``이 :class:`sqlalchemy.Uuid` 그대로라 DDL도 ``CHAR(32)``로 같다 —
    **마이그레이션이 필요 없다.** 바뀌는 것은 파이썬 쪽 입력 관용도뿐이다.
    """

    impl = sa.Uuid
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: sa.Dialect) -> Any:
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
