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


async def list_regulation_years(
    session: AsyncSession, *, active_only: bool = True
) -> Sequence[RegulationYear]:
    """규정 연도 목록을 연도순으로 조회한다 (``API_SPEC §7.1``, #444).

    ``active_only``가 기본 ``True``인 이유는 :func:`get_regulation_year`와 같다 —
    **개정으로 대체된 행이 현행처럼 보이면 안 된다.**
    """
    stmt = select(RegulationYear).order_by(RegulationYear.year)
    if active_only:
        stmt = stmt.where(RegulationYear.is_active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def list_reference_lines(
    session: AsyncSession, ship_type: str | None = None
) -> Sequence[CiiReferenceLine]:
    """기준선 후보 행을 조회한다. ``ship_type``이 없으면 전 선종 (#444).

    **한 행만 골라 오지 않는다.** 어느 행이 맞는지는 ``condition_expr``을 평가해야
    알 수 있고(``DWT >= 279000`` 등) 그 평가는 ``calc.capacity.select_reference_line()``이
    한다. 저장소가 조건을 해석하면 같은 규칙이 두 곳에 생긴다.

    선종을 지정하지 않는 경로는 조회 API(``API_SPEC §7.3``)를 위한 것이다 — 계산은
    언제나 한 선종만 본다.
    """
    stmt = select(CiiReferenceLine).order_by(
        CiiReferenceLine.ship_type, CiiReferenceLine.condition_expr
    )
    if ship_type is not None:
        stmt = stmt.where(CiiReferenceLine.ship_type == ship_type)
    return list((await session.execute(stmt)).scalars().all())


async def list_rating_boundaries(
    session: AsyncSession, ship_type: str | None = None
) -> Sequence[CiiRatingBoundary]:
    """등급 경계 후보 행을 조회한다. ``ship_type``이 없으면 전 선종 (#444).

    행 선택은 ``calc.rating_engine.select_rating_boundary()``가 한다
    (:func:`list_reference_lines`와 같은 이유).
    """
    stmt = select(CiiRatingBoundary).order_by(
        CiiRatingBoundary.ship_type, CiiRatingBoundary.condition_expr
    )
    if ship_type is not None:
        stmt = stmt.where(CiiRatingBoundary.ship_type == ship_type)
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

    이 함수를 쓰는 곳은 ``API_SPEC §7.2`` 조회 API다 (#444). :func:`list_fuel_types`의
    기본 경로와 같으며, 이름이 뜻을 그대로 말해 주므로 호출부를 남겨 둔다.
    """
    return await list_fuel_types(session, active=True)


async def list_fuel_types(
    session: AsyncSession, *, active: bool | None = True
) -> Sequence[FuelType]:
    """연료 종류를 코드순으로 조회한다 (``API_SPEC §7.2``, #444).

    ``active``는 세 값을 갖는다 — ``True``(활성만) · ``False``(비활성만) ·
    ``None``(전부). **「전부」와 「활성만」을 한 함수로 두되 기본을 활성으로 두는** 이유는,
    선택지로 쓰이는 쪽이 압도적으로 많고 비활성 연료가 선택지에 섞이면 사용자가
    저장 단계에서야 거부를 만나기 때문이다.
    """
    stmt = select(FuelType).order_by(FuelType.code)
    if active is not None:
        stmt = stmt.where(FuelType.is_active.is_(active))
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
