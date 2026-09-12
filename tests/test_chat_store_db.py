"""챗봇 대화 저장소 — 보존과 격리 (#120).

케이스: IT-CHAT-010 ~ IT-CHAT-015 (`TEST_PLAN §3.17`)

``chat_session``·``chat_message``는 **90일 뒤 지우는 표**다(`PRD §16.3` 채팅 보존
정책). ⚠️ **지우지 않는 `audit_log`와 성격이 정반대**라, 여기서 보는 것은 「저장이
되는가」가 아니라 **「지워지는가」와 「본문이 한 곳에만 있는가」**다.

두 곳에 같은 내용이 있으면 삭제 요청(`§16.3` GDPR 유사)이 왔을 때 **한쪽을 지울 수
없어 요구를 만족시킬 수 없다.**
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.models.chat import RETENTION_DAYS, ROLE_ASSISTANT, ROLE_USER
from cii_platform.db.repositories import chat as chat_repo
from cii_platform.services.audit import content_digest

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _insert_user(session, email: str) -> UUID:
    row = await session.execute(
        text(f"INSERT INTO app_user (email, password_hash) VALUES ('{email}', 'x') RETURNING id")
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_expiry_is_fixed_at_creation(session):
    """IT-CHAT-010 — 만료일은 **만든 시점에 확정**된다. 조회 때 계산하지 않는다.

    계산으로 유도하면 보존 정책을 고치는 순간 **과거 대화의 만료일이 전부 바뀐다.**
    만든 시점의 약속이 그대로 남아야 한다.
    """
    user_id = await _insert_user(session, "chat1@example.com")

    created = await chat_repo.create_session(session, user_id=user_id, now=NOW)

    assert created.expires_at == NOW + timedelta(days=RETENTION_DAYS)
    assert RETENTION_DAYS == 90  # `PRD §16.3` 채팅 보존 정책


@pytest.mark.asyncio
async def test_expired_sessions_are_purged_with_their_messages(session):
    """IT-CHAT-011 — 만료 세션을 지우면 **메시지도 함께** 사라진다.

    세션만 지우고 메시지가 남으면 고아 행이 쌓이고, 그것이 곧 **「지웠다고 했는데
    남아 있는」** 상태다. FK `ON DELETE CASCADE`가 그것을 막는다.
    """
    user_id = await _insert_user(session, "chat2@example.com")
    old = await chat_repo.create_session(session, user_id=user_id, now=NOW - timedelta(days=100))
    await chat_repo.add_message(session, session_id=old.id, role=ROLE_USER, content="지워질 것")
    fresh = await chat_repo.create_session(session, user_id=user_id, now=NOW)
    await chat_repo.add_message(session, session_id=fresh.id, role=ROLE_USER, content="남을 것")

    purged = await chat_repo.purge_expired(session, now=NOW)

    assert purged == 1
    left = await session.execute(
        text(f"SELECT count(*) FROM chat_message WHERE session_id = '{old.id}'::uuid")
    )
    assert left.scalar_one() == 0
    assert len(await chat_repo.list_messages(session, session_id=fresh.id)) == 1


@pytest.mark.asyncio
async def test_a_session_that_has_not_expired_survives(session):
    """IT-CHAT-012 — 만료 전 세션은 남는다. 청소가 과하면 대화가 사라진다."""
    user_id = await _insert_user(session, "chat3@example.com")
    live = await chat_repo.create_session(session, user_id=user_id, now=NOW)

    assert await chat_repo.purge_expired(session, now=NOW + timedelta(days=89)) == 0
    assert await chat_repo.purge_expired(session, now=NOW + timedelta(days=91)) == 1
    assert live.expires_at > NOW


@pytest.mark.asyncio
async def test_history_is_cut_to_recent_turns(session):
    """IT-CHAT-013 — 이력은 **최근 N건**으로 자른다 (비용 가드 3).

    대화가 길어질수록 입력 토큰이 누적된다. 자르되 **순서는 시간순**이어야 한다 —
    뒤집힌 이력을 모델에 주면 대화가 거꾸로 읽힌다.
    """
    user_id = await _insert_user(session, "chat4@example.com")
    chat = await chat_repo.create_session(session, user_id=user_id, now=NOW)
    for i in range(8):
        await chat_repo.add_message(
            session,
            session_id=chat.id,
            role=ROLE_USER if i % 2 == 0 else ROLE_ASSISTANT,
            content=f"메시지 {i}",
            now=NOW + timedelta(minutes=i),
        )

    recent = await chat_repo.list_messages(session, session_id=chat.id, limit=3)

    assert [m.content for m in recent] == ["메시지 5", "메시지 6", "메시지 7"]


@pytest.mark.asyncio
async def test_role_is_constrained_to_two_values(session):
    """IT-CHAT-014 — `role`은 둘뿐이다 (`PRD §7.9`). DB가 막는다."""
    from sqlalchemy.exc import IntegrityError

    user_id = await _insert_user(session, "chat5@example.com")
    chat = await chat_repo.create_session(session, user_id=user_id, now=NOW)

    with pytest.raises(IntegrityError):
        await chat_repo.add_message(
            session, session_id=chat.id, role="SYSTEM", content="허용되지 않는 역할"
        )


def test_audit_keeps_a_digest_not_the_text():
    """IT-CHAT-015 — 감사 로그는 **해시**를 남긴다. 원문이 아니다.

    ⚠️ `audit_log`는 **지우지 않는 기록**이고 `chat_message`는 **90일 뒤 지우는
    기록**이다. 같은 내용을 두 곳에 넣으면 삭제 요청을 만족시킬 수 없다.
    """
    text_in = "우리 HANARO호 이야기"

    digest = content_digest(text_in)

    assert len(digest) == 64  # sha256 hex
    assert text_in not in digest
    # 같은 내용인지 대조는 된다 — 그것이 해시를 남기는 이유다.
    assert digest == content_digest(text_in)
    assert digest != content_digest(text_in + " ")
