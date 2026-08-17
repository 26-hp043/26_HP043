"""기상 스냅샷 저장소 — 쿼리만 담당한다 (TECH_SPEC §16).

``weather_snapshot``(``DB_SCHEMA §2.13``)은 **캐시이자 근거**다. 계산이 어떤 기상
값을 썼는지 나중에 물을 수 있어야 하므로(``TECH_SPEC §5.4``), 조회할 때마다 덮어쓰지
않고 **행을 쌓는다** — ``idx_weather_cache``가 `(lat_rounded, lon_rounded,
fetched_at DESC)`인 것이 그 전제다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from cii_platform.db.models.weather_snapshot import WeatherSnapshot

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession


async def insert_snapshot(
    session: AsyncSession,
    *,
    lat: Decimal,
    lon: Decimal,
    lat_rounded: Decimal,
    lon_rounded: Decimal,
    fetched_at: datetime,
    wave_height_m: Decimal | None,
    wave_direction_deg: Decimal | None,
    wave_period_s: Decimal | None,
    wind_speed_ms: Decimal | None,
    wind_direction_deg: Decimal | None,
    source: str,
) -> WeatherSnapshot:
    """스냅샷 한 건을 넣는다. **commit은 호출부가 한다** (다른 저장소와 같은 규약)."""
    snapshot = WeatherSnapshot(
        lat=lat,
        lon=lon,
        lat_rounded=lat_rounded,
        lon_rounded=lon_rounded,
        fetched_at=fetched_at,
        wave_height_m=wave_height_m,
        wave_direction_deg=wave_direction_deg,
        wave_period_s=wave_period_s,
        wind_speed_ms=wind_speed_ms,
        wind_direction_deg=wind_direction_deg,
        source=source,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def find_last_snapshot(
    session: AsyncSession, *, lat_rounded: Decimal, lon_rounded: Decimal
) -> WeatherSnapshot | None:
    """그 격자의 **가장 최근** 스냅샷 (``TECH_SPEC §7.1`` ``get_last_snapshot``).

    **신선도를 여기서 판정하지 않는다.** 24시간이 넘었는지, 6시간이 넘었는지는
    fallback 정책(``§7.3``)이고 그 판단은 서비스 계층의 몫이다 — 저장소가 오래된
    행을 숨기면 「없다」와 「낡았다」가 구분되지 않는다.
    """
    stmt = (
        select(WeatherSnapshot)
        .where(
            WeatherSnapshot.lat_rounded == lat_rounded,
            WeatherSnapshot.lon_rounded == lon_rounded,
        )
        .order_by(WeatherSnapshot.fetched_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()
