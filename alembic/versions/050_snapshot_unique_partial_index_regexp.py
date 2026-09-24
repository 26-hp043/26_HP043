"""건너뛰기를 걷어 드러난 제약 셋을 CUBRID에서 실제로 세운다 (`#1058`)

Revision ID: 050
Revises: 049
Create Date: 2026-09-16

``049``가 ``_CUBRID_SKIP_FILES``를 비우자 **가려져 있던 제약 부재 셋**이 드러났다
(인계 v7 §6). 셋 다 「CUBRID가 못 하는 형태로 적혀 있어 아무것도 세우지 못한」 것이다.

⑴ 1스냅샷 = 1시뮬레이션이 DB에서 강제되지 않았다
-------------------------------------------------
``DB_SCHEMA §2.6 [S-6]``의 1:1은 종전 PostgreSQL에서 유니크 인덱스였다::

    CREATE UNIQUE INDEX idx_sim_snapshot_unique ON annual_simulation_run (snapshot_id);

전환에서 그 줄이 사유 없이 꺼졌고, 되살리려 하면 CUBRID가 거부한다 — **FK가 그 열에
이미 인덱스를 만들어 두기 때문**이다. 빈 표로 재현했다::

    CREATE TABLE _c2 (… s CHAR(32), CONSTRAINT _fkx FOREIGN KEY (s) REFERENCES _p2(id) …)
    CREATE UNIQUE INDEX _uqx ON _c2 (s)
      → ERROR: Index "_fkx" already defined for class "dba._c2".
    ALTER TABLE _c2 DROP FOREIGN KEY _fkx        → Execute OK
    CREATE UNIQUE INDEX _uqx ON _c2 (s)          → Execute OK    ← FK를 뺀 뒤에는 선다

**사용자가 고른 안은 「FK를 빼고 UNIQUE + 트리거」다**(결정요청 §0-3⑵ · 가). 그대로 한다.

FK를 빼도 잃는 것이 없다 — 이것이 이 안을 고를 수 있는 이유다.

* **부모 쪽**(``simulation_snapshot``의 DELETE·UPDATE 금지)은 ``a7d3e9b14f26``의
  ``trg_snapshot_no_delete``·``trg_snapshot_immutable_update``가 **이미 전면 차단**한다.
  FK의 ``ON DELETE RESTRICT``보다 **더 강하다** — 참조가 없어도 못 지운다.
* **자식 쪽**(없는 스냅샷을 가리키지 못함)만 남으므로 그것을 트리거로 옮긴다.
  ``a7d3e9b14f26``이 ``fuel_type`` 참조 3건에 쓴 것과 같은 형태다.

⑵ 정박 구간의 partial 인덱스에 조건이 없었다
--------------------------------------------
``idx_not_underway_period_vessel_year``·``…_vessel_started``는 ``#345``·``#368`` 이래
**활성 행만** 인덱싱하게 되어 있었다(``vessel``의 ``idx_vessel_imo`` 패턴)::

    CREATE INDEX … ON not_underway_period (vessel_id, regulation_year)
      WHERE is_deleted = false

전환이 조건을 떼었다. ``047``이 실측한 네 조합 중 **비유일 + 필터 열이 키에 있음**만
CUBRID에서 서므로, ``is_deleted``를 키에 넣고 조건을 붙인다. 유일성이 아니라 **조회
범위**를 줄이는 인덱스라 비유일이어도 뜻이 그대로다.

``idx_not_underway_period_voyage``는 **일부러 조건을 붙이지 않는다** — FK의 SET NULL
확인 경로라 지워진 행도 봐야 한다(``tests/test_not_underway_migrations`` 주석).

⑶ ``'fixed abc'``가 ``capacity_rule``을 통과했다
------------------------------------------------
정본 ``DB_SCHEMA §2.10 [M-7]``은 「``fixed`` 뒤에 **숫자만**」이다::

    CHECK (capacity_rule IN ('DWT','GT') OR capacity_rule ~ '^fixed \\d+$')

그런데 ``1c444a5c4819``과 ORM은 ``LIKE 'fixed %'``로 적고 있었다 — ``fixed`` 뒤에
**무엇이든** 통과한다. ``048``이 그 조건을 기계로 옮겼으므로 **트리거도 같이 헐거웠다.**

``REGEXP``로 좁히되 **``BINARY``를 붙인다.** CUBRID의 ``REGEXP``는 기본이
대소문자 무시라 정본의 ``~``(대소문자 구분)보다 넓다 — 실측이다::

    'FIXED 12' REGEXP        '^fixed [0-9]+$'   → 통과   ← 정본은 거부해야 한다
    'FIXED 12' REGEXP BINARY '^fixed [0-9]+$'   → 거부
    'fixed 12' REGEXP BINARY '^fixed [0-9]+$'   → 통과

시드 세 값(``fixed 279000``·``fixed 65000``·``fixed 57700``)이 통과하고
``fixed abc``·``fixed``·``fixed 12 ``(뒤 공백)·``xfixed 12``가 거부되는 것을 확인했다.

🔴 CHECK 선언은 DB에 **남아 있지도 않다**
-----------------------------------------
``046``·``048``은 「CHECK 선언은 지우지 않았다 — 검사되지 않을 뿐 선언으로서는 맞다」로
두었다. 이번에 더 재 보니 CUBRID는 **선언을 보관조차 하지 않는다**::

    CREATE TABLE _ck (n INT, CONSTRAINT _chk_n CHECK (n > 0))   → Committed
    ALTER TABLE _ck DROP CONSTRAINT _chk_n                      → ERROR: Constraint
                                                                  "_chk_n" not found.

즉 마이그레이션·ORM·정본에 적힌 CHECK는 **문서로만** 존재한다. 그래서 ⑶의 선언 수정은
이 리비전이 아니라 **ORM(`db/models/cii_reference_line.py`)과 정본**에서 한다 —
DB에 바꿀 대상이 없다. 여기서는 **집행하는 트리거**만 고친다.
"""

from __future__ import annotations

from alembic import op
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


# ── ⑴ 1스냅샷 = 1시뮬레이션 ────────────────────────────────────────────────────

#: 빼는 FK. CUBRID가 이 FK 때문에 ``snapshot_id``에 인덱스를 또 두지 못한다.
SNAPSHOT_FK = "fk_annual_simulation_run_snapshot"
SNAPSHOT_INDEX = "idx_sim_snapshot_unique"

#: FK의 자식 쪽 역할을 대신하는 트리거. 앞머리 ``trg_``는 ``cubrid_errors``가
#: ``IntegrityError``로 옮기는 기본 갈래다(불변성 표식이 아니므로).
SNAPSHOT_REF_TRIGGER = "trg_annual_sim_snapshot_ref"

#: ``snapshot_id``는 NOT NULL이라 NULL 갈래를 두지 않는다 — 원래 FK도 NULL을 받지 않았다.
_SNAPSHOT_EXISTS = "EXISTS (SELECT 1 FROM simulation_snapshot WHERE id = new.snapshot_id)"


# ── ⑵ 정박 구간 partial 인덱스 ────────────────────────────────────────────────

#: (인덱스 이름, 본래 키 열). ``is_deleted``를 키 끝에 더하고 조건을 붙인다.
#:
#: ⚠️ ``is_deleted``는 BOOLEAN이 아니라 SMALLINT다(``047``·``a7d3e9b14f26`` 실측) —
#: ``= 0``으로 비교한다.
PARTIAL_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("idx_not_underway_period_vessel_year", ("vessel_id", "regulation_year")),
    ("idx_not_underway_period_vessel_started", ("vessel_id", "started_at")),
)
PARTIAL_TABLE = "not_underway_period"
PARTIAL_FILTER = "is_deleted = 0"


# ── ⑶ capacity_rule ───────────────────────────────────────────────────────────

CAPACITY_CHECK = "chk_capacity_rule"
CAPACITY_TABLE = "cii_reference_line"

#: ``048``이 건 조건 — ``1c444a5c4819``의 CHECK 본문 그대로라 함께 헐거웠다.
CAPACITY_OLD = "new.capacity_rule IN ('DWT','GT') OR new.capacity_rule LIKE 'fixed %'"

#: 정본 ``§2.10 [M-7]``의 뜻 — ``fixed`` 뒤에 숫자만, 대소문자 구분.
CAPACITY_NEW = (
    "new.capacity_rule IN ('DWT','GT') OR new.capacity_rule REGEXP BINARY '^fixed [0-9]+$'"
)

_EVENTS: tuple[str, ...] = ("INSERT", "UPDATE")


def _capacity_trigger(event: str) -> str:
    """``048``의 이름 규칙과 같아야 한다 — 그 리비전이 건 것을 여기서 갈아 끼운다."""
    return f"trg_{CAPACITY_CHECK}_{event.lower()[:3]}"


def upgrade() -> None:
    """트리거 DDL은 `db/trigger_ddl.py`를 지난다 — 있으면 만들지 않고 없으면 지우지 않는다.

    `#1373`.
    """
    # ── ⑴ ────────────────────────────────────────────────────────────────────
    op.execute(f"ALTER TABLE annual_simulation_run DROP FOREIGN KEY {SNAPSHOT_FK}")
    op.execute(f"CREATE UNIQUE INDEX {SNAPSHOT_INDEX} ON annual_simulation_run (snapshot_id)")
    for event in _EVENTS:
        create_trigger(
            op,
            f"{SNAPSHOT_REF_TRIGGER}_{event.lower()[:3]}",
            f"BEFORE {event} ON annual_simulation_run IF NOT ({_SNAPSHOT_EXISTS}) EXECUTE REJECT",
        )

    # ── ⑵ ────────────────────────────────────────────────────────────────────
    # `op.drop_index`를 쓰지 않는다 — alembic이 내는 `DROP INDEX <이름>`은 PostgreSQL
    # 문법이고 CUBRID는 테이블을 함께 적어야 한다(`047` 실측).
    for name, columns in PARTIAL_INDEXES:
        keys = ", ".join((*columns, "is_deleted"))
        op.execute(f"DROP INDEX {name} ON {PARTIAL_TABLE}")
        op.execute(f"CREATE INDEX {name} ON {PARTIAL_TABLE} ({keys}) WHERE {PARTIAL_FILTER}")

    # ── ⑶ ────────────────────────────────────────────────────────────────────
    # `048`이 건 것을 지우고 좁힌 조건으로 다시 만든다. 지운 뒤에 만들므로 「있으면
    # 건너뜀」에 걸리지 않는다 — 지우지 못한 경우(중복 상태)에만 옛 조건이 남는다.
    for event in _EVENTS:
        drop_trigger(op, _capacity_trigger(event))
        create_trigger(
            op,
            _capacity_trigger(event),
            f"BEFORE {event} ON {CAPACITY_TABLE} IF NOT ({CAPACITY_NEW}) EXECUTE REJECT",
        )


def downgrade() -> None:
    """건 것만 되돌린다.

    **데이터를 한 행도 지우지 않는다** — ``migration_guard``의 세 분류
    (IRREVERSIBLE·EPHEMERAL·REGENERABLE) 어디에도 넣지 않고
    ``guard_irreversible_downgrade``도 부르지 않는다(``a7d3e9b14f26``·``046``·``047``·
    ``048``과 같은 판단).

    ⚠️ ⑴을 되돌리면 **한 스냅샷에 연간 시뮬레이션이 여러 건 매달릴 수 있는 상태**로
    돌아간다. 그런 행이 이미 있으면 다시 upgrade할 때 ``CREATE UNIQUE INDEX``가 그 자리에서
    실패한다 — 조용히 한쪽을 지우지 않는다. 무엇을 지울지는 사람이 정할 일이다.
    """
    for event in _EVENTS:
        drop_trigger(op, _capacity_trigger(event))
        create_trigger(
            op,
            _capacity_trigger(event),
            f"BEFORE {event} ON {CAPACITY_TABLE} IF NOT ({CAPACITY_OLD}) EXECUTE REJECT",
        )

    for name, columns in PARTIAL_INDEXES:
        op.execute(f"DROP INDEX {name} ON {PARTIAL_TABLE}")
        op.execute(f"CREATE INDEX {name} ON {PARTIAL_TABLE} ({', '.join(columns)})")

    for event in _EVENTS:
        drop_trigger(op, f"{SNAPSHOT_REF_TRIGGER}_{event.lower()[:3]}")
    op.execute(f"DROP INDEX {SNAPSHOT_INDEX} ON annual_simulation_run")
    op.execute(
        "ALTER TABLE annual_simulation_run ADD CONSTRAINT "
        f"{SNAPSHOT_FK} FOREIGN KEY (snapshot_id) REFERENCES simulation_snapshot(id) "
        "ON DELETE RESTRICT ON UPDATE RESTRICT"
    )
