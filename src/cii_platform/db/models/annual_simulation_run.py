"""annual_simulation_run ORM 모델.

DB_SCHEMA.md §2.6 (annual_simulation_run) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 014와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class AnnualSimulationRun(Base):
    """연간 CII 시뮬레이션 실행 기록."""

    __tablename__ = "annual_simulation_run"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    calculation_run_id = sa.Column(UuidText, nullable=False)
    vessel_id = sa.Column(UuidText, nullable=False)
    regulation_year = sa.Column(sa.Integer(), nullable=False)
    target_rating = sa.Column(sa.String(length=1), nullable=False)
    simulation_runs = sa.Column(sa.Integer(), nullable=False)
    snapshot_id = sa.Column(UuidText, nullable=False)
    #: 실적 보정계수를 켜고 돌렸는가 (``PRD §12.2.1`` · `#363` · 마이그레이션 ``042``).
    #: **계수 값은 저장하지 않는다** — 같은 실행의 스냅샷에서 다시 계산하면 같은 값이다.
    apply_feedback_factor = sa.Column(
        sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False
    )
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_annual_simulation_run"),
        # §7.1 [DB-C-3]: immutable 테이블(calculation_run) 참조 → RESTRICT.
        sa.ForeignKeyConstraint(
            ["calculation_run_id"],
            ["calculation_run.id"],
            name="fk_annual_simulation_run_calculation_run",
            ondelete="RESTRICT",
        ),
        # §7.1 [DB-C-3]: 시뮬레이션 이력 보존 → 선박 물리 삭제 시 RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_annual_simulation_run_vessel",
            ondelete="RESTRICT",
        ),
        # §7.1 [DB-C-3]: immutable 테이블(simulation_snapshot) 참조 → RESTRICT.
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["simulation_snapshot.id"],
            name="fk_annual_simulation_run_snapshot",
            ondelete="RESTRICT",
        ),
        # §2.6 [M-4] (원문 그대로): E 불가.
        sa.CheckConstraint(
            "target_rating IN ('A','B','C','D')",
            name="chk_target_rating",
        ),
        # §2.6 [M-5] (원문 그대로).
        sa.CheckConstraint("simulation_runs > 0", name="chk_sim_runs_positive"),
        # §2.6 [S-6] (원문 그대로): 1스냅샷 = 1시뮬레이션 (1:1 관계 보장).
        sa.Index(
            "idx_sim_snapshot_unique",
            "snapshot_id",
            unique=True,
        ),
    )
