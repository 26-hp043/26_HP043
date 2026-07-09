"""regulation_year 테이블

Revision ID: 004
Revises: 003
Create Date: 2026-07-09

DB_SCHEMA.md §2.8 (regulation_year — 규정 연도 Z-factor) 참조.
FK가 없는 독립 테이블이며, updated_at 컬럼이 없으므로 트리거를 두지 않는다.
Z-factor seed 데이터는 이 PR 범위에서 제외한다 (DB_SCHEMA §8.1: 스키마와 seed 분리).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "regulation_year",
        # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("z_factor_percent", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_regulation_year"),
        sa.UniqueConstraint("year", name="uq_regulation_year_year"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("regulation_year")
