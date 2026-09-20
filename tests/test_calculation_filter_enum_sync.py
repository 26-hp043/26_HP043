"""계산 목록 필터의 허용값 ↔ 모델 CHECK ↔ `DB_SCHEMA §2.5` 대조 (`#1367`).

## 왜 필요한가

`GET /calculations`의 ``type``·해시 필터를 이제 서비스가 **거른다**. 그 판정에 쓰는
집합이 DB가 실제로 허용하는 것과 갈리면 **두 방향 모두 나쁘다.**

- 코드가 **더 좁으면** — DB에 있는 행을 필터로 꺼낼 수 없다. 422가 나는데 그 값은 실재한다
- 코드가 **더 넓으면** — 검증이 통과하고 빈 목록이 돌아온다. **검증을 넣은 이유가 사라진다**

사슬은 셋이다.

.. code-block:: text

    calc_run_repo.CALCULATION_TYPES  ==  모델 CheckConstraint  ==  DB_SCHEMA §2.5

해시 형식도 같다 — 서비스의 정규식은 `DB_SCHEMA`가 트리거로 집행하는 것과 **같은 글자**여야
한다. 다르면 「API는 받는데 INSERT가 튕기는」(또는 그 반대) 구간이 생긴다.
"""

from __future__ import annotations

import re
from pathlib import Path

from cii_platform.db.models.calculation_run import CalculationRun
from cii_platform.db.repositories.calculation_run import CALCULATION_TYPES
from cii_platform.services.calculation import _HASH_PATTERN

DB_SCHEMA = Path(__file__).resolve().parents[1] / "DB_SCHEMA.md"


def _values_from_check(sql: str) -> tuple[str, ...]:
    """``... IN ('A','B',...)``에서 값을 순서대로 읽는다.

    ``IN``과 ``(`` 사이가 줄바꿈일 수 있어(`DB_SCHEMA`의 DDL이 그렇다) 정규식으로 찾는다.
    """
    match = re.search(r"\bIN\s*\(([^)]*)\)", sql, re.S)
    assert match is not None, f"IN 목록을 찾지 못했다: {sql!r}"
    return tuple(re.findall(r"'([A-Z_]+)'", match.group(1)))


def _model_check_sql() -> str:
    for constraint in CalculationRun.__table__.constraints:
        if getattr(constraint, "name", None) == "chk_calculation_type":
            return str(constraint.sqltext)
    raise AssertionError("모델에 chk_calculation_type이 없다")


def _doc_check_sql() -> str:
    text = DB_SCHEMA.read_text(encoding="utf-8")
    start = text.index("ADD CONSTRAINT chk_calculation_type")
    return text[start : text.index(";", start)]


def test_코드_목록이_모델_CHECK와_같다() -> None:
    assert _values_from_check(_model_check_sql()) == CALCULATION_TYPES


def test_코드_목록이_DB_SCHEMA와_같다() -> None:
    assert _values_from_check(_doc_check_sql()) == CALCULATION_TYPES


def test_목록이_비어_있지_않다() -> None:
    """빈 튜플이면 위 둘이 **양쪽 다 비어도** 통과한다."""
    assert len(CALCULATION_TYPES) == 4


def test_해시_정규식이_DB_SCHEMA가_집행하는_것과_같다() -> None:
    """서비스의 형식 검사 ↔ `DB_SCHEMA §2.5` CHECK (`#1367`).

    글자가 다르면 **API가 받는데 INSERT가 튕기는** 구간(또는 그 반대)이 생긴다.
    """
    text = DB_SCHEMA.read_text(encoding="utf-8")
    documented = re.findall(r"CHECK \((?:input|parameter)_hash ~ '([^']+)'\)", text)

    assert documented, "DB_SCHEMA에서 해시 형식 CHECK를 찾지 못했다"
    assert set(documented) == {_HASH_PATTERN.pattern}
