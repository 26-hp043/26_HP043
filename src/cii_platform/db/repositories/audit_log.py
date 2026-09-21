"""감사 로그 저장소 (TECH_SPEC §16, #277 · 조회 #1241).

``audit_log``는 append-only다 — 이 모듈에 UPDATE·DELETE는 없다.

⚠️ **``action``은 CUBRID 예약어다.** ORM 식(``AuditLog.action``)은 컴파일러가
인용하므로 안전하지만, 생 SQL을 쓸 때는 반드시 ``"action"``으로 인용한다
(`#673` 실측).
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy import select, tuple_

from cii_platform.db.models.app_user import AppUser
from cii_platform.db.models.audit_log import AuditLog

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

#: 한 페이지 기본·최대 (``API_SPEC §1.5`` 공통 정책 · `§1.9`와 같은 값).
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: 커서 인코딩 구분자 — ISO 8601 문자열과 UUID에 등장할 수 없는 제어문자.
_CURSOR_SEP = "\x00"


class AuditCursor(NamedTuple):
    """keyset 커서 — 정렬 키 ``(timestamp, id)``의 마지막 값.

    offset을 쓰지 않는 이유는 계산 이력(`#51`)과 같다: 앞 페이지에서 행이 빠지면
    offset은 다음 페이지가 한 건을 건너뛴다. ``timestamp``는 ``now()``
    server_default라 **같은 요청 안에서 여러 건이 같은 값**을 가질 수 있어
    ``id``를 2차 키로 둔다.

    값은 **네이티브 타입**으로 가진다 — 문자열을 그대로 바인딩하면 비교 연산자를
    찾지 못한다. 직렬화는 encode/decode에서만 일어난다.
    """

    timestamp: datetime
    audit_log_id: UUID


def encode_cursor(cursor: AuditCursor) -> str:
    raw = f"{cursor.timestamp.isoformat()}{_CURSOR_SEP}{cursor.audit_log_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> AuditCursor | None:
    """커서를 되돌린다. 형식이 깨졌으면 ``None`` — **예외를 던지지 않는다.**

    잘못된 커서는 사용자가 URL을 손댄 경우가 대부분이고, 그때 500이 나가면 안 된다.
    오류로 볼지 첫 페이지로 볼지는 서비스가 정한다(`§1.9`와 같은 규약).
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    head, sep, tail = raw.partition(_CURSOR_SEP)
    if not sep:
        return None
    try:
        return AuditCursor(datetime.fromisoformat(head), UUID(tail))
    except ValueError:
        return None


async def insert_event(
    session: AsyncSession,
    *,
    action: str,
    user_id: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    details: dict[str, object] | None = None,
    ip_address: str | None = None,
) -> None:
    """감사 로그 1건을 INSERT 하고 flush한다. ``commit``은 호출부가 담당한다."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details_json=details,
            ip_address=ip_address,
        )
    )
    await session.flush()


async def list_events(
    session: AsyncSession,
    *,
    limit: int,
    cursor: AuditCursor | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditLog]:
    """감사 로그를 최신순으로 조회한다 (``API_SPEC §16.1`` · `#1241`).

    ``limit + 1``건을 가져온다 — 호출부가 별도 COUNT 없이 ``has_more``를 판단한다.

    ⚠️ **쓰기 경로를 방해하지 않는다.** 이 함수는 ``SELECT``만 하고 잠금을 잡지
    않는다. `#1241`의 완료 기준 둘째가 그것이다 — 조회가 계산·적재를 막으면
    감사 자체가 부담이 된다.

    필터는 전부 AND다. ``until``은 **경계를 포함한다**(``<=``) — 「9월 20일까지」를
    적은 사용자는 그날 23:59의 사건을 기대한다.
    """
    stmt = select(AuditLog)

    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if since is not None:
        stmt = stmt.where(AuditLog.timestamp >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.timestamp <= until)

    if cursor is not None:
        # 행 값 비교 — OR로 풀어 쓰면 인덱스를 타지 못하는 형태가 되기 쉽다.
        stmt = stmt.where(
            tuple_(AuditLog.timestamp, AuditLog.id) < (cursor.timestamp, cursor.audit_log_id)
        )

    stmt = stmt.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit + 1)
    return list((await session.execute(stmt)).scalars())


async def get_actors(session: AsyncSession, user_ids: Sequence[str]) -> dict[str, AppUser]:
    """감사 행의 ``user_id`` → ``app_user`` 행 (`#1515`).

    **탈퇴 계정도 포함한다** — ``is_deleted``로 거르지 않는다. 감사가 답해야 하는
    질문은 「지금 누가 있는가」가 아니라 **「그때 누가 했는가」**이고, 탈퇴는 soft
    delete라 행이 남아 있다(``services.audit.record_account_delete``).

    ``audit_log.user_id``는 ``VARCHAR``이고 ``app_user.id``는 ``CHAR(32)``라 SQL
    JOIN으로 묶지 않는다 — 문자열 모양(하이픈 유무)이 갈리면 조용히 0건이 된다.
    UUID로 파싱되는 값만 골라 ``IN``으로 묻고, 파싱되지 않는 값(`dev` 스텁·검사용
    표식)은 「행위자를 못 찾음」으로 남긴다. 반환 dict의 키는 **호출자가 준 문자열
    그대로**다.
    """
    # 같은 계정이 하이픈 유무가 다른 두 문자열로 적혀 있어도 둘 다 풀리게 UUID마다
    # 원문 목록을 둔다.
    wanted: dict[UUID, list[str]] = {}
    for raw in user_ids:
        if raw is None:
            continue
        try:
            wanted.setdefault(UUID(str(raw)), []).append(raw)
        except ValueError:
            continue
    if not wanted:
        return {}
    stmt = select(AppUser).where(AppUser.id.in_(list(wanted)))
    rows = (await session.execute(stmt)).scalars().all()
    return {raw: row for row in rows for raw in wanted.get(UUID(str(row.id)), ())}
