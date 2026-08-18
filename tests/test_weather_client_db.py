"""Open-Meteo 조회·스냅샷 저장 (TECH_SPEC §7, #61).

**네트워크를 쓰지 않는다.** `httpx.MockTransport`로 응답을 만들어 넣는다 — 실 API를
부르면 결과가 외부 서비스의 가용성에 묶여, 실패했을 때 우리 코드가 틀린 것인지
알 수 없다.

여기서 잠그는 것은 넷이다.

1. **두 엔드포인트를 모두 부른다** — 파고는 Marine, 풍속은 Forecast다(`§7.2`)
2. **한쪽이 실패해도 나머지를 쓴다** — 파고만 있으면 경험식이 돌고, 둘 다 없어야 실패다
3. **시각에 가장 가까운 값을 고른다** — 배열 첫 값을 쓰면 0시 파고로 오후를 보정한다
4. **조회한 것은 남긴다** — 계산 근거를 나중에 물을 수 있어야 한다(`§5.4`)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import weather as weather_repo
from cii_platform.errors import ModelBreakdownError, ParameterError, WeatherFetchError
from cii_platform.services.weather import (
    MODEL_NONE,
    MODEL_SIMPLE_RULE,
    MODEL_TOWNSIN_KWON,
    NEUTRAL_FACTOR,
    fetch_and_store,
    resolve_weather_factor,
    round_to_grid,
)
from cii_platform.weather.open_meteo import (
    MARINE_ENDPOINT,
    SOURCE_MERGED,
    WIND_ENDPOINT,
    OpenMeteoProvider,
)

AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

MARINE_BODY = {
    "hourly": {
        "time": ["2026-08-18T00:00", "2026-08-18T12:00", "2026-08-18T23:00"],
        "wave_height": [0.4, 2.5, 1.1],
        "wave_direction": [10.0, 45.0, 90.0],
        "wave_period": [5.0, 7.5, 6.0],
    }
}

WIND_BODY = {
    "hourly": {
        "time": ["2026-08-18T00:00", "2026-08-18T12:00"],
        "wind_speed_10m": [3.0, 11.5],
        "wind_direction_10m": [180.0, 200.0],
    }
}


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


def provider_for(handler) -> OpenMeteoProvider:
    """`MockTransport`를 실은 클라이언트를 주입한다."""
    return OpenMeteoProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def both_ok(request: httpx.Request) -> httpx.Response:
    if str(request.url).startswith(MARINE_ENDPOINT):
        return httpx.Response(200, json=MARINE_BODY)
    return httpx.Response(200, json=WIND_BODY)


# ─────────────────────────────────────────────────────────────────────────────
# 조회
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_endpoints_are_called():
    """`§7.2` — 파고와 풍속의 출처가 다르다."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url).split("?")[0])
        return both_ok(request)

    await provider_for(handler).fetch(35.1, 129.0, AT)

    assert MARINE_ENDPOINT in seen
    assert WIND_ENDPOINT in seen


@pytest.mark.asyncio
async def test_the_value_nearest_the_requested_hour_is_used():
    """배열 첫 값을 쓰면 **0시 파고로 오후 항해를 보정**한다."""
    observation = await provider_for(both_ok).fetch(35.1, 129.0, AT)

    assert observation.wave_height_m == 2.5
    assert observation.wind_speed_ms == 11.5


@pytest.mark.asyncio
async def test_marine_failure_still_yields_wind():
    """한쪽 실패가 전체 실패는 아니다 — 남은 값으로 `SIMPLE_RULE`이 돈다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(500)
        return httpx.Response(200, json=WIND_BODY)

    observation = await provider_for(handler).fetch(35.1, 129.0, AT)

    assert observation.wave_height_m is None
    assert observation.wind_speed_ms == 11.5
    assert observation.source != SOURCE_MERGED


@pytest.mark.asyncio
async def test_both_failing_is_a_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    with pytest.raises(WeatherFetchError):
        await provider_for(handler).fetch(35.1, 129.0, AT)


@pytest.mark.asyncio
async def test_null_values_are_not_read_as_zero():
    """Open-Meteo는 값이 없는 시간대에 `null`을 준다.

    0으로 바꾸면 「파고 0m의 잔잔한 바다」가 되어 **보정이 조용히 사라진다.**
    """
    body = {"hourly": {"time": ["2026-08-18T12:00"], "wave_height": [None]}}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(200, json=body)
        return httpx.Response(200, json=WIND_BODY)

    observation = await provider_for(handler).fetch(35.1, 129.0, AT)

    assert observation.wave_height_m is None


@pytest.mark.asyncio
async def test_empty_response_is_a_fetch_error():
    """값이 하나도 없으면 조회에 성공한 것이 아니다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hourly": {"time": []}})

    with pytest.raises(WeatherFetchError):
        await provider_for(handler).fetch(35.1, 129.0, AT)


# ─────────────────────────────────────────────────────────────────────────────
# 캐시 격자 · 저장
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [(35.1, "35.0"), (35.3, "35.5"), (129.04, "129.0"), (-12.26, "-12.5")],
)
def test_coordinates_round_to_the_cache_grid(value, expected):
    """`§7.3` 캐시 key는 0.5° 격자다.

    원좌표로 캐시하면 같은 해역을 지나면서도 **매번 새로 조회**한다.
    """
    assert round_to_grid(value) == Decimal(expected)


@pytest.mark.asyncio
async def test_fetched_weather_is_stored(session):
    """조회한 것은 남긴다 — 남기지 않으면 같은 계산을 재현할 수 없다 (`§5.4`)."""
    snapshot = await fetch_and_store(session, provider_for(both_ok), lat=35.12, lon=129.04, at=AT)

    assert snapshot.wave_height_m == Decimal("2.50")
    assert snapshot.wind_speed_ms == Decimal("11.50")
    assert snapshot.lat_rounded == Decimal("35.0")
    assert snapshot.source == SOURCE_MERGED

    stored = await session.execute(
        text("SELECT count(*) FROM weather_snapshot WHERE lat_rounded = 35.0")
    )
    assert stored.scalar_one() >= 1


@pytest.mark.asyncio
async def test_last_snapshot_is_the_most_recent_one(session):
    """`§7.1` `get_last_snapshot` — 같은 격자의 최신 행."""
    older = await weather_repo.insert_snapshot(
        session,
        lat=Decimal("35.1"),
        lon=Decimal("129.0"),
        lat_rounded=Decimal("35.0"),
        lon_rounded=Decimal("129.0"),
        fetched_at=datetime(2026, 8, 17, 0, 0, tzinfo=UTC),
        wave_height_m=Decimal("1.0"),
        wave_direction_deg=None,
        wave_period_s=None,
        wind_speed_ms=None,
        wind_direction_deg=None,
        source="sample",
    )
    newer = await weather_repo.insert_snapshot(
        session,
        lat=Decimal("35.1"),
        lon=Decimal("129.0"),
        lat_rounded=Decimal("35.0"),
        lon_rounded=Decimal("129.0"),
        fetched_at=datetime(2026, 8, 18, 0, 0, tzinfo=UTC),
        wave_height_m=Decimal("3.0"),
        wave_direction_deg=None,
        wave_period_s=None,
        wind_speed_ms=None,
        wind_direction_deg=None,
        source="sample",
    )

    found = await weather_repo.find_last_snapshot(
        session, lat_rounded=Decimal("35.0"), lon_rounded=Decimal("129.0")
    )

    assert found is not None
    assert found.id == newer.id
    assert found.id != older.id


@pytest.mark.asyncio
async def test_repository_does_not_hide_stale_rows(session):
    """저장소는 신선도를 판정하지 않는다.

    오래된 행을 숨기면 **「없다」와 「낡았다」가 구분되지 않는다** — 그 구분이
    fallback 체인(`#62`)의 입력이다.
    """
    await weather_repo.insert_snapshot(
        session,
        lat=Decimal("10.0"),
        lon=Decimal("20.0"),
        lat_rounded=Decimal("10.0"),
        lon_rounded=Decimal("20.0"),
        fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
        wave_height_m=Decimal("1.0"),
        wave_direction_deg=None,
        wave_period_s=None,
        wind_speed_ms=None,
        wind_direction_deg=None,
        source="sample",
    )

    found = await weather_repo.find_last_snapshot(
        session, lat_rounded=Decimal("10.0"), lon_rounded=Decimal("20.0")
    )

    assert found is not None


# ─────────────────────────────────────────────────────────────────────────────
# 모델 디스패치
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_none_model_does_not_correct(session):
    """UT-WX-001 — `NONE`이면 1.0. `input_hash`도 그 값으로 계산된다 (`§5.3`)."""
    snapshot = await fetch_and_store(session, provider_for(both_ok), lat=35.12, lon=129.04, at=AT)

    factor = await resolve_weather_factor(
        session, weather_model=MODEL_NONE, snapshot=snapshot, ship_type="BULK_CARRIER"
    )

    assert factor == NEUTRAL_FACTOR


@pytest.mark.asyncio
async def test_missing_snapshot_does_not_correct(session):
    """스냅샷이 없으면 보정하지 않는다 — 없는 기상을 지어내지 않는다."""
    factor = await resolve_weather_factor(
        session, weather_model=MODEL_TOWNSIN_KWON, snapshot=None, ship_type="BULK_CARRIER"
    )

    assert factor == NEUTRAL_FACTOR


@pytest.mark.asyncio
async def test_townsin_kwon_reads_coefficients_from_the_table(session):
    """계수는 마이그레이션 019가 넣은 `weather_model_parameter`에서 온다 (`#434`와 같은 규칙)."""
    snapshot = await fetch_and_store(session, provider_for(both_ok), lat=35.12, lon=129.04, at=AT)

    factor = await resolve_weather_factor(
        session,
        weather_model=MODEL_TOWNSIN_KWON,
        snapshot=snapshot,
        ship_type="BULK_CARRIER",
    )

    assert factor > NEUTRAL_FACTOR


@pytest.mark.asyncio
async def test_ship_type_without_coefficients_is_a_parameter_error(session):
    """계수가 없는 선종은 **서버 데이터 문제**다 — 사용자가 입력으로 고칠 수 없다."""
    snapshot = await fetch_and_store(session, provider_for(both_ok), lat=35.12, lon=129.04, at=AT)

    with pytest.raises(ParameterError):
        await resolve_weather_factor(
            session,
            weather_model=MODEL_TOWNSIN_KWON,
            snapshot=snapshot,
            ship_type="CRUISE_PASSENGER",
        )


@pytest.mark.asyncio
async def test_simple_rule_uses_wave_and_wind(session):
    snapshot = await fetch_and_store(session, provider_for(both_ok), lat=35.12, lon=129.04, at=AT)

    factor = await resolve_weather_factor(
        session,
        weather_model=MODEL_SIMPLE_RULE,
        snapshot=snapshot,
        ship_type="BULK_CARRIER",
    )

    # 1.0 + 2.5×0.02 + 11.5×0.005
    assert factor == Decimal("1.10750")


@pytest.mark.asyncio
async def test_model_breakdown_is_not_a_server_error(session):
    """`calc`의 `ValueError`를 그대로 올리면 **500**이 된다.

    적용 범위를 벗어난 것은 서버 오류가 아니므로 422(`ModelBreakdownError`)로 옮긴다
    (`TECH_SPEC §12.2`).
    """
    storm = {
        "hourly": {
            "time": ["2026-08-18T12:00"],
            "wave_height": [12.0],
            "wave_direction": [0.0],
            "wave_period": [9.0],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(200, json=storm)
        return httpx.Response(200, json=WIND_BODY)

    snapshot = await fetch_and_store(session, provider_for(handler), lat=35.12, lon=129.04, at=AT)

    with pytest.raises(ModelBreakdownError):
        await resolve_weather_factor(
            session,
            weather_model=MODEL_TOWNSIN_KWON,
            snapshot=snapshot,
            ship_type="BULK_CARRIER",
        )
