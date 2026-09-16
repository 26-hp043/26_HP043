"""함대 감축 계획 (``UIFLOW 2-10`` · ``PRD §12.3.2`` · `#513` · 마이그레이션 043).

**저장 시점의 결과를 그대로 담는다** — 다시 계산해 채우지 않는다. 항차가 바뀐 뒤 다시 낸 값은
그때 경영진에게 보고한 숫자가 아니다. 단가(``prices``)도 그 계획의 **가정**이라 계획과 함께 남는다.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from cii_platform.db.models.base import FK_ON_UPDATE, Base
from cii_platform.db.types import JSONText, UuidText


class FleetReductionPlan(Base):
    """감축 계획안 한 건."""

    __tablename__ = "fleet_reduction_plan"

    # CUBRID에는 `gen_random_uuid()`가 없고 `id`에 기본값을 둘 수단도 없다 (`#1058`).
    # `default=uuid.uuid4`로 **ORM이 넣을 때 만든다** — 다른 모델(`calculation_run` 등)과
    # 같은 형태다. 빼 두면 flush가 `NULL identity key`로 선다.
    id = sa.Column(UuidText(), primary_key=True, default=uuid.uuid4)
    name = sa.Column(sa.String(length=100), nullable=False)
    regulation_year = sa.Column(sa.Integer(), nullable=False)
    target = sa.Column(sa.String(length=20), nullable=False)
    adjustments = sa.Column(JSONText(), nullable=False)
    prices = sa.Column(JSONText(), nullable=False)
    result = sa.Column(JSONText(), nullable=False)
    created_by = sa.Column(UuidText(), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_fleet_reduction_plan"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name="fk_fleet_reduction_plan_user",
            ondelete="SET NULL",
            onupdate=FK_ON_UPDATE,
        ),
        # CHECK를 적지 않는다 (`#1058` · `DB_SCHEMA §7.4`) — CUBRID는 받기만 하고
        # **검사하지 않아**, 적어 두면 「막힌다」고 오해된다. `target`은 마이그레이션
        # `043`의 트리거가 막고, `name` 공백 검사는 입력 스키마가 한다.
        sa.Index("idx_fleet_reduction_plan_created", sa.text("created_at DESC")),
    )
