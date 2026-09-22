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


def is_expired(row: ChatSession, *, now: datetime | None = None) -> bool:
    """대화가 보존 기한(``expires_at`` · 생성 + 90일)을 넘겼는가 (`#1632`).

    **경계는 만료다**(``expires_at <= now``) — :func:`purge_expired`가 같은 조건으로
    지운다. 두 조건이 어긋나면 「지워지지 않았지만 쓸 수 없는」 또는 그 반대의 순간이 생긴다.

    ⚠️ **청소 작업의 실행 여부에 기대지 않는다.** 청소는 하루 한 번 도는 보관 정리이고,
    그 사이에 만료된 대화로 외부 모델을 부르거나 메시지를 쌓는 것을 막는 것은 API의 일이다.

    시간대 없는 값은 UTC로 읽는다 — 저장이 UTC로 되며(``create_session``), 드라이버가
    시간대를 떼어 돌려주는 경우가 있다.
    """
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= (now or datetime.now(UTC))


async def get_session_row(session: AsyncSession, *, session_id: UUID) -> ChatSession | None:
    """대화 하나. 없으면 ``None``.

    **주인 확인은 호출부가 한다** — 저장소는 「누가 볼 수 있는가」를 모른다. 여기서
    ``user_id``까지 받으면 라우트가 404와 403을 구분할 근거를 잃는다
    (``API_SPEC §15.4``는 남의 대화를 **404**로 규정한다). 귀속 선박(``vessel_id``)을
    읽는 경로도 이 함수 하나다 (#1242).
    """
    stmt = select(ChatSession).where(ChatSession.id == session_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_vessel(session: AsyncSession, *, session_id: UUID, vessel_id: UUID | None) -> None:
    """대화의 선박 귀속을 정한다 (#1242).

    화면이 ``vessel_id``를 넘긴 턴은 그 값을 **세션에도 싣는다**(화면이 항상 더
    최신) — 다음 턴부터 화면 없이 물어도 그 선박으로 답한다. ``search_vessel``의
    고유 일치도 같은 경로로 싣는다. **commit은 호출부가 한다**(다른 함수와 같은 규약).
    """
    row = await get_session_row(session, session_id=session_id)
    if row is None or row.vessel_id == vessel_id:
        return
    row.vessel_id = vessel_id
    await session.flush()


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


async def delete_for_user(session: AsyncSession, *, user_id: UUID) -> int:
    """그 사용자의 대화를 **전부 지운다** (``PRD §16.3`` GDPR 유사 삭제 · `#1330`).

    :returns: 지운 세션 수.

    :func:`purge_expired`와 같은 이유로 세션만 지운다 — 메시지는 FK
    ``ON DELETE CASCADE``로 함께 간다.

    ## 왜 soft delete가 아닌가

    탈퇴(``app_user.is_deleted``)가 soft delete인 것은 **계산·감사 기록의 주체를
    되짚을 수 있어야** 하기 때문이다(``DB_SCHEMA §7.1``·``§7.3``). 대화 원문은 그
    근거가 아니다 — 규제 대응에 쓰이지 않고, 남겨 둘 이유가 **보존 정책 90일뿐**인데
    삭제 요청은 그 기간을 앞당기는 것이다. 플래그만 세우면 **원문이 그대로 남아
    「지웠다」가 거짓**이 된다.
    """
    result = await session.execute(delete(ChatSession).where(ChatSession.user_id == user_id))
    return result.rowcount or 0


async def delete_one(session: AsyncSession, *, session_id: UUID, user_id: UUID) -> bool:
    """대화 하나를 지운다 (`#1330`).

    :returns: 지웠으면 ``True``.

    **``user_id``를 조건에 함께 넣는다** — 먼저 조회해 주인을 확인하고 지우면 그
    사이에 다른 요청이 끼어들 수 있고, 무엇보다 **조건을 두 곳에 적게 된다.**
    남의 대화를 지우려는 요청은 0행이 지워지고 호출부가 404를 낸다(``§15.1``이
    조회에서 쓰는 규칙과 같다 — 남의 것은 **없는 것**이다).
    """
    result = await session.execute(
        delete(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
    )
    return bool(result.rowcount)
