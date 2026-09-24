"""전환에서 사라진 제약을 CUBRID에서 강제되는 형태로 되살린다 (#1058).

**CUBRID 11.4.6은 CHECK 제약을 구문으로 받기만 하고 검사하지 않는다.** 실측이다.

    CREATE TABLE _t2 (n INT, CONSTRAINT chk_n CHECK (n > 0))   → Committed
    INSERT INTO _t2 VALUES (-5)                                → row affected
    SELECT n FROM _t2                                          → -5

그래서 CHECK로 되돌려 놓아도 아무것도 막지 못한다. **트리거는 실제로 막는다** —
같은 방식으로 확인했다.

**FK도 이 세 건에는 쓸 수 없다.** CUBRID의 FK는 참조 대상이 **PK여야** 한다.

    ALTER TABLE vessel ADD CONSTRAINT fk_vessel_default_fuel_type
      FOREIGN KEY (default_fuel_type) REFERENCES fuel_type(code)
    → ERROR: The foreign key 'fk_vessel_default_fuel_type' does not include
             the primary key member 'id'.  (errno=-920)

`fuel_type`은 PK가 `id`이고 `code`는 **별도 UNIQUE**(`uq_fuel_type_code`)라 대상이 되지
못한다. 빈 테이블로 재현해 확인했다 — PK가 아닌 UNIQUE를 가리키면 같은 오류다. 그래서
세 건도 **트리거**로 건다. 트리거 조건의 `EXISTS` 서브쿼리는 동작한다(확인함).

## 무엇을 되살리는가

전환 분기점(`0f4b062`)의 ORM 모델과 지금을 대조해 **사라진 것은 CHECK 6 · FK 3**이다.
그중 **재현성 계약(`TECH_SPEC §5.4`)과 참조 정합에 직결되는 9가지**를 되살린다.

* **해시 형식 4** — `calculation_run`·`simulation_snapshot`의 `input_hash`·`parameter_hash`.
  `sha256:` + 64 hex(`DB_SCHEMA §2.5` 원문). 형식이 깨진 해시가 들어가면 **그 실행은
  영영 재현 대조를 할 수 없다** — 저장 뒤에는 immutable이라 고칠 수도 없다.
* **참조 정합 3** — `vessel`·`voyage_fuel_use`·`not_underway_fuel_use`의
  `fuel_type → fuel_type.code`. 없는 연료 코드가 들어가면 CF를 못 찾아 계산이 조용히
  틀린다. **FK로 걸 수 없어**(위 참조) 자식 쪽 INSERT·UPDATE를 트리거로 막는다.
  **부모 쪽 DELETE는 막지 못한다** — `REPLACE INTO`가 DELETE로 구현돼 재적재가 걸린다
  (`upgrade()` 주석 참조).
* **불변성 2** — `calculation_run`·`simulation_snapshot`의 UPDATE·DELETE 차단.
  **이것이 지금 하나도 없다** — 전환 뒤 이 DB의 트리거는 **0개**였다.

## `calculation_run`은 전면 불변이 아니다

`024`가 정한 계약 그대로다 — DELETE는 언제나 거부하고, UPDATE는 **`needs_recalc`가
0 → 1로 가면서 다른 열이 하나도 바뀌지 않은 경우**만 통과한다(`#283`·`#944`가 서비스에서
그 플립만 한다). PostgreSQL 쪽은 `to_jsonb(NEW) - 'needs_recalc'` 비교로 그것을 적었는데
CUBRID에는 그 연산이 없어 **열을 열거**한다. 열이 늘면 이 조건도 함께 늘려야 한다 —
빠뜨리면 그 열이 조용히 수정 가능해진다. `tests/test_constraint_triggers_db.py`가
열 목록을 스키마와 대조해 그것을 잡는다.

## CUBRID에서 달라진 것

* 상관명이 `OLD`가 아니라 **`obj`**다(`old`는 「Attribute "old" was not found」로 선다).
* **`ON UPDATE CASCADE`를 지원하지 않는다.** 분기점의 세 FK는 전부
  `onupdate="CASCADE", ondelete="NO ACTION"`이었는데, CUBRID는 참조 동작 절을 붙이면
  구문 오류를 낸다. 기본값(제한)으로 건다 — 연료 코드를 개명하면 전파되는 대신
  **막힌다.** 여는 쪽이 아니라 닫는 쪽으로 다른 것이라 그대로 둔다.
* `needs_recalc`는 `BOOLEAN`이 아니라 `SMALLINT`라 `= 1`·`= 0`으로 비교한다.

`1c444a5c4819`(교수님 파일)를 고치지 않고 뒤에 새 리비전으로 붙인다 —
`6c7496c4d122`(부트스트랩)와 같은 방식이다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, existing_triggers

revision: str = "a7d3e9b14f26"
down_revision: str | Sequence[str] | None = "6c7496c4d122"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `DB_SCHEMA §2.5` [S-7] 원문 — `sha256:` + 64 hex.
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: (트리거 이름 앞머리, 테이블, 열) — 분기점 모델의 `fuel_type` 참조 3건.
#: 원래 이름은 `fk_vessel_default_fuel_type`·`fk_voyage_fuel_use_fuel_type`·
#: `fk_not_underway_fuel_use_fuel_type`였다. FK로 걸 수 없어 트리거로 바꾸므로
#: 이름도 `trg_`로 바꾼다 — `db_index`에 없는데 `fk_`로 부르면 다음 사람이 찾다 못 찾는다.
FUEL_TYPE_REFS: tuple[tuple[str, str, str], ...] = (
    ("trg_vessel_fuel_type_ref", "vessel", "default_fuel_type"),
    ("trg_voyage_fuel_use_fuel_type_ref", "voyage_fuel_use", "fuel_type"),
    ("trg_nu_fuel_use_fuel_type_ref", "not_underway_fuel_use", "fuel_type"),
)

#: (트리거 이름, 테이블, 열) — 해시 형식 4건.
HASH_TRIGGERS: tuple[tuple[str, str, str], ...] = (
    ("trg_calcrun_input_hash_format", "calculation_run", "input_hash"),
    ("trg_calcrun_param_hash_format", "calculation_run", "parameter_hash"),
    ("trg_snap_input_hash_format", "simulation_snapshot", "input_hash"),
    ("trg_snap_param_hash_format", "simulation_snapshot", "parameter_hash"),
)

#: `calculation_run`에서 `needs_recalc`를 뺀 전 열. 스키마가 늘면 여기도 늘린다.
CALC_RUN_FROZEN_NOT_NULL: tuple[str, ...] = (
    "id",
    "calculation_type",
    "vessel_id",
    "input_hash",
    "parameter_hash",
    "model_version",
    "result_json",
    "parameters_used",
    "created_at",
)
CALC_RUN_FROZEN_NULLABLE: tuple[str, ...] = (
    "voyage_id",
    "weather_snapshot_id",
    "warnings_json",
    "duration_ms",
)

IMMUTABLE_DELETE_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("trg_calcrun_no_delete", "calculation_run"),
    ("trg_snapshot_no_delete", "simulation_snapshot"),
)


def _unchanged(column: str, *, nullable: bool) -> str:
    """`obj`(갱신 전)와 `new`(갱신 후)가 같은가. NULL은 `=`로 비교되지 않는다."""
    same = f"new.{column} = obj.{column}"
    if not nullable:
        return same
    return f"({same} OR (new.{column} IS NULL AND obj.{column} IS NULL))"


def _calc_run_allowed_update() -> str:
    """`needs_recalc`가 0 → 1이고 나머지가 그대로인가 (`024` 계약)."""
    parts = ["new.needs_recalc = 1", "obj.needs_recalc = 0"]
    parts += [_unchanged(c, nullable=False) for c in CALC_RUN_FROZEN_NOT_NULL]
    parts += [_unchanged(c, nullable=True) for c in CALC_RUN_FROZEN_NULLABLE]
    return " AND ".join(parts)


def upgrade() -> None:
    """제약을 트리거·FK로 되살린다.

    트리거 DDL은 `db/trigger_ddl.py`를 지난다 — 이미 있으면 만들지 않는다 (`#1373`).
    """
    have = existing_triggers(op)
    for name, table, column in FUEL_TYPE_REFS:
        # NULL은 통과시킨다 — 원래 FK도 NULL을 막지 않았다(세 열 모두 nullable).
        exists = f"EXISTS (SELECT 1 FROM fuel_type WHERE code = new.{column})"
        for event in ("INSERT", "UPDATE"):
            create_trigger(
                op,
                f"{name}_{event.lower()[:3]}",
                f"BEFORE {event} ON {table} "
                f"IF NOT (new.{column} IS NULL OR {exists}) EXECUTE REJECT",
                existing=have,
            )

    # 부모 쪽(참조 중인 연료 코드 삭제 금지)은 **두지 않는다.** 한 번 넣었다가 뺐다.
    #
    # `db/seed.py`의 재적재가 `sqlalchemy_cubrid.dml.replace`(= `REPLACE INTO`)를 쓰는데,
    # **CUBRID의 `REPLACE`는 DELETE + INSERT로 구현되어** `BEFORE DELETE` 트리거를 깨운다.
    # 같은 `code`가 곧바로 다시 들어가므로 고아가 생기지 않는데도 재적재 전체가 막혔다 —
    # `tests/test_seed_data.py` 7건이 fixture 단계에서 죽었다. 트리거는 REPLACE가 부른
    # DELETE와 사람이 친 DELETE를 구분하지 못한다.
    #
    # 자식 쪽(위)이 **계산이 조용히 틀리는 경로**(없는 연료 코드 → CF 조회 실패)를 막으므로
    # 그쪽을 남기고 부모 쪽을 포기한다. 남는 구멍은 `DELETE FROM fuel_type`을 직접 쳐서
    # 참조 중인 코드를 지우는 경우이며, `DB_SCHEMA §7.4`에 그대로 적었다.

    for name, table, column in HASH_TRIGGERS:
        create_trigger(
            op,
            name,
            f"BEFORE INSERT ON {table} "
            f"IF NOT (new.{column} REGEXP '{HASH_PATTERN}') EXECUTE REJECT",
            existing=have,
        )

    create_trigger(
        op,
        "trg_calcrun_immutable_update",
        f"BEFORE UPDATE ON calculation_run IF NOT ({_calc_run_allowed_update()}) EXECUTE REJECT",
        existing=have,
    )
    # `simulation_snapshot`은 `009` 그대로 전면 불변이다 — 허용되는 UPDATE가 없다.
    create_trigger(
        op,
        "trg_snapshot_immutable_update",
        "BEFORE UPDATE ON simulation_snapshot EXECUTE REJECT",
        existing=have,
    )
    for name, table in IMMUTABLE_DELETE_TRIGGERS:
        create_trigger(op, name, f"BEFORE DELETE ON {table} EXECUTE REJECT", existing=have)


def downgrade() -> None:
    """건 것만 내린다 — 다시 upgrade하면 같은 것이 돌아온다.

    **데이터를 한 행도 지우지 않는다.** 제약과 트리거만 떼므로
    `migration_guard`의 세 분류(IRREVERSIBLE·EPHEMERAL·REGENERABLE) 어디에도 넣지 않고
    `guard_irreversible_downgrade`도 부르지 않는다 — 그 셋은 **데이터 손실**을 가르는
    분류다. 왕복을 실측했다: 트리거 14 → 0 → 14 (연료 참조 3×2 + 해시 4 + 불변 2×2).

    없는 것은 지우지 않는다 (`#1373` · `db/trigger_ddl.py`).
    """
    have = existing_triggers(op)
    for name, _ in IMMUTABLE_DELETE_TRIGGERS:
        drop_trigger(op, name, existing=have)
    drop_trigger(op, "trg_snapshot_immutable_update", existing=have)
    drop_trigger(op, "trg_calcrun_immutable_update", existing=have)
    for name, _table, _column in HASH_TRIGGERS:
        drop_trigger(op, name, existing=have)
    for name, _table, _column in FUEL_TYPE_REFS:
        for event in ("INSERT", "UPDATE"):
            drop_trigger(op, f"{name}_{event.lower()[:3]}", existing=have)
