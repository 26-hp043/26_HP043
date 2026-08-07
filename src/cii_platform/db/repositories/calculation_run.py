"""계산 이력 저장소 — 쓰기만 담당한다 (TECH_SPEC §16).

``calculation_run``은 **append-only**다. 같은 입력으로 다시 요청하면 새 행이 생긴다
(#55 「항상 새로 생성, 멱등성 없음」). ``input_hash``·``parameter_hash``는 중복 제거용이
아니라 **재현성 추적용**이다 — 같은 해시의 두 행이 다른 결과를 담고 있으면 그 사이에
코드나 파라미터가 바뀐 것이며, 그것을 찾아내는 것이 이 컬럼의 목적이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.db.models.calculation_run import CalculationRun

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: DB_SCHEMA §2.5 ``chk_calculation_type``의 허용값 중 기능①에 해당하는 것.
#: 이 문자열이 틀리면 INSERT가 CHECK 제약에 걸린다.
CALCULATION_TYPE_VOYAGE = "VOYAGE_ESTIMATE"


async def insert_voyage_estimate(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    input_hash: str,
    parameter_hash: str,
    model_version: dict[str, object],
    result_json: dict[str, object],
    parameters_used: dict[str, object],
    warnings: list[str],
    duration_ms: int,
) -> CalculationRun:
    """기능① 계산 이력 1건을 저장하고 flush한다.

    **commit하지 않는다.** 트랜잭션 경계는 서비스 계층이 정한다(``db/session.py``의
    ``get_session`` docstring 참조).

    ``flush``는 하는 이유: 응답의 ``calculation_run_id``에 이 행의 PK가 필요한데,
    PK가 ``gen_random_uuid()`` server_default라 **DB에 문장을 보내기 전에는 값이 없다.**

    ``warnings``를 ``warnings_json``에 넣을 때 리스트를 그대로 쓴다 — 컬럼이 JSONB이고
    TECH_SPEC §12.2 4항이 「모든 오류를 warnings_json에 기록」으로 규정한다.
    """
    run = CalculationRun(
        calculation_type=CALCULATION_TYPE_VOYAGE,
        vessel_id=vessel_id,
        voyage_id=None,
        weather_snapshot_id=None,
        input_hash=input_hash,
        parameter_hash=parameter_hash,
        model_version=model_version,
        result_json=result_json,
        parameters_used=parameters_used,
        warnings_json=warnings,
        duration_ms=duration_ms,
    )
    session.add(run)
    await session.flush()
    return run
