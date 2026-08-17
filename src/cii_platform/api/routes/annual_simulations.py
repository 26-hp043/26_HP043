"""연간 시뮬레이션 라우트 (API_SPEC §6.1, #64).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 스냅샷·계산·저장은
``services.annual_simulation``이 맡는다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.annual_simulation import AnnualSimulationRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services.annual_simulation import run_annual_simulation

router = APIRouter(tags=["annual-simulations"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.post("/annual-simulations")
async def run_annual_simulation_route(
    request: Request,
    payload: AnnualSimulationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """연간 시뮬레이션을 실행한다 (API_SPEC §6.1).

    **201이 아니라 200이다.** 리소스를 만드는 것이 목적이 아니라 계산 결과를 받는
    것이 목적이고, `API_SPEC §6.1`이 200으로 적는다. 실행 이력이 저장되는 것은
    재현성을 위한 부수 효과다.
    """
    data = await run_annual_simulation(
        session,
        vessel_id=payload.vessel_id,
        regulation_year=payload.regulation_year,
        target_rating=payload.target_rating,
        simulation_runs=payload.simulation_runs,
        random_seed=payload.random_seed,
        distribution_profile=payload.distribution_profile,
        as_of=payload.as_of,
    )
    return {"data": data, "meta": _meta(request)}
