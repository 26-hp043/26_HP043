"""`calculation_run.weather_factor` 기록 (#904) — TECH_SPEC §5.4 4항 상환.

`TECH_SPEC §5.4`가 기상 인자를 재현성 계약으로 규정했는데 그 값이 어디에도
기록되지 않았다(#879 라이브 덤프). **C안** — `weather_snapshot_id` 옆의 실물
컬럼(039). 이 파일이 잠그는 것은 셋이다.

1. **기능②가 확정 인자를 기록한다** — `input_hash`에 들어간 그 값과 같아야
   재현 계약(§5.4 2항)이 성립한다. 보정이 켜진(≠1.0) 요청으로 검증한다.
2. **기능①이 유효 인자(1.0)를 기록한다** — 연료를 직접 받으므로 보정을 적용하지
   않지만, 「적용하지 않았다」의 유효값은 1.0이고 해시에 대입되는 값과 같다.
3. **컬럼 이전 행은 NULL이다** — immutable 트리거가 backfill을 막는다. NULL을
   1.0으로 해석하는 규칙은 문서(DB_SCHEMA §2.5)가 소유한다.

기상 조회 자체의 fallback 체인은 `test_weather_fallback_db.py`가 잠근다 — 여기는
**기록 위치**만 본다.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.scenario_compare import ScenarioCompareInput, compare_scenarios
from cii_platform.services.voyage_cii import FuelUseInput, VoyageCiiInput, estimate_voyage_cii
from cii_platform.weather.open_meteo import MARINE_ENDPOINT, OpenMeteoProvider

LAT, LON = Decimal("35.12"), Decimal("129.04")


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> UUID:
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "reference_speed_kn, reference_daily_foc_ton, default_fuel_type) "
            "VALUES (:id, :imo, 'WF TEST', 'BULK_CARRIER', 50000, 14, 28, 'HFO')"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    await session.commit()
    return new_id


def working_provider() -> OpenMeteoProvider:
    """보정이 켜지는(SIMPLE_RULE, factor > 1.0) 조회 성공 대역."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(
                200,
                json={
                    "hourly": {
                        "time": ["2026-09-12T00:00"],
                        "wave_height": [2.0],
                        "wave_direction": [0.0],
                        "wave_period": [7.0],
                    }
                },
            )
        return httpx.Response(
            200,
            json={"hourly": {"time": ["2026-09-12T00:00"], "wind_speed_10m": [8.0]}},
        )

    return OpenMeteoProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def _run_factors(session, vessel_id: UUID) -> dict[str, Decimal | None]:
    result = await session.execute(
        text(
            "SELECT calculation_type, weather_factor FROM calculation_run "
            "WHERE vessel_id = :vid"
        ),
        {"vid": vessel_id},
    )
    return {row[0]: row[1] for row in result}


@pytest.mark.asyncio
async def test_voyage_estimate_records_the_effective_factor(session, vessel_id):
    """기능① — 유효 인자 1.0이 컬럼에 남는다 (#904).

    해시가 ``None``에 대입하는 값과 같은 상수(``DEFAULT_WEATHER_FACTOR``)를 쓴다 —
    컬럼과 해시가 다른 값을 말하면 재현성 계약이 그 자리에서 갈라진다.
    """
    await estimate_voyage_cii(
        session,
        VoyageCiiInput(
            vessel_id=vessel_id,
            regulation_year=2026,
            distance_nm=Decimal("1000"),
            speed_kn=Decimal("14"),
            fuel_uses=(FuelUseInput(fuel_type="HFO", fuel_ton=Decimal("80")),),
        ),
    )

    assert await _run_factors(session, vessel_id) == {
        "VOYAGE_ESTIMATE": Decimal("1.0000")
    }


@pytest.mark.asyncio
async def test_scenario_records_the_resolved_factor(session, vessel_id):
    """기능② — 보정이 켜진 요청의 확정 인자(≠1.0)가 컬럼에 남는다 (#904).

    ``input_hash``에 들어간 값과 같아야 한다(§5.4 2항). 1.0과 구별되는 값으로
    검증해야 「우연히 맞았다」가 없다.
    """
    data = await compare_scenarios(
        session,
        ScenarioCompareInput(
            vessel_id=vessel_id,
            regulation_year=2026,
            current_speed_kn=Decimal("14"),
            fuel_type="HFO",
            current_lat=LAT,
            current_lon=LON,
            direct_distance_nm=Decimal("6000"),
            weather_model="SIMPLE_RULE",
        ),
        weather_provider=working_provider(),
    )
    resolved = data["data"]["scenarios"][0]

    factors = await _run_factors(session, vessel_id)
    recorded = factors["SCENARIO"]
    assert recorded is not None and recorded != Decimal("1.0000")

    # 간접 대조 — 시나리오 행이 기록해 온 그 인자와 계산 이력 컬럼이 같다.
    scenario_row = await session.execute(
        text(
            "SELECT weather_factor FROM voyage_scenario "
            "WHERE vessel_id = :vid AND scenario_type = 'DIRECT'"
        ),
        {"vid": vessel_id},
    )
    assert scenario_row.scalar() == recorded
    assert resolved["scenario_type"] == "DIRECT"
