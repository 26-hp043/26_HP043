"""선박 조회 라우트 (API_SPEC §2.1 · §2.2).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 조회 규칙과 페이지네이션 판단은
``services.vessel``이 맡는다.

범위(#51)는 **조회 두 건**이다. 등록(#50) · 수정·삭제(#52)는 별도 이슈다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

# TYPE_CHECKING 블록에 두면 안 된다. `from __future__ import annotations`로 애노테이션이
# 문자열이 되는데, FastAPI는 의존성 시그니처를 **런타임에** 해석하므로 이름을 찾지 못해
# PydanticUserError(`is not fully defined`)로 앱 기동이 실패한다.
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.db.session import get_session
from cii_platform.services.vessel import get_vessel, list_vessels

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
