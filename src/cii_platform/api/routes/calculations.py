"""계산 API 라우트 (API_SPEC §4).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1) — 검증은 Pydantic이, 계산 흐름은
``services.voyage_cii``가, 쿼리는 ``db/repositories``가 한다. 이 모듈에 계산식이나
쿼리가 생기면 계층이 무너진 것이다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

# TYPE_CHECKING 블록에 두면 안 된다. `from __future__ import annotations`로 애노테이션이
# 문자열이 되는데, FastAPI는 의존성 시그니처를 **런타임에** 해석하므로 이름을 찾지 못해
# PydanticUserError(`is not fully defined`)로 앱 기동이 실패한다.
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.voyage_cii import VoyageCiiRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services import audit as audit_svc
from cii_platform.services.calculation import list_calculation_runs
from cii_platform.services.voyage_cii import (
    FuelUseInput,
    VoyageCiiInput,
    estimate_voyage_cii,
)

router = APIRouter(tags=["calculations"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    """API_SPEC §1.3.1 ``meta``. 미들웨어가 주입한 요청 컨텍스트를 옮긴다."""
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/calculations")
async def list_calculations_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    input_hash: Annotated[str | None, Query(description="sha256: + 64 hex chars")] = None,
    parameter_hash: Annotated[str | None, Query(description="sha256: + 64 hex chars")] = None,
    type: Annotated[
        str | None,
        Query(description="VOYAGE_ESTIMATE, SCENARIO, ANNUAL_DETERMINISTIC, ANNUAL_MONTE_CARLO"),
    ] = None,
    vessel_id: Annotated[UUID | None, Query(description="선박 필터")] = None,
    limit: Annotated[int | None, Query(description="페이지 크기 (기본 20, 최대 100)")] = None,
    cursor: Annotated[str | None, Query(description="페이지네이션 커서")] = None,
) -> dict[str, object]:
    """계산 결과를 조회한다 (API_SPEC §1.9, #56).

    ``input_hash`` + ``parameter_hash``를 모두 지정하면 **정확히 일치하는** 계산 결과만
    반환한다 — 재현성 검증 용법. ``meta``에 ``next_cursor``·``has_more``가 함께 들어간다.
    """
    data, page_meta = await list_calculation_runs(
        session,
        limit=limit,
        cursor=cursor,
        input_hash=input_hash,
        parameter_hash=parameter_hash,
        calculation_type=type,
        vessel_id=vessel_id,
    )
    return {"data": data, "meta": _meta(request, **page_meta)}


@router.post("/calculations/voyage-cii")
async def voyage_cii(
    request: Request,
    payload: VoyageCiiRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차 CII를 추정한다 (API_SPEC §4.1).

    ``meta``는 여기서 붙인다. ``request_id``·``timestamp``는 미들웨어가 요청 단위로
    만든 값이고, 서비스가 ``request`` 객체를 알면 계층 방향이 뒤집힌다(§16.1).

    Pydantic 모델을 서비스에 그대로 넘기지 않고 DTO로 옮기는 것도 같은 이유다 —
    ``services``가 ``api.schemas``를 import하면 아래 계층이 위 계층에 의존하게 된다.
    """
    result = await estimate_voyage_cii(
        session,
        VoyageCiiInput(
            vessel_id=payload.vessel_id,
            regulation_year=payload.regulation_year,
            distance_nm=payload.distance_nm,
            speed_kn=payload.speed_kn,
            fuel_uses=tuple(
                FuelUseInput(fuel_type=item.fuel_type, fuel_ton=item.fuel_ton)
                for item in payload.fuel_uses
            ),
            weather_model=payload.weather_model,
        ),
    )

    # 서비스가 잰 계산 시간을 meta로 옮긴다. 내부 키(`_duration_ms`)는 응답에서 뺀다.
    duration_ms = result.pop("_duration_ms")
    state = getattr(request, "state", None)
    result["meta"] = {
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        "duration_ms": duration_ms,
    }

    # 계산 실행 감사 (TECH_SPEC §13.1 · #277) — 인증 미들웨어가 request.state에
    # 심은 사용자를 주체로 기록한다. 서비스가 request를 알면 계층이 깨지므로(§16.1)
    # 라우트가 값을 뽑아 넘긴다.
    session_user = getattr(state, "session_user", None)
    await audit_svc.record_calculation_run(
        session,
        user_id=str(session_user.id) if session_user is not None else None,
        run_id=UUID(result["calculation_run_id"]),
        input_hash=result["input_hash"],
        parameter_hash=result["parameter_hash"],
        model_version=result["model_version"],
        duration_ms=duration_ms,
        warnings_count=len(result["warnings"]),
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()
    return result
