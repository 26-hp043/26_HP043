"""불변성 가드가 NULL 열의 변경을 놓치고 있었다 (`#1058` · `#283`/`#944`의 계약)

Revision ID: 051
Revises: 050
Create Date: 2026-09-16

무엇이 통과하고 있었나
----------------------
``024``의 계약은 ``calculation_run``의 UPDATE 중 **``needs_recalc``가 0 → 1로 가면서 다른
열이 하나도 바뀌지 않은 경우**만 허용한다. ``a7d3e9b14f26``이 그것을 트리거로 옮길 때
nullable 열을 이렇게 비교했다::

    (new.c = obj.c) OR (new.c IS NULL AND obj.c IS NULL)

**한쪽만 NULL이면 이 식은 참도 거짓도 아니라 NULL이다.** 그리고 CUBRID의
``IF NOT (NULL) EXECUTE REJECT``는 **거부하지 않는다**(인계 v7 §7 실측 — CHECK와 같은
의미다). 그래서 NULL이던 열에 값을 넣거나 값이 있던 열을 NULL로 만드는 UPDATE가
**플립과 함께 그대로 통과했다.** 여덟 경우를 쟀다::

    플립만                              통과해야   통과
    플립 + duration_ms NULL→1           거부해야   통과   ← 🔴
    플립 + duration_ms 1→2              거부해야   거부
    플립 + duration_ms 1→NULL           거부해야   통과   ← 🔴
    플립 + warnings_json NULL→값        거부해야   통과   ← 🔴
    플립 + model_version 변경            거부해야   거부
    플립 아님(1→1)                       거부해야   거부

무엇이 어긋나는가
-----------------
``calculation_run``은 **재현성 계약**(``TECH_SPEC §5.4`` · ``DB_SCHEMA §7.3``)이다.
저장된 실행은 고칠 수 없어야 한다.

* ``warnings_json`` — 화면·리포트가 그 실행에 붙여 보여 주는 경고다. 나중에 지우거나
  넣을 수 있으면 **「그때 무슨 경고가 있었나」가 사실이 아니게 된다.**
* ``duration_ms`` — 성능 기록이다. 사후에 채워 넣으면 측정이 아니라 주장이 된다.

둘 다 nullable이라 **정확히 이 구멍에 걸린다.** 새로 만든 실행은 두 열이 NULL인 채로
저장되는 경우가 많아, 현실에서 가장 흔한 모양이 막히지 않고 있었다.

어떻게 고치는가 — NULL 갈래를 **손으로 적는다**
-----------------------------------------------
🔴 ``<=>``(NULL-safe 등호)로 가려다 **되돌렸다.** CUBRID는 ``SELECT``에서는 그것을
평가하지만 **트리거 조건 안에서는 못 한다** — 실측이다::

    SELECT (NULL <=> NULL), (1 <=> NULL), (1 <=> 1)     →  1   0   1      ← 된다

    CREATE TRIGGER … IF NOT (… new.id <=> obj.id …) EXECUTE REJECT       ← 문법은 통과
    UPDATE calculation_run SET needs_recalc = 1 WHERE id = …
      → DatabaseError: Error evaluating condition for
        "dba.trg_calcrun_immutable_update": Cannot evaluate 'new.id<=>obj.id'.
        (errno=-527)

**조건 평가가 실패하면 트리거가 전부 거부한다** — 구멍이 막히는 대신 `#283`이 쓰는
정상 플립까지 막혔다. 구멍보다 나쁜 상태다. 그래서 NULL 갈래를 명시적으로 적는다::

    (new.c IS NULL AND obj.c IS NULL)
      OR (new.c IS NOT NULL AND obj.c IS NOT NULL AND new.c = obj.c)

한쪽만 NULL이면 **거짓**이 되고(참도 거짓도 아닌 NULL이 아니다), 둘 다 NULL이면 참이다.
빈 표로 확인했다 — ``NOT (…)``이 ``거부한다``를 낸다. NOT NULL 열은 NULL이 될 수 없으니
``new.c = obj.c`` 그대로 둔다(문장이 길어지는 것을 막는다).

열 목록은 ``a7d3e9b14f26``에서 **읽어 온다**
--------------------------------------------
목록을 여기 다시 적으면 두 곳이 갈린다 — ``calculation_run``에 열이 늘 때 한쪽만 고치면
그 열이 조용히 수정 가능해진다. ``tests/test_constraint_triggers_db.py``가 쓰는 것과
**같은 방식**(glob + importlib)으로 원본 리비전에서 읽는다. 파일명을 박지 않는 이유도
같다 — 리비전 hex가 바뀌면 박아 둔 이름은 그 자리에서 죽는다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None

TRIGGER = "trg_calcrun_immutable_update"
TABLE = "calculation_run"


def _load_origin() -> ModuleType:
    """열 목록의 원본 리비전(``a7d3e9b14f26``)을 읽는다."""
    versions = Path(__file__).resolve().parent
    hits = sorted(versions.glob("*_restore_constraints_as_triggers.py"))
    if len(hits) != 1:
        raise RuntimeError(f"제약 복원 마이그레이션을 하나로 특정하지 못했습니다: {hits}")
    spec = importlib.util.spec_from_file_location("migration_constraints_origin", hits[0])
    if spec is None or spec.loader is None:
        raise RuntimeError(f"불러올 수 없습니다: {hits[0]}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _same(column: str, *, nullable: bool) -> str:
    """``obj``(갱신 전)와 ``new``(갱신 후)가 같은가 — **NULL에서도 참·거짓이 선다.**

    ``a7d3e9b14f26``의 ``_unchanged``와 다른 점은 한쪽만 NULL일 때다. 그쪽은
    ``new.c = obj.c OR (둘 다 NULL)``이라 NULL을 냈고, ``IF NOT (NULL)``은 거부하지
    않는다. 여기서는 ``IS NOT NULL``을 양쪽에 붙여 **거짓**이 되게 한다.
    """
    if not nullable:
        return f"new.{column} = obj.{column}"
    return (
        f"((new.{column} IS NULL AND obj.{column} IS NULL) "
        f"OR (new.{column} IS NOT NULL AND obj.{column} IS NOT NULL "
        f"AND new.{column} = obj.{column}))"
    )


def _null_safe_condition() -> str:
    """``needs_recalc``가 0 → 1이고 나머지가 그대로인가 — NULL이 섞여도 판정이 선다."""
    origin = _load_origin()
    parts = ["new.needs_recalc = 1", "obj.needs_recalc = 0"]
    parts += [_same(c, nullable=False) for c in origin.CALC_RUN_FROZEN_NOT_NULL]
    parts += [_same(c, nullable=True) for c in origin.CALC_RUN_FROZEN_NULLABLE]
    return " AND ".join(parts)


def _legacy_condition() -> str:
    """``a7d3e9b14f26``이 걸었던 조건 그대로 — ``downgrade``가 되돌릴 대상이다."""
    origin = _load_origin()
    parts = ["new.needs_recalc = 1", "obj.needs_recalc = 0"]
    parts += [origin._unchanged(c, nullable=False) for c in origin.CALC_RUN_FROZEN_NOT_NULL]
    parts += [origin._unchanged(c, nullable=True) for c in origin.CALC_RUN_FROZEN_NULLABLE]
    return " AND ".join(parts)


def upgrade() -> None:
    """지우고 다시 만든다 — 트리거 DDL은 `db/trigger_ddl.py`를 지난다 (`#1373`).

    지운 뒤에 만들므로 「있으면 건너뜀」에 걸리지 않는다. 지우지 못한 경우(같은 이름이
    둘 이상)에만 옛 조건이 남고, 그 상태는 `test_zz_roundtrip`의 중복 단언이 잡는다.
    """
    drop_trigger(op, TRIGGER)
    create_trigger(
        op,
        TRIGGER,
        f"BEFORE UPDATE ON {TABLE} IF NOT ({_null_safe_condition()}) EXECUTE REJECT",
    )


def downgrade() -> None:
    """종전 조건으로 되돌린다.

    **데이터를 한 행도 지우지 않는다** — ``migration_guard``의 세 분류 어디에도 넣지 않고
    ``guard_irreversible_downgrade``도 부르지 않는다(``a7d3e9b14f26``~``050``과 같은 판단).

    ⚠️ 되돌리면 위 표의 🔴 세 경우가 다시 통과한다.
    """
    drop_trigger(op, TRIGGER)
    create_trigger(
        op,
        TRIGGER,
        f"BEFORE UPDATE ON {TABLE} IF NOT ({_legacy_condition()}) EXECUTE REJECT",
    )
