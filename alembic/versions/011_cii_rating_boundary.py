"""cii_rating_boundary 테이블

Revision ID: 011
Revises: 010
Create Date: 2026-07-18

DB_SCHEMA.md §2.11 (cii_rating_boundary: 컬럼/인덱스/검증 제약 [M-3]) 참조.
이슈 #103 체크리스트 011.

주의 (AGENTS §3): 스키마만 생성한다. d-vector seed 값(§3.4)은 #33 seed가 넣는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | Sequence[str] | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "cii_rating_boundary",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("ship_type", sa.String(length=50), nullable=False),
        sa.Column("condition_expr", sa.String(length=200), nullable=False),
        sa.Column("capacity_basis", sa.String(length=10), nullable=False),
        sa.Column("d1", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("d2", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("d3", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("d4", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cii_rating_boundary"),
        # §2.11 [M-3] (원문 그대로): d-vector 순서 보장.
        sa.CheckConstraint(
            "d1 < d2 AND d2 < d3 AND d3 < d4",
            name="chk_d_order",
        ),
    )

    # §2.11 인덱스 (원문 그대로).
    op.execute(
        "CREATE UNIQUE INDEX idx_boundary_unique "
        "ON cii_rating_boundary (ship_type, condition_expr);"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("cii_rating_boundary")
