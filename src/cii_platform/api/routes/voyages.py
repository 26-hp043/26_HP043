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
    VoyageActualsRequest,
    VoyageCreateRequest,
    VoyageTransitionRequest,
    VoyageUpdateRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services import audit as audit_svc
from cii_platform.services.voyage import (
    create_voyage,
    delete_voyage,
    get_voyage,
    list_voyages,
    set_actuals,
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
    # exclude_unset: 생략된 필드는 아예 전달하지 않는다(변경 없음).
    # 명시적 null은 그대로 전달돼 클리어를 뜻한다 (#312).
    update_fields = payload.model_dump(exclude_unset=True)
    data = await update_voyage(session, voyage_id, **update_fields)
    return {"data": data, "meta": _meta(request)}


@router.put("/voyages/{voyage_id}/actuals")
async def set_voyage_actuals_route(
    request: Request,
    voyage_id: UUID,
    payload: VoyageActualsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차 실적을 입력한다 (`API_SPEC §3.6`, #440). 없으면 404.

    **`status`는 바꾸지 않는다** — 전환은 `POST /voyages/{id}/transition`이 한다.
    한 번에 처리하면 `PRD §8.1.1` 전환 가드가 자기 입력을 보고 통과하게 된다.
    """
    fields = payload.model_dump(exclude_unset=True)
    fuel_uses = fields.pop("fuel_uses", None)
    data = await set_actuals(session, voyage_id, fuel_uses=fuel_uses, **fields)
    return {"data": data, "meta": _meta(request)}


@router.post("/voyages/{voyage_id}/transition")
async def transition_voyage_route(
    request: Request,
    voyage_id: UUID,
    payload: VoyageTransitionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차 상태를 전환한다 (API_SPEC §3.5, #54).

    **확정 전환은 감사 로그에 남는다** (`TECH_SPEC §13.1`, #65). 주체(user)와 IP는
    HTTP 개념이라 라우트가 뽑아 넘긴다 — 서비스가 `request`를 알면 계층이 깨진다(§16.1).
    """
    data = await transition_voyage(
        session,
        voyage_id,
        to_status=payload.to_status,
        annual_inclusion_policy=payload.annual_inclusion_policy,
    )
    # 서비스가 실어 보낸 「변경 전」 값. 응답에서는 뺀다(`_duration_ms`와 같은 규약).
    from_status = data.pop("_from_status")

    if data["status"] == "CONFIRMED":
        state = getattr(request, "state", None)
        session_user = getattr(state, "session_user", None)
        await audit_svc.record_voyage_confirm(
            session,
            user_id=str(session_user.id) if session_user is not None else None,
            voyage_id=voyage_id,
            from_status=from_status,
            annual_inclusion_policy=data["annual_inclusion_policy"],
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()

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
