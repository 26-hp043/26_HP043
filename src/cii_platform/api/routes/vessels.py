"""선박 조회·등록·수정·삭제 라우트 (API_SPEC §2.1~§2.5).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 비즈니스 규칙·검증·트랜잭션은
``services.vessel``이 맡는다.

범위: 조회(#51) + 등록(#50) + 수정·삭제(#52).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

# TYPE_CHECKING 블록에 두면 안 된다. `from __future__ import annotations`로 애노테이션이
# 문자열이 되는데, FastAPI는 의존성 시그니처를 **런타임에** 해석하므로 이름을 찾지 못해
# PydanticUserError(`is not fully defined`)로 앱 기동이 실패한다.
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.vessel import (
    VesselCreateRequest,
    VesselPositionUpdateRequest,
    VesselUpdateRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services.cii_history import list_cii_history
from cii_platform.services.vessel import (
    create_vessel,
    delete_vessel,
    get_vessel,
    list_vessels,
    update_vessel,
    update_vessel_position,
)

router = APIRouter(tags=["vessels"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    """API_SPEC §1.3.1 ``meta``. 미들웨어가 주입한 요청 컨텍스트를 옮긴다."""
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/vessels")
async def list_vessels_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int | None, Query(description="페이지 크기 (기본 20, 최대 100)")] = None,
    cursor: Annotated[str | None, Query(description="페이지네이션 커서")] = None,
    ship_type: Annotated[str | None, Query(description="선종 필터")] = None,
    search: Annotated[str | None, Query(description="선박명 또는 IMO 번호 검색")] = None,
) -> dict[str, object]:
    """선박 목록을 조회한다 (API_SPEC §2.1).

    ``meta``에 ``next_cursor``·``has_more``가 함께 들어간다 — §2.1 예시가 그 둘을
    ``request_id``·``timestamp``와 같은 객체에 둔다.
    """
    data, page_meta = await list_vessels(
        session, limit=limit, cursor=cursor, ship_type=ship_type, search=search
    )
    return {"data": data, "meta": _meta(request, **page_meta)}


@router.get("/vessels/{vessel_id}")
async def get_vessel_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """선박 상세를 조회한다 (API_SPEC §2.2). 없으면 404 ``NOT_FOUND``."""
    return {"data": await get_vessel(session, vessel_id), "meta": _meta(request)}


@router.get("/vessels/{vessel_id}/cii-history")
async def get_cii_history_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    from_year: Annotated[
        int | None,
        Query(alias="from", description="시작 연도. 기본 to-2 (최근 3년 창)"),
    ] = None,
    to_year: Annotated[
        int | None, Query(alias="to", description="종료 연도. 기본 as_of 연도(올해)")
    ] = None,
    as_of: Annotated[
        datetime | None,
        Query(
            description=(
                "확정/진행 중 판정 기준 시각 (ISO 8601). 미지정이면 서버 현재 시각. "
                "응답 meta.as_of를 그대로 되돌려 보내면 같은 결과를 얻는다 (#368 계약 ⑶)"
            ),
        ),
    ] = None,
) -> dict[str, object]:
    """선박의 연도별 CII 이력을 조회한다 (API_SPEC §2.7, #355). 없으면 404.

    ``from``/``to``는 Python 예약어와 겹쳐 파라미터명을 ``from_year``/``to_year``로
    두고 ``alias``로 노출한다 — OpenAPI에 보이는 이름은 ``from``/``to``다.
    ``meta.as_of``는 확정/진행 중 판정에 쓴 시각이다.
    """
    history = await list_cii_history(
        session,
        vessel_id=vessel_id,
        from_year=from_year,
        to_year=to_year,
        as_of=as_of,
    )
    # 서비스 계약상 as_of는 항상 datetime이다(#368 계약 ⑵ — resolve_as_of가 확정).
    as_of: object = history["as_of"]
    return {
        "data": {
            "vessel_id": history["vessel_id"],
            "from": history["from"],
            "to": history["to"],
            "years": history["years"],
        },
        "meta": _meta(request, as_of=as_of.isoformat() if isinstance(as_of, datetime) else as_of),
    }


@router.post("/vessels", status_code=201)
async def create_vessel_route(
    request: Request,
    payload: VesselCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """선박을 등록한다 (API_SPEC §2.3, #50). 성공 시 201 Created.

    ``status_code=201``을 라우트에 단 이유 — FastAPI 기본값(200)으로 두면 OpenAPI가
    잘못된 응답 코드를 문서화하고, 클라이언트가 201을 기대하면 어긋난다.
    """
    data = await create_vessel(
        session,
        imo_number=payload.imo_number,
        name=payload.name,
        ship_type=payload.ship_type,
        gross_tonnage=payload.gross_tonnage,
        deadweight=payload.deadweight,
        default_fuel_type=payload.default_fuel_type,
        reference_speed_kn=payload.reference_speed_kn,
        reference_daily_foc_ton=payload.reference_daily_foc_ton,
    )
    return {"data": data, "meta": _meta(request)}


@router.patch("/vessels/{vessel_id}")
async def update_vessel_route(
    request: Request,
    vessel_id: UUID,
    payload: VesselUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """선박을 수정한다 (API_SPEC §2.4, #52). 없으면 404."""
    data = await update_vessel(
        session,
        vessel_id,
        name=payload.name,
        ship_type=payload.ship_type,
        gross_tonnage=payload.gross_tonnage,
        deadweight=payload.deadweight,
        default_fuel_type=payload.default_fuel_type,
        reference_speed_kn=payload.reference_speed_kn,
        reference_daily_foc_ton=payload.reference_daily_foc_ton,
    )
    return {"data": data, "meta": _meta(request)}


@router.patch("/vessels/{vessel_id}/position")
async def update_vessel_position_route(
    request: Request,
    vessel_id: UUID,
    payload: VesselPositionUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """선박의 현재 위치·운항 상태를 갱신한다 (API_SPEC §2.6, #369). 없으면 404.

    ``require_csrf``를 다른 변경 API와 **같은 방식으로** 건다 — ``#307``이
    「만든 것과 붙인 것이 달랐던」 사례를 남겼기 때문에, 새 변경 엔드포인트는
    인증 게이트 배선을 항상 함께 확인한다.
    """
    data = await update_vessel_position(
        session,
        vessel_id,
        underway_state=payload.underway_state,
        detail_status=payload.detail_status,
        current_lat=payload.current_lat,
        current_lon=payload.current_lon,
    )
    return {"data": data, "meta": _meta(request)}


@router.delete("/vessels/{vessel_id}")
async def delete_vessel_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """선박을 soft delete 한다 (API_SPEC §2.5, #52).

    응답 형태가 ``data.deleted = true`` — 204가 아니다. §2.5가 200 OK + 본문을
    규정하기 때문이고, 클라이언트가 삭제 결과를 JSON으로 받을 수 있어야 한다.
    """
    data = await delete_vessel(session, vessel_id)
    return {"data": data, "meta": _meta(request)}
