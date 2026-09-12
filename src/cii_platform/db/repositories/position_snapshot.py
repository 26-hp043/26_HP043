"""선박 위치 스냅샷 저장소 — 쿼리만 담당한다 (TECH_SPEC §16).

``vessel_position_snapshot``(``DB_SCHEMA §2.21``)은 **덮어쓰지 않고 쌓는다** —
``vessel.current_lat/lon``이 「지금」 한 칸이라면 이 표는 「지나온 자리」다.
``idx_vessel_position_snapshot_vessel_observed``가 `(vessel_id, observed_at DESC)`인
것이 그 전제다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
    """스냅샷 한 건을 넣는다. **이미 있으면 넣지 않고 ``False``를 돌려준다.**

    AIS는 같은 관측을 **여러 번 보내는 것이 정상**이다(재전송·구독 중복). 중복을
    그대로 쌓으면 항적이 같은 점에서 여러 번 꺾인 것처럼 보이고, 스냅샷 수로 수집
    상태를 가늠할 수 없게 된다. 그래서 `(vessel_id, source, observed_at)` UNIQUE에
    ``ON CONFLICT DO NOTHING``을 건다 — **먼저 조회해 보고 넣는 방식은 경쟁 조건에서
    새고**, 수집은 여러 배치가 겹쳐 돌 수 있다.

    **commit은 호출부가 한다** (다른 저장소와 같은 규약).
    """
    statement = (
        pg_insert(VesselPositionSnapshot)
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
        .on_conflict_do_nothing(index_elements=["vessel_id", "source", "observed_at"])
        .returning(VesselPositionSnapshot.id)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None


async def latest_for_vessel(
    session: AsyncSession, *, vessel_id: UUID
) -> VesselPositionSnapshot | None:
    """가장 최근 **관측** 한 건. 수신 시각이 아니라 ``observed_at`` 기준이다."""
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
    """항적 — 오래된 것부터. 지도가 선을 그리려면 시간순이어야 한다.

    ``limit``은 **방어 상한**이다. AIS는 분 단위로 들어오므로 한 척의 한 달이 수만
    행이 될 수 있고, 창을 지정하지 않은 요청 하나가 그것을 전부 끌어오면 안 된다.
    """
    statement = select(VesselPositionSnapshot).where(VesselPositionSnapshot.vessel_id == vessel_id)
    if since is not None:
        statement = statement.where(VesselPositionSnapshot.observed_at >= since)
    if until is not None:
        statement = statement.where(VesselPositionSnapshot.observed_at <= until)
    result = await session.execute(
        statement.order_by(VesselPositionSnapshot.observed_at.asc()).limit(limit)
    )
    return list(result.scalars().all())
