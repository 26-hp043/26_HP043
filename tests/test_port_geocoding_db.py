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

케이스: IT-GEO-001 ~ IT-GEO-008 (`TEST_PLAN §3.12`)
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
            text("SELECT query, source, kind FROM port_geocode WHERE query = :q"),
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
            text("SELECT count(*) FROM port_geocode WHERE query = :q"),
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
