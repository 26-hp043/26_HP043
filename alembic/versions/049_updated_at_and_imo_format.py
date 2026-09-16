"""``updated_at``이 갱신되지 않는 것과 IMO 형식 제약을 되살린다 (`#1058`)

Revision ID: 049
Revises: 048
Create Date: 2026-09-16

## 🔴 ``updated_at``을 갱신하는 것이 하나도 없었다

일곱 테이블이 ``updated_at`` 열을 갖는다 — ``app_user`` · ``fuel_type`` ·
``not_underway_period`` · ``vessel`` · ``voyage`` · ``voyage_fuel_use`` ·
``voyage_scenario``. 그런데 **그 값을 갱신하는 것이 DB에 하나도 없다.** 실측이다::

    SELECT name FROM db_trigger WHERE name LIKE '%updated%'   → 0행

ORM은 있다고 적고 있다 — ``db/models/vessel.py``의 「``updated_at`` 자동 갱신은 DB
트리거(``trg_vessel_updated``, ``§7.2``)가 담당한다」. **주석만 남고 트리거는 전환에서
사라졌다.**

결과는 조용하다. 행을 고쳐도 ``updated_at``은 **만들어진 시각에 그대로 멈춘다**
(``server_default``가 ``CURRENT_TIMESTAMP``라 INSERT 때만 채워진다). 화면·리포트의
「최종 수정」이 언제나 틀리고, 「언제 바뀌었나」로 되짚을 수단이 없다.

``tests/test_not_underway_migrations.py::test_period_update_touches_updated_at``와
``tests/test_app_user_migration.py::test_app_user_update_touches_updated_at``가 그것을
잡는데 앞의 것은 건너뛰기 목록에 있었고, 뒤의 것은 다른 이유(``ResourceClosedError``)로
먼저 서서 **이 사실까지 가려져 있었다.**

### 왜 트리거가 아니라 열 속성인가

트리거로 하려면 자기 테이블을 다시 UPDATE해야 해서 **재귀에 걸린다** — 실측이다::

    CREATE TRIGGER … AFTER UPDATE ON t EXECUTE UPDATE t SET updated_at = SYS_DATETIME
      WHERE id = obj.id
    → Error evaluating action …, Maximum … depth

``BEFORE``에서 ``UPDATE new SET``·``UPDATE obj SET``으로 값을 바꾸는 것은 CUBRID가
**컴파일 단계에서 거부**한다.

**CUBRID는 MySQL 호환 ``ON UPDATE`` 열 속성을 지원한다.** 빈 테이블로 확인했다::

    ALTER TABLE t MODIFY updated_at DATETIMETZ ON UPDATE CURRENT_DATETIME   → OK
    UPDATE t SET n = 2                                                      → updated_at 갱신됨

트리거보다 짧고, 재귀가 없고, 카탈로그에 열 속성으로 남아 다음 사람이 찾기 쉽다.

## IMO 형식 제약 — ``chk_imo_format``

전환 분기점(``0f4b062``)의 ORM은 이렇게 적고 있었다::

    sa.CheckConstraint(r"imo_number ~ '^\\d{7}$'", name="chk_imo_format")

``~``는 PostgreSQL 전용이라 전환(``9ddeb22``)이 제약을 **뺐다**. 그러면서 주석 줄이
다음 줄과 붙어 ``chk_gt_positive``까지 함께 죽은 것이 v5가 찾은 결함이다.

**CUBRID에는 ``REGEXP``가 있다** — ``a7d3e9b14f26``의 해시 형식 트리거가 이미 쓰고
있다. 같은 방식으로 되살린다. IMO 번호는 7자리 숫자이고(``DB_SCHEMA §2.1``), 6자리나
문자가 섞인 값이 들어가면 **IMO 조회·대조가 조용히 빗나간다.**
"""

from __future__ import annotations

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


#: ``updated_at``을 갖는 테이블과 그 열의 타입. 타입은 ``MODIFY``에 그대로 적어야
#: 하므로 ``db_attribute`` 실측값(``DATETIMETZ``)을 쓴다.
UPDATED_AT_TABLES: tuple[str, ...] = (
    "app_user",
    "fuel_type",
    "not_underway_period",
    "vessel",
    "voyage",
    "voyage_fuel_use",
    "voyage_scenario",
)

#: 분기점 ORM의 ``imo_number ~ '^\d{7}$'``를 CUBRID ``REGEXP``로 옮긴 것.
_IMO_PATTERN = r"^[0-9]{7}$"


def upgrade() -> None:
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"ALTER TABLE {table} MODIFY updated_at DATETIMETZ "
            f"DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_DATETIME"
        )

    for event in ("INSERT", "UPDATE"):
        op.execute(
            f"CREATE TRIGGER trg_chk_imo_format_{event.lower()[:3]} "
            f"BEFORE {event} ON vessel "
            f"IF NOT (new.imo_number REGEXP '{_IMO_PATTERN}') EXECUTE REJECT"
        )


def downgrade() -> None:
    """``ON UPDATE``를 떼고 트리거를 내린다 — 데이터를 지우지 않는다.

    ``updated_at``에 이미 들어간 값은 그대로 둔다. 되돌린다는 것은 「앞으로 갱신하지
    않는다」는 뜻이고, 이미 갱신된 시각을 만들어진 시각으로 **되돌릴 방법은 없다** —
    되돌릴 수 없는 것을 되돌린 척하지 않는다.
    """
    for event in ("INSERT", "UPDATE"):
        op.execute(f"DROP TRIGGER trg_chk_imo_format_{event.lower()[:3]}")

    for table in UPDATED_AT_TABLES:
        op.execute(f"ALTER TABLE {table} MODIFY updated_at DATETIMETZ DEFAULT CURRENT_TIMESTAMP")
