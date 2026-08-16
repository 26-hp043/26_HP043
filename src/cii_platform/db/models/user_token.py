"""일회용 인증 토큰 (#408).

`DB_SCHEMA.md` §2.15.1 참조. 이메일 인증과 비밀번호 재설정에 쓰는 **한 번 쓰고
버리는 증명**이다.

세션(`user_session`)과 수명주기가 달라 별도 테이블로 둔다 — 세션은 로그인 상태를
유지하고 이 토큰은 단발성이다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base

#: 가입 확인 메일의 링크.
PURPOSE_EMAIL_VERIFY = "EMAIL_VERIFY"
#: 비밀번호 재설정 메일의 링크.
PURPOSE_PASSWORD_RESET = "PASSWORD_RESET"


class UserToken(Base):
    """일회용 인증 토큰 — 원문이 아니라 해시만 담는다."""

    __tablename__ = "user_token"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    user_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    purpose = sa.Column(sa.String(length=20), nullable=False)
    #: 토큰의 SHA-256 hex. **원문을 저장하지 않는다** — DB가 유출돼도 토큰을
    #: 되돌릴 수 없어야 한다(`user_session.session_token_hash`와 같은 규칙).
    token_hash = sa.Column(sa.String(length=64), nullable=False)
    expires_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    #: 사용 시각. NOT NULL이면 재사용 불가.
    used_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_user_token"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name="fk_user_token_user",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "purpose IN ('EMAIL_VERIFY', 'PASSWORD_RESET')",
            name="chk_user_token_purpose",
        ),
        sa.Index("idx_user_token_hash", "token_hash", unique=True),
        sa.Index("idx_user_token_user_purpose", "user_id", "purpose"),
    )
