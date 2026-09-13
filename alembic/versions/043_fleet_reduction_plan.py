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
from sqlalchemy.dialects import postgresql

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fleet_reduction_plan",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("regulation_year", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("adjustments", postgresql.JSONB(), nullable=False),
        sa.Column("prices", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        # 계정이 지워져도 계획은 남긴다 — 보고한 산출물이다.
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fleet_reduction_plan"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name="fk_fleet_reduction_plan_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "target IN ('NO_AT_RISK','ALL_C_OR_BETTER')", name="chk_fleet_reduction_plan_target"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="chk_fleet_reduction_plan_name"),
    )
    op.create_index(
        "idx_fleet_reduction_plan_created",
        "fleet_reduction_plan",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    guard_irreversible_downgrade("043")
    op.drop_index("idx_fleet_reduction_plan_created", table_name="fleet_reduction_plan")
    op.drop_table("fleet_reduction_plan")
