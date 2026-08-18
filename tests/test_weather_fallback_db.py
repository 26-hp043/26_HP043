"""기상 fallback 체인 (PRD §11.6 · TECH_SPEC §7.3, #62).

**바깥 서비스가 죽어도 우리 계산은 돌아야 한다.** 기상은 보정이지 계산의 전제가
아니므로, 조회 실패가 곧 계산 실패가 되면 「Open-Meteo가 내려가면 CII도 못 낸다」는
상태가 된다.

`PRD §11.6`이 정한 네 칸을 그대로 잠근다.

====================================  ==========================================
 최신 조회 성공                         최신 값 사용
 실패 + 6시간 이내 캐시                  캐시 사용
 실패 + 6~24시간 캐시                   계산 허용 + ``WEATHER_STALE``
 실패 + 캐시 없음 / 24시간 초과          보정 없이 계산 + ``WEATHER_NONE_FALLBACK``
====================================  ==========================================

**「보정하지 않았다」를 조용히 넘기지 않는 것**이 이 파일의 요점이다. 값은 언제나
나오므로, 경고가 없으면 사용자는 보정된 값으로 읽는다.

케이스 (`TEST_PLAN §14.5`):
    IT-WX-001 · IT-WX-002 · IT-WX-003 · UT-WX-004
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import weather as weather_repo
from cii_platform.services.weather import (
    MODEL_NONE,
    MODEL_SIMPLE_RULE,
    MODEL_TOWNSIN_KWON,
    NEUTRAL_FACTOR,
    WARNING_CB_ESTIMATED,
    WARNING_EXPERIMENTAL_MODEL,
    WARNING_WEATHER_NONE_FALLBACK,
    WARNING_WEATHER_STALE,
    resolve_with_fallback,
    round_to_grid,
)
from cii_platform.weather.open_meteo import MARINE_ENDPOINT, OpenMeteoProvider

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
LAT, LON = 35.12, 129.04

MARINE_BODY = {
    "hourly": {
        "time": ["2026-08-18T12:00"],
        "wave_height": [2.0],
        "wave_direction": [0.0],
        "wave_period": [7.0],
    }
}
WIND_BODY = {
    "hourly": {"time": ["2026-08-18T12:00"], "wind_speed_10m": [8.0], "wind_direction_10m": [90.0]}
}


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


def working_provider() -> OpenMeteoProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(MARINE_ENDPOINT):
            return httpx.Response(200, json=MARINE_BODY)
        return httpx.Response(200, json=WIND_BODY)

    return OpenMeteoProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def dead_provider() -> OpenMeteoProvider:
    """조회가 통째로 실패하는 상황 — 타임아웃."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    return OpenMeteoProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def _seed_cache(session, *, age_hours: float, wave_height: str = "3.0") -> None:
    await weather_repo.insert_snapshot(
        session,
        lat=Decimal(str(LAT)),
        lon=Decimal(str(LON)),
        lat_rounded=round_to_grid(LAT),
        lon_rounded=round_to_grid(LON),
        fetched_at=NOW - timedelta(hours=age_hours),
        wave_height_m=Decimal(wave_height),
        wave_direction_deg=Decimal("0"),
        wave_period_s=Decimal("7"),
        wind_speed_ms=Decimal("8.0"),
        wind_direction_deg=Decimal("90"),
        source="sample",
    )


async def _resolve(session, **over):
    kwargs = {
        "weather_model": MODEL_SIMPLE_RULE,
        "lat": LAT,
        "lon": LON,
        "ship_type": "BULK_CARRIER",
        "at": NOW,
        "provider": working_provider(),
    }
    kwargs.update(over)
    return await resolve_with_fallback(session, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# IT-WX-001 · 정상 조회
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_fetch_applies_the_factor_without_warnings(session):
    """IT-WX-001 — 조회가 되면 경고 없이 보정한다."""
    result = await _resolve(session)

    assert result.factor > NEUTRAL_FACTOR
    assert result.model_used == MODEL_SIMPLE_RULE
    assert result.warnings == ()
    assert result.synced_at is not None


@pytest.mark.asyncio
async def test_live_fetch_is_stored_as_evidence(session):
    """조회한 값은 스냅샷으로 남는다 — 계산 근거를 나중에 물을 수 있어야 한다."""
    result = await _resolve(session)

    assert result.snapshot_id is not None


# ─────────────────────────────────────────────────────────────────────────────
# IT-WX-002 · 실패 + 캐시
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_cache_is_used_without_the_stale_warning(session):
    """6시간 이내 캐시는 「오래됐다」가 아니다.

    `API_SPEC §1.6`이 `WEATHER_STALE`의 조건을 **6~24시간**으로, 문구를 「오래된
    기상 데이터를 사용 중입니다」로 확정했다 — 3시간 전 값에 그 문구를 붙이면
    **틀린 말**이 된다.
    """
    await _seed_cache(session, age_hours=3)

    result = await _resolve(session, provider=dead_provider())

    assert result.model_used == MODEL_SIMPLE_RULE
    assert result.factor > NEUTRAL_FACTOR
    assert WARNING_WEATHER_STALE not in result.warnings


@pytest.mark.asyncio
async def test_stale_cache_is_used_with_a_warning(session):
    """IT-WX-002 — 6~24시간 캐시는 **쓰되 알린다**.

    쓰지 않으면 보정이 사라지고, 알리지 않으면 사용자가 최신 기상으로 읽는다.
    """
    await _seed_cache(session, age_hours=10)

    result = await _resolve(session, provider=dead_provider())

    assert result.model_used == MODEL_SIMPLE_RULE
    assert WARNING_WEATHER_STALE in result.warnings


@pytest.mark.asyncio
async def test_cache_older_than_a_day_is_not_used(session):
    """24시간을 넘긴 값으로 오늘 항해를 보정하면 **보정이 아니라 잡음**이다."""
    await _seed_cache(session, age_hours=30)

    result = await _resolve(session, provider=dead_provider())

    assert result.model_used == MODEL_NONE
    assert result.factor == NEUTRAL_FACTOR
    assert WARNING_WEATHER_NONE_FALLBACK in result.warnings


# ─────────────────────────────────────────────────────────────────────────────
# IT-WX-003 · 실패 + 캐시 없음
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_cache_falls_back_to_no_correction(session):
    """IT-WX-003 — **계산은 계속된다.** 바깥 서비스가 죽어도 CII는 나와야 한다."""
    result = await _resolve(session, provider=dead_provider())

    assert result.factor == NEUTRAL_FACTOR
    assert result.model_used == MODEL_NONE
    assert WARNING_WEATHER_NONE_FALLBACK in result.warnings


@pytest.mark.asyncio
async def test_missing_coordinates_still_warn(session):
    """좌표가 없어 조회조차 못 한 경우도 **알린다.**

    사용자 입장에서는 「모델을 골랐는데 적용되지 않은」 것이며, 조용히 넘어가면
    결과를 보정된 값으로 읽는다. 기능①(`API_SPEC §4.1`)이 위치를 받지 않으므로
    실제로 자주 지나는 경로다.
    """
    result = await _resolve(session, lat=None, lon=None, provider=None)

    assert result.model_used == MODEL_NONE
    assert WARNING_WEATHER_NONE_FALLBACK in result.warnings


@pytest.mark.asyncio
async def test_none_model_is_not_a_fallback(session):
    """요청이 `NONE`이면 경고가 없다 — 보정하지 않기로 한 것이지 실패가 아니다."""
    result = await _resolve(session, weather_model=MODEL_NONE)

    assert result.warnings == ()
    assert result.factor == NEUTRAL_FACTOR


# ─────────────────────────────────────────────────────────────────────────────
# UT-WX-004 · 실험 모델 배지
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_townsin_kwon_is_marked_experimental(session):
    """UT-WX-004 — `PRD §11.4.2`가 「실험 모델 배지 표시」를 요구한다.

    경험식이 ±20% 오차를 갖는다는 사실이 결과에 남지 않으면, 사용자는 그 값을
    다른 계산과 같은 신뢰도로 읽는다.
    """
    result = await _resolve(session, weather_model=MODEL_TOWNSIN_KWON)

    assert WARNING_EXPERIMENTAL_MODEL in result.warnings


@pytest.mark.asyncio
async def test_default_block_coefficient_is_disclosed(session):
    """CB를 모르면 선종 기본값을 쓰고 **그 사실을 알린다** (`CB_ESTIMATED`)."""
    result = await _resolve(session, weather_model=MODEL_TOWNSIN_KWON)

    assert WARNING_CB_ESTIMATED in result.warnings


@pytest.mark.asyncio
async def test_given_block_coefficient_is_not_reported_as_estimated(session):
    """선박 제원에서 온 CB는 추정값이 아니다."""
    result = await _resolve(
        session, weather_model=MODEL_TOWNSIN_KWON, block_coefficient=Decimal("0.80")
    )

    assert WARNING_CB_ESTIMATED not in result.warnings
    assert WARNING_EXPERIMENTAL_MODEL in result.warnings


@pytest.mark.asyncio
async def test_simple_rule_is_not_marked_experimental(session):
    """배지는 경험식(`TOWNSIN_KWON_ALPHA`)에만 붙는다 (`API_SPEC §1.6` 조건)."""
    result = await _resolve(session, weather_model=MODEL_SIMPLE_RULE)

    assert WARNING_EXPERIMENTAL_MODEL not in result.warnings
