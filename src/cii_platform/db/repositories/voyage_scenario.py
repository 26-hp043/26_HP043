"""운항 시나리오 저장소 — 쿼리만 담당한다 (TECH_SPEC §16, #57).

비즈니스 판단은 ``services``가, 이 모듈은 INSERT만 한다. ``commit``은 호출부
(서비스)가 정한다 — ``calculation_run`` 저장소와 같은 규약이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.db.models.voyage_scenario import VoyageScenario

if TYPE_CHECKING:
    from decimal import Decimal
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def insert(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    scenario_type: str,
    scenario_name: str,
    distance_nm: Decimal,
    speed_kn: Decimal,
    duration_hours: Decimal,
    fuel_ton: Decimal,
    weather_factor: Decimal,
    cii_value: Decimal,
    estimated_rating: str,
    risk_level: str,
) -> VoyageScenario:
    """독립 시나리오 1건을 INSERT 하고 flush 한다.

    기능②(#57)의 시나리오는 항차에 묶이지 않는다 — ``voyage_id``는 NULL이다
    (DB_SCHEMA §2.4 [S-8] 독립 시나리오 허용). ``scenario_id``를 응답에 실어야
    하므로 flush 한다 — PK가 ``gen_random_uuid()`` server_default라 DB에 문장을
    보내기 전에는 값이 없다.

    ``cii_value``는 [M-8] denormalized 캐시다. canonical 값은 ``calculation_run``의
    ``result_json``이 소유하므로, 여기 들어가는 값은 컬럼 스케일(15,8)로 반올림된
    복사본이다.
    """
    scenario = VoyageScenario(
        vessel_id=vessel_id,
        voyage_id=None,
        scenario_type=scenario_type,
        scenario_name=scenario_name,
        distance_nm=distance_nm,
        speed_kn=speed_kn,
        duration_hours=duration_hours,
        fuel_ton=fuel_ton,
        weather_factor=weather_factor,
        cii_value=cii_value,
        estimated_rating=estimated_rating,
        risk_level=risk_level,
        weather_snapshot_id=None,
    )
    session.add(scenario)
    await session.flush()
    return scenario
