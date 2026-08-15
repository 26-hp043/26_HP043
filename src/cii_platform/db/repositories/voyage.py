"""항차 저장소 — 쿼리만 담당한다 (TECH_SPEC §16, #53).

비즈니스 판단은 ``services``의 몫이다. 이 모듈은 **찾으면 반환하고 없으면 ``None``**을 준다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import func, or_, select, tuple_

from cii_platform.db.models.voyage import Voyage
from cii_platform.db.models.voyage_fuel_use import VoyageFuelUse

if TYPE_CHECKING:
    from datetime import datetime
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


async def list_fuel_uses_by_voyage_ids(
    session: AsyncSession, voyage_ids: list[UUID]
) -> dict[UUID, list[VoyageFuelUse]]:
    """여러 항차의 연료 사용 내역을 **IN 쿼리 1회**로 조회한다 (#314).

    목록 조회의 N+1(항차마다 ``list_fuel_uses``)을 없앤다. 반환은
    ``{voyage_id: [fuel_use, …]}`` 그룹핑 — 내역이 없는 항차는 키가 없다.
    """
    if not voyage_ids:
        return {}
    stmt = select(VoyageFuelUse).where(VoyageFuelUse.voyage_id.in_(voyage_ids))
    rows = (await session.execute(stmt)).scalars().all()
    grouped: dict[UUID, list[VoyageFuelUse]] = {}
    for fuel_use in rows:
        grouped.setdefault(fuel_use.voyage_id, []).append(fuel_use)
    return grouped


async def has_calculation_run_refs(session: AsyncSession, voyage_id: UUID) -> bool:
    """항차를 참조하는 ``calculation_run`` 행이 있는지 (#313).

    ``fk_calculation_run_voyage``는 ON DELETE **RESTRICT**라 참조가 있으면
    물리 DELETE가 ``IntegrityError``(→500)로 실패한다 — 서비스가 미리 409로
    가리기 위한 조회다.
    """
    from sqlalchemy import exists

    from cii_platform.db.models.calculation_run import CalculationRun

    stmt = select(exists().where(CalculationRun.voyage_id == voyage_id))
    return bool(await session.scalar(stmt))


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


async def list_annual_inclusions(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    policy: str,
    as_of: datetime | None = None,
) -> list[Voyage]:
    """연간 집계에 들어가는 항차를 ``annual_inclusion_policy``로 골라 온다 (#353).

    포함 여부의 정본은 ``PRD §8.1.2`` 매트릭스이며, 그 값이 ``voyage`` 행에 이미
    들어 있다. 따라서 여기서는 ``status``를 다시 해석하지 않고 **정책 컬럼 하나로**
    거른다 — ``status``로 판정하면 같은 규칙이 DB CHECK(``chk_voyage_inclusion``)와
    코드 두 곳에 생긴다.

    **``as_of`` 절단은 「도착 시각」 기준이다** — ``actual_arrival_at``이 있으면 그것을,
    없으면 ``planned_arrival_at``을 쓴다(``COALESCE``). 둘 다 NULL이면 절단하지 않고
    포함한다: 시각을 모르는 행을 «아직 아니다»로 단정할 근거가 없고, ``regulation_year``
    가 이미 연도를 한정하고 있다.

    :param policy: ``INCLUDE_AS_ACTUAL`` 또는 ``INCLUDE_AS_PLAN``. ``EXCLUDE``를
        넘기는 것은 호출부의 실수이므로 막지 않고 그대로 조회한다 — 저장소는 규칙을
        판정하지 않는다(TECH_SPEC §16).
    """
    stmt = select(Voyage).where(
        Voyage.vessel_id == vessel_id,
        Voyage.regulation_year == regulation_year,
        Voyage.annual_inclusion_policy == policy,
        Voyage.is_deleted.is_(False),
    )

    if as_of is not None:
        arrival_at = func.coalesce(Voyage.actual_arrival_at, Voyage.planned_arrival_at)
        stmt = stmt.where(or_(arrival_at.is_(None), arrival_at <= as_of))

    stmt = stmt.order_by(Voyage.created_at, Voyage.id)
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
