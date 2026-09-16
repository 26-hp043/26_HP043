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

## 무엇을 하지 않는가

**모든 트리거 거부를 옮기지 않는다.** 이름이 ``trg_chk_``·``trg_uq_``로 시작하는 것,
즉 **제약을 대신하는 트리거**만 옮긴다.

옮기지 않는 것은 성질이 다르다 — 이것들은 무결성 위반이 아니라 **금지된 연산**이다.

* ``trg_calcrun_immutable_update`` · ``trg_snapshot_no_delete`` — 불변성(`#824`).
  「값이 틀렸다」가 아니라 「이 연산은 허용되지 않는다」이고,
  ``tests/test_calc_run_needs_recalc_db.py``가 ``DBAPIError``로 받는다.
* ``trg_vessel_fuel_type_ref`` 등 참조 정합 3건 — FK 대용이라 성격은 무결성에 가깝지만,
  옮기면 ``DatabaseError``로 받는 기존 검사가 깨진다. 지금은 건드리지 않는다.

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

#: 제약을 대신하는 트리거의 이름 앞머리. 이 트리거가 거부한 것만 옮긴다.
CONSTRAINT_TRIGGER_PREFIXES: tuple[str, ...] = ("trg_chk_", "trg_uq_")

#: 거부 메시지에서 트리거 이름을 집는다. 이름 앞에 스키마(``dba.``)가 붙는다.
_REJECTED = re.compile(
    r'rejected by trigger "(?:[^".]+\.)?(?P<name>[^"]+)"',
    re.IGNORECASE,
)


def _rejected_trigger_name(exception: BaseException | None) -> str | None:
    if exception is None:
        return None
    m = _REJECTED.search(str(exception))
    return m.group("name") if m else None


@event.listens_for(Engine, "handle_error")
def _translate_constraint_trigger_rejection(context: Any) -> Any:
    """제약 트리거의 거부를 ``IntegrityError``로 바꿔 올린다.

    ``handle_error``에서 예외를 **반환**하면 SQLAlchemy가 그것을 대신 올린다.
    ``None``을 반환하면 원래 예외가 그대로 간다.
    """
    name = _rejected_trigger_name(context.original_exception)
    if name is None or not name.startswith(CONSTRAINT_TRIGGER_PREFIXES):
        return None

    return IntegrityError(
        context.statement,
        context.parameters,
        context.original_exception,
    )
