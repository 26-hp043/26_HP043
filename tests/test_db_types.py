"""CUBRID 호환 커스텀 타입의 계약 (#1058 · ``db/types.py``).

**이 모듈에는 검사가 하나도 없었다.** `#1058`이 PostgreSQL 전용 타입 둘
(``JSONB``·``UUID``)을 파이썬 쪽 타입으로 옮겼는데, 옮긴 자리의 입출력 계약을 잠근 곳이
없어 **입력 관용도가 조용히 좁아진 것을 아무도 보지 못했다** — 2026-09-15 전체 pytest에서
`59건`이 `'str' object has no attribute 'hex'` 한 줄로 떨어지고 나서야 드러났다.

여기서 고정하는 것은 셋이다.

1. :class:`UuidText`가 **``str``을 받는다** — 전환 전 ``postgresql.UUID(as_uuid=True)``는
   psycopg가 문자열을 받아 줬다. 되돌린 것이지 넓힌 것이 아니다.
2. 그러면서도 **아무 문자열이나 통과시키지 않는다** — 파싱 못 하면 ``ValueError``다.
3. **저장 모양이 바뀌지 않는다** — ``impl``이 :class:`sqlalchemy.Uuid` 그대로라 DDL이
   ``CHAR(32)``로 같고 **마이그레이션이 필요 없다.** 이것이 깨지면 스키마가 갈린다.

DB가 필요 없다 — bind processor를 직접 불러 본다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — CUBRID 타입 계약)
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from cii_platform.db.types import JSONText, UuidText

#: CUBRID 방언과 같은 계열(네이티브 UUID가 없어 ``CHAR(32)``로 간다).
_DIALECT = mysql.dialect()

_SAMPLE = uuid.UUID("00000000-0000-4000-8000-000000000301")


def _uuid_bind(value: object) -> object:
    return UuidText().bind_processor(_DIALECT)(value)


# ---------------------------------------------------------------------------
# UuidText — 받는 것
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [_SAMPLE, str(_SAMPLE), _SAMPLE.hex, str(_SAMPLE).upper()],
    ids=["uuid", "dashed-str", "hex-str", "upper-str"],
)
def test_all_accepted_forms_store_the_same_value(value: object):
    """UUID·대시 문자열·hex 문자열·대문자가 **같은 값**으로 저장된다.

    형태에 따라 다른 값이 들어가면 같은 대상을 가리키는 행이 둘이 된다.
    """
    assert _uuid_bind(value) == _SAMPLE.hex


def test_none_passes_through():
    """NULL은 그대로 간다 — nullable 컬럼이 여럿이다."""
    assert _uuid_bind(None) is None


def test_plain_uuid_still_works():
    """``uuid.UUID``를 넘기던 기존 호출부가 그대로 동작한다."""
    assert _uuid_bind(_SAMPLE) == _SAMPLE.hex


# ---------------------------------------------------------------------------
# UuidText — 받지 않는 것
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "not-a-uuid", "12345", "sha256:" + "0" * 64])
def test_unparseable_values_raise_value_error(value: str):
    """아무 문자열이나 통과시키지 않는다.

    ``ValueError``인 것이 중요하다 — 종전 ``AttributeError``('str' object has no
    attribute 'hex')는 **무엇이 틀렸는지 말하지 않는다.**
    """
    with pytest.raises(ValueError):
        _uuid_bind(value)


# ---------------------------------------------------------------------------
# 저장 모양 — 이것이 깨지면 마이그레이션이 필요해진다
# ---------------------------------------------------------------------------


def test_impl_is_sqlalchemy_uuid_so_the_ddl_does_not_change():
    """``impl``이 :class:`sqlalchemy.Uuid` 그대로다.

    이 타입은 **입력 관용도만** 되돌린다. ``impl``을 바꾸면 DDL이 달라져
    **기존 DB와 갈린다** — 그때는 마이그레이션이 필요하고, 이 검사가 먼저 실패한다.
    """
    assert UuidText.impl is sa.Uuid


def test_ddl_matches_plain_uuid():
    """생성되는 컬럼 타입이 ``sa.Uuid``와 같다."""
    plain = sa.Uuid().compile(dialect=_DIALECT)
    ours = UuidText().compile(dialect=_DIALECT)
    assert str(ours) == str(plain)


# ---------------------------------------------------------------------------
# JSONText — 같은 모듈의 다른 타입. 여기도 검사가 없었다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [{"a": 1}, [1, 2, 3], {"한글": "값"}, {"nested": {"x": [1, {"y": None}]}}],
    ids=["dict", "list", "korean", "nested"],
)
def test_json_round_trips(value: object):
    """쓰고 읽으면 같은 값이 나온다."""
    t = JSONText()
    stored = t.process_bind_param(value, _DIALECT)
    assert isinstance(stored, str)
    assert t.process_result_value(stored, _DIALECT) == value


def test_json_keeps_korean_readable():
    """``ensure_ascii=False`` — 저장된 문자열에 한글이 그대로 있다.

    ``\\uD55C`` 이스케이프로 들어가면 DB에서 눈으로 읽을 수 없고 길이도 늘어난다.
    """
    stored = JSONText().process_bind_param({"선종": "벌크선"}, _DIALECT)
    assert "벌크선" in stored


def test_json_none_passes_through():
    """NULL은 그대로 간다 — ``warnings_json``이 nullable이다."""
    t = JSONText()
    assert t.process_bind_param(None, _DIALECT) is None
    assert t.process_result_value(None, _DIALECT) is None


def test_json_does_not_double_encode():
    """이미 문자열인 값을 넣으면 **JSON 문자열로** 감싼다 — 이중 인코딩의 모양이다.

    읽어 오면 ``dict``가 아니라 ``str``이 나와 호출부가 ``.get``에서 선다. 미리
    ``json.dumps``한 값을 이 컬럼에 넣으면 안 된다는 것을 이 검사가 기록한다.
    """
    t = JSONText()
    pre_serialized = json.dumps({"a": 1})
    stored = t.process_bind_param(pre_serialized, _DIALECT)

    assert t.process_result_value(stored, _DIALECT) == pre_serialized
    assert not isinstance(t.process_result_value(stored, _DIALECT), dict)
