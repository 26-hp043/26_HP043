"""vessel 테이블

Revision ID: 003
Revises: 002
Create Date: 2026-07-09

DB_SCHEMA.md §2.1 (vessel: 컬럼/인덱스/검증 제약), §2.1 [S-1] & §7.1 (FK 정책),
§7.2 [M-2] (updated_at 트리거) 참조.
default_fuel_type이 fuel_type(code)를 참조하므로 fuel_type(002) 이후에 생성된다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "vessel",
        # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("imo_number", sa.String(length=7), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("ship_type", sa.String(length=50), nullable=False),
        sa.Column("gross_tonnage", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("deadweight", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("default_fuel_type", sa.String(length=30), nullable=True),
        sa.Column("reference_speed_kn", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("reference_daily_foc_ton", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column(
            "is_cii_applicable_hint",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_vessel"),
        # [S-1] / §7.1: default_fuel_type → fuel_type(code), ON UPDATE CASCADE, ON DELETE NO ACTION.
        sa.ForeignKeyConstraint(
            ["default_fuel_type"],
            ["fuel_type.code"],
            name="fk_vessel_default_fuel_type",
            onupdate="CASCADE",
            ondelete="NO ACTION",
        ),
        # §2.1 검증 제약 (원문 그대로).
        sa.CheckConstraint(r"imo_number ~ '^\d{7}$'", name="chk_imo_format"),
        sa.CheckConstraint("gross_tonnage IS NULL OR gross_tonnage > 0", name="chk_gt_positive"),
        sa.CheckConstraint("deadweight IS NULL OR deadweight > 0", name="chk_dwt_positive"),
        sa.CheckConstraint(
            "reference_speed_kn IS NULL OR reference_speed_kn > 0", name="chk_speed_positive"
        ),
    )

    # §2.1 인덱스 (모두 partial: WHERE is_deleted = false). soft delete 호환.
    op.execute(
        "CREATE UNIQUE INDEX idx_vessel_imo ON vessel (imo_number) WHERE is_deleted = false;"
    )
    op.execute("CREATE INDEX idx_vessel_ship_type ON vessel (ship_type) WHERE is_deleted = false;")
    # pg_trgm GIN 인덱스 (001에서 extension 생성됨).
    op.execute(
        "CREATE INDEX idx_vessel_name ON vessel USING gin (name gin_trgm_ops) "
        "WHERE is_deleted = false;"
    )

    # §7.2: updated_at 자동 갱신 트리거.
    op.execute(
        """
        CREATE TRIGGER trg_vessel_updated
        BEFORE UPDATE ON vessel
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 트리거·인덱스·제약은 테이블과 함께 삭제되지만 트리거는 명시적으로 제거한다.
    op.execute("DROP TRIGGER IF EXISTS trg_vessel_updated ON vessel;")
    op.drop_table("vessel")
