"""공급자 호출 결과로 보는 챗봇 사용 가능 상태 (``API_SPEC §15.7`` · `#2289`).

설정(``provider.is_enabled``)만 보면 **공급자가 응답하지 않아도 「쓸 수 있음」**이 된다.
사용자는 질문마다 최대 30초를 기다린 뒤 같은 실패 문구를 받는다. 여기서는 **이미
일어난 호출의 결과**를 세어, 연속으로 실패하면 새 호출을 막는다.

## 값은 운영 정책이다

:data:`FAILURE_THRESHOLD` · :data:`BLOCK_SECONDS` · :data:`MAX_PROBE_INTERVAL_SECONDS`는
규제값도 공급자 보장값도 아니다(2026-10-08 · 10-09 결정). 일시 오류 한 번으로 기능을
숨기지 않으면서, 반복 장애 때 여러 사용자가 긴 대기를 되풀이하지 않게 하는 기준이다.

## 차단이 풀리는 조건은 시간이 아니다

:data:`BLOCK_SECONDS`가 지난 것은 **복구를 확인할 자격이 생긴 것**일 뿐 복구의 증거가
아니다. 그 뒤 :func:`start_probe_if_due`가 **사용자 질문도 선박 자료도 넣지 않은**
:data:`PROBE_MESSAGE` 한 건을 실제 키·모델 경로로 보내고, 정상 응답일 때만 차단을 푼다.
실패하면 다음 시험 시각을 뒤로 미룬다.

## 상태는 프로세스 메모리에 둔다

운영 이미지는 워커 하나로 돈다(``Dockerfile`` 운영 단계 주석). 요청 한도 카운터
(``api/rate_limit.py``)와 같은 자리다 — 재기동하면 차단이 풀리고, 워커를 늘리면 워커마다
따로 센다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cii_platform.llm.provider import LLMError, LLMResponse, LLMUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

    from cii_platform.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

#: 연속으로 이만큼 실패하면 새 호출을 막는다.
FAILURE_THRESHOLD = 2

#: 차단한 뒤 첫 시험 요청까지의 간격(초). 시험이 실패할 때마다 두 배로 늘린다.
BLOCK_SECONDS = 300.0

#: 시험 요청 간격의 상한(초).
MAX_PROBE_INTERVAL_SECONDS = 1800.0

#: 시험 요청 한 건의 시간 상한(초). 공급자 단일 호출 상한(``anthropic.TIMEOUT_SECONDS``)과
#: 같은 값이다 — 넘기면 실패로 센다. 상한이 없으면 응답 없는 시험이 다음 시험을 막는다.
PROBE_TIMEOUT_SECONDS = 30.0

#: 시험 요청의 본문. **사용자 질문 · 선박 자료 · 시스템 지시를 싣지 않는다** — 전송
#: 화이트리스트(``API_SPEC §15.3``)가 다룰 것이 없는 고정 문자열이다.
PROBE_MESSAGE = "연결 확인입니다. '확인'이라고만 답해 주세요."


@dataclass
class _State:
    failures: int = 0
    blocked: bool = False
    next_probe_at: float = 0.0
    interval: float = BLOCK_SECONDS
    probing: bool = False


_state = _State()
# 끝나지 않은 시험 작업을 붙들어 둔다 — 참조가 없으면 이벤트 루프가 도중에 거둘 수 있다.
_tasks: set[asyncio.Task[None]] = set()


def reset() -> None:
    """상태를 처음으로 되돌린다. 검사가 서로의 실패 횟수를 물려받지 않게 한다."""
    global _state
    _state = _State()


def is_blocked() -> bool:
    """연속 실패로 새 호출을 막고 있는가."""
    return _state.blocked


def record_success() -> None:
    """공급자 호출이 성공했다 — 연속 실패 수를 0으로 되돌린다."""
    _state.failures = 0


def record_failure(*, now: float | None = None) -> None:
    """공급자 호출이 실패했다. :data:`FAILURE_THRESHOLD`에 닿으면 차단한다."""
    _state.failures += 1
    if _state.blocked or _state.failures < FAILURE_THRESHOLD:
        return
    _state.blocked = True
    _state.interval = BLOCK_SECONDS
    _state.next_probe_at = (time.monotonic() if now is None else now) + BLOCK_SECONDS
    logger.warning("챗봇 공급자 연속 실패 %d회 — 새 호출을 막는다", _state.failures)


def probe_due(*, now: float | None = None) -> bool:
    """지금 시험 요청을 보낼 차례인가. 이미 보내는 중이면 아니다."""
    current = time.monotonic() if now is None else now
    return _state.blocked and not _state.probing and current >= _state.next_probe_at


async def run_probe(provider: LLMProvider, *, now: Callable[[], float] = time.monotonic) -> None:
    """시험 요청 한 건을 보내고 결과대로 차단을 풀거나 다음 시험을 미룬다.

    정상 응답은 **오류 없이 글자가 돌아온 것**이다. 빈 응답은 복구로 보지 않는다 —
    사용자 질문에서도 빈 답은 답이 아니다.
    """
    _state.probing = True
    recovered = False
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            response: LLMResponse = await provider.complete(
                messages=[{"role": "user", "content": PROBE_MESSAGE}], tools=None
            )
        recovered = bool(response.text.strip())
    except (LLMError, TimeoutError):
        pass
    except Exception:
        # 공급자 계층이 감싸지 못한 예외도 「복구되지 않음」이다. 그대로 올리면 다음 시험
        # 시각이 밀리지 않아, 상태 조회마다 시험이 다시 나간다.
        logger.exception("챗봇 공급자 시험 요청이 예상하지 못한 예외로 끝났다")
    finally:
        _state.probing = False

    if recovered:
        _state.blocked = False
        _state.failures = 0
        _state.interval = BLOCK_SECONDS
        logger.warning("챗봇 공급자 시험 요청 성공 — 차단을 푼다")
        return
    _state.interval = min(_state.interval * 2, MAX_PROBE_INTERVAL_SECONDS)
    _state.next_probe_at = now() + _state.interval
    logger.warning("챗봇 공급자 시험 요청 실패 — 다음 시험까지 %d초", int(_state.interval))


def start_probe_if_due(
    make_provider: Callable[[], LLMProvider], *, now: float | None = None
) -> bool:
    """시험할 차례면 **기다리지 않고** 백그라운드로 한 건을 시작한다.

    상태 조회(``GET /chat/status``)가 부른다. 조회 자체는 공급자를 기다리지 않고 확인된
    상태만 읽는다 — 시험 결과는 다음 조회에 반영된다. 보는 화면이 없으면 조회도 없어
    외부 호출이 생기지 않는다.

    :returns: 이번 호출이 시험을 시작했는가.
    """
    if not probe_due(now=now):
        return False
    # 공급자 생성과 작업 등록이 **끝난 뒤에** 「보내는 중」을 세운다. 먼저 세우면 둘 중
    # 하나가 실패했을 때 풀어 줄 곳이 없어, 재기동 전까지 시험이 다시 시작되지 않는다.
    task = asyncio.get_running_loop().create_task(run_probe(make_provider()))
    # 작업이 실제로 돌기 전에 두 번째 조회가 들어와도 한 건만 나가게 여기서 세운다.
    _state.probing = True
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


class TrackedProvider:
    """호출 결과를 세는 공급자 포장. 응답과 예외는 **그대로** 지나간다.

    취소(턴 시간 상한 · 연결 끊김)는 세지 않는다 — 공급자가 실패한 것인지 가릴 수 없다.
    :class:`LLMUnavailableError`도 세지 않는다. 그것은 설정이 없다는 뜻이고
    ``is_enabled``가 이미 「쓸 수 없음」으로 답한다.
    """

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    async def complete(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> LLMResponse:
        try:
            response = await self._inner.complete(messages=messages, tools=tools)
        except LLMUnavailableError:
            raise
        except LLMError:
            record_failure()
            raise
        record_success()
        return response
