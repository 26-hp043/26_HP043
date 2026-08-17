"""규제 파라미터 저장소 — 쿼리만 담당한다 (TECH_SPEC §16).

``regulation_year``(Z계수) · ``cii_reference_line``(기준선) · ``cii_rating_boundary``
(d-vector) · ``fuel_type``(CF) 네 테이블을 읽는다.

이 값들은 **``scripts/seed.py``가 적재**한다. 마이그레이션이 아니라 스크립트인 것은
현재 상태이며, data migration 승격은 ``#127``이 다룬다. 따라서 **적재되지 않은 DB에서는
여기가 빈 결과를 돌려주고, 그것을 오류로 바꾸는 것은 서비스 계층의 판단**이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from cii_platform.db.models.cii_rating_boundary import CiiRatingBoundary
from cii_platform.db.models.cii_reference_line import CiiReferenceLine
from cii_platform.db.models.fuel_type import FuelType
from cii_platform.db.models.regulation_year import RegulationYear
from cii_platform.db.models.simulation_parameter import SimulationParameter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


async def get_regulation_year(session: AsyncSession, year: int) -> RegulationYear | None:
    """해당 연도의 Z계수 행을 조회한다.

    ``is_active``가 false인 행은 제외한다 — 규정 개정으로 대체된 행을 계산에 쓰면
    안 된다.
    """
    stmt = select(RegulationYear).where(
        RegulationYear.year == year, RegulationYear.is_active.is_(True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_reference_lines(session: AsyncSession, ship_type: str) -> Sequence[CiiReferenceLine]:
    """선종의 기준선 후보 행을 전부 조회한다.

    **한 행만 골라 오지 않는다.** 어느 행이 맞는지는 ``condition_expr``을 평가해야
    알 수 있고(``DWT >= 279000`` 등) 그 평가는 ``calc.capacity.select_reference_line()``이
    한다. 저장소가 조건을 해석하면 같은 규칙이 두 곳에 생긴다.
    """
    stmt = (
        select(CiiReferenceLine)
        .where(CiiReferenceLine.ship_type == ship_type)
        .order_by(CiiReferenceLine.condition_expr)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_rating_boundaries(
    session: AsyncSession, ship_type: str
) -> Sequence[CiiRatingBoundary]:
    """선종의 등급 경계 후보 행을 전부 조회한다.

    행 선택은 ``calc.rating_engine.select_rating_boundary()``가 한다
    (:func:`list_reference_lines`와 같은 이유).
    """
    stmt = (
        select(CiiRatingBoundary)
        .where(CiiRatingBoundary.ship_type == ship_type)
        .order_by(CiiRatingBoundary.condition_expr)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_fuel_types_by_codes(
    session: AsyncSession, codes: Sequence[str]
) -> dict[str, FuelType]:
    """연료 코드 → 행 매핑을 한 번의 쿼리로 가져온다.

    코드 하나씩 조회하면 연료 종류 수만큼 왕복이 생긴다. 요청에 없는 코드는 결과
    dict에 없으며, **없는 코드를 오류로 바꾸는 것은 서비스 계층의 판단**이다.

    ``is_active``가 false인 연료는 제외한다 (API_SPEC §4.1 VAL-006 「active fuel_type」).
    """
    if not codes:
        return {}
    stmt = select(FuelType).where(FuelType.code.in_(list(codes)), FuelType.is_active.is_(True))
    rows = (await session.execute(stmt)).scalars().all()
    return {row.code: row for row in rows}


async def list_active_fuel_types(session: AsyncSession) -> Sequence[FuelType]:
    """활성 연료 종류 전체를 코드순으로 돌려준다 (#370).

    화면이 연료 선택지를 자기 코드에 박아 두면 seed와 갈라진다 — 실제로 ``MDO``는
    유효해 보이지만 시드에 없는 코드고, 박아 두었다면 사용자는 저장 단계에서야
    거부를 만난다. 서버가 선택지를 주는 편이 갈릴 여지 자체를 없앤다.

    ``API_SPEC §7.2``의 연료 조회 API가 이 역할을 하도록 명세돼 있으나 **아직
    구현되지 않았다**. 그 엔드포인트가 생기면 이 함수를 함께 쓰면 된다.
    """
    stmt = select(FuelType).where(FuelType.is_active.is_(True)).order_by(FuelType.code)
    return (await session.execute(stmt)).scalars().all()


async def load_distribution_profile(
    session: AsyncSession, profile: str = "DEFAULT"
) -> Sequence[SimulationParameter]:
    """Monte Carlo 분포 파라미터를 프로파일 단위로 읽는다 (#434).

    ``PRD §12.4.1``이 *"분포 기본값은 ``simulation_parameter``로 관리하며 코드
    하드코딩하지 않는다"* 를 요구한다. ``#63`` 엔진은 분포를 인자로 받으므로, 그
    인자를 만드는 것이 이 함수의 몫이다.

    :returns: 변수(``DISTANCE``·``FUEL``·``SPEED``)별 1행. **없으면 빈 목록**이며,
        「기본값이 없다」를 오류로 만들지 판단하는 것은 서비스의 몫이다.
    """
    stmt = (
        select(SimulationParameter)
        .where(
            SimulationParameter.profile == profile,
            SimulationParameter.is_active.is_(True),
        )
        .order_by(SimulationParameter.variable)
    )
    return (await session.execute(stmt)).scalars().all()
