"""항만명 → 좌표 조회 (`API_SPEC §3.10` · `#768` · `PRD §15.1` MAY).

`#760`이 샘플 항만 43곳을 넣어 목록에 있는 항은 이미 좌표가 붙는다. 남은 것은 **목록 밖
항만**이고, 지금은 사용자가 좌표를 직접 찾아 넣어야 한다(`PRD §1 COR-5`가 그 상태를 결함으로
적었다).

## 사용 정책이 설계를 정한다

공개 Nominatim은 **초당 1회**, **User-Agent 필수**, **결과 캐시 필수**, **자동완성 금지**다.
그래서 여기서 보는 것은 속도가 아니라 **정책을 코드가 지키는가**이다.

1. 샘플 목록에 있으면 **외부를 부르지 않는다**
2. 한 번 물은 이름은 **캐시에서 답한다** — 정책이 요구하는 캐시의 실체
3. **항만이 아닌 결과는 버린다** — 「부산」은 도시이기도 하다
4. 조회가 실패해도 **계산을 막지 않는다** — 이유를 구분해 돌려준다

5. 제공자는 **프로세스에 하나**다 — 요청마다 새로 만들면 「초당 1회」 시각이 매번 0으로
   돌아가 상한이 한 번도 걸리지 않는다(`#1335`). 라우트 두 번이 한 인스턴스를 쓰는지,
   동시에 들어온 조회가 간격을 지키는지 **가짜 시계**로 본다(실제로 기다리지 않는다)

케이스: IT-GEO-001 ~ IT-GEO-011 (`TEST_PLAN §3.12`)
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.geocode.nominatim import (
    MIN_INTERVAL_SECONDS,
    USER_AGENT,
    GeocodeError,
    NominatimProvider,
)
from cii_platform.services.geocoding import (
    REASON_LOOKUP_FAILED,
    REASON_NO_PROVIDER,
    REASON_NOT_A_PORT,
    SOURCE_CACHE,
    SOURCE_LOOKUP,
    SOURCE_SAMPLE,
    lookup_port,
    normalize_query,
)

#: 샘플 목록에 없는 이름. 조회 경로를 타게 한다.
UNLISTED = "TEST PORT ALPHA"

_HARBOUR_ROW = {
    "display_name": "Test Harbour, Testland",
    "lat": "1.234567",
    "lon": "103.765432",
    "class": "waterway",
    "type": "harbour",
}
_CITY_ROW = {
    "display_name": "Test City, Testland",
    "lat": "35.0",
    "lon": "129.0",
    "class": "place",
    "type": "city",
}


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


class _FakeProvider:
    """외부를 부르지 않는 대역. **CI는 네트워크를 쓰지 않는다.**"""

    def __init__(self, result=None, error: bool = False) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    async def lookup(self, name: str):
        self.calls.append(name)
        if self.error:
            raise GeocodeError("boom")
        return self.result


def _provider_from_rows(rows) -> NominatimProvider:
    """실 어댑터에 가짜 HTTP를 물린다 — 필터·헤더·간격을 그대로 통과시킨다."""
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["last"] = request
        return httpx.Response(200, json=rows)

    provider = NominatimProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    provider.seen = seen  # type: ignore[attr-defined]
    return provider


async def test_sample_list_answers_without_calling_out(session):
    """IT-GEO-001 — 목록에 있으면 **외부를 부르지 않는다**(정책상 호출은 아낄수록 좋다)."""
    provider = _FakeProvider(result=None)

    found, reason = await lookup_port(session, name="BUSAN", provider=provider)

    assert reason is None
    assert found is not None
    assert found.source == SOURCE_SAMPLE
    assert provider.calls == []


async def test_korean_name_and_spacing_hit_the_same_entry(session):
    """IT-GEO-002 — 한글 이름과 공백·대소문자 차이가 같은 항을 가리킨다."""
    provider = _FakeProvider(result=None)

    found, _ = await lookup_port(session, name="  부산  ", provider=provider)

    assert found is not None
    assert found.name == "BUSAN"
    assert provider.calls == []
    assert normalize_query("busan  port") == "BUSAN PORT"


async def test_lookup_is_cached_and_asked_only_once(session):
    """IT-GEO-003 — 같은 이름을 두 번 묻지 않는다. **정책이 캐시를 요구한다.**"""
    provider = _provider_from_rows([_HARBOUR_ROW])

    first, _ = await lookup_port(session, name=UNLISTED, provider=provider)
    second, _ = await lookup_port(session, name=UNLISTED.lower(), provider=provider)

    assert first is not None and first.source == SOURCE_LOOKUP
    assert second is not None and second.source == SOURCE_CACHE
    assert second.lat == Decimal("1.234567")

    rows = (
        await session.execute(
            text('SELECT "query", source, kind FROM port_geocode WHERE "query" = :q'),
            {"q": normalize_query(UNLISTED)},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].source == "nominatim"
    assert rows[0].kind == "harbour"


async def test_a_city_is_not_a_port(session):
    """IT-GEO-004 — 항만이 아닌 결과는 버린다. 도시 좌표를 항만으로 저장하지 않는다."""
    provider = _provider_from_rows([_CITY_ROW])

    found, reason = await lookup_port(session, name=UNLISTED, provider=provider)

    assert found is None
    assert reason == REASON_NOT_A_PORT
    count = (
        await session.execute(
            text('SELECT count(*) FROM port_geocode WHERE "query" = :q'),
            {"q": normalize_query(UNLISTED)},
        )
    ).scalar_one()
    assert count == 0


async def test_failure_is_told_apart_from_not_found(session):
    """IT-GEO-005 — 「바깥이 죽었다」와 「그런 항만이 없다」는 다른 답이다."""
    broken = _FakeProvider(error=True)

    found, reason = await lookup_port(session, name=UNLISTED, provider=broken)

    assert found is None
    assert reason == REASON_LOOKUP_FAILED


async def test_without_a_provider_it_never_goes_out(session):
    """IT-GEO-006 — 제공자가 없으면 샘플·캐시까지만 본다(오프라인·테스트 환경)."""
    found, reason = await lookup_port(session, name=UNLISTED)

    assert found is None
    assert reason == REASON_NO_PROVIDER


async def test_the_request_identifies_the_application(session):
    """IT-GEO-007 — 정책이 요구하는 User-Agent를 싣는다(라이브러리 기본값은 차단 대상)."""
    provider = _provider_from_rows([_HARBOUR_ROW])

    await lookup_port(session, name=UNLISTED, provider=provider)

    request = provider.seen["last"]  # type: ignore[attr-defined]
    assert request.headers["user-agent"] == USER_AGENT
    assert "BlueLog" in USER_AGENT
    assert request.url.params["q"] == UNLISTED


@pytest.mark.asyncio
async def test_calls_are_spaced_by_the_policy_interval():
    """IT-GEO-008 — 초당 1회를 **코드가 강제**한다. 문서에만 적으면 지켜지지 않는다."""
    import time

    provider = _provider_from_rows([_HARBOUR_ROW])

    started = time.monotonic()
    await provider.lookup("A")
    await provider.lookup("B")
    elapsed = time.monotonic() - started

    assert elapsed >= MIN_INTERVAL_SECONDS


# ── 제공자는 프로세스에 하나다 (`#1335`) ──────────────────────────────────────────
#
# 「초당 1회」는 어댑터 **인스턴스 안의** 락·직전 호출 시각으로 강제된다. 라우트가 요청마다
# 새 인스턴스를 만들면 시각이 매번 0으로 돌아가 상한이 한 번도 걸리지 않는다 — 감사에서
# 요청별 5회가 0.001초 안에 나갔다. 아래는 실제로 1초를 기다리지 않고 **가짜 시계**로 본다.


class _FakeClock:
    """가짜 시계. ``sleep``이 시각을 앞당길 뿐 기다리지 않는다 — 검사가 1초씩 늘지 않는다."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        # 다른 태스크에 차례를 넘긴다 — 동시 요청 검사가 실제 경합을 거치게 한다.
        await asyncio.sleep(0)


def _provider_with_clock(rows, clock: _FakeClock) -> tuple[NominatimProvider, list[float]]:
    """가짜 시계 + 가짜 HTTP. **바깥으로 나간 시각**을 기록한다 — 간격은 그 차이로 본다."""
    sent_at: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_at.append(clock.now)
        return httpx.Response(200, json=rows)

    provider = NominatimProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=clock,
        sleep=clock.sleep,
    )
    return provider, sent_at


#: 라우트 검사가 쓰는 이름의 접두. 앱 엔진으로 커밋되므로 끝나고 이 접두로 지운다.
_ROUTE_PREFIX = "TEST PORT ROUTE"


@pytest_asyncio.fixture
async def shared_provider(migrated_db, app_fresh_engine):
    """앱의 **공유 제공자**를 가짜 시계·가짜 HTTP로 바꾼다.

    `conftest._fresh_rate_limiter`와 같은 수법 — 라우트가 요청마다 ``app.state``를 다시
    읽으므로 교체가 그대로 든다. 끝나면 되돌리고, 이 파일이 앱 엔진으로 심은 행만 지운다.
    """
    from cii_platform.db.session import get_sessionmaker

    async def clear_rows() -> None:
        async with get_sessionmaker()() as db:
            await db.execute(
                text('DELETE FROM port_geocode WHERE "query" LIKE :p'), {"p": f"{_ROUTE_PREFIX}%"}
            )
            await db.commit()

    # 앞선 실행이 정리 전에 죽었으면 캐시가 먼저 답해 조회 경로가 검사되지 않는다.
    await clear_rows()
    clock = _FakeClock()
    provider, sent_at = _provider_with_clock([_HARBOUR_ROW], clock)
    previous = getattr(app.state, "geocode_provider", None)
    app.state.geocode_provider = provider
    try:
        yield provider, clock, sent_at
    finally:
        app.state.geocode_provider = previous
        await clear_rows()


def _lookup(client: TestClient, name: str) -> httpx.Response:
    return client.get(f"{API_V1_PREFIX}/ports/lookup", params={"name": name})


async def test_the_route_shares_one_provider_across_requests(shared_provider):
    """IT-GEO-009 — 라우트 두 번이 **한 제공자**를 쓴다. 두 번째 외부 호출이 1초 뒤에 나간다.

    요청마다 새 인스턴스를 만들면 ``app.state``의 가짜 제공자는 쓰이지도 않고, 두 번째
    호출은 기다리지 않는다 — 그 상태가 `#1335`다.
    """
    provider, clock, sent_at = shared_provider

    with TestClient(app, base_url="https://testserver") as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        first = _lookup(client, f"{_ROUTE_PREFIX} A")
        second = _lookup(client, f"{_ROUTE_PREFIX} B")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["source"] == SOURCE_LOOKUP
    assert second.json()["data"]["source"] == SOURCE_LOOKUP
    assert app.state.geocode_provider is provider
    assert len(sent_at) == 2
    assert sent_at[1] - sent_at[0] >= MIN_INTERVAL_SECONDS
    assert clock.sleeps == pytest.approx([MIN_INTERVAL_SECONDS])


async def test_concurrent_lookups_are_spaced_by_the_interval():
    """IT-GEO-010 — **동시에** 들어온 세 조회도 바깥으로는 1초 간격으로 나간다.

    락 없이 각자 「1초 지났다」고 재면 셋이 같은 시각에 나간다. 가짜 시계라 실제로는
    기다리지 않는다.
    """
    clock = _FakeClock()
    provider, sent_at = _provider_with_clock([_HARBOUR_ROW], clock)

    results = await asyncio.gather(provider.lookup("A"), provider.lookup("B"), provider.lookup("C"))

    assert all(result is not None for result in results)
    assert len(sent_at) == 3
    gaps = [later - earlier for earlier, later in zip(sent_at, sent_at[1:], strict=False)]
    assert all(gap >= MIN_INTERVAL_SECONDS for gap in gaps), gaps
    assert clock.sleeps == pytest.approx([MIN_INTERVAL_SECONDS, MIN_INTERVAL_SECONDS])


async def test_the_route_answers_from_cache_without_a_second_call(shared_provider):
    """IT-GEO-011 — 같은 이름을 두 번 물으면 두 번째는 **캐시**다. 바깥으로 한 번만 나간다."""
    _provider, clock, sent_at = shared_provider

    with TestClient(app, base_url="https://testserver") as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        first = _lookup(client, f"{_ROUTE_PREFIX} CACHE")
        second = _lookup(client, f"{_ROUTE_PREFIX} CACHE")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["source"] == SOURCE_LOOKUP
    assert second.json()["data"]["source"] == SOURCE_CACHE
    assert len(sent_at) == 1
    assert clock.sleeps == []
