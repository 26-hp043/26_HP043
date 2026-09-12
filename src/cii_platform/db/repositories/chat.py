"""챗봇 대화 저장소 — 쿼리만 담당한다 (TECH_SPEC §16).

``chat_session``·``chat_message``(``DB_SCHEMA`` · ``PRD §7.8``·``§7.9``)는 **90일 뒤
지우는 표**다. 지우지 않는 ``audit_log``와 성격이 정반대라, 만료 청소가 이 모듈의
고유 책임이다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from cii_platform.db.models.chat import RETENTION_DAYS, ChatMessage, ChatSession

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def create_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    title: str | None = None,
    now: datetime | None = None,
) -> ChatSession:
    """세션 하나. ``expires_at``은 **여기서 확정한다**.

    보존 기간을 조회 시점에 계산하지 않는 이유 — 정책이 바뀌면 **과거 대화의 만료일이
    전부 따라 움직인다.** 만든 시점의 약속이 그대로 남아야 한다.

    **commit은 호출부가 한다** (다른 저장소와 같은 규약).
    """
    created = now or datetime.now(UTC)
    row = ChatSession(
        user_id=user_id,
        title=title,
        created_at=created,
        expires_at=created + timedelta(days=RETENTION_DAYS),
    )
    session.add(row)
    await session.flush()
    return row


async def add_message(
    session: AsyncSession,
    *,
    session_id: UUID,
    role: str,
    content: str,
    now: datetime | None = None,
) -> ChatMessage:
    """메시지 하나. ``content``에 **본문을 담는다**(``PRD §7.9``)."""
    row = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        sent_at=now or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def list_messages(
    session: AsyncSession, *, session_id: UUID, limit: int | None = None
) -> list[ChatMessage]:
    """세션의 메시지를 시간순으로.

    ``limit``은 **최근 N건**을 뜻한다 — 모델에 실어 보낼 이력을 자르는 데 쓴다
    (``llm/provider.py`` `MAX_HISTORY_TURNS` · 비용 가드 3).
    """
    statement = select(ChatMessage).where(ChatMessage.session_id == session_id)
    if limit is None:
        return list((await session.execute(statement.order_by(ChatMessage.sent_at))).scalars())
    recent = (
        await session.execute(statement.order_by(ChatMessage.sent_at.desc()).limit(limit))
    ).scalars()
    return sorted(recent, key=lambda row: row.sent_at)


async def purge_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """만료된 세션을 지운다 (``PRD §16.3`` 채팅 보존 정책 90일).

    :returns: 지운 세션 수.

    메시지는 FK ``ON DELETE CASCADE``로 함께 지워진다 — **두 번 지우지 않는다.**
    세션만 지우고 메시지가 남으면 고아 행이 쌓이고, 그것이 곧 「지웠다고 했는데
    남아 있는」 상태다.
    """
    cutoff = now or datetime.now(UTC)
    result = await session.execute(delete(ChatSession).where(ChatSession.expires_at <= cutoff))
    return result.rowcount or 0
