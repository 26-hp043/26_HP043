"""챗봇 대화 세션·메시지 (``PRD §7.8``·``§7.9`` · `#120`).

## 계산 경로와 격리한다

``§7.8``이 *"계산·보고 경로와 완전히 격리된 별도 저장소를 사용한다"*로 규정한다.
그래서 이 두 표는 ``calculation_run``·``voyage``를 **참조하지 않는다.** 챗봇이 인용한
계산은 감사 로그(``CHAT_TOOL_CALL``)가 ``calculation_run.id``로 가리킨다 — **재현의
원본은 그쪽**이고 챗봇 로그는 가리키기만 한다.

## 지우는 표다

``expires_at``이 생성 + 90일이다(``§16.3`` 채팅 보존 정책). ⚠️ **지우지 않는
``audit_log``와 성격이 정반대**라, 같은 내용을 두 곳에 넣으면 삭제 요청을 만족시킬 수
없다. 본문은 여기에만 있고 감사 로그에는 **해시만** 남는다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base

#: ``PRD §16.3`` 채팅 보존 정책 — ChatMessage 보존 기간 90일.
RETENTION_DAYS = 90

#: ``PRD §7.9`` — role은 둘이다.
ROLE_USER = "USER"
ROLE_ASSISTANT = "ASSISTANT"


class ChatSession(Base):
    """대화 세션 한 건 (``PRD §7.8``)."""

    __tablename__ = "chat_session"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성.
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    user_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    title = sa.Column(sa.String(length=200), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    #: 생성 + 90일. **컬럼으로 두는 이유**는 보존 기간이 바뀌어도 이미 만든 세션의
    #: 만료일이 따라 움직이지 않게 하기 위해서다 — 계산으로 유도하면 정책을 고치는
    #: 순간 과거 대화의 만료일이 전부 바뀐다.
    expires_at = sa.Column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_chat_session"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_chat_session_user", ondelete="CASCADE"
        ),
        sa.CheckConstraint("expires_at > created_at", name="chk_chat_session_expires"),
        sa.Index("idx_chat_session_expires", "expires_at"),
        sa.Index("idx_chat_session_user", "user_id", sa.text("created_at DESC")),
    )


class ChatMessage(Base):
    """메시지 한 건 (``PRD §7.9``).

    ``content``에 **본문을 담는다** — 정본이 *"메시지 본문(인용값 포함)"*으로 정했다.
    해시만 남기는 것은 **도구 호출의 인자**이고 그쪽은 감사 로그 소관이다. 둘을 섞으면
    정본과 어긋난다.
    """

    __tablename__ = "chat_message"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    session_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    role = sa.Column(sa.String(length=10), nullable=False)
    content = sa.Column(sa.Text(), nullable=False)
    sent_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_chat_message"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_session.id"],
            name="fk_chat_message_session",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("role IN ('USER','ASSISTANT')", name="chk_chat_message_role"),
        sa.Index("idx_chat_message_session", "session_id", "sent_at"),
    )
