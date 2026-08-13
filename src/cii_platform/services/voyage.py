"""항차 생성·조회 서비스 (TECH_SPEC §16, #53).

``api/routes``와 ``db/repositories`` 사이에서 비즈니스 규칙을 담당한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _number(value: Decimal | None) -> float | None:
    """선박 제원과 동일 — Layer 1 값이 아니므로 JSON number."""
    return None if value is None else float(value)


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


def _fuel_use_to_dict(fuel_use) -> dict[str, object]:
    """VoyageFuelUse ORM → API_SPEC §3.1 연료 객체."""
    return {
        "id": str(fuel_use.id),
        "fuel_type": fuel_use.fuel_type,
        "planned_fuel_ton": _number(fuel_use.planned_fuel_ton),
        "actual_fuel_ton": _number(fuel_use.actual_fuel_ton),
        "cf_used": _number(fuel_use.cf_used),
        "source": fuel_use.source,
    }


def to_dict(voyage, fuel_uses: list) -> dict[str, object]:
    """ORM 객체를 API_SPEC §3.1 항차 객체로 옮긴다."""
    return {
        "id": str(voyage.id),
        "vessel_id": str(voyage.vessel_id),
        "voyage_no": voyage.voyage_no,
        "status": voyage.status,
        "departure_port_name": voyage.departure_port_name,
        "departure_lat": _number(voyage.departure_lat),
        "departure_lon": _number(voyage.departure_lon),
        "arrival_port_name": voyage.arrival_port_name,
        "arrival_lat": _number(voyage.arrival_lat),
        "arrival_lon": _number(voyage.arrival_lon),
        "planned_distance_nm": _number(voyage.planned_distance_nm),
        "actual_distance_nm": _number(voyage.actual_distance_nm),
        "planned_speed_kn": _number(voyage.planned_speed_kn),
        "actual_avg_speed_kn": _number(voyage.actual_avg_speed_kn),
        "planned_departure_at": _iso(voyage.planned_departure_at),
        "planned_arrival_at": _iso(voyage.planned_arrival_at),
        "actual_departure_at": _iso(voyage.actual_departure_at),
        "actual_arrival_at": _iso(voyage.actual_arrival_at),
        "annual_inclusion_policy": voyage.annual_inclusion_policy,
        "regulation_year": voyage.regulation_year,
        "created_from": voyage.created_from,
        "fuel_uses": [_fuel_use_to_dict(fu) for fu in fuel_uses],
        "notes": voyage.notes,
        "created_at": _iso(voyage.created_at),
    }


async def create_voyage(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    voyage_no: str | None,
    departure_port_name: str,
    departure_lat: Decimal | None,
    departure_lon: Decimal | None,
    arrival_port_name: str,
    arrival_lat: Decimal | None,
    arrival_lon: Decimal | None,
    planned_distance_nm: Decimal,
    planned_speed_kn: Decimal,
    planned_departure_at,
    planned_arrival_at,
    regulation_year: int | None,
    fuel_uses: list[dict],
    notes: str | None,
) -> dict[str, object]:
    """항차를 생성한다 (API_SPEC §3.3, #53). 성공 시 201.

    초기 상태: ``status=DRAFT``, ``annual_inclusion_policy=EXCLUDE``,
    ``created_from=MANUAL`` (PRD §8.1.1).
    """
    # 연료 CF 조회 — 모든 fuel_type이 active여야 한다.
    codes = [fu["fuel_type"] for fu in fuel_uses]
    fuel_rows = await param_repo.get_fuel_types_by_codes(session, codes)
    for fu in fuel_uses:
        if fu["fuel_type"] not in fuel_rows:
            raise ValidationError(
                f"알 수 없는 연료 종류입니다: {fu['fuel_type']}",
                field="fuel_uses",
                field_label="연료 종류",
            )

    voyage = await voyage_repo.insert(
        session,
        vessel_id=vessel_id,
        voyage_no=voyage_no,
        status="DRAFT",
        departure_port_name=departure_port_name,
        departure_lat=departure_lat,
        departure_lon=departure_lon,
        arrival_port_name=arrival_port_name,
        arrival_lat=arrival_lat,
        arrival_lon=arrival_lon,
        planned_distance_nm=planned_distance_nm,
        planned_speed_kn=planned_speed_kn,
        planned_departure_at=planned_departure_at,
        planned_arrival_at=planned_arrival_at,
        regulation_year=regulation_year,
        annual_inclusion_policy="EXCLUDE",
        created_from="MANUAL",
        notes=notes,
    )

    for fu in fuel_uses:
        cf = Decimal(str(fuel_rows[fu["fuel_type"]].cf))
        await voyage_repo.insert_fuel_use(
            session,
            voyage_id=voyage.id,
            fuel_type=fu["fuel_type"],
            planned_fuel_ton=fu["planned_fuel_ton"],
            cf_used=cf,
            source=fu["source"],
        )

    await session.commit()

    fuel_use_rows = await voyage_repo.list_fuel_uses(session, voyage.id)
    return to_dict(voyage, fuel_use_rows)


async def get_voyage(session: AsyncSession, voyage_id: UUID) -> dict[str, object]:
    """항차 상세 (API_SPEC §3.2). 없으면 404."""
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")
    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage_id)
    return to_dict(voyage, fuel_uses)


async def list_voyages(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    status: str | None = None,
    regulation_year: int | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """항차 목록과 페이지네이션 메타를 반환한다 (API_SPEC §3.1)."""
    page_size = min(limit or voyage_repo.DEFAULT_LIMIT, voyage_repo.MAX_LIMIT)

    parsed_cursor = None
    if cursor is not None:
        parsed_cursor = voyage_repo.decode_cursor(cursor)
        if parsed_cursor is None:
            raise ValidationError(
                "cursor 형식이 올바르지 않습니다.",
                field="cursor",
                field_label="커서",
            )

    rows = await voyage_repo.list_active(
        session,
        vessel_id=vessel_id,
        limit=page_size,
        cursor=parsed_cursor,
        status=status,
        regulation_year=regulation_year,
    )

    has_more = len(rows) > page_size
    page = rows[:page_size]

    next_cursor = None
    if has_more and page:
        import datetime as dt

        last = page[-1]
        next_cursor = voyage_repo.encode_cursor(
            voyage_repo.VoyageCursor(
                created_at=last.created_at.isoformat()
                if isinstance(last.created_at, dt.datetime)
                else str(last.created_at),
                voyage_id=str(last.id),
            )
        )

    data = []
    for voyage in page:
        fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
        data.append(to_dict(voyage, fuel_uses))

    return data, {"next_cursor": next_cursor, "has_more": has_more}
