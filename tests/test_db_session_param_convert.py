"""운영 엔진의 CUBRID 파라미터 변환 훅 (`#1058` · `#955`).

## 왜 이 파일이 있는가

`cii_platform.db.session.cubrid_param_convert`는 **배포 엔진에만** 붙는
``before_cursor_execute`` 훅이다. 그런데 검사는 `tests/conftest.py`가 붙이는 **제
변환기**를 쓰는 엔진으로 돈다 — 그래서 이 함수는 전 검사(2,500여 건)에서 **한 번도
돌지 않았다.** 커버리지 하한 게이트가 그것을 `db/session.py 78.6%`로 가리켰고, 그 미커버
구간(52-62)이 정확히 이 훅이었다.

🔴 **그 갈라짐은 이미 한 번 결함을 냈다.** `conftest` 쪽 변환기가 모든 ``datetime``을 초로
깎고 타임존을 떼고 있었는데 운영에는 그 이벤트가 붙지 않아, **검사가 없는 결함을 만들어
내고** 있었다(`2538271`). 두 변환기가 갈리면 검사는 초록인데 운영이 깨지거나, 그 반대가
된다. 여기서는 **운영 쪽 규칙 자체**를 못 박는다.

## 무엇을 못 박는가

⑴ `uuid.UUID` → 저장 형식(hex 32자) ⑵ `Decimal` → `str` ⑶ 그 밖의 값은 **손대지 않는다**
(특히 ``datetime`` — 손대면 밀리초가 사라진다) ⑷ `CAST(? AS 타입)` → `?`
⑸ `IS 0`/`IS 1` → `= 0`/`= 1`.

⚠️ 훅은 엔진 없이 **직접 부른다.** 엔진을 만들면 `DATABASE_URL`에 매이고, 확인하려는 것은
연결이 아니라 **변환 규칙**이다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from cii_platform.db.session import cubrid_param_convert


def _convert(statement: str, parameters):
    """훅의 여섯 인자 중 이 함수가 쓰지 않는 넷은 ``None``으로 넘긴다."""
    return cubrid_param_convert(None, None, statement, parameters, None, False)


def test_uuid_becomes_the_stored_hex_form():
    """`UUID`는 저장 형식(hex 32자)으로 간다 — 대시가 남으면 어느 행과도 맞지 않는다."""
    value = uuid.UUID("00000000-0000-4000-8000-000000000301")

    _, params = _convert("SELECT 1", (value,))

    assert params == ("00000000000040008000000000000301",)


def test_decimal_becomes_a_string():
    """`Decimal`은 문자열로 간다 — pycubrid가 `Decimal`을 그대로 받지 않는다."""
    _, params = _convert("SELECT 1", (Decimal("1145.8333"),))

    assert params == ("1145.8333",)


def test_datetime_is_left_alone():
    """🔴 `datetime`은 **건드리지 않는다.**

    `conftest` 쪽 변환기가 여기서 `strftime("%Y-%m-%d %H:%M:%S")`를 해 밀리초를 깎고
    타임존을 뗐고, 그 탓에 검사만 `created_at` 5건이 깨졌다(`2538271`). 운영 훅이 같은
    일을 하기 시작하면 **이번에는 진짜로** 밀리초가 사라진다.
    """
    moment = datetime(2026, 9, 16, 5, 7, 21, 697000, tzinfo=UTC)

    _, params = _convert("SELECT 1", (moment,))

    assert params == (moment,)


def test_other_values_pass_through():
    """문자열·정수·`None`은 그대로 간다."""
    _, params = _convert("SELECT 1", ("HFO", 12, None))

    assert params == ("HFO", 12, None)


def test_empty_parameters_are_not_touched():
    """파라미터가 없으면 그대로 돌려준다 — 빈 튜플을 채우지 않는다."""
    _, params = _convert("SELECT 1", ())

    assert params == ()


def test_dict_parameters_are_not_rewritten():
    """딕셔너리 파라미터는 손대지 않는다 — 변환은 위치 인자 경로만 본다."""
    given = {"id": uuid.uuid4()}

    _, params = _convert("SELECT 1", given)

    assert params is given


def test_cast_placeholder_is_unwrapped():
    """`CAST(? AS 타입)` → `?`. CUBRID가 이 캐스트를 받지 못하는 자리가 있다."""
    statement, _ = _convert(
        "INSERT INTO t (a, b) VALUES (CAST(? AS jsonb), CAST(? AS uuid))", ("{}", "x")
    )

    assert statement == "INSERT INTO t (a, b) VALUES (?, ?)"


def test_a_real_cast_of_a_column_is_left_alone():
    """열을 캐스트하는 것은 그대로 둔다 — 떼어 내는 것은 **자리표시자**뿐이다."""
    statement, _ = _convert("SELECT CAST(n AS INT) FROM t", ())

    assert statement == "SELECT CAST(n AS INT) FROM t"


def test_is_boolean_literal_becomes_equals():
    """`IS 0`/`IS 1` → `= 0`/`= 1`. CUBRID에서 `IS`의 오른쪽은 NULL·TRUE·FALSE만 온다."""
    statement, _ = _convert("SELECT 1 FROM t WHERE a IS 0 AND b IS 1", ())

    assert statement == "SELECT 1 FROM t WHERE a = 0 AND b = 1"


def test_is_null_is_left_alone():
    """`IS NULL`은 그대로 둔다 — 바꾸면 **NULL 비교가 영원히 거짓**이 된다."""
    statement, _ = _convert("SELECT 1 FROM t WHERE a IS NULL AND b IS NOT NULL", ())

    assert statement == "SELECT 1 FROM t WHERE a IS NULL AND b IS NOT NULL"


def test_the_hook_is_registered_on_the_engine():
    """훅이 **실제로 엔진에 붙는지**까지 본다.

    규칙만 검사하고 등록을 보지 않으면, 등록 한 줄이 사라져도 이 파일은 초록이다.
    """
    from sqlalchemy import event

    from cii_platform.db.session import get_engine

    engine = get_engine()

    assert event.contains(engine.sync_engine, "before_cursor_execute", cubrid_param_convert)


def test_rewrites_leave_an_observability_trace(caplog):
    """치환은 흔적을 남긴다 (#1246) — 예상 밖 문장에 닿는 순간을 잡는 수단.

    정규식 리라이팅은 dialect가 못 내는 문장을 앱이 고쳐 쓰는 것이다. 몇 번 일어나는지
    보이지 않으면 ORM이 문장 형태를 바꾸는 순간 조용히 깨진다.
    """
    import logging

    with caplog.at_level(logging.DEBUG, logger="cii_platform.db.session"):
        statement, _ = _convert("SELECT 1 FROM t WHERE a = CAST(? AS VARCHAR) AND b IS 1", ())

    assert statement == "SELECT 1 FROM t WHERE a = ? AND b = 1"
    message = next(
        r.getMessage() for r in caplog.records if "cubrid_param_convert" in r.getMessage()
    )
    assert "cast=1" in message
    assert "bool=1" in message


def test_clean_statements_are_not_logged(caplog):
    """치환이 없으면 로그도 없다 — 운영 로그가 문장으로 시끄러워지지 않는다."""
    import logging

    with caplog.at_level(logging.DEBUG, logger="cii_platform.db.session"):
        _convert("SELECT 1 FROM t WHERE a = ?", ())

    assert not [r for r in caplog.records if "cubrid_param_convert" in r.getMessage()]
