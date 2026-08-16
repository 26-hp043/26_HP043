"""user_token 테이블 — 일회용 인증 토큰 (#408)

Revision ID: 034
Revises: 033
Create Date: 2026-08-17

`DB_SCHEMA §2.15.1`(#413 신설) 계약을 그대로 구현한다. 이메일 인증과 비밀번호
재설정에 쓰는 한 번 쓰고 버리는 증명이다.

원문 대신 해시만 저장한다
--------------------------
``user_session.session_token_hash``(§2.16)와 같은 규칙이다 — **DB가 유출돼도 토큰을
되돌릴 수 없어야 한다.** 원문은 메일 본문에만 실린다.

``token_hash``에 UNIQUE를 거는 이유는 검증이 이 값으로 단건 조회하기 때문이고,
해시 충돌이 곧 남의 토큰으로 통과하는 경로가 되기 때문이다.

soft delete를 두지 않는다
--------------------------
일회용 증명이라 「지웠지만 흔적을 남긴다」가 의미가 없다. 사용 여부는 ``used_at``이
표시하고, 사용자가 삭제되면 FK CASCADE로 함께 사라진다 — 토큰만 남으면 소유자를
알 수 없는 증명이 된다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "034"
down_revision: str | Sequence[str] | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_token",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
    )
    op.create_index("idx_user_token_hash", "user_token", ["token_hash"], unique=True)
    op.create_index("idx_user_token_user_purpose", "user_token", ["user_id", "purpose"])


def downgrade() -> None:
    op.drop_index("idx_user_token_user_purpose", table_name="user_token")
    op.drop_index("idx_user_token_hash", table_name="user_token")
    op.drop_table("user_token")
