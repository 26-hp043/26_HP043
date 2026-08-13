"""app_user updated_at 자동 갱신 트리거

Revision ID: 022
Revises: 021
Create Date: 2026-08-13

DB_SCHEMA.md §7.2 [M-2] (updated_at 자동 갱신 트리거) · §2.15 (app_user) 참조.
020(app_user)이 ``updated_at`` 컬럼을 두고도 트리거를 빠뜨려 값이 영구히
``created_at``과 같았다. 001의 ``update_timestamp()`` 함수를 쓰는 다른
테이블(002 fuel_type · 003 vessel · 005~008)과 같은 패턴으로 맞춘다 (#317).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "022"
down_revision: str | Sequence[str] | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """DB_SCHEMA §7.2: updated_at 자동 갱신 트리거 — 002의 패턴과 동일."""
    op.execute(
        """
        CREATE TRIGGER trg_app_user_updated
        BEFORE UPDATE ON app_user
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_app_user_updated ON app_user;")
