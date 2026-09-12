"""요청 안에서 같은 규제 파라미터를 다시 읽지 않는다 (`#989` ⑴ · `services/request_cache.py`).

선대 요약은 선박마다 `compute_ytd_cii`를 최대 네 번 부르고(올해 · 직전 2개 연도 · 최근 30일
창), 그 네 번이 각각 **규정연도 · 기준선 · 등급 경계 · 선박을 처음부터 다시 읽었다**. 200척에서
8,402 쿼리 · 10.7초가 나온 실측(`#772`)에서 같은 값을 다시 읽는 몫이 약 45%였다.

두 가지를 본다. **줄어드는가**(저장소 호출 횟수)와 **값이 같은가**(캐시를 끈 실행과 응답이
글자 그대로 같은가). 뒤가 없으면 앞은 의미가 없다 — 빨라졌는데 답이 달라지면 고친 것이 아니다.

캐시는 **켠 요청에서만** 돈다. 마지막 검사가 그 성질을 고정한다 — 고치는 경로가 자기가 방금
바꾼 값을 못 보는 일이 없어야 한다.

케이스: IT-CACHE-001 ~ IT-CACHE-004 (`TEST_PLAN §3.11`)
"""

from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.demo_seed import VESSEL_ID_BULK
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.services import fleet_summary, request_cache
from cii_platform.services import ytd_cii as ytd_module

YEAR = 2026


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


class _Counter:
    """저장소 호출을 세는 대역. 원래 함수를 그대로 부른다."""

    def __init__(self, target, name: str) -> None:
        self.calls: list[tuple] = []
        self._inner = getattr(target, name)

    async def __call__(self, session, *args, **kwargs):
        self.calls.append((args, tuple(sorted(kwargs.items()))))
        return await self._inner(session, *args, **kwargs)


def _install(monkeypatch: pytest.MonkeyPatch) -> dict[str, _Counter]:
    """``ytd_cii``·``fleet_summary``가 실제로 부르는 이름을 센다."""
    counters = {
        "regulation_year": _Counter(param_repo, "get_regulation_year"),
        "reference_lines": _Counter(param_repo, "list_reference_lines"),
        "rating_boundaries": _Counter(param_repo, "list_rating_boundaries"),
        "vessel": _Counter(vessel_repo, "get_by_id"),
    }
    monkeypatch.setattr(param_repo, "get_regulation_year", counters["regulation_year"])
    monkeypatch.setattr(param_repo, "list_reference_lines", counters["reference_lines"])
    monkeypatch.setattr(param_repo, "list_rating_boundaries", counters["rating_boundaries"])
    monkeypatch.setattr(vessel_repo, "get_by_id", counters["vessel"])
    return counters


async def test_fleet_summary_reads_each_parameter_once(session, monkeypatch):
    """IT-CACHE-001 — 같은 (연도 · 선종)을 두 번 읽지 않고, 선박은 목록 한 번으로 끝난다."""
    counters = _install(monkeypatch)

    await fleet_summary.get_fleet_summary(session, regulation_year=YEAR)

    for name in ("regulation_year", "reference_lines", "rating_boundaries"):
        calls = counters[name].calls
        assert calls, f"{name}을(를) 한 번도 읽지 않았다 — 검사가 헛돈다"
        assert len(calls) == len(set(calls)), f"{name}을(를) 같은 인자로 다시 읽었다: {calls}"

    # 선박은 목록(`list_all_active`)으로 이미 읽었다 — 개별 조회가 남아 있으면 안 된다.
    assert counters["vessel"].calls == []


async def test_the_cache_does_not_change_the_answer(session, monkeypatch, conn):
    """IT-CACHE-002 — 캐시를 끈 실행과 응답이 같다. 값이 달라지면 성능 개선이 아니라 결함이다."""
    with_cache = await fleet_summary.get_fleet_summary(session, regulation_year=YEAR)

    # 같은 요청을 캐시 없이 — `enable`을 아무 일도 하지 않게 바꾼다.
    monkeypatch.setattr(fleet_summary, "enable_request_cache", lambda _session: None)
    async with AsyncSession(bind=conn, expire_on_commit=False) as plain:
        without_cache = await fleet_summary.get_fleet_summary(plain, regulation_year=YEAR)
        assert not request_cache.is_enabled(plain)

    # `as_of`는 서버가 확정하는 시각이라 두 실행이 다르다 — 그 파생값만 빼고 비교한다.
    for body in (with_cache, without_cache):
        body.pop("as_of", None)
        body.get("summary", {}).pop("as_of", None)
    assert with_cache == without_cache


async def test_the_cache_is_opt_in(session):
    """IT-CACHE-003 — 켜지 않은 세션은 매번 읽는다. 고치는 경로가 방금 바꾼 값을 보게 한다."""
    reads = 0

    async def load():
        nonlocal reads
        reads += 1
        return "값"

    assert not request_cache.is_enabled(session)
    await request_cache.cached(session, ("k",), load)
    await request_cache.cached(session, ("k",), load)
    assert reads == 2

    request_cache.enable(session)
    await request_cache.cached(session, ("k",), load)
    await request_cache.cached(session, ("k",), load)
    assert reads == 3


async def test_a_failed_read_is_not_remembered(session):
    """IT-CACHE-004 — 실패를 기억하면 뒤쪽 호출이 이유를 모른 채 같은 실패를 받는다."""
    request_cache.enable(session)
    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("첫 번째는 실패")
        return "두 번째는 성공"

    with pytest.raises(RuntimeError):
        await request_cache.cached(session, ("k",), flaky)
    assert await request_cache.cached(session, ("k",), flaky) == "두 번째는 성공"


async def test_ytd_cii_alone_does_not_cache(session, monkeypatch):
    """IT-CACHE-003 — 단건 계산 경로는 캐시를 켜지 않는다. 켜는 것은 요청이 정한다."""
    counters = _install(monkeypatch)

    for _ in range(2):
        await ytd_module.compute_ytd_cii(
            session, vessel_id=UUID(VESSEL_ID_BULK), regulation_year=YEAR
        )

    assert not request_cache.is_enabled(session)
    assert len(counters["vessel"].calls) == 2
