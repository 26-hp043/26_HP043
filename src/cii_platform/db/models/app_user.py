"""app_user ORM 모델 (#273).

DB_SCHEMA.md §2.15 (app_user) 참조. 구글 OIDC `sub`를 식별자로 쓴다.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class AppUser(Base):
    """사용자 — 구글 OIDC 인증 주체."""

    __tablename__ = "app_user"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    google_sub = sa.Column(sa.String(length=255), nullable=False)
    email = sa.Column(sa.String(length=320), nullable=False)
    display_name = sa.Column(sa.String(length=100), nullable=True)
    last_login_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    is_deleted = sa.Column(sa.Boolean(), server_default=sa.text("false"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.CheckConstraint(
            r"email ~ '^[^@[:space:]]+@[^@[:space:]]+$'",
            name="chk_app_user_email_format",
        ),
        sa.Index(
            "idx_app_user_google_sub",
            "google_sub",
            unique=True,
            postgresql_where=sa.text("is_deleted = false"),
        ),
        sa.Index(
            "idx_app_user_email",
            "email",
            postgresql_where=sa.text("is_deleted = false"),
        ),
    )
