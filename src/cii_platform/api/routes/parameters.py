"""규제 파라미터 조회 라우트 (API_SPEC §7.1~§7.4, #444).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 조회·직렬화는
``services.parameters``가 맡는다.

## 읽기만 있다

``§7.5`` 파라미터 import는 여기 없다. 규정 개정 적재는 ``is_active`` 전환과 이력
보존 규칙(``DB_SCHEMA §3``)을 함께 정해야 하고, **누가 할 수 있는가**가 `#359`
(어드민 계정·권한 범위)에 걸려 있다. 조회부터 열어 두면 화면이 우회 없이 선택지를
받을 수 있고, 그것이 이 이슈가 고치려는 상태다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.db.session import get_session
from cii_platform.services.parameters import (
    list_fuel_types,
    list_rating_boundaries,
    list_reference_lines,
    list_regulation_years,
)

router = APIRouter(tags=["parameters"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/parameters/regulation-years")
async def list_regulation_years_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """규정 연도(Z계수) 목록 (API_SPEC §7.1)."""
    data = await list_regulation_years(session)
    return {"data": data, "meta": _meta(request, total=len(data))}


@router.get("/parameters/fuel-types")
async def list_fuel_types_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    active: Annotated[
        bool | None, Query(description="활성 여부 필터. 생략하면 활성만 (기본)")
    ] = True,
) -> dict[str, object]:
    """연료 종류·CF 목록 (API_SPEC §7.2).

    **기본이 활성만이다.** 이 목록의 주 용도가 화면의 연료 선택지인데, 비활성 연료가
    섞이면 사용자는 고른 뒤 저장 단계에서야 거부를 만난다. 이력을 보려는 호출자는
    ``?active=false``로 명시한다.
    """
    data = await list_fuel_types(session, active=active)
    return {"data": data, "meta": _meta(request, total=len(data))}


@router.get("/parameters/reference-lines")
async def list_reference_lines_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    ship_type: Annotated[str | None, Query(description="선종 필터. 생략하면 전 선종")] = None,
) -> dict[str, object]:
    """선종별 기준선 (API_SPEC §7.3)."""
    data = await list_reference_lines(session, ship_type=ship_type)
    return {"data": data, "meta": _meta(request, total=len(data))}


@router.get("/parameters/rating-boundaries")
async def list_rating_boundaries_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    ship_type: Annotated[str | None, Query(description="선종 필터. 생략하면 전 선종")] = None,
) -> dict[str, object]:
    """선종별 등급 경계 d-vector (API_SPEC §7.4)."""
    data = await list_rating_boundaries(session, ship_type=ship_type)
    return {"data": data, "meta": _meta(request, total=len(data))}
