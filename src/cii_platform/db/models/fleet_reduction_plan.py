"""함대 감축 계획 (``UIFLOW 2-10`` · ``PRD §12.3.2`` · `#513` · 마이그레이션 043).

**저장 시점의 결과를 그대로 담는다** — 다시 계산해 채우지 않는다. 항차가 바뀐 뒤 다시 낸 값은
그때 경영진에게 보고한 숫자가 아니다. 단가(``prices``)도 그 계획의 **가정**이라 계획과 함께 남는다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class FleetReductionPlan(Base):
    """감축 계획안 한 건."""

    __tablename__ = "fleet_reduction_plan"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    name = sa.Column(sa.String(length=100), nullable=False)
    regulation_year = sa.Column(sa.Integer(), nullable=False)
    target = sa.Column(sa.String(length=20), nullable=False)
    adjustments = sa.Column(postgresql.JSONB(), nullable=False)
    prices = sa.Column(postgresql.JSONB(), nullable=False)
    result = sa.Column(postgresql.JSONB(), nullable=False)
    created_by = sa.Column(postgresql.UUID(as_uuid=True), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
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
        sa.Index("idx_fleet_reduction_plan_created", sa.text("created_at DESC")),
    )
