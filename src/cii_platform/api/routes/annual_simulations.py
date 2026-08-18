"""연간 시뮬레이션 라우트 (API_SPEC §6.1~§6.4, #64 · #443).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 스냅샷·계산·저장은
``services.annual_simulation``이 맡는다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.annual_simulation import AnnualSimulationRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.services.annual_simulation import (
    get_annual_simulation,
    list_snapshot_voyages,
    reproduce_annual_simulation,
    run_annual_simulation,
)

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


@router.get("/annual-simulations/{simulation_run_id}")
async def get_annual_simulation_route(
    request: Request,
    simulation_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """저장된 실행 결과를 조회한다 (API_SPEC §6.2).

    **경로의 식별자는 `annual_simulation_run.id`다** — §6.1 응답의 `simulation_id`.
    같은 응답에 `calculation_run_id`도 있어 둘 다 받을 수 있게 만들 수 있지만,
    한 경로가 두 종류의 ID를 받으면 **잘못된 ID를 넣어도 404가 아니라 다른 실행의
    결과가 돌아올 수 있다.** 리소스 이름(`annual-simulations`)과 같은 것을 받는다.
    """
    data = await get_annual_simulation(session, simulation_run_id)
    return {"data": data, "meta": _meta(request)}


@router.get("/annual-simulations/{simulation_run_id}/snapshot-voyages")
async def list_snapshot_voyages_route(
    request: Request,
    simulation_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """실행 당시 스냅샷의 항차 목록 (API_SPEC §6.3).

    **페이지네이션을 두지 않는다.** 한 실행의 스냅샷은 그 자체가 하나의 근거 묶음이라
    잘라 내면 「그때 무슨 데이터로 돌렸나」에 부분으로만 답하게 된다. 잔여 계획 항차는
    `PRD §12.8`이 200건으로 상한을 두고 있어 크기도 한정된다.
    """
    data = await list_snapshot_voyages(session, simulation_run_id)
    return {"data": data, "meta": _meta(request)}


@router.post("/annual-simulations/{simulation_run_id}/reproduce")
async def reproduce_annual_simulation_route(
    request: Request,
    simulation_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """같은 seed·같은 스냅샷으로 재실행해 결과가 같은지 확인한다 (API_SPEC §6.4).

    **`POST`인데 아무것도 만들지 않는다.** 계산을 다시 돌리는 것은 부작용이 없는
    조작이 아니므로(비용·시간) `GET`으로 두지 않았고, §6.4가 `POST`로 규정한다.
    새 실행 기록을 남기지 않는 이유는 서비스 docstring에 적었다.
    """
    data = await reproduce_annual_simulation(session, simulation_run_id)
    return {"data": data, "meta": _meta(request)}
