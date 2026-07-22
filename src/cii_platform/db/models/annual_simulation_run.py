"""annual_simulation_run ORM 모델.

DB_SCHEMA.md §2.6 (annual_simulation_run) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 014와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class AnnualSimulationRun(Base):
    """연간 CII 시뮬레이션 실행 기록."""

    __tablename__ = "annual_simulation_run"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    calculation_run_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    vessel_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    regulation_year = sa.Column(sa.Integer(), nullable=False)
    target_rating = sa.Column(sa.String(length=1), nullable=False)
    simulation_runs = sa.Column(sa.Integer(), nullable=False)
    snapshot_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
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
