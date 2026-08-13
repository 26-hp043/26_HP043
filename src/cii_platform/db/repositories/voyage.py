"""항차 저장소 — 쿼리만 담당한다 (TECH_SPEC §16, #53).

비즈니스 판단은 ``services``의 몫이다. 이 모듈은 **찾으면 반환하고 없으면 ``None``**을 준다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import select, tuple_

from cii_platform.db.models.voyage import Voyage
from cii_platform.db.models.voyage_fuel_use import VoyageFuelUse

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: API_SPEC §3.1 — 페이지 크기 기본 20, 최대 100 (vessel과 동일).
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

_CURSOR_SEP = "\x00"


class VoyageCursor(NamedTuple):
    """keyset 페이지네이션 커서 — ``(created_at, id)``의 마지막 값."""

    created_at: str
    voyage_id: str


def encode_cursor(cursor: VoyageCursor) -> str:
    import base64

    raw = f"{cursor.created_at}{_CURSOR_SEP}{cursor.voyage_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> VoyageCursor | None:
    import base64
    import binascii

    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    created_at, sep, voyage_id = raw.partition(_CURSOR_SEP)
    if not sep or not voyage_id:
        return None
    return VoyageCursor(created_at=created_at, voyage_id=voyage_id)


async def get_by_id(session: AsyncSession, voyage_id: UUID) -> Voyage | None:
    """활성 항차 1건을 조회한다 (soft delete 제외)."""
    stmt = select(Voyage).where(Voyage.id == voyage_id, Voyage.is_deleted.is_(False))
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_fuel_uses(session: AsyncSession, voyage_id: UUID) -> list[VoyageFuelUse]:
    """항차의 연료 사용 내역을 조회한다."""
    stmt = select(VoyageFuelUse).where(VoyageFuelUse.voyage_id == voyage_id)
    return list((await session.execute(stmt)).scalars().all())


async def list_active(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    limit: int,
    cursor: VoyageCursor | None = None,
    status: str | None = None,
    regulation_year: int | None = None,
) -> list[Voyage]:
    """활성 항차 목록을 조회한다 (API_SPEC §3.1).

    ``limit + 1``건을 가져온다 — ``has_more`` 판단용.
    """
    stmt = select(Voyage).where(Voyage.vessel_id == vessel_id, Voyage.is_deleted.is_(False))

    if status is not None:
        stmt = stmt.where(Voyage.status == status)
    if regulation_year is not None:
        stmt = stmt.where(Voyage.regulation_year == regulation_year)

    if cursor is not None:
        stmt = stmt.where(
            tuple_(Voyage.created_at, Voyage.id) > (cursor.created_at, cursor.voyage_id)
        )

    stmt = stmt.order_by(Voyage.created_at, Voyage.id).limit(limit + 1)
    return list((await session.execute(stmt)).scalars().all())


async def insert(session: AsyncSession, **fields: object) -> Voyage:
    """새 항차를 INSERT 한다. ``commit``은 호출부가 담당한다."""
    voyage = Voyage(**fields)
    session.add(voyage)
    await session.flush()
    return voyage


async def insert_fuel_use(session: AsyncSession, **fields: object) -> VoyageFuelUse:
    """항차 연료 사용 1건을 INSERT 한다."""
    fuel_use = VoyageFuelUse(**fields)
    session.add(fuel_use)
    await session.flush()
    return fuel_use
