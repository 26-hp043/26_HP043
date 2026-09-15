"""app_user ORM 모델 (#273).

DB_SCHEMA.md §2.15 (app_user) 참조. **`email`이 로그인 ID이자 식별 기준**이다 (#413).
"""

import uuid

from datetime import datetime, timezone

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class AppUser(Base):
    """사용자 — 이메일·비밀번호 인증 주체 (#414)."""

    __tablename__ = "app_user"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    email = sa.Column(sa.String(length=320), nullable=False)
    #: Argon2id 해시. **평문 비밀번호는 저장하지 않는다** (`DB_SCHEMA §2.15`).
    password_hash = sa.Column(sa.String(length=255), nullable=False)
    #: 이메일 인증 완료 시각. NULL이면 미인증 — **미인증도 로그인은 허용한다**
    #: (`PRD §7.10`). 토큰 발급·검증은 #408 소관이다.
    email_verified_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    display_name = sa.Column(sa.String(length=100), nullable=True)
    last_login_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    is_deleted = sa.Column(sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        # 이메일 형식 검증은 Pydantic 스키마에서 수행한다. CUBRID는 regex CHECK를
        # 지원하지 않으므로 DB 레벨 제약은 제거한다 (#1058).
        # `email`이 로그인 ID이자 유일 키다 (#413 · `DB_SCHEMA §2.15`).
        # 종전에는 `google_sub`이 유일 키였고 email에는 unique를 걸지 않았는데,
        # 그 근거(「구글 계정의 이메일은 변경될 수 있다」)는 구글 위임을
        # 그만두면서 전제 자체가 사라졌다.
        sa.Index(
            "idx_app_user_email",
            "email",
            unique=True,
        ),
    )
