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
from cii_platform.services import audit as audit_svc
from cii_platform.services.annual_simulation import (
    get_annual_simulation,
    list_snapshot_voyages,
    reproduce_annual_simulation,
    run_annual_simulation,
)

router = APIRouter(tags=["annual-simulations"])

#: 기능③이 저장하는 ``calculation_run.calculation_type`` (`services/annual_simulation.py`
#: 의 INSERT와 같은 값). ``TECH_SPEC §13.1`` 필드 표가 드는 네 값 중 하나다.
_CALCULATION_TYPE = "ANNUAL_MONTE_CARLO"


async def _record_run(
    request: Request,
    session: AsyncSession,
    result: dict[str, object],
    *,
    details_extra: dict[str, object] | None = None,
) -> None:
    """계산 실행을 감사 로그에 남긴다 (``TECH_SPEC §13.1``, #869).

    **기능③만 이 기록이 없었다.** §13.1은 「**모든** ``CalculationRun`` 생성 시」로
    적고 ``calculation_type`` 행에 ``ANNUAL_DETERMINISTIC``·``ANNUAL_MONTE_CARLO``를
    명시하는데, 이 라우트는 ``calculation_run`` 행을 실제로 만들면서(서비스의 raw
    INSERT) 감사 기록만 빠뜨렸다 — 세 기능 중 **가장 무거운 계산**의 실행 이력이
    남지 않았고, 사후 복구가 불가능했다.

    인증 미들웨어가 ``request.state``에 심은 사용자를 주체로 기록한다. 서비스가
    ``request``를 알면 계층이 깨지므로(``TECH_SPEC §16.1``) 라우트가 값을 뽑아
    넘긴다 — 기능①(``routes/calculations.py:125-139``)과 같은 형태다.
    """
    state = getattr(request, "state", None)
    session_user = getattr(state, "session_user", None)
    meta = result["meta"]
    assert isinstance(meta, dict)  # noqa: S101 — _with_meta가 방금 넣었다
    await audit_svc.record_calculation_run(
        session,
        user_id=str(session_user.id) if session_user is not None else None,
        run_id=UUID(str(result["calculation_run_id"])),
        input_hash=str(result["input_hash"]),
        parameter_hash=str(result["parameter_hash"]),
        model_version=result["model_version"],  # type: ignore[arg-type]
        duration_ms=int(meta["duration_ms"]),  # type: ignore[call-overload]
        warnings_count=len(result["warnings"]),  # type: ignore[arg-type]
        ip_address=request.client.host if request.client else None,
        calculation_type=_CALCULATION_TYPE,
        details_extra=details_extra,
    )
    await session.commit()


def _meta(request: Request, **extra: object) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


def _with_meta(request: Request, result: dict[str, object]) -> dict[str, object]:
    """서비스가 만든 ``API_SPEC §1.3.1`` 봉투에 ``meta``를 붙인다 (#752).

    서비스가 잰 계산 시간을 ``meta.duration_ms``로 옮기고 내부 키(``_duration_ms``)는
    응답에서 뺀다 — 기능①(``routes/calculations.py:116-123``)과 같은 방식이다.
    **시간을 여기서 재지 않는 이유**는 라우트에서 재면 요청 파싱·직렬화가 섞여
    ``PRD §16.1``의 「Monte Carlo 5,000회 p95 < 3초」와 다른 것을 재기 때문이다.
    """
    duration_ms = result.pop("_duration_ms")
    result["meta"] = _meta(request, duration_ms=duration_ms)
    return result


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
    result = _with_meta(request, data)
    await _record_run(request, session, result)
    return result


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
    return _with_meta(request, data)


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

    ## 화면에 연결하지 않는다 (#556 · #776 재판정)

    `#556`이 「서버에 있는데 화면에서 도달할 수 없는 엔드포인트」를 전수 대조했고,
    이 엔드포인트가 그중 하나였다. **판정 결과는 「범위 밖 명시」다** —
    「그때 무슨 데이터로 돌렸나」는 감사·검증 경로다.

    확인한 정본은 `PRD §5.1` MVP 표 · `PRD §6.2` SCR 목록 · `UIFLOW` 화면 목록 ·
    **`PRD §12.4.3` seed 정책**이며, 어디에도 이 목록을 보여 주는 화면의 대응이 없다.
    ⚠️ `#556`은 앞의 셋만 보고 판정했고, 그래서 같은 판정을 받았던 `reproduce`는
    `§12.4.3`의 「결과 재현 버튼」을 놓쳤다(`#776`에서 화면 연결로 뒤집혔다). 이
    엔드포인트는 `§12.4.3`까지 보고 **다시 범위 밖으로 확정**했다.

    **API를 지우는 것이 아니라 「빠뜨린 것이 아니다」를 여기 남기는 것**이다. 화면이
    필요해지면 `AGENTS §3.2.3`에 따라 `PRD §5` 개정이 먼저다.
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

    ## 화면에 연결한다 — 「이 seed로 다시 실행」 (#776)

    `PRD §12.4.3` seed 정책이 **「결과 재현 버튼 — `이 seed로 다시 실행` 버튼을
    제공한다」**로 화면 요구를 명시한다. 기능③ 결과의 재현 정보 블록
    (`frontend/src/features/annual-simulation/AnnualSimulation.tsx`)이 이 경로를 부른다.

    ⚠️ `#556`은 이 엔드포인트를 「재현성은 `TECH_SPEC §5.4` 계약이고 검증 수단이지
    사용자 기능이 아니다」로 **범위 밖** 판정했다. 확인한 정본이 `PRD §5.1`·`§6.2`·
    `UIFLOW` 셋뿐이어서 `§12.4.3`을 놓친 것이다. `AGENTS §3.1`상 `PRD`가 `TECH_SPEC`보다
    상위이므로 `#776`이 판정을 뒤집었다.
    """
    data = await reproduce_annual_simulation(session, simulation_run_id)
    result = _with_meta(request, data)
    # 재현은 새 `calculation_run` 행을 만들지 않고 **원본의 run_id**를 그대로 쓴다.
    # 표식이 없으면 감사 로그에서 원본 실행과 구분되지 않는다 (#869).
    await _record_run(request, session, result, details_extra={"reproduced": True})
    return result
