"""not under way 구간 라우트 (API_SPEC §3.8, #370).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 검증·트랜잭션은
``services.not_underway``가 맡는다.

변경 엔드포인트(POST·PATCH·DELETE)는 전부 ``require_csrf``를 건다 — ``#307``이
「만든 것과 붙인 것이 달랐던」 사례를 남겼으므로 새 변경 엔드포인트는 배선을
테스트로 확인한다(``tests/test_not_underway_api.py``).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.not_underway import (
    NotUnderwayPeriodCreateRequest,
    NotUnderwayPeriodUpdateRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services.not_underway import (
    create_period,
    delete_period,
    get_period,
    list_periods,
    update_period,
)

router = APIRouter(tags=["not-underway-periods"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/vessels/{vessel_id}/not-underway-periods")
async def list_periods_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    regulation_year: Annotated[int | None, Query(description="규제연도 필터")] = None,
    period_type: Annotated[str | None, Query(description="구간 유형 필터 (6값)")] = None,
    ongoing: Annotated[bool | None, Query(description="true=진행 중만, false=종료만")] = None,
    limit: Annotated[int | None, Query(description="페이지 크기 (기본 20, 최대 100)")] = None,
    cursor: Annotated[str | None, Query(description="페이지네이션 커서")] = None,
) -> dict[str, object]:
    """선박의 not under way 구간 목록을 조회한다 (API_SPEC §3.8.2)."""
    data, page_meta = await list_periods(
        session,
        vessel_id,
        regulation_year=regulation_year,
        period_type=period_type,
        ongoing=ongoing,
        limit=limit,
        cursor=cursor,
    )
    return {"data": data, "meta": _meta(request, **page_meta)}


@router.post("/vessels/{vessel_id}/not-underway-periods", status_code=201)
async def create_period_route(
    request: Request,
    vessel_id: UUID,
    payload: NotUnderwayPeriodCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """구간을 생성한다 (API_SPEC §3.8.1, #370). 성공 시 201 Created."""
    data = await create_period(
        session,
        vessel_id,
        period_type=payload.period_type,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        regulation_year=payload.regulation_year,
        port_name=payload.port_name,
        lat=payload.lat,
        lon=payload.lon,
        voyage_id=payload.voyage_id,
        distance_nm=payload.distance_nm,
        fuel_uses=[
            {
                "consumer_type": fu.consumer_type,
                "fuel_type": fu.fuel_type,
                "fuel_ton": fu.fuel_ton,
            }
            for fu in payload.fuel_uses
        ],
    )
    return {"data": data, "meta": _meta(request)}


@router.get("/not-underway-periods/{period_id}")
async def get_period_route(
    request: Request,
    period_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """구간 상세를 조회한다 (API_SPEC §3.8.3). 없으면 404."""
    return {"data": await get_period(session, period_id), "meta": _meta(request)}


@router.patch("/not-underway-periods/{period_id}")
async def update_period_route(
    request: Request,
    period_id: UUID,
    payload: NotUnderwayPeriodUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """구간을 수정한다 (API_SPEC §3.8.4). 진행 중 구간의 ``ended_at`` 확정 포함.

    ``exclude_unset`` — 생략된 필드는 변경 없음, 명시적 ``null``은 클리어 (#312).
    """
    fields = payload.model_dump(exclude_unset=True)
    data = await update_period(session, period_id, fields)
    return {"data": data, "meta": _meta(request)}


@router.delete("/not-underway-periods/{period_id}")
async def delete_period_route(
    request: Request,
    period_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """구간을 soft delete 한다 (API_SPEC §3.8.5)."""
    data = await delete_period(session, period_id)
    return {"data": data, "meta": _meta(request)}
