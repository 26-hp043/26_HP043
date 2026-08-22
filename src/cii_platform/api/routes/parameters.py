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
    """선종별 기준선 (API_SPEC §7.3).

    ## MVP 화면에 연결하지 않는다 (#556 · #359)

    `#556`이 「서버에 있는데 화면에서 도달할 수 없는 엔드포인트」를 전수 대조했을 때
    이 엔드포인트가 그중 하나였고, **판정을 `#359`(어드민 계정·권한 범위)에 맡겨
    두었다.** 그 결정이 2026-08-23에 났다 — **어드민 계정은 1차 시연 범위 밖**이다
    (`PRD §20 O-14` 각주).

    이 값을 보여 주는 화면은 `PRD §6.2`의 `SCR-006` Parameter Management이고
    `UIFLOW`가 그것을 `2-6 설정`으로 흡수했는데, 그 화면의 사용자가 「관리자」다.
    권한 체계가 post-MVP로 미뤄졌으므로 **화면도 함께 미뤄진다** — `UIFLOW 2-6`이
    「계정 관리만 MVP」로 확정됐다.

    **API를 지우는 것이 아니라 「빠뜨린 것이 아니다」를 여기 남기는 것**이다.
    값 자체는 IMO가 공개한 규제 상수이고 인증만 되면 조회할 수 있다 — 화면을 열지
    않는 것이 접근을 막는 조치는 아니다. 재개 지점은 `#672`다.
    """
    data = await list_reference_lines(session, ship_type=ship_type)
    return {"data": data, "meta": _meta(request, total=len(data))}


@router.get("/parameters/rating-boundaries")
async def list_rating_boundaries_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    ship_type: Annotated[str | None, Query(description="선종 필터. 생략하면 전 선종")] = None,
) -> dict[str, object]:
    """선종별 등급 경계 d-vector (API_SPEC §7.4).

    ## MVP 화면에 연결하지 않는다 (#556 · #359)

    `#556`이 「서버에 있는데 화면에서 도달할 수 없는 엔드포인트」를 전수 대조했을 때
    이 엔드포인트가 그중 하나였고, **판정을 `#359`(어드민 계정·권한 범위)에 맡겨
    두었다.** 그 결정이 2026-08-23에 났다 — **어드민 계정은 1차 시연 범위 밖**이다
    (`PRD §20 O-14` 각주).

    이 값을 보여 주는 화면은 `PRD §6.2`의 `SCR-006` Parameter Management이고
    `UIFLOW`가 그것을 `2-6 설정`으로 흡수했는데, 그 화면의 사용자가 「관리자」다.
    권한 체계가 post-MVP로 미뤄졌으므로 **화면도 함께 미뤄진다** — `UIFLOW 2-6`이
    「계정 관리만 MVP」로 확정됐다.

    **API를 지우는 것이 아니라 「빠뜨린 것이 아니다」를 여기 남기는 것**이다.
    값 자체는 IMO가 공개한 규제 상수이고 인증만 되면 조회할 수 있다 — 화면을 열지
    않는 것이 접근을 막는 조치는 아니다. 재개 지점은 `#672`다.
    """
    data = await list_rating_boundaries(session, ship_type=ship_type)
    return {"data": data, "meta": _meta(request, total=len(data))}
