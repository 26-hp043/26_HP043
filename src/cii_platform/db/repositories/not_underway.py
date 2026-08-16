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
from sqlalchemy import or_ as sa_or
from sqlalchemy import true as sa_true

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


# ─────────────────────────────────────────────────────────────────────────────
# 쓰기 경로 (#370) — 구간을 **운영 중에 넣고 고칠 수 있게** 한다.
#
# 위쪽 조회 함수들이 「YTD 집계에 필요한 조회만 둔다」고 적어 둔 것은 #353 시점의
# 범위였다. 이 이슈가 CRUD를 채우면서 그 범위가 넓어졌다 — 다만 **판단은 여전히
# services의 몫**이고, 여기에는 WHERE 절과 INSERT만 둔다.
# ─────────────────────────────────────────────────────────────────────────────


async def get_period(session: AsyncSession, period_id: UUID) -> NotUnderwayPeriod | None:
    """구간 1건. **삭제된 행도 돌려준다** — 「없음」과 「지워짐」의 구분은 서비스가 한다."""
    return await session.get(NotUnderwayPeriod, period_id)


async def list_periods(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
) -> list[NotUnderwayPeriod]:
    """선박의 구간 목록 — 화면 조회용 (``API_SPEC §2.9``).

    :func:`list_periods_for_year`와 **연도 인자의 의미가 다르다.** 저쪽은 규제연도가
    필수(계산 대상이 연도로 확정된다)지만, 이쪽은 선택이다 — 입력 화면은 「이 선박의
    최근 기록」을 연도와 무관하게 보여 줘야 방금 넣은 행을 확인할 수 있다.

    정렬은 **최근 구간이 위**다. 조회 함수들이 오름차순인 것과 반대인데, 계산은
    시간순으로 훑고 화면은 방금 넣은 것부터 본다.
    """
    stmt = select(NotUnderwayPeriod).where(
        NotUnderwayPeriod.vessel_id == vessel_id,
        NotUnderwayPeriod.is_deleted.is_(False),
    )
    if regulation_year is not None:
        stmt = stmt.where(NotUnderwayPeriod.regulation_year == regulation_year)
    if started_from is not None:
        stmt = stmt.where(NotUnderwayPeriod.started_at >= started_from)
    if started_to is not None:
        stmt = stmt.where(NotUnderwayPeriod.started_at <= started_to)

    stmt = stmt.order_by(NotUnderwayPeriod.started_at.desc(), NotUnderwayPeriod.id)
    return list((await session.execute(stmt)).scalars().all())


async def find_overlapping(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    started_at: datetime,
    ended_at: datetime | None,
    exclude_id: UUID | None = None,
) -> NotUnderwayPeriod | None:
    """같은 선박에서 ``[started_at, ended_at)``과 겹치는 구간 **한 건**을 찾는다.

    겹침을 막는 이유는 연료가 이중으로 집계되기 때문이다 — 같은 정박을 두 번 넣으면
    ``M``이 두 배가 되고 등급이 실제보다 나쁘게 나온다(``#353`` 분자 경로).

    **열린 구간(``ended_at IS NULL``)은 무한대로 취급한다.** 진행 중 구간은 아직
    끝나지 않았으므로 그 이후 어떤 시각과도 겹친다. 이 규칙이 없으면 「정박 중」인
    선박에 다음 정박을 미리 넣을 수 있고, 그러면 둘 중 하나는 반드시 틀린 기록이다.

    경계는 **닫힘-열림**이다 — 앞 구간의 ``ended_at``과 뒤 구간의 ``started_at``이
    같은 시각인 것은 겹침이 아니다. 접안 종료 즉시 운하 진입 같은 연속 기록이
    정상이기 때문이다.

    :param exclude_id: 수정 시 자기 자신을 겹침으로 판정하지 않도록 제외한다.
    :returns: 겹치는 구간 1건, 없으면 ``None``. 서비스가 메시지에 시각을 싣는다.
    """
    # 겹침 = 기존.started < 새.ended  AND  새.started < 기존.ended
    # (NULL은 무한대 — coalesce 대신 OR로 풀어 인덱스 사용을 막지 않는다.)
    ends_after_new_start = sa_or(
        NotUnderwayPeriod.ended_at.is_(None),
        NotUnderwayPeriod.ended_at > started_at,
    )
    starts_before_new_end = (
        sa_true() if ended_at is None else NotUnderwayPeriod.started_at < ended_at
    )

    stmt = (
        select(NotUnderwayPeriod)
        .where(
            NotUnderwayPeriod.vessel_id == vessel_id,
            NotUnderwayPeriod.is_deleted.is_(False),
            ends_after_new_start,
            starts_before_new_end,
        )
        .order_by(NotUnderwayPeriod.started_at)
        .limit(1)
    )
    if exclude_id is not None:
        stmt = stmt.where(NotUnderwayPeriod.id != exclude_id)

    return (await session.execute(stmt)).scalars().first()


async def insert_period(session: AsyncSession, **fields: object) -> NotUnderwayPeriod:
    """구간 1건을 INSERT 한다. ``commit``은 호출부가 담당한다(voyage 저장소와 동일)."""
    period = NotUnderwayPeriod(**fields)
    session.add(period)
    await session.flush()
    return period


async def insert_fuel_use(session: AsyncSession, **fields: object) -> NotUnderwayFuelUse:
    """구간 연료 1건을 INSERT 한다. ``cf_used``는 **서비스가 떠 온 snapshot**이다."""
    fuel_use = NotUnderwayFuelUse(**fields)
    session.add(fuel_use)
    await session.flush()
    return fuel_use


async def list_fuel_uses(session: AsyncSession, period_id: UUID) -> list[NotUnderwayFuelUse]:
    """구간의 연료 기록 목록. 정렬은 화면 표시 순서(소비원 → 유종)다."""
    stmt = (
        select(NotUnderwayFuelUse)
        .where(NotUnderwayFuelUse.period_id == period_id)
        .order_by(NotUnderwayFuelUse.consumer_type, NotUnderwayFuelUse.fuel_type)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_fuel_uses_for_periods(
    session: AsyncSession, period_ids: list[UUID]
) -> dict[UUID, list[NotUnderwayFuelUse]]:
    """여러 구간의 연료를 **한 번에** 읽어 구간별로 묶는다.

    목록 화면이 구간마다 조회하면 N+1이 된다. 정박은 항차마다 최소 2회 생기므로
    한 해 구간 수가 금방 수백 건이 되고, 그때 이 차이가 그대로 응답 시간이 된다.
    """
    if not period_ids:
        return {}

    stmt = (
        select(NotUnderwayFuelUse)
        .where(NotUnderwayFuelUse.period_id.in_(period_ids))
        .order_by(NotUnderwayFuelUse.consumer_type, NotUnderwayFuelUse.fuel_type)
    )
    grouped: dict[UUID, list[NotUnderwayFuelUse]] = {pid: [] for pid in period_ids}
    for row in (await session.execute(stmt)).scalars().all():
        grouped.setdefault(row.period_id, []).append(row)
    return grouped


async def get_fuel_use(session: AsyncSession, fuel_use_id: UUID) -> NotUnderwayFuelUse | None:
    """연료 기록 1건."""
    return await session.get(NotUnderwayFuelUse, fuel_use_id)


async def delete_fuel_use(session: AsyncSession, fuel_use: NotUnderwayFuelUse) -> None:
    """연료 기록을 **물리 삭제**한다.

    구간과 달리 소프트 삭제하지 않는다 — ``not_underway_fuel_use``에는
    ``is_deleted`` 열이 없고(``#345`` 설계), 부모가 CASCADE로 지운다. 잘못 넣은
    연료 한 줄을 남겨 둘 이유가 없다.
    """
    await session.delete(fuel_use)
    await session.flush()
