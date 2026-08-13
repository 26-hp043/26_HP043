"""항차 생성·조회 서비스 (TECH_SPEC §16, #53).

``api/routes``와 ``db/repositories`` 사이에서 비즈니스 규칙을 담당한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError

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


#: API_SPEC §3.5 — 허용되는 상태 전환 매핑.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"PLANNED", "CANCELLED"}),
    "PLANNED": frozenset({"IN_PROGRESS", "CANCELLED"}),
    "IN_PROGRESS": frozenset({"COMPLETED", "CANCELLED"}),
    "COMPLETED": frozenset({"CONFIRMED"}),
    "CONFIRMED": frozenset({"COMPLETED", "ARCHIVED"}),
    "CANCELLED": frozenset(),
    "ARCHIVED": frozenset(),
}

#: API_SPEC §3.5 — status × annual_inclusion_policy 허용 조합 (PRD §8.1.2).
_POLICY_BY_STATUS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"EXCLUDE"}),
    "PLANNED": frozenset({"EXCLUDE", "INCLUDE_AS_PLAN"}),
    "IN_PROGRESS": frozenset({"EXCLUDE", "INCLUDE_AS_PLAN"}),
    "COMPLETED": frozenset({"EXCLUDE", "INCLUDE_AS_ACTUAL"}),
    "CONFIRMED": frozenset({"EXCLUDE", "INCLUDE_AS_ACTUAL"}),
    "CANCELLED": frozenset({"EXCLUDE"}),
    "ARCHIVED": frozenset({"EXCLUDE"}),
}


async def update_voyage(
    session: AsyncSession,
    voyage_id: UUID,
    **fields,
) -> dict[str, object]:
    """항차를 수정한다 (API_SPEC §3.4, #54). 없으면 404.

    ``fields``는 라우트가 ``model_dump(exclude_unset=True)``로 만든 것 —
    **생략 = 변경 없음, 명시적 ``null`` = 클리어**다 (#312).
    ``regulation_year``를 ``None``으로 지우는 요청은 ``annual_inclusion_policy ≠
    EXCLUDE``인 경우 ``chk_year_policy`` 제약에 걸리므로 거부한다 (#150).
    """
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")

    if (
        "regulation_year" in fields
        and fields["regulation_year"] is None
        and voyage.annual_inclusion_policy != "EXCLUDE"
    ):
        raise ValidationError(
            "annual_inclusion_policy가 EXCLUDE가 아닌 항차에서 regulation_year를 지울 수 없습니다.",
            field="regulation_year",
            field_label="기준연도",
        )

    for key, value in fields.items():
        setattr(voyage, key, value)

    await session.commit()
    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
    return to_dict(voyage, fuel_uses)


async def transition_voyage(
    session: AsyncSession,
    voyage_id: UUID,
    to_status: str,
    annual_inclusion_policy: str | None = None,
) -> dict[str, object]:
    """항차 상태를 전환한다 (API_SPEC §3.5, #54). 없으면 404.

    PRD §8.1 상태 머신 + policy 가드를 따른다.
    """
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")

    current = voyage.status
    if to_status not in _TRANSITIONS.get(current, frozenset()):
        raise StateTransitionError(f"허용되지 않은 상태 전환입니다: {current} → {to_status}.")

    if annual_inclusion_policy is not None:
        allowed = _POLICY_BY_STATUS.get(to_status, frozenset())
        if annual_inclusion_policy not in allowed:
            raise StateTransitionError(
                f"상태 {to_status}에서 policy {annual_inclusion_policy}는 허용되지 않습니다."
            )
        if annual_inclusion_policy != "EXCLUDE" and voyage.regulation_year is None:
            raise StateTransitionError(
                f"annual_inclusion_policy를 {annual_inclusion_policy}로 설정하려면 "
                "regulation_year가 필요합니다."
            )
        voyage.annual_inclusion_policy = annual_inclusion_policy
    elif len(_POLICY_BY_STATUS.get(to_status, frozenset())) == 1:
        # EXCLUDE-only 상태(CANCELLED·ARCHIVED)는 스펙이 자동 설정을 규정한다
        # (API_SPEC §3.5 「자동 설정」·ORACLE-C-4).
        voyage.annual_inclusion_policy = "EXCLUDE"
    elif voyage.annual_inclusion_policy not in _POLICY_BY_STATUS[to_status]:
        # 미지정 = 현행 유지가 원칙이나, 목표 상태가 현행 policy를 허용하지 않으면
        # 조용히 보정하지 않고 명시적 재지정을 요구한다 (#310).
        raise StateTransitionError(
            f"상태 {to_status}에서 policy {voyage.annual_inclusion_policy}는 "
            "허용되지 않습니다. annual_inclusion_policy를 명시적으로 지정하세요."
        )

    voyage.status = to_status
    await session.commit()
    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
    return to_dict(voyage, fuel_uses)


async def delete_voyage(
    session: AsyncSession,
    voyage_id: UUID,
) -> dict[str, object]:
    """항차를 삭제한다 (API_SPEC §3.7, #54).

    - DRAFT, CANCELLED → hard delete
    - COMPLETED, CONFIRMED, ARCHIVED → soft delete
    - PLANNED, IN_PROGRESS → 422 (먼저 CANCELLED로 전환 필요)
    """
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")

    hard_delete_statuses = {"DRAFT", "CANCELLED"}
    soft_delete_statuses = {"COMPLETED", "CONFIRMED", "ARCHIVED"}

    if voyage.status in hard_delete_statuses:
        await session.delete(voyage)
        await session.commit()
        return {"id": str(voyage.id), "deleted": True, "hard_delete": True}

    if voyage.status in soft_delete_statuses:
        voyage.is_deleted = True
        await session.commit()
        return {"id": str(voyage.id), "deleted": True, "hard_delete": False}

    raise StateTransitionError(
        f"상태 {voyage.status}인 항차는 삭제할 수 없습니다. 먼저 CANCELLED로 전환하세요."
    )
