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

#: 실제 Open-Meteo 응답 형태다 — ``hourly_units``를 함께 싣는다 (#813).
#:
#: 종전 픽스처는 이 블록이 없어 **단위를 m/s로 단정**했다. 실제 API의 기본 단위는
#: ``km/h``이고, 코드가 변환 없이 저장해 값이 3.6배 커지고 있었다. **픽스처가 잘못된
#: 전제를 고정하면 그 결함이 테스트를 통과한다.**
WIND_BODY = {
    "hourly_units": {"time": "iso8601", "wind_speed_10m": "m/s", "wind_direction_10m": "°"},
    "hourly": {
        "time": ["2026-08-18T00:00", "2026-08-18T12:00"],
        "wind_speed_10m": [3.0, 11.5],
        "wind_direction_10m": [180.0, 200.0],
    },
}

#: 단위가 예상과 다른 응답 — 요청에 ``wind_speed_unit=ms``를 실었어도 서버가 다른
#: 단위를 주면 이 모양이 된다 (#813).
WIND_BODY_KMH = {
    "hourly_units": {"time": "iso8601", "wind_speed_10m": "km/h", "wind_direction_10m": "°"},
    "hourly": {
        "time": ["2026-08-18T00:00", "2026-08-18T12:00"],
        "wind_speed_10m": [10.8, 41.4],
        "wind_direction_10m": [180.0, 200.0],
    },
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


# ─────────────────────────────────────────────────────────────────────────────
# 풍속 단위 (#813)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wind_request_pins_the_unit_to_ms():
    """요청이 ``wind_speed_unit=ms``를 싣는다 (`TECH_SPEC §7.2`, #813).

    Open-Meteo의 **기본 단위는 km/h**다. 종전에는 이 파라미터를 보내지 않고 응답을
    그대로 ``wind_speed_ms``에 넣어 값이 **3.6배** 커졌다 — `SIMPLE_RULE`의 풍속
    계수는 「10 m/s당 약 5%」 전제라(`TECH_SPEC §8`), 실제 10 m/s에서 풍속항이
    `0.05`가 아니라 `0.18`이 됐다.

    ``/3.6``으로 나누지 않고 **요청에 단위를 싣는 이유**는, 나누는 쪽이 「기본값이
    계속 km/h다」라는 가정에 기대기 때문이다. 기본값이 바뀌면 조용히 이중 변환이 된다.
    """
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(200, json=MARINE_BODY)
        return httpx.Response(200, json=WIND_BODY)

    await provider_for(handler).fetch(35.1, 129.0, AT)

    wind_url = next(url for url in seen if str(url).startswith(WIND_ENDPOINT))
    assert wind_url.params["wind_speed_unit"] == "ms"


@pytest.mark.asyncio
async def test_unexpected_wind_unit_is_not_stored():
    """단위가 예상과 다르면 **풍속을 쓰지 않는다** (#813).

    요청에 단위를 실었어도 응답이 그 단위라는 보장은 없다. 이 결함은 조용했다 —
    값이 3.6배 커져도 화면은 멀쩡했고 전수 검토를 해야 드러났다.

    **틀린 값을 저장하는 것보다 쓰지 않는 편이 낫다.** 파고만 쓰거나
    ``weather_factor=1.0``으로 가는 길은 이미 있다(`#62` fallback 체인).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(200, json=MARINE_BODY)
        return httpx.Response(200, json=WIND_BODY_KMH)

    observation = await provider_for(handler).fetch(35.1, 129.0, AT)

    assert observation.wind_speed_ms is None, (
        f"km/h 응답이 m/s로 저장됐다: {observation.wind_speed_ms}"
    )
    assert observation.wind_direction_deg is None
    # 파고는 살아 있다 — 한쪽 문제가 전체를 죽이지 않는다.
    assert observation.wave_height_m == 2.5


@pytest.mark.asyncio
async def test_missing_unit_block_is_not_assumed_to_be_ms():
    """단위가 **적혀 있지 않으면** 참으로 보지 않는다 (#813).

    없는 것을 「기본값이겠지」로 읽는 것이 이 결함을 만든 사고방식이다.
    """
    body = {"hourly": WIND_BODY["hourly"]}  # `hourly_units` 없음

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(200, json=MARINE_BODY)
        return httpx.Response(200, json=body)

    observation = await provider_for(handler).fetch(35.1, 129.0, AT)

    assert observation.wind_speed_ms is None
