"""위치 스냅샷 저장소 (#764)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy_cubrid.dml import insert as cubrid_insert

from cii_platform.db.models.vessel_position_snapshot import VesselPositionSnapshot

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def insert_snapshot(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    source: str,
    lat: Decimal,
    lon: Decimal,
    observed_at: datetime,
    sog_kn: Decimal | None = None,
    cog_deg: Decimal | None = None,
    nav_status: int | None = None,
) -> bool:
    """스냅샷 한 건을 넣는다. 이미 있으면 넣지 않고 False를 돌려준다."""
    # CUBRID: ON DUPLICATE KEY UPDATE로 중복 무시.
    # RETURNING 미지원이므로 rowcount로 판단.
    statement = (
        cubrid_insert(VesselPositionSnapshot)
        .values(
            vessel_id=vessel_id,
            source=source,
            lat=lat,
            lon=lon,
            observed_at=observed_at,
            sog_kn=sog_kn,
            cog_deg=cog_deg,
            nav_status=nav_status,
        )
        .on_duplicate_key_update(source=source)
    )
    result = await session.execute(statement)
    return result.rowcount > 0


async def latest_for_vessel(
    session: AsyncSession, *, vessel_id: UUID
) -> VesselPositionSnapshot | None:
    """가장 최근 관측 한 건."""
    result = await session.execute(
        select(VesselPositionSnapshot)
        .where(VesselPositionSnapshot.vessel_id == vessel_id)
        .order_by(VesselPositionSnapshot.observed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_track(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
) -> list[VesselPositionSnapshot]:
    """항적 — 오래된 것부터."""
    statement = select(VesselPositionSnapshot).where(VesselPositionSnapshot.vessel_id == vessel_id)
    if since is not None:
        statement = statement.where(VesselPositionSnapshot.observed_at >= since)
    if until is not None:
        statement = statement.where(VesselPositionSnapshot.observed_at <= until)
    result = await session.execute(
        statement.order_by(VesselPositionSnapshot.observed_at.asc()).limit(limit)
    )
    return list(result.scalars().all())
