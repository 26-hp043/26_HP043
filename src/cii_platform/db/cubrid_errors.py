"""CUBRID가 트리거로 강제하는 제약 위반을 ``IntegrityError``로 올린다 (`#1058`).

## 왜 필요한가

**CUBRID 11.4.6은 CHECK 제약을 구문으로 받기만 하고 검사하지 않는다** — 실측이며,
마이그레이션 ``a7d3e9b14f26``의 docstring이 그 측정을 담고 있다. 그래서 값 범위
제약은 ``046``이 **트리거**로 되살렸다.

그런데 트리거가 거부할 때 드라이버가 내는 예외가 다르다. 실측이다::

    INSERT INTO fuel_type … VALUES (…, -1, …)
    → pycubrid.exceptions.DatabaseError:
      The operation has been rejected by trigger "dba.trg_chk_cf_positive_ins".
      (errno=-517)

PostgreSQL에서 같은 위반은 ``IntegrityError``였다. SQLAlchemy는 DBAPI 예외 **클래스**로
갈래를 정하므로, 손대지 않으면 종전에 ``IntegrityError``를 잡던 자리가 전부 빗나간다 —
``sqlalchemy.exc.IntegrityError``는 ``DatabaseError``의 하위 클래스라 **반대 방향으로는
잡히지 않는다.**

## 무엇을 옮기는가

PostgreSQL이 ``IntegrityError``로 올리던 것과 **같은 집합**을 옮긴다. 드라이버 errno를
실측해 갈랐다.

====== ====================================================== ======================
errno  CUBRID 메시지                                           PostgreSQL에서
====== ====================================================== ======================
-517   ``rejected by trigger "…"``                            CHECK · FK 위반
-922   ``The constraint of the foreign key … is invalid``      FK 위반
-924   ``Update/Delete operations are restricted by the …``    FK RESTRICT
-225   ``Missing value for attribute "…"``                     NOT NULL 위반
====== ====================================================== ======================

트리거 거부(-517)는 **제약을 대신하는 트리거만** 옮긴다. `a7d3e9b14f26`·`046`·`047`이
건 트리거는 전부 CHECK 아니면 FK 대용이므로 **기본이 「옮긴다」**이고, 성질이 다른 것만
:data:`IMMUTABILITY_TRIGGER_MARKS`로 뺀다.

## 무엇을 하지 않는가

**불변성 트리거는 옮기지 않는다** — ``trg_calcrun_no_delete`` ·
``trg_snapshot_immutable_update`` 따위(`#824`). 「값이 틀렸다」가 아니라 **「이 연산은
허용되지 않는다」**이고, PostgreSQL에서도 이것들은 트리거가 올리는 예외라
``IntegrityError``가 아니었다. ``tests/test_calc_run_needs_recalc_db.py``가
``DBAPIError``로 받는데, ``IntegrityError``도 그 하위라 옮겨도 검사는 통과한다 —
**통과하니까가 아니라 성질이 다르니까** 빼는 것이다.

## 왜 엔진 하나가 아니라 클래스에 거는가

``Engine`` 클래스에 걸어 **이 프로세스가 만드는 모든 엔진**에 적용한다. 앱 엔진
(:func:`cii_platform.db.session.get_engine`)과 검사·마이그레이션·시드가 저마다 엔진을
만드는데, 이것은 앱 정책이 아니라 **드라이버 차이를 메우는 보정**이라 한 곳이라도
빠지면 같은 위반이 자리마다 다른 예외로 온다.

패키지 ``cii_platform.db``를 임포트하면 등록된다(``__init__``이 이 모듈을 부른다).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

#: 무결성 위반으로 옮기는 CUBRID errno. 위 표의 근거는 실측이다.
INTEGRITY_ERRNOS: frozenset[int] = frozenset({-517, -922, -924, -225})

#: 이 조각이 이름에 들어간 트리거의 거부는 **옮기지 않는다** — 불변성이다.
IMMUTABILITY_TRIGGER_MARKS: tuple[str, ...] = ("_no_delete", "_immutable_")

#: 거부 메시지에서 트리거 이름을 집는다. 이름 앞에 스키마(``dba.``)가 붙는다.
_REJECTED = re.compile(
    r'rejected by trigger "(?:[^".]+\.)?(?P<name>[^"]+)"',
    re.IGNORECASE,
)

#: ``(errno=-517, sqlstate='HY000')``에서 숫자를 집는다.
_ERRNO = re.compile(r"errno=(?P<errno>-?\d+)")


def _errno(exception: BaseException | None) -> int | None:
    if exception is None:
        return None
    m = _ERRNO.search(str(exception))
    return int(m.group("errno")) if m else None


def _rejected_trigger_name(exception: BaseException | None) -> str | None:
    if exception is None:
        return None
    m = _REJECTED.search(str(exception))
    return m.group("name") if m else None


def _is_integrity_violation(exception: BaseException | None) -> bool:
    """PostgreSQL이 ``IntegrityError``로 올렸을 위반인가."""
    if _errno(exception) not in INTEGRITY_ERRNOS:
        return False

    name = _rejected_trigger_name(exception)
    if name is None:
        return True  # 트리거가 아닌 FK·NOT NULL 위반

    return not any(mark in name for mark in IMMUTABILITY_TRIGGER_MARKS)


@event.listens_for(Engine, "handle_error")
def _translate_constraint_violation(context: Any) -> Any:
    """제약 위반을 ``IntegrityError``로 바꿔 올린다.

    ``handle_error``에서 예외를 **반환**하면 SQLAlchemy가 그것을 대신 올린다.
    ``None``을 반환하면 원래 예외가 그대로 간다.
    """
    if isinstance(context.sqlalchemy_exception, IntegrityError):
        return None  # 드라이버가 이미 제대로 갈랐다
    if not _is_integrity_violation(context.original_exception):
        return None

    return IntegrityError(
        context.statement,
        context.parameters,
        context.original_exception,
    )
