"""weather_model_parameter 테이블

Revision ID: 012
Revises: 011
Create Date: 2026-07-18

DB_SCHEMA.md §2.12 (weather_model_parameter: 컬럼/인덱스 [S-5]) 참조.
이슈 #103 체크리스트 012.

주의 (AGENTS §3): 스키마만 생성한다. Townsin-Kwon 파라미터 seed 값은 #35가 넣는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | Sequence[str] | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "weather_model_parameter",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # NONE, SIMPLE_RULE, TOWNSIN_KWON_ALPHA (§2.12 설명 — CHECK는 정본에 없음).
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("source_ref", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weather_model_parameter"),
    )

    # §2.12 [S-5] (원문 그대로): (model_version, key) 조합의 유일성 보장.
    op.execute(
        "CREATE UNIQUE INDEX idx_weather_param_unique "
        "ON weather_model_parameter (model_version, key);"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("weather_model_parameter")
