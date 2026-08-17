"""not under way 구간 CRUD 라우트 (API_SPEC §2.9~§2.13, #370).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 검증·CF snapshot·겹침 판정은
``services.not_underway``가 맡는다.

경로가 두 갈래인 것은 항차(``#53``·``#54``)와 같은 이유다 — 목록·생성은 부모
아래(``/vessels/{id}/…``), 단건 수정·삭제는 자기 ID로(``/not-underway-periods/{id}``).
구간 ID를 아는 시점에는 어느 선박의 것인지 서버가 알고 있어, 경로에 선박을 다시
싣게 하면 둘이 어긋났을 때를 처리해야 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.not_underway import (
    NotUnderwayFuelUseCreateRequest,
    NotUnderwayPeriodCreateRequest,
    NotUnderwayPeriodUpdateRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services.not_underway import (
    CONSUMER_TYPES,
    PERIOD_TYPES,
    add_fuel_use,
    create_period,
    delete_fuel_use,
    delete_period,
    list_periods,
    update_period,
)

router = APIRouter(tags=["not-underway"])


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
    started_from: Annotated[datetime | None, Query(description="시작 시각 하한")] = None,
    started_to: Annotated[datetime | None, Query(description="시작 시각 상한")] = None,
) -> dict[str, object]:
    """선박의 not under way 구간 목록을 조회한다 (API_SPEC §2.9).

    상태 열거값(``period_types``·``consumer_types``)을 ``meta``에 함께 싣는다. 화면이
    열거값을 자기 코드에 박아 두면 DB CHECK 제약과 조용히 갈라지고, 사용자는 저장
    단계에서야 거부를 만난다. 이 둘은 **이 리소스의 상태값**이라 여기가 제자리다.

    **연료 코드는 더 이상 여기서 주지 않는다** (#444). ``§7.2``가 구현되기 전의
    임시 우회였고, 지금은 화면이 ``GET /parameters/fuel-types``를 직접 부른다 —
    연료 선택지는 이 엔드포인트의 소관이 아니며, 남겨 두면 같은 목록을 주는 곳이
    둘이 되어 어느 쪽이 정본인지 흐려진다.
    """
    data = await list_periods(
        session,
        vessel_id,
        regulation_year=regulation_year,
        started_from=started_from,
        started_to=started_to,
    )
    return {
        "data": data,
        "meta": _meta(
            request,
            total=len(data),
            period_types=list(PERIOD_TYPES),
            consumer_types=list(CONSUMER_TYPES),
        ),
    }


@router.post("/vessels/{vessel_id}/not-underway-periods", status_code=201)
async def create_period_route(
    request: Request,
    vessel_id: UUID,
    payload: NotUnderwayPeriodCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """구간을 생성한다 (API_SPEC §2.10). 성공 시 201 Created."""
    data = await create_period(
        session,
        vessel_id,
        period_type=payload.period_type,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        port_name=payload.port_name,
        lat=payload.lat,
        lon=payload.lon,
        distance_nm=payload.distance_nm,
        regulation_year=payload.regulation_year,
        voyage_id=payload.voyage_id,
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


@router.patch("/not-underway-periods/{period_id}")
async def update_period_route(
    request: Request,
    period_id: UUID,
    payload: NotUnderwayPeriodUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """구간을 수정한다 (API_SPEC §2.11). 진행 중 구간의 종료 확정이 주 용도다."""
    # exclude_unset: 생략된 필드는 전달하지 않는다(변경 없음) — 항차 수정과 같은 규약.
    data = await update_period(session, period_id, **payload.model_dump(exclude_unset=True))
    return {"data": data, "meta": _meta(request)}


@router.delete("/not-underway-periods/{period_id}")
async def delete_period_route(
    request: Request,
    period_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """구간을 소프트 삭제한다 (API_SPEC §2.12)."""
    return {"data": await delete_period(session, period_id), "meta": _meta(request)}


@router.post("/not-underway-periods/{period_id}/fuel-uses", status_code=201)
async def add_fuel_use_route(
    request: Request,
    period_id: UUID,
    payload: NotUnderwayFuelUseCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """구간에 연료 기록을 추가한다 (API_SPEC §2.13). 성공 시 201 Created."""
    data = await add_fuel_use(
        session,
        period_id,
        consumer_type=payload.consumer_type,
        fuel_type=payload.fuel_type,
        fuel_ton=payload.fuel_ton,
    )
    return {"data": data, "meta": _meta(request)}


@router.delete("/not-underway-periods/{period_id}/fuel-uses/{fuel_use_id}")
async def delete_fuel_use_route(
    request: Request,
    period_id: UUID,
    fuel_use_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """연료 기록을 삭제한다 (API_SPEC §2.13)."""
    data = await delete_fuel_use(session, period_id, fuel_use_id)
    return {"data": data, "meta": _meta(request)}
