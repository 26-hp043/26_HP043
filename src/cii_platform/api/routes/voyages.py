"""항차 생성·조회 라우트 (API_SPEC §3.1~§3.3, #53).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 비즈니스 규칙·검증은
``services.voyage``가 맡는다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.voyage import (
    VoyageCreateRequest,
    VoyageTransitionRequest,
    VoyageUpdateRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services.voyage import (
    create_voyage,
    delete_voyage,
    get_voyage,
    list_voyages,
    transition_voyage,
    update_voyage,
)

router = APIRouter(tags=["voyages"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/vessels/{vessel_id}/voyages")
async def list_voyages_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[str | None, Query(description="상태 필터")] = None,
    regulation_year: Annotated[int | None, Query(description="기준연도 필터")] = None,
    limit: Annotated[int | None, Query(description="페이지 크기")] = None,
    cursor: Annotated[str | None, Query(description="페이지네이션 커서")] = None,
) -> dict[str, object]:
    """선박별 항차 목록을 조회한다 (API_SPEC §3.1)."""
    data, page_meta = await list_voyages(
        session,
        vessel_id,
        limit=limit,
        cursor=cursor,
        status=status,
        regulation_year=regulation_year,
    )
    return {"data": data, "meta": _meta(request, **page_meta)}


@router.get("/voyages/{voyage_id}")
async def get_voyage_route(
    request: Request,
    voyage_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """항차 상세를 조회한다 (API_SPEC §3.2). 없으면 404."""
    return {"data": await get_voyage(session, voyage_id), "meta": _meta(request)}


@router.post("/vessels/{vessel_id}/voyages", status_code=201)
async def create_voyage_route(
    request: Request,
    vessel_id: UUID,
    payload: VoyageCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차를 생성한다 (API_SPEC §3.3). 성공 시 201 Created."""
    data = await create_voyage(
        session,
        vessel_id,
        voyage_no=payload.voyage_no,
        departure_port_name=payload.departure_port_name,
        departure_lat=payload.departure_lat,
        departure_lon=payload.departure_lon,
        arrival_port_name=payload.arrival_port_name,
        arrival_lat=payload.arrival_lat,
        arrival_lon=payload.arrival_lon,
        planned_distance_nm=payload.planned_distance_nm,
        planned_speed_kn=payload.planned_speed_kn,
        planned_departure_at=payload.planned_departure_at,
        planned_arrival_at=payload.planned_arrival_at,
        regulation_year=payload.regulation_year,
        fuel_uses=[
            {
                "fuel_type": fu.fuel_type,
                "planned_fuel_ton": fu.planned_fuel_ton,
                "source": fu.source,
            }
            for fu in payload.fuel_uses
        ],
        notes=payload.notes,
    )
    return {"data": data, "meta": _meta(request)}


@router.patch("/voyages/{voyage_id}")
async def update_voyage_route(
    request: Request,
    voyage_id: UUID,
    payload: VoyageUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차를 수정한다 (API_SPEC §3.4, #54). 없으면 404."""
    update_fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    data = await update_voyage(session, voyage_id, **update_fields)
    return {"data": data, "meta": _meta(request)}


@router.post("/voyages/{voyage_id}/transition")
async def transition_voyage_route(
    request: Request,
    voyage_id: UUID,
    payload: VoyageTransitionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차 상태를 전환한다 (API_SPEC §3.5, #54)."""
    data = await transition_voyage(
        session,
        voyage_id,
        to_status=payload.to_status,
        annual_inclusion_policy=payload.annual_inclusion_policy,
    )
    return {"data": data, "meta": _meta(request)}


@router.delete("/voyages/{voyage_id}")
async def delete_voyage_route(
    request: Request,
    voyage_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차를 삭제한다 (API_SPEC §3.7, #54)."""
    data = await delete_voyage(session, voyage_id)
    return {"data": data, "meta": _meta(request)}
