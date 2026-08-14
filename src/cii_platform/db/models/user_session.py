"""user_session ORM 모델 (#273).

DB_SCHEMA.md §2.16 (user_session) 참조. 세션 토큰 원문을 저장하지 않는다.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class UserSession(Base):
    """로그인 세션 — SHA-256 해시만 저장."""

    __tablename__ = "user_session"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    user_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    session_token_hash = sa.Column(sa.String(length=64), nullable=False)
    csrf_token_hash = sa.Column(sa.String(length=64), nullable=False)
    expires_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    revoked_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    user_agent = sa.Column(sa.String(length=255), nullable=True)
    ip_address = sa.Column(sa.String(length=45), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_user_session"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name="fk_user_session_user",
            ondelete="CASCADE",
        ),
        sa.Index("idx_session_token", "session_token_hash", unique=True),
        sa.Index(
            "idx_session_user",
            "user_id",
            sa.text("created_at DESC"),
        ),
        sa.Index(
            "idx_session_expiry",
            "expires_at",
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )
