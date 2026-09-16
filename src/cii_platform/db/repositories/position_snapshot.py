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
    # **`== 1`이다. `> 0`이 아니다** (`#1058`).
    #
    # CUBRID에는 `RETURNING`이 없어 `ON CONFLICT DO NOTHING … RETURNING id`를
    # `ON DUPLICATE KEY UPDATE`로 옮겼는데, 그 구문은 중복일 때 **행을 갱신한다.**
    # CUBRID는 MySQL 규약을 따라 삽입이면 1, 갱신이면 2를 돌려준다 — 로컬 실측이다.
    #
    #     최초 INSERT      rowcount=1
    #     중복(값 그대로)  rowcount=2
    #     중복(값 바뀜)    rowcount=2
    #
    # `> 0`이면 **중복도 참**이 되어 이 함수의 약속(「이미 있으면 넣지 않고 False」)이
    # 깨진다. AIS는 같은 관측을 여러 번 보내는 것이 정상이라(위 docstring) 그 판정이
    # 무너지면 수집 상태를 스냅샷 수로 가늠할 수 없게 된다.
    return result.rowcount == 1


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
