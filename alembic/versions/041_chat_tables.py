"""챗봇 대화 세션·메시지 테이블 신설

Revision ID: 041
Revises: 040
Create Date: 2026-09-13

이슈 #120 · **정본이 필드까지 정해 두었는데 테이블이 없었다.**

무엇을 만드나
--------------
``chat_session`` · ``chat_message`` — ``PRD §7.8``·``§7.9``의 필드 표 그대로다.
값을 새로 정하지 않았다.

계산 경로와 격리한다
--------------------
``PRD §7.8``이 *"계산·보고 경로와 완전히 격리된 별도 저장소를 사용한다"*로 규정한다.
그래서 이 두 표는 ``calculation_run``·``voyage``를 **참조하지 않는다.** 챗봇이 인용한
계산은 감사 로그(``CHAT_TOOL_CALL``)가 ``calculation_run.id``로 가리킨다 —
**재현의 원본은 그쪽이고 챗봇 로그는 가리키기만 한다** (`#120` 아키텍처).

90일 뒤 지운다
--------------
``expires_at``이 생성 + 90일이다(``PRD §16.3`` 채팅 보존 정책 · ``§7.8``).
**이 표는 지우는 표**라, 지우지 않는 ``audit_log``와 성격이 정반대다. 그래서 같은
내용을 두 곳에 넣지 않는다 — 넣으면 삭제 요청(``§16.3`` GDPR 유사)을 만족시킬 수 없다.

되돌리기
--------
``downgrade``는 표를 지운다. **90일 뒤 어차피 지워지는 대화 기록**이고 계산 원본은
``calculation_run``에 따로 있으므로, 잃는 것은 그 사이의 대화뿐이다. ``EPHEMERAL``로
분류한다 — ``user_session``(다시 로그인하면 된다)과 같은 성격이다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_session",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_chat_session"),
        # 계정을 지우면 대화도 함께 지운다 — 계산 이력과 달리 **보존 의무가 없다**
        # (90일 만료 대상이다). `app_user`는 탈퇴 시 행이 남으므로(`#506`) 실제
        # 물리 삭제는 드물지만, 남는 쪽을 고르면 삭제 요청을 만족시킬 수 없다.
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name="fk_chat_session_user",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("expires_at > created_at", name="chk_chat_session_expires"),
    )
    # 만료분 청소가 이 인덱스를 쓴다.
    op.create_index("idx_chat_session_expires", "chat_session", ["expires_at"])
    op.create_index(
        "idx_chat_session_user", "chat_session", ["user_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "chat_message",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_message"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_session.id"],
            name="fk_chat_message_session",
            ondelete="CASCADE",
        ),
        # `PRD §7.9` — role은 USER·ASSISTANT 둘이다.
        sa.CheckConstraint("role IN ('USER','ASSISTANT')", name="chk_chat_message_role"),
    )
    op.create_index("idx_chat_message_session", "chat_message", ["session_id", "sent_at"])


def downgrade() -> None:
    op.drop_index("idx_chat_message_session", table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_index("idx_chat_session_user", table_name="chat_session")
    op.drop_index("idx_chat_session_expires", table_name="chat_session")
    op.drop_table("chat_session")
