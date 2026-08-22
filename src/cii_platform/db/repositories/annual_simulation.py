"""annual_simulation_run 조회 (DB_SCHEMA §2.6).

이 표를 다루는 자리는 종전에 ``services/annual_simulation.py``의 raw SQL뿐이었다.
내보내기(`API_SPEC §8.1` · `#59`)가 **선박 단위 목록**을 필요로 하면서 조회가 하나
더 생겼고, 그것을 서비스에 또 raw SQL로 적으면 같은 조인이 두 곳에 남는다
(`TECH_SPEC §16` — 질의는 저장소가 갖는다).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from cii_platform.db.models.annual_simulation_run import AnnualSimulationRun
from cii_platform.db.models.calculation_run import CalculationRun

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def list_for_export(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int | None = None,
) -> list[tuple[AnnualSimulationRun, CalculationRun]]:
    """선박의 연간 시뮬레이션 실행을 결과 본문과 함께 조회한다 (`§8.1`, #59).

    ``calculation_run``을 **INNER JOIN**한다 — ``calculation_run_id``가 NOT NULL이라
    (`DB_SCHEMA §2.6`) 짝이 없는 행은 존재할 수 없고, OUTER로 두면 있을 수 없는
    경우를 처리하는 분기가 호출부에 생긴다.

    정렬은 ``(created_at, id)`` 오름차순 — **내보낸 파일의 행 순서가 실행 순서**다.
    최신순으로 두면 스프레드시트에서 시간이 거꾸로 흐른다.
    """
    stmt = (
        select(AnnualSimulationRun, CalculationRun)
        .join(CalculationRun, CalculationRun.id == AnnualSimulationRun.calculation_run_id)
        .where(AnnualSimulationRun.vessel_id == vessel_id)
    )
    if regulation_year is not None:
        stmt = stmt.where(AnnualSimulationRun.regulation_year == regulation_year)

    stmt = stmt.order_by(AnnualSimulationRun.created_at, AnnualSimulationRun.id)
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]
