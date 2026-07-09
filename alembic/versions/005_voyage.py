"""voyage 테이블

Revision ID: 005
Revises: 004
Create Date: 2026-07-09

DB_SCHEMA.md §2.2 (voyage: 컬럼/인덱스/검증 제약), §7.1 (FK ON DELETE 정책),
§7.2 [M-2] (updated_at 트리거) 참조.
vessel_id가 vessel(id)를 참조하므로 vessel(003) 이후에 생성된다.

주의: 이슈 #27 본문은 요약본이며 스키마 정본은 DB_SCHEMA.md이다(AGENTS §3).
- status는 CANCELLED 포함 7개 값.
- annual_inclusion_policy는 EXCLUDE / INCLUDE_AS_PLAN / INCLUDE_AS_ACTUAL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | Sequence[str] | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "voyage",
        # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voyage_no", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        # [C-1] annual_inclusion_policy ≠ EXCLUDE인 경우 NOT NULL 필수 (chk_year_policy).
        sa.Column("regulation_year", sa.Integer(), nullable=True),
        sa.Column("departure_port_name", sa.String(length=200), nullable=False),
        sa.Column("departure_lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("departure_lon", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("arrival_port_name", sa.String(length=200), nullable=False),
        sa.Column("arrival_lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("arrival_lon", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("planned_distance_nm", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("actual_distance_nm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("planned_speed_kn", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("actual_avg_speed_kn", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("planned_departure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_departure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "annual_inclusion_policy",
            sa.String(length=30),
            server_default=sa.text("'EXCLUDE'"),
            nullable=False,
        ),
        sa.Column(
            "created_from",
            sa.String(length=30),
            server_default=sa.text("'MANUAL'"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_voyage"),
        # §7.1 [C-3]: vessel은 soft-delete만 허용하므로 물리 삭제 시 항차 orphan 방지 → RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_voyage_vessel",
            ondelete="RESTRICT",
        ),
        # §2.2 검증 제약 (원문 그대로). status는 CANCELLED 포함 7개 값.
        sa.CheckConstraint(
            "status IN ('DRAFT','PLANNED','IN_PROGRESS','COMPLETED','CONFIRMED',"
            "'CANCELLED','ARCHIVED')",
            name="chk_voyage_status",
        ),
        sa.CheckConstraint(
            "annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN','INCLUDE_AS_ACTUAL')",
            name="chk_voyage_policy",
        ),
        # status × annual_inclusion_policy 제약 (PRD §8.1.2 ORACLE-R1).
        sa.CheckConstraint(
            "(status = 'DRAFT' AND annual_inclusion_policy = 'EXCLUDE')"
            " OR (status IN ('PLANNED','IN_PROGRESS')"
            " AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN'))"
            " OR (status IN ('COMPLETED','CONFIRMED')"
            " AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_ACTUAL'))"
            " OR (status IN ('CANCELLED','ARCHIVED') AND annual_inclusion_policy = 'EXCLUDE')",
            name="chk_status_policy",
        ),
        # regulation_year 범위 및 policy 연관 제약 [C-1].
        sa.CheckConstraint(
            "regulation_year IS NULL OR regulation_year BETWEEN 2019 AND 2050",
            name="chk_regulation_year_range",
        ),
        sa.CheckConstraint(
            "annual_inclusion_policy = 'EXCLUDE' OR regulation_year IS NOT NULL",
            name="chk_year_policy",
        ),
        sa.CheckConstraint("planned_distance_nm > 0", name="chk_distance_positive"),
        sa.CheckConstraint("planned_speed_kn >= 1.0", name="chk_speed_positive"),
        # [M-6] actual 값은 nullable.
        sa.CheckConstraint(
            "actual_distance_nm IS NULL OR actual_distance_nm > 0",
            name="chk_actual_dist_positive",
        ),
        sa.CheckConstraint(
            "actual_avg_speed_kn IS NULL OR actual_avg_speed_kn >= 1.0",
            name="chk_actual_speed_positive",
        ),
        sa.CheckConstraint(
            "departure_lat IS NULL OR departure_lat BETWEEN -90 AND 90",
            name="chk_dep_lat_range",
        ),
        sa.CheckConstraint(
            "departure_lon IS NULL OR departure_lon BETWEEN -180 AND 180",
            name="chk_dep_lon_range",
        ),
        # [S-3]
        sa.CheckConstraint(
            "arrival_lat IS NULL OR arrival_lat BETWEEN -90 AND 90",
            name="chk_arr_lat_range",
        ),
        sa.CheckConstraint(
            "arrival_lon IS NULL OR arrival_lon BETWEEN -180 AND 180",
            name="chk_arr_lon_range",
        ),
    )

    # §2.2 인덱스 (모두 partial: WHERE is_deleted = false). soft delete 호환.
    op.execute(
        "CREATE INDEX idx_voyage_vessel ON voyage (vessel_id, created_at DESC) "
        "WHERE is_deleted = false;"
    )
    op.execute(
        "CREATE INDEX idx_voyage_status ON voyage (vessel_id, status) WHERE is_deleted = false;"
    )
    op.execute(
        "CREATE INDEX idx_voyage_year ON voyage (vessel_id, regulation_year) "
        "WHERE is_deleted = false;"
    )

    # §7.2: updated_at 자동 갱신 트리거.
    op.execute(
        """
        CREATE TRIGGER trg_voyage_updated
        BEFORE UPDATE ON voyage
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 트리거·인덱스·제약은 테이블과 함께 삭제되지만 트리거는 명시적으로 제거한다.
    op.execute("DROP TRIGGER IF EXISTS trg_voyage_updated ON voyage;")
    op.drop_table("voyage")
