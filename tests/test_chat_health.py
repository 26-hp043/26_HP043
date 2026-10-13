"""공급자 호출 결과로 보는 챗봇 사용 가능 상태 (``API_SPEC §15.7`` · `#2289`).

DB 없이 돈다 — 상태 관리(``llm/health.py``)만 본다. HTTP에서의 동작은
``test_chat_api_db.py``가 본다.
"""

from __future__ import annotations

import asyncio

import pytest

from cii_platform.llm import health
from cii_platform.llm.provider import (
    FakeProvider,
    LLMError,
    LLMResponse,
    LLMUnavailableError,
)


@pytest.fixture(autouse=True)
def _fresh_state():
    health.reset()
    yield
    health.reset()


class _Failing:
    """항상 실패하는 공급자."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self._error = error or LLMError("실패")

    async def complete(self, *, messages, tools=None) -> LLMResponse:
        self.calls += 1
        raise self._error


def test_one_failure_does_not_block() -> None:
    """일시 오류 한 번으로 모든 사용자의 기능을 숨기지 않는다."""
    health.record_failure(now=0.0)
    assert not health.is_blocked()


def test_consecutive_failures_block_at_the_threshold() -> None:
    for _ in range(health.FAILURE_THRESHOLD):
        health.record_failure(now=0.0)
    assert health.is_blocked()


def test_a_success_between_failures_resets_the_count() -> None:
    """「연속」이다 — 사이에 성공이 끼면 다시 처음부터 센다."""
    for _ in range(health.FAILURE_THRESHOLD - 1):
        health.record_failure(now=0.0)
    health.record_success()
    for _ in range(health.FAILURE_THRESHOLD - 1):
        health.record_failure(now=0.0)
    assert not health.is_blocked()


def test_time_alone_never_unblocks() -> None:
    """차단 시간이 지난 것은 시험할 자격이지 복구의 증거가 아니다."""
    for _ in range(health.FAILURE_THRESHOLD):
        health.record_failure(now=0.0)
    assert not health.probe_due(now=health.BLOCK_SECONDS - 1)
    assert health.probe_due(now=health.BLOCK_SECONDS)
    assert health.is_blocked()


async def test_tracked_provider_passes_results_through_and_counts() -> None:
    ok = health.TrackedProvider(FakeProvider([LLMResponse(text="답")]))
    assert (await ok.complete(messages=[])).text == "답"

    failing = health.TrackedProvider(_Failing())
    for _ in range(health.FAILURE_THRESHOLD):
        with pytest.raises(LLMError):
            await failing.complete(messages=[])
    assert health.is_blocked()


async def test_missing_configuration_is_not_counted_as_a_provider_failure() -> None:
    """설정 없음은 ``is_enabled``가 답할 일이다 — 차단으로 겹쳐 세지 않는다."""
    tracked = health.TrackedProvider(_Failing(LLMUnavailableError("키 없음")))
    for _ in range(health.FAILURE_THRESHOLD + 1):
        with pytest.raises(LLMUnavailableError):
            await tracked.complete(messages=[])
    assert not health.is_blocked()


async def test_cancellation_is_not_counted() -> None:
    """턴 시간 상한으로 끊긴 호출은 공급자 실패인지 가릴 수 없다."""

    class _Hanging:
        async def complete(self, *, messages, tools=None) -> LLMResponse:
            await asyncio.sleep(60)
            return LLMResponse(text="")

    tracked = health.TrackedProvider(_Hanging())
    for _ in range(health.FAILURE_THRESHOLD + 1):
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await tracked.complete(messages=[])
    assert not health.is_blocked()


def _block() -> None:
    for _ in range(health.FAILURE_THRESHOLD):
        health.record_failure(now=0.0)


async def test_a_successful_probe_unblocks_and_carries_no_user_data() -> None:
    _block()
    provider = FakeProvider([LLMResponse(text="확인")])
    await health.run_probe(provider, now=lambda: health.BLOCK_SECONDS)
    assert not health.is_blocked()
    # 시험 요청은 고정 문자열 한 건이다 — 시스템 지시도 대화 이력도 싣지 않는다.
    assert provider.calls == [[{"role": "user", "content": health.PROBE_MESSAGE}]]


async def test_after_recovery_it_takes_the_full_threshold_to_block_again() -> None:
    """풀린 뒤에는 처음부터 다시 센다 — 실패 한 번으로 되막히지 않는다."""
    _block()
    await health.run_probe(FakeProvider([LLMResponse(text="확인")]), now=lambda: 0.0)
    for _ in range(health.FAILURE_THRESHOLD - 1):
        health.record_failure(now=0.0)
    assert not health.is_blocked()
    health.record_failure(now=0.0)
    assert health.is_blocked()
    # 다시 막힌 뒤의 첫 시험 간격도 처음 값이다 — 앞선 차단의 늘어난 간격을 물려받지 않는다.
    assert health.probe_due(now=health.BLOCK_SECONDS)


async def test_an_unexpected_probe_error_is_a_failed_probe_not_a_stuck_one() -> None:
    """공급자 계층이 감싸지 못한 예외에도 다음 시험이 밀리고, 다시 시작할 수 있다."""
    _block()
    await health.run_probe(_Failing(TypeError("형식")), now=lambda: health.BLOCK_SECONDS)
    assert health.is_blocked()
    assert not health.probe_due(now=health.BLOCK_SECONDS + health.BLOCK_SECONDS * 2 - 1)
    assert health.probe_due(now=health.BLOCK_SECONDS + health.BLOCK_SECONDS * 2)


async def test_a_probe_that_never_answers_is_cut_off_and_counted_as_failed(monkeypatch) -> None:
    class _Hanging:
        async def complete(self, *, messages, tools=None) -> LLMResponse:
            await asyncio.sleep(60)
            return LLMResponse(text="확인")

    _block()
    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.01)
    await health.run_probe(_Hanging(), now=lambda: 0.0)
    assert health.is_blocked()
    assert not health.probe_due(now=health.BLOCK_SECONDS * 2 - 1)
    assert health.probe_due(now=health.BLOCK_SECONDS * 2)


async def test_a_provider_that_cannot_be_built_does_not_stop_later_probes() -> None:
    """시험 공급자 생성이 실패해도 「보내는 중」이 남지 않는다 — 다음 조회가 다시 시도한다."""
    _block()

    def _broken() -> FakeProvider:
        raise RuntimeError("설정 오류")

    with pytest.raises(RuntimeError):
        health.start_probe_if_due(_broken, now=health.BLOCK_SECONDS)
    provider = FakeProvider([LLMResponse(text="확인")])
    assert health.start_probe_if_due(lambda: provider, now=health.BLOCK_SECONDS) is True
    await asyncio.gather(*health._tasks)
    assert not health.is_blocked()


async def test_a_failed_probe_keeps_the_block_and_pushes_the_next_probe_back() -> None:
    _block()
    failing = _Failing()
    await health.run_probe(failing, now=lambda: health.BLOCK_SECONDS)
    assert health.is_blocked()
    first_gap = health.BLOCK_SECONDS * 2
    assert not health.probe_due(now=health.BLOCK_SECONDS + first_gap - 1)
    assert health.probe_due(now=health.BLOCK_SECONDS + first_gap)


async def test_probe_interval_stops_growing_at_the_cap() -> None:
    _block()
    failing = _Failing()
    clock = 0.0
    for _ in range(10):
        await health.run_probe(failing, now=lambda: clock)
    assert not health.probe_due(now=clock + health.MAX_PROBE_INTERVAL_SECONDS - 1)
    assert health.probe_due(now=clock + health.MAX_PROBE_INTERVAL_SECONDS)


async def test_an_empty_probe_answer_is_not_a_recovery() -> None:
    _block()
    await health.run_probe(FakeProvider([LLMResponse(text="  ")]), now=lambda: 0.0)
    assert health.is_blocked()


async def test_only_one_probe_starts_however_many_status_calls_arrive() -> None:
    """시험할 차례에 조회가 몰려도 외부 호출은 한 건이다."""
    _block()
    provider = FakeProvider([LLMResponse(text="확인")])
    started = [
        health.start_probe_if_due(lambda: provider, now=health.BLOCK_SECONDS) for _ in range(5)
    ]
    assert started == [True, False, False, False, False]
    await asyncio.gather(*health._tasks)
    assert len(provider.calls) == 1
    assert not health.is_blocked()


def test_no_probe_starts_while_not_blocked_or_before_it_is_due() -> None:
    def _never() -> FakeProvider:
        raise AssertionError("시험 공급자를 만들면 안 된다")

    assert health.start_probe_if_due(_never) is False
    _block()
    assert health.start_probe_if_due(_never, now=health.BLOCK_SECONDS - 1) is False
