"""not under way 구간 저장소 — 쿼리만 담당한다 (TECH_SPEC §16, #353·#370).

``not_underway_period`` · ``not_underway_fuel_use``(``#345``, 마이그레이션 025)의
조회(#353 YTD 집계)와 CRUD(#370 입력 경로)를 담는다.

비즈니스 판단은 ``services``의 몫이다 — 어떤 구간을 포함할지의 규칙(연도 귀속·
``as_of`` 절단)·겹침 판정의 의미는 인자로 받고, 여기서는 그대로 WHERE 절로 옮긴다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import func, or_, select

from cii_platform.db.models.not_underway_fuel_use import NotUnderwayFuelUse
from cii_platform.db.models.not_underway_period import NotUnderwayPeriod

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class NotUnderwayFuelTotal(NamedTuple):
    """유종 × CF snapshot별 not under way 연료 합계 1행.

    ``cf_used``까지 묶는 이유는 030(``#378``) 참조 — CF가 개정되면 같은 유종이라도
    기록 시점에 따라 snapshot이 갈리고, 그때 각 묶음은 **자기 CF로** 곱해져야 한다.
    """

    fuel_type: str
    fuel_ton: Decimal
    cf_used: Decimal


async def sum_fuel_by_type(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime | None = None,
) -> list[NotUnderwayFuelTotal]:
    """선박·규제연도의 not under way 연료를 **유종 × CF snapshot별로 합산**해 돌려준다.

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

    **``cf_used``까지 묶어 집계한다** (030 · ``#378``). 같은 유종이라도 CF 개정 전후로
    기록된 행은 snapshot이 다르므로, 하나로 합쳐 대표 CF 하나를 고르면 그 차이가
    사라진다. 계산 엔진은 같은 ``fuel_code``가 여러 번 들어와도 배출량을 합산하므로
    (``ytd_engine`` 내역 누적), 묶음을 그대로 넘기는 것이 정확하다.

    :returns: ``(fuel_type, fuel_ton, cf_used)`` 목록. 기록이 없으면 **빈 목록**이다 —
        정박 기록이 없는 선박은 정상 상태이므로 오류로 만들지 않는다.
    """
    stmt = (
        select(
            NotUnderwayFuelUse.fuel_type,
            func.sum(NotUnderwayFuelUse.fuel_ton).label("fuel_ton"),
            NotUnderwayFuelUse.cf_used,
        )
        .join(NotUnderwayPeriod, NotUnderwayFuelUse.period_id == NotUnderwayPeriod.id)
        .where(
            NotUnderwayPeriod.vessel_id == vessel_id,
            NotUnderwayPeriod.regulation_year == regulation_year,
            NotUnderwayPeriod.is_deleted.is_(False),
        )
        .group_by(NotUnderwayFuelUse.fuel_type, NotUnderwayFuelUse.cf_used)
        .order_by(NotUnderwayFuelUse.fuel_type, NotUnderwayFuelUse.cf_used)
    )
    if as_of is not None:
        stmt = stmt.where(NotUnderwayPeriod.started_at <= as_of)

    rows = (await session.execute(stmt)).all()
    return [
        NotUnderwayFuelTotal(fuel_type=row.fuel_type, fuel_ton=row.fuel_ton, cf_used=row.cf_used)
        for row in rows
    ]


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


# --- CRUD (#370 — 입력 경로) ------------------------------------------------------


async def insert_period(session: AsyncSession, **fields: object) -> NotUnderwayPeriod:
    """구간을 INSERT 한다. ``commit``은 호출부(서비스)가 담당한다."""
    period = NotUnderwayPeriod(**fields)
    session.add(period)
    await session.flush()
    return period


async def insert_fuel_use(session: AsyncSession, **fields: object) -> NotUnderwayFuelUse:
    """구간 연료 1건을 INSERT 한다. ``cf_used``는 서비스가 채운 뒤 넘긴다 (030)."""
    fuel_use = NotUnderwayFuelUse(**fields)
    session.add(fuel_use)
    await session.flush()
    return fuel_use


async def get_period_by_id(session: AsyncSession, period_id: UUID) -> NotUnderwayPeriod | None:
    """구간 1건. soft delete된 행도 돌려준다 — PATCH·DELETE 대상 식별은 서비스 판단."""
    return await session.get(NotUnderwayPeriod, period_id)


async def list_active_periods(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int | None = None,
    period_type: str | None = None,
    ongoing: bool | None = None,
    limit: int = 20,
    cursor: tuple[datetime, UUID] | None = None,
) -> list[NotUnderwayPeriod]:
    """활성 구간 목록 (API_SPEC §3.8.2, #370).

    최근 시작 순(``started_at desc, id desc``) — 입력 직후 구간이 첫 페이지에
    보이는 것이 입력 화면의 자연스러운 피드백이다. ``limit + 1``건을 가져와
    ``has_more`` 판단은 호출부가 한다(voyage ``list_active`` 패턴).

    :param ongoing: ``True`` = 진행 중(``ended_at IS NULL``)만, ``False`` = 종료만.
    :param cursor: ``(started_at, id)``의 마지막 반환 값 — 서비스가 파싱해 넘긴다.
        컬럼 타입과 맞춰야 asyncpg 바인딩이 성립한다(문자열 그대로는 실패).
    """
    stmt = select(NotUnderwayPeriod).where(
        NotUnderwayPeriod.vessel_id == vessel_id,
        NotUnderwayPeriod.is_deleted.is_(False),
    )
    if regulation_year is not None:
        stmt = stmt.where(NotUnderwayPeriod.regulation_year == regulation_year)
    if period_type is not None:
        stmt = stmt.where(NotUnderwayPeriod.period_type == period_type)
    if ongoing is True:
        stmt = stmt.where(NotUnderwayPeriod.ended_at.is_(None))
    elif ongoing is False:
        stmt = stmt.where(NotUnderwayPeriod.ended_at.is_not(None))

    if cursor is not None:
        started_at, period_id = cursor
        # 같은 started_at의 동률 처리 — id desc로 끊는다 (keyset 정합성).
        stmt = stmt.where(
            or_(
                NotUnderwayPeriod.started_at < started_at,
                (NotUnderwayPeriod.started_at == started_at) & (NotUnderwayPeriod.id < period_id),
            )
        )

    stmt = stmt.order_by(NotUnderwayPeriod.started_at.desc(), NotUnderwayPeriod.id.desc())
    stmt = stmt.limit(limit + 1)
    return list((await session.execute(stmt)).scalars().all())


async def list_fuel_uses_by_period_ids(
    session: AsyncSession, period_ids: list[UUID]
) -> dict[UUID, list[NotUnderwayFuelUse]]:
    """``period_id``별 자식 연료 목록 — 목록 화면이 N+1 없이 자식을 싣는 데 쓴다."""
    if not period_ids:
        return {}
    stmt = (
        select(NotUnderwayFuelUse)
        .where(NotUnderwayFuelUse.period_id.in_(period_ids))
        .order_by(NotUnderwayFuelUse.consumer_type, NotUnderwayFuelUse.fuel_type)
    )
    rows = (await session.execute(stmt)).scalars().all()
    by_period: dict[UUID, list[NotUnderwayFuelUse]] = {}
    for row in rows:
        by_period.setdefault(row.period_id, []).append(row)
    return by_period


async def delete_fuel_uses(session: AsyncSession, period_id: UUID) -> None:
    """구간 자식 연료를 전부 지운다 — PATCH에서 목록을 통째로 교체할 때 쓴다.

    물리 삭제다. 자식에는 soft delete 플래그가 없고(#345 설계), 집계 제외는 부모
    플래그로 판정하므로 물리 삭제해도 감사 경로는 부모 이력이 담당한다.
    """
    if not period_id:
        return
    stmt = select(NotUnderwayFuelUse).where(NotUnderwayFuelUse.period_id == period_id)
    for row in (await session.execute(stmt)).scalars().all():
        await session.delete(row)
    await session.flush()


async def find_overlapping(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    started_at: datetime,
    ended_at: datetime | None,
    exclude_id: UUID | None = None,
) -> NotUnderwayPeriod | None:
    """같은 선박의 활성 구간 중 ``[started_at, ended_at]``와 겹치는 첫 행.

    겹침 판정 — 양쪽 끝점이 열려 있다(반개 구간):

    - 새 구간이 진행 중(``ended_at is None``)이면 시작 이후의 모든 구간과 겹칠 수
      있으므로 시작 조건을 생략한다.
    - 기존 구간이 진행 중이면 아직 끝나지 않았으므로 새 시작 이후와 겹친다.

    겹치는 구간을 조용히 병합하지 않는다 — ``#368`` ``_overlap_hours``가 겹침을
    두 번 빼는 문서화된 전제(병합은 입력 경로 #370의 책임)를 이 조회로 강제한다.
    ``idx_not_underway_period_vessel_started``(029)가 내려받는다.
    """
    stmt = select(NotUnderwayPeriod).where(
        NotUnderwayPeriod.vessel_id == vessel_id,
        NotUnderwayPeriod.is_deleted.is_(False),
    )
    if exclude_id is not None:
        stmt = stmt.where(NotUnderwayPeriod.id != exclude_id)
    if ended_at is not None:
        stmt = stmt.where(NotUnderwayPeriod.started_at < ended_at)
    stmt = stmt.where(
        or_(
            NotUnderwayPeriod.ended_at.is_(None),
            NotUnderwayPeriod.ended_at > started_at,
        )
    )
    stmt = stmt.order_by(NotUnderwayPeriod.started_at).limit(1)
    return (await session.execute(stmt)).scalars().first()
