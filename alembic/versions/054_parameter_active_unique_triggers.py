"""파라미터 개정 적재 경로를 여는 스키마 정리 (#673)

Revision ID: 054
Revises: 053
Create Date: 2026-09-18

무엇이 막혀 있었나
------------------
``DB_SCHEMA §7.2``는 파라미터 개정을 **새 ``version`` 행을 넣고 ``is_active``를
전환**하는 것으로 정한다(``#98``). 그런데 실제 스키마는 그 정책을 지지하지
않았다 — 둘 갈래였다:

1. ``cii_reference_line``·``cii_rating_boundary``에는 ``version``·``is_active``
   **컬럼 자체가 없다**(실측 — ``db_attribute`` 조회). 정책이 적힐 때부터 이 두
   테이블에서는 물리적으로 불가능했다.
2. ``regulation_year``·두 테이블의 키에 **전역 UNIQUE 인덱스**가 걸려 있어 같은
   키의 이행 행을 만들 수 없었다::

       regulation_year      UNIQUE(year)                      — uq_regulation_year_year
       cii_reference_line   UNIQUE(ship_type, condition_expr) — idx_refline_unique
       cii_rating_boundary  UNIQUE(ship_type, condition_expr) — idx_boundary_unique

지금까지 문제가 없었던 것은 **쓰는 경로 자체가 없었기 때문이다**(`#444` · `#673`).
``POST /parameters/import``를 여는 PR과 함께 이 모순을 푼다.

해법
----
⑴ 두 테이블에 ``version``·``is_active``를 추가한다. 기존 행은 **현행**이므로
``is_active = 1``이 맞는 초깃값이다(기본값으로 얻는다).

⑵ 전역 UNIQUE를 빼고 **활성 행끼리만** 유일성을 집행하는 트리거로 바꾼다 —
``050`` ⑴이 ``snapshot_id``에 쓴 패턴이다. CUBRID는 부분 유니크 인덱스를 만들
수 없으므로(``047`` 실측) 트리거가 유일성을 가진다::

    IF EXISTS (SELECT 1 FROM <테이블>
               WHERE <키> = new.<키> AND is_active = 1 AND id <> new.id)
    EXECUTE REJECT

``id <> new.id``는 UPDATE에서 자기 자신을 빼는 조건이다. INSERT에서는 새 ``id``를
가진 행이 아직 없으므로 항상 참이 된다.

``fuel_type``은 건드리지 않는다
-------------------------------
``DB_SCHEMA §7.2``가 ``fuel_type``을 **명시적 예외**로 둔다 — ``parameter_hash``
계약(``TECH_SPEC §5.2``)이 CF 값의 **제자리 갱신 추적**을 요구하고 ``content_hash``와
``updated_at``이 그 역할을 한다. ``UNIQUE(code)``는 그 운용과 충돌하지 않는다.

Boolean은 SHORT다
-----------------
``is_active``를 ``sa.Boolean``로 선언해도 CUBRID에서는 ``SHORT``로 저장된다(
``a7d3e9b14f26``·``047`` 실측). 여기서 raw SQL을 쓰므로 ``SHORT``로 적는다 —
선언(ORM)과 집행(마이그레이션)이 같은 타입을 가리키게 한다.
"""

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


#: ⑴ — ``version``·``is_active``가 없어서 개정 정책을 못 따르던 테이블.
VERSIONED_COLUMNS_TABLES: tuple[str, ...] = ("cii_reference_line", "cii_rating_boundary")


#: ⑵ — (테이블, 지우는 UNIQUE 인덱스, 유일성의 키 열).
#:
#: ``year``는 CUBRID 예약어라 SQL에서 반드시 겹따옴표로 감싼다(실측 — ``csql``이
#: ``ERROR: invalid use of year``로 거부한다).
ACTIVE_UNIQUE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("regulation_year", "uq_regulation_year_year", ('"year"',)),
    ("cii_reference_line", "idx_refline_unique", ("ship_type", "condition_expr")),
    ("cii_rating_boundary", "idx_boundary_unique", ("ship_type", "condition_expr")),
)

_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")


def _trigger_name(table: str, event: str) -> str:
    """``050``의 이름 규칙과 같다 — 이벤트 접두사는 앞 세 글자."""
    return f"trg_{table}_active_unique_{event.lower()[:3]}"


def _condition(table: str, keys: tuple[str, ...]) -> str:
    joined = " AND ".join(f"{key} = new.{key}" for key in keys)
    return f"EXISTS (SELECT 1 FROM {table} WHERE {joined} AND is_active = 1 AND id <> new.id)"


def upgrade() -> None:
    for table in VERSIONED_COLUMNS_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN version VARCHAR(50) NOT NULL DEFAULT '1.0'")
        op.execute(f"ALTER TABLE {table} ADD COLUMN is_active SHORT NOT NULL DEFAULT 1")

    for table, index, keys in ACTIVE_UNIQUE:
        # `op.drop_index`가 아니라 `op.execute`로 — alembic이 내는 `DROP INDEX <이름>`은
        # PostgreSQL 문법이고 CUBRID는 테이블을 함께 적어야 한다(`047`·`050` 실측).
        op.execute(f"DROP INDEX {index} ON {table}")
        # 이미 있으면 만들지 않는다 (`#1373` · `db/trigger_ddl.py`).
        for event in _EVENTS:
            create_trigger(
                op,
                _trigger_name(table, event),
                f"BEFORE {event} ON {table} IF {_condition(table, keys)} EXECUTE REJECT",
            )


def downgrade() -> None:
    """건 것만 되돌린다.

    ⚠️ **되돌리는 순간 개정 이행 행이 있으면 UNIQUE 재생성이 그 자리에서 실패한다** —
    같은 키의 행이 둘 이상 남아 있기 때문이다. 조용히 한쪽을 지우지 않는다.
    무엇을 지울지는 사람이 정할 일이다(``050`` downgrade와 같은 판단). 이행 행을
    정리한 뒤에만 내릴 수 있다는 뜻에서 데이터 변경은 하지 않는다 — 컬럼 추가는
    되돌리되 그 값(현행 ``is_active = 1``)은 날아간다.
    """
    for table, index, keys in ACTIVE_UNIQUE:
        # 없으면 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
        for event in _EVENTS:
            drop_trigger(op, _trigger_name(table, event))
        op.execute(f"CREATE UNIQUE INDEX {index} ON {table} ({', '.join(keys)})")

    for table in VERSIONED_COLUMNS_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN is_active")
        op.execute(f"ALTER TABLE {table} DROP COLUMN version")
