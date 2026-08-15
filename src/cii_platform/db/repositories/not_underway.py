"""not under way 구간 저장소 — 쿼리만 담당한다 (TECH_SPEC §16, #353).

``not_underway_period`` · ``not_underway_fuel_use``(``#345``, 마이그레이션 025)를
읽는다. 구간 CRUD는 ``#370`` 소관이며 여기에는 **YTD 집계에 필요한 조회만** 둔다.

비즈니스 판단은 ``services``의 몫이다 — 어떤 구간을 포함할지의 규칙(연도 귀속·
``as_of`` 절단)은 인자로 받고, 여기서는 그대로 WHERE 절로 옮긴다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import func, select

from cii_platform.db.models.not_underway_fuel_use import NotUnderwayFuelUse
from cii_platform.db.models.not_underway_period import NotUnderwayPeriod

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class NotUnderwayFuelTotal(NamedTuple):
    """유종별 not under way 연료 합계 1행."""

    fuel_type: str
    fuel_ton: Decimal


async def sum_fuel_by_type(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime | None = None,
) -> list[NotUnderwayFuelTotal]:
    """선박·규제연도의 not under way 연료를 **유종별로 합산**해 돌려준다.

    행을 그대로 넘기지 않고 DB에서 합산하는 이유는, 한 선박의 한 해 구간 수가
    항차 수보다 훨씬 많을 수 있기 때문이다(정박은 항차마다 최소 2회 생긴다).
    ``idx_not_underway_period_vessel_year``가 이 조회의 인덱스다.

    **``as_of`` 절단은 ``started_at`` 기준이다.** 구간이 ``as_of``를 걸쳐 진행
    중이면 그 구간에 **이미 기록된 연료를 전액 포함**한다. ``not_underway_fuel_use``
    행은 소모가 확인된 실적이지 기간에 비례해 안분할 수 있는 값이 아니며, 기간으로
    자르면 「정박이 지속되면 등급이 나빠진다」가 구간 종료 시점에만 반영되어 실시간
    화면(``UIFLOW 2-9``)의 전제가 깨진다.

    ``is_deleted`` 구간은 제외한다. 자식 행(``not_underway_fuel_use``)에는 소프트
    삭제 플래그가 없고 부모가 CASCADE로 지우므로, 부모 플래그 하나로 판정한다.

    :returns: ``(fuel_type, fuel_ton)`` 목록. 기록이 없으면 **빈 목록**이다 —
        정박 기록이 없는 선박은 정상 상태이므로 오류로 만들지 않는다.
    """
    stmt = (
        select(
            NotUnderwayFuelUse.fuel_type,
            func.sum(NotUnderwayFuelUse.fuel_ton).label("fuel_ton"),
        )
        .join(NotUnderwayPeriod, NotUnderwayFuelUse.period_id == NotUnderwayPeriod.id)
        .where(
            NotUnderwayPeriod.vessel_id == vessel_id,
            NotUnderwayPeriod.regulation_year == regulation_year,
            NotUnderwayPeriod.is_deleted.is_(False),
        )
        .group_by(NotUnderwayFuelUse.fuel_type)
        .order_by(NotUnderwayFuelUse.fuel_type)
    )
    if as_of is not None:
        stmt = stmt.where(NotUnderwayPeriod.started_at <= as_of)

    rows = (await session.execute(stmt)).all()
    return [NotUnderwayFuelTotal(fuel_type=row.fuel_type, fuel_ton=row.fuel_ton) for row in rows]


async def sum_distance(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime | None = None,
) -> Decimal:
    """선박·규제연도의 not under way **이동 거리 합**을 돌려준다 (마이그레이션 028).

    이 값은 CII 분모에 더해진다 — ``MEPC.412(84)`` §4.2가 ``Dt``를 *"the total
    distance travelled (both under way and not under way)"* 로 정의한다. 접안·묘박은
    0이므로 대부분의 구간이 합계에 기여하지 않고, 실제로 늘어나는 것은 운하 통과·
    표류·STS다.

    절단·삭제 기준은 :func:`sum_fuel_by_type`과 같다.

    :returns: 합계. 구간이 없으면 ``Decimal(0)`` — ``SUM``의 NULL을 여기서 흡수해
        호출부가 ``None``을 다루지 않게 한다.
    """
    stmt = select(func.coalesce(func.sum(NotUnderwayPeriod.distance_nm), 0)).where(
        NotUnderwayPeriod.vessel_id == vessel_id,
        NotUnderwayPeriod.regulation_year == regulation_year,
        NotUnderwayPeriod.is_deleted.is_(False),
    )
    if as_of is not None:
        stmt = stmt.where(NotUnderwayPeriod.started_at <= as_of)
    return Decimal(await session.scalar(stmt) or 0)


async def list_periods_for_year(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime | None = None,
) -> list[NotUnderwayPeriod]:
    """선박·규제연도의 not under way 구간 목록.

    :func:`sum_fuel_by_type`이 계산에 쓰는 합계만 주는 것과 달리, 이쪽은 구간
    자체를 준다 — 화면이 *"올해 며칠을 정박했는가"*를 세거나(``#356`` 선박 상세),
    ``#368``이 ``[t0, as_of]``와 겹치는 구간을 빼는 데 쓴다.

    절단 기준은 :func:`sum_fuel_by_type`과 같다(``started_at <= as_of``).
    """
    stmt = select(NotUnderwayPeriod).where(
        NotUnderwayPeriod.vessel_id == vessel_id,
        NotUnderwayPeriod.regulation_year == regulation_year,
        NotUnderwayPeriod.is_deleted.is_(False),
    )
    if as_of is not None:
        stmt = stmt.where(NotUnderwayPeriod.started_at <= as_of)

    stmt = stmt.order_by(NotUnderwayPeriod.started_at, NotUnderwayPeriod.id)
    return list((await session.execute(stmt)).scalars().all())
