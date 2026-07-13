"""pg_trgm extension + update_timestamp 함수

Revision ID: 001
Revises:
Create Date: 2026-07-09

DB_SCHEMA.md §2.1(인덱스), §7.2 [M-2] 참조.
- pg_trgm: vessel.name GIN 트라이그램 인덱스에 필요한 확장.
- update_timestamp(): updated_at 컬럼을 가진 테이블의 자동 갱신 트리거 함수.
  이후 마이그레이션(002 fuel_type, 003 vessel)의 트리거가 이 함수를 참조하므로
  가장 먼저 생성한다.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    # DB_SCHEMA.md §7.2 [M-2] 원문 그대로.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION IF EXISTS update_timestamp();")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm;")
