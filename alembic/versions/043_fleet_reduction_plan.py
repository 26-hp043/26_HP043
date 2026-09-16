"""함대 감축 계획 저장 테이블 신설

Revision ID: 043
Revises: 042
Create Date: 2026-09-13

이슈 #513 · ``UIFLOW 2-10`` · ``PRD §12.3.2``.

무엇을 저장하나
----------------
``fleet_reduction_plan`` — 담당자가 만든 **감축 계획안 한 건**. 경영진에게 보고하는 산출물이라
휘발되면 안 된다(``UIFLOW 2-10`` · `#513` 「계획 저장 모델」).

- ``adjustments`` — 선박별 감속률
- ``prices`` — **그 계획이 가정한** 일일 용선료·연료 단가(USD). 2026-09-13 결정 C: 단가는
  시장 가정이라 **계획과 함께** 남는다. 선박 제원에 두면 단가를 고친 순간 과거 계획의 손익이
  조용히 바뀐다.
- ``result`` — 저장 시점에 서버가 낸 결과 전체. **다시 계산해 채우지 않는다** — 항차가 바뀌면
  다시 계산한 값은 그때 보고한 숫자가 아니다.

draft는 저장하지 않는다 — 슬라이더를 움직이는 동안은 화면 상태이고, 「저장」을 누른 것만 행이 된다.

되돌리기
--------
``downgrade``는 표를 지운다. **사람이 만든 계획안 전부**가 사라지고 다시 만들 근거가 없다.
``IRREVERSIBLE``로 분류한다.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade
from cii_platform.db.types import JSONText, UuidText

revision = "043"
down_revision = "a7d3e9b14f26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fleet_reduction_plan",
        # CUBRID에는 `gen_random_uuid()`가 없고 `id`에 기본값을 둘 수단도 없다
        # (`#1058`) — **넣는 쪽이 `uuid4().hex`로 만든다.** `services/fleet_reduction.py`가
        # 그렇게 한다.
        sa.Column("id", UuidText(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("regulation_year", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("adjustments", JSONText(), nullable=False),
        sa.Column("prices", JSONText(), nullable=False),
        sa.Column("result", JSONText(), nullable=False),
        # 계정이 지워져도 계획은 남긴다 — 보고한 산출물이다.
        sa.Column("created_by", UuidText(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fleet_reduction_plan"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name="fk_fleet_reduction_plan_user",
            ondelete="SET NULL",
        ),
        # CHECK를 걸지 않는다 (`#1058` · `DB_SCHEMA §7.4`) — CUBRID는 받기만 하고
        # **검사하지 않는다.** `target`은 아래 트리거로 막고, `name` 공백 검사는
        # 입력 스키마(`api/schemas/fleet_reduction.py`)가 이미 한다.
    )
    op.create_index(
        "idx_fleet_reduction_plan_created",
        "fleet_reduction_plan",
        [sa.text("created_at DESC")],
    )
    # `target`은 계획의 성격을 가르는 값이라 트리거로 막는다 — 틀린 값이 들어가면
    # 어느 목표로 세운 계획인지 알 수 없게 되고, 이 표는 **보고한 산출물**이다.
    for event in ("INSERT", "UPDATE"):
        op.execute(
            f"CREATE TRIGGER trg_fleet_plan_target_{event.lower()[:3]} "
            f"BEFORE {event} ON fleet_reduction_plan "
            "IF NOT (new.target IN ('NO_AT_RISK', 'ALL_C_OR_BETTER')) EXECUTE REJECT"
        )


def downgrade() -> None:
    guard_irreversible_downgrade("043")
    # 인덱스를 따로 지우지 않는다. CUBRID는 `DROP INDEX <이름>`을 받지 않고
    # `... ON <테이블>`을 요구하는데, alembic의 `drop_index()`가 내는 구문은 앞쪽이라
    # `Syntax error: unexpected END OF STATEMENT`로 선다 (`#1058`).
    #
    # **테이블을 드롭하면 그 인덱스도 함께 사라지므로 결과가 같다.**
    # `1c444a5c4819`의 downgrade가 이미 같은 판단을 적어 두었다 — `043`이 `main`에서
    # 옮겨 오면서 이 줄만 PostgreSQL 판본 그대로 남았다.
    op.drop_table("fleet_reduction_plan")
