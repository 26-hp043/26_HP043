"""시나리오 비교 API 라우트 (API_SPEC §5).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1) — 검증은 Pydantic이, 계산 흐름은
``services.scenario_compare``가, 저장은 ``db/repositories``가 한다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

# TYPE_CHECKING 블록에 두면 안 된다. FastAPI는 의존성 시그니처를 런타임에 해석하므로
# AsyncSession을 모듈 스코프에서 import해야 한다 (calculations.py와 같은 이유).
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.scenario_compare import ScenarioCompareRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services import audit as audit_svc
from cii_platform.services.scenario_compare import ScenarioCompareInput, compare_scenarios

router = APIRouter(tags=["scenarios"])


@router.post("/scenarios/compare")
async def scenario_compare(
    request: Request,
    payload: ScenarioCompareRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """직항·우회·감속 시나리오를 중립 비교한다 (API_SPEC §5.1, #57)."""
    # Pydantic 모델을 DTO로 옮겨 실은다 — services가 api 패키지를 import하면 계층
    # 방향이 뒤집힌다 (calculations.py의 기능① 패턴과 같은 이유).
    result = await compare_scenarios(
        session,
        ScenarioCompareInput(
            vessel_id=payload.vessel_id,
            regulation_year=payload.regulation_year,
            current_speed_kn=payload.current_speed_kn,
            fuel_type=payload.fuel_type,
            current_lat=payload.current_lat,
            current_lon=payload.current_lon,
            destination_lat=payload.destination_lat,
            destination_lon=payload.destination_lon,
            base_daily_foc_ton=payload.base_daily_foc_ton,
            direct_distance_nm=payload.direct_distance_nm,
            detour_distance_nm=payload.detour_distance_nm,
            slow_speed_kn=payload.slow_speed_kn,
            weather_model=payload.weather_model,
        ),
    )

    duration_ms = result.pop("_duration_ms")
    state = getattr(request, "state", None)
    result["meta"] = {
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        "duration_ms": duration_ms,
    }

    # 계산 실행 감사 (TECH_SPEC §13.1 · #277) — 기능① 라우트와 같은 패턴.
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
        calculation_type="SCENARIO",
    )
    await session.commit()
    return result
