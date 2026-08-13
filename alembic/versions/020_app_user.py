"""app_user 테이블 — 구글 OIDC 인증 주체 (#273)

Revision ID: 020
Revises: 019
Create Date: 2026-08-13

PRD §7.10 · API_SPEC §1.2 기준. 인증은 구글 OIDC에 위임하며 비밀번호 관련
컬럼을 두지 않는다. 식별자는 ``google_sub``이고 ``email``은 non-unique다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "020"
down_revision: str | Sequence[str] | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("google_sub", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.CheckConstraint(
            r"email ~ '^[^@[:space:]]+@[^@[:space:]]+$'",
            name="chk_app_user_email_format",
        ),
    )
    op.create_index(
        "idx_app_user_google_sub",
        "app_user",
        ["google_sub"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_app_user_email",
        "app_user",
        ["email"],
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_table("app_user")
