"""``fuel_type.code`` 개명을 부모 쪽 트리거로 막는다 (#2260)

Revision ID: 068
Revises: 067
Create Date: 2026-10-07

무엇이 어긋나 있었나
--------------------
연료 코드 참조(``vessel.default_fuel_type`` · ``voyage_fuel_use.fuel_type`` ·
``not_underway_fuel_use.fuel_type``)는 FK가 아니라 **자식 쪽** 트리거 여섯이 지킨다
(``a7d3e9b14f26`` — CUBRID의 FK는 PK만 가리킬 수 있고 ``code``는 별도 UNIQUE다). 그래서
부모 쪽에는 아무 장치가 없었고, ``UPDATE fuel_type SET code = 'HFO_RENAMED' WHERE code = 'HFO'``
는 **막히지도 전파되지도 않았다** — 자식 행 36건이 없는 코드 ``HFO``를 그대로 가리켰다
(2026-10-07 ``cii_test`` head ``067`` 실측 · #2260). 문서는 「전파된다」(``DB_SCHEMA §7.1``)와
「막는다」(``§7.4`` 2항) 두 가지로 적는데 실제는 둘 다 아니었다.

어떻게 — 부모 쪽 ``BEFORE UPDATE``, ``code``가 바뀔 때만 거부
-----------------------------------------------------------
::

    CREATE TRIGGER trg_fuel_type_code_no_rename
      BEFORE UPDATE ON fuel_type IF new.code <> obj.code EXECUTE REJECT

* ``obj``가 갱신 전, ``new``가 갱신 후다(``a7d3e9b14f26`` ``trg_calcrun_immutable_update``와
  같은 모양 — CUBRID 상관명은 ``OLD``가 아니라 ``obj``).
* ``code``가 그대로인 UPDATE(``cf``·``display_name``·``is_active``·``version`` 갱신)는 조건이
  거짓이라 통과한다 — ``services/parameter_import._apply_fuel_types``의 제자리 갱신이 그 경로다.
* ``code``는 ``NOT NULL``이라 조건이 NULL이 되는 경우가 없다(``§7.4`` 5항의 구멍이 없다).

**참조 행이 있을 때만 막지 않고 무조건 막는다.** 조건에 세 표의 ``EXISTS``를 ``OR``로 잇는
형태가 문법상 불가능하지는 않지만(``a7d3e9b14f26``이 조건 안 ``EXISTS``를 쓴다) 그렇게 하지
않는 이유는 셋이다. ⑴ ``code``는 앱 전체가 연료를 부르는 **이름**이다 — 적재·seed·CF 조회가
전부 ``code``로 찾고, 계산 이력의 ``parameters_used``에도 문자열로 남는다. 자식 세 표에
참조가 없는 순간에도 그 이름을 바꾸면 이력과 어긋난다. ⑵ 코드를 바꾸는 앱 경로가 없다.
연료를 바꾸려면 **새 코드를 넣고 옛 코드를 ``is_active = 0``으로 끄는 것**이 정본의 운용이며
(``DB_SCHEMA §7.2``), 개명은 DB에 직접 SQL을 칠 때만 닿는 구멍이다. ⑶ 조건 없는 쪽이 거부
집합이 더 넓어 안전하고, 세 표를 묻는 조건은 표가 늘면 함께 늘려야 하는 열거가 된다.

기존 경로에 대한 영향
--------------------
* ``db/seed.py`` ``_upsert_fuel_types``는 ``REPLACE INTO``(``cubrid_replace``)이고 CUBRID의
  REPLACE는 **DELETE + INSERT**로 동작한다(``a7d3e9b14f26`` 주석 · seed 재실행 시 ``id``가 바뀌는
  것으로 확인). UPDATE가 아니므로 이 트리거에 걸리지 않는다.
* ``services/parameter_import._apply_fuel_types``는 ``code``로 찾은 행의 다른 열만 바꾼다 —
  ``code``는 그대로라 통과한다.
* ``demo_seed``는 ``fuel_type``을 쓰지 않는다(``default_fuel_type``은 NULL · 연료 행은 읽기만).
* 부모 쪽 **DELETE**는 여전히 막지 않는다 — REPLACE 때문에 막을 수 없다는 판단(``a7d3e9b14f26``)은
  그대로이고, ``test_parent_side_delete_is_deliberately_not_guarded``가 그 상태를 고정한다.

downgrade
---------
트리거 하나를 지운다. 데이터를 한 행도 바꾸지 않으므로 ``migration_guard``의 세 분류 어디에도
넣지 않는다(``a7d3e9b14f26``·``066``·``067``과 같은 판단). ``DB_SCHEMA §7.4`` 합계 176 → **177**.
"""

from __future__ import annotations

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None

#: 부모 쪽 개명 거부 트리거의 이름. 이 REJECT(errno ``-517``)는 ``db/cubrid_errors.py``가
#: ``IntegrityError``로 옮긴다 — 옮기지 않는 것은 이름에 ``IMMUTABILITY_TRIGGER_MARKS``
#: (``_no_delete``·``_immutable_``)가 든 트리거뿐이고, 이 이름에는 그 표식이 없다.
#: 참조 정합 위반이라 PostgreSQL FK의 ``RESTRICT`` 위반과 같은 갈래로 받는 것이 맞다.
TRIGGER_NAME = "trg_fuel_type_code_no_rename"

#: ``code``가 바뀌는 UPDATE만 거부한다. ``code``는 NOT NULL이라 조건이 NULL이 되지 않는다.
TRIGGER_BODY = "BEFORE UPDATE ON fuel_type IF new.code <> obj.code EXECUTE REJECT"


def upgrade() -> None:
    """부모 쪽 개명 거부 트리거를 건다 — 이미 있으면 만들지 않는다(``#1373``)."""
    create_trigger(op, TRIGGER_NAME, TRIGGER_BODY)


def downgrade() -> None:
    """트리거만 지운다 — 없으면 지우지 않는다. 데이터는 한 행도 바꾸지 않는다."""
    drop_trigger(op, TRIGGER_NAME)
