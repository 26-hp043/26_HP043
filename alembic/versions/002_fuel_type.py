"""fuel_type 테이블

Revision ID: 002
Revises: 001
Create Date: 2026-07-09

DB_SCHEMA.md §2.9 (fuel_type), §7.2 [M-2] (updated_at 트리거) 참조.
vessel.default_fuel_type가 fuel_type(code)를 FK로 참조하므로(§2.1 [S-1], §7.1)
vessel(003)보다 먼저 생성한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | Sequence[str] | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "fuel_type",
        # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("cf", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column(
            "unit",
            sa.String(length=30),
            server_default=sa.text("'tCO₂/tFuel'"),
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        # [X-3] version / content_hash: 파라미터 세트 변경 추적용.
        sa.Column(
            "version",
            sa.String(length=50),
            server_default=sa.text("'1.0'"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=71), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_fuel_type"),
        sa.UniqueConstraint("code", name="uq_fuel_type_code"),
    )
    # DB_SCHEMA §7.2: updated_at 자동 갱신 트리거.
    op.execute(
        """
        CREATE TRIGGER trg_fuel_type_updated
        BEFORE UPDATE ON fuel_type
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 트리거는 테이블과 함께 삭제되지만 명시적으로 제거한 뒤 테이블을 삭제한다.
    op.execute("DROP TRIGGER IF EXISTS trg_fuel_type_updated ON fuel_type;")
    op.drop_table("fuel_type")
