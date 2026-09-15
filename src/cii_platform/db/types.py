"""CUBRID 호환 커스텀 SQLAlchemy 타입 (#1058).

PostgreSQL JSONB 대체 — CUBRID에 JSONB가 없으므로 TEXT에 JSON 직렬화한다.
"""

from __future__ import annotations

import json
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
