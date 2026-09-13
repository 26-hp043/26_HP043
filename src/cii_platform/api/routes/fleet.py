"""선대 요약 라우트 (`API_SPEC §2.8`).

**HTTP 요청/응답만 다룬다** (`TECH_SPEC §16.1`). 집계·판정은
``services.fleet_summary``가 맡는다.

범위: #350.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

# TYPE_CHECKING 블록에 두면 안 된다. `from __future__ import annotations`로 애노테이션이
# 문자열이 되는데, FastAPI는 의존성 시그니처를 **런타임에** 해석하므로 이름을 찾지 못해
# PydanticUserError로 앱 기동이 실패한다 (vessels.py와 같은 근거).
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.fleet_reduction import ReductionPlanRequest, ReductionPlanSaveRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services.data_quality import get_fleet_data_quality
from cii_platform.services.fleet_reduction import (
    evaluate_reduction_plan,
    get_reduction_plan,
    list_reduction_plans,
    save_reduction_plan,
)
from cii_platform.services.fleet_summary import get_fleet_summary

router = APIRouter(tags=["fleet"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    """`API_SPEC §1.3.1` ``meta``. 미들웨어가 주입한 요청 컨텍스트를 옮긴다."""
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/fleet/summary")
async def get_fleet_summary_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    regulation_year: Annotated[
        int | None,
        Query(ge=2000, le=2100, description="집계 대상 규제연도. 미지정이면 as_of 연도"),
    ] = None,
    as_of: Annotated[
        datetime | None,
        Query(description="기준 시각 (ISO 8601 UTC). 미지정이면 서버가 확정"),
    ] = None,
    sort: Annotated[str, Query(description="vessels[] 정렬 — risk(기본) · name · grade")] = (
        "risk"
    ),
    limit: Annotated[int | None, Query(description="vessels[] 페이지 크기 (기본 20, 최대 100)")] = (
        None
    ),
    cursor: Annotated[str | None, Query(description="이전 응답의 meta.next_cursor")] = None,
) -> dict[str, object]:
    """대시보드가 한 번의 호출로 선대 전체 현황을 받는다 (#350).

    **선박이 0척인 것은 오류가 아니다.** 아직 등록하지 않은 선사가 정상적으로
    만나는 상태이므로 200에 빈 배열을 돌려준다 — 404로 내면 화면이
    「기능 미구현」과 구분하지 못한다.
    """
    data = await get_fleet_summary(
        session,
        regulation_year=regulation_year,
        as_of=as_of,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    # `vessels[]` 페이지 정보는 `§1.5`대로 meta에 싣는다 (#772). summary·actions는 선대 전체다.
    page = data.pop("_page")
    # `as_of` 계약 ⑵ — 실제로 사용한 값을 meta에도 싣는다. 클라이언트가 이 값으로
    # 다시 물어 같은 결과를 얻을 수 있어야 한다. 다음 페이지도 이 값으로 묻는다.
    return {"data": data, "meta": _meta(request, as_of=data["as_of"], **page)}


@router.get("/fleet/data-quality")
async def get_fleet_data_quality_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    regulation_year: Annotated[
        int | None,
        Query(ge=2000, le=2100, description="점검 대상 규제연도. 미지정이면 올해"),
    ] = None,
) -> dict[str, object]:
    """선대의 CII 계산에 **실측이 아닌 값이** 어디에 들어갔는지 (`API_SPEC §2.16` · #513).

    **읽기 전용이다** (`UIFLOW 2-11`). 고치는 경로는 실적 보정(`PRD §17.2`)과 항차 편집이다.
    """
    data = await get_fleet_data_quality(session, regulation_year=regulation_year)
    return {"data": data, "meta": _meta(request)}


def _payload(body: ReductionPlanRequest) -> dict[str, object]:
    """요청 모델 → 서비스 인자. 수치는 **문자열로** 넘긴다 — 저장본(JSONB)에 float가 섞이지 않게."""
    return {
        "regulation_year": body.regulation_year,
        "target": body.target,
        "adjustments": [
            {
                "vessel_id": str(item.vessel_id),
                "speed_reduction_percent": str(item.speed_reduction_percent),
            }
            for item in body.adjustments
        ],
        "prices": {
            "charter_usd_per_day": {k: str(v) for k, v in body.prices.charter_usd_per_day.items()},
            "fuel_usd_per_ton": {k: str(v) for k, v in body.prices.fuel_usd_per_ton.items()},
        },
    }


@router.post("/fleet/reduction-plans/evaluate")
async def evaluate_reduction_plan_route(
    request: Request,
    body: ReductionPlanRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """감축 계획안을 **계산만** 한다 — 저장하지 않는다 (`API_SPEC §2.17.1` · #513).

    화면이 슬라이더를 움직일 때마다 부른다. **결정론만** 쓰므로 Monte Carlo 비용이 없다.
    """
    data = await evaluate_reduction_plan(session, **_payload(body))
    return {"data": data, "meta": _meta(request)}


@router.post("/fleet/reduction-plans", status_code=201)
async def save_reduction_plan_route(
    request: Request,
    body: ReductionPlanSaveRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """계획안을 저장한다 — 서버가 **다시 계산해** 결과까지 남긴다 (`API_SPEC §2.17.2`)."""
    state = getattr(request, "state", None)
    user = getattr(state, "session_user", None)
    data = await save_reduction_plan(
        session,
        plan_name=body.plan_name,
        user_id=user.id if user is not None else None,
        **_payload(body),
    )
    await session.commit()
    return {"data": data, "meta": _meta(request)}


@router.get("/fleet/reduction-plans")
async def list_reduction_plans_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """저장한 계획안 — 최근순 20건 (`API_SPEC §2.17.3`). 결과 본문은 단건 조회에 있다."""
    return {"data": await list_reduction_plans(session), "meta": _meta(request)}


@router.get("/fleet/reduction-plans/{plan_id}")
async def get_reduction_plan_route(
    request: Request,
    plan_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """저장한 계획안 한 건 — 저장 시점의 결과 그대로 (`API_SPEC §2.17.4`)."""
    return {"data": await get_reduction_plan(session, plan_id), "meta": _meta(request)}
