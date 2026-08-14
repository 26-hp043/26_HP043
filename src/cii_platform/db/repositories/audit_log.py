"""감사 로그 저장소 — 쓰기만 담당한다 (TECH_SPEC §16, #277).

``audit_log``는 append-only다. 조회 요구(화면 표시)는 #65가 담당하며, 그 전에는
이 모듈의 ``insert_event``만 쓴다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.db.models.audit_log import AuditLog

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


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
