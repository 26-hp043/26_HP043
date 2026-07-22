"""annual_simulation_run 테이블

Revision ID: 014
Revises: 013
Create Date: 2026-07-18

DB_SCHEMA.md §2.6 (annual_simulation_run: 컬럼/검증 제약 [M-4, M-5, S-6]),
§7.1 (FK 정책) 참조. 이슈 #103 체크리스트 014.
calculation_run(008), vessel(003), simulation_snapshot(009)을 참조한다.

주의 (이슈 본문 대비 정본 우선, AGENTS §3):
- 이슈 #103 본문은 snapshot_id UNIQUE와 simulation_runs > 0만 언급하나, 정본 §2.6에는
  chk_target_rating(A~D, E 불가 [M-4])과 FK 3건(전부 ON DELETE RESTRICT [DB-C-3])이
  추가로 정의되어 있어 모두 포함한다.
- regulation_year는 INTEGER 컬럼이며 FK가 아니다(§2.6 — regulation_year 테이블 참조
  아님. voyage.regulation_year와 동일한 패턴).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | Sequence[str] | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "annual_simulation_run",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("calculation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("regulation_year", sa.Integer(), nullable=False),
        sa.Column("target_rating", sa.String(length=1), nullable=False),
        sa.Column("simulation_runs", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
    )

    # §2.6 [S-6] (원문 그대로): 1스냅샷 = 1시뮬레이션 (1:1 관계 보장).
    op.execute(
        "CREATE UNIQUE INDEX idx_sim_snapshot_unique ON annual_simulation_run (snapshot_id);"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("annual_simulation_run")
