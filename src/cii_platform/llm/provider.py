"""LLM 공급자 계약과 가짜 구현 (`#120`).

## 왜 추상화부터 두나

**CI가 외부 모델을 부르면 신뢰할 수 없게 된다** — ⑴ PR마다 과금되고 ⑵ 같은 입력에
다른 출력이 나와(비결정성) 검사가 불규칙하게 깨지며 ⑶ 키가 CI에 들어가야 한다.

그래서 인터페이스를 두고 검사에는 :class:`FakeProvider`를 끼운다. 그러면
**오케스트레이션 전부를 결정적으로 검사**할 수 있다 — 「자연어 X가 들어오면 도구 Y가
인자 Z로 불리는가」, 「도구 응답으로 최종 응답을 만드는 경로가 맞는가」, 「수학 가드가
불일치를 잡는가」.

**못 잡는 것은 「실제 모델이 도구를 제대로 고르는가」**이고, 그것은 CI의 일이 아니라
**릴리스 게이트의 일**이다(수동 대조 체크리스트).

## 비용 가드 — 넷이 함께여야 성립한다

``PRD §16.1``이 쿼리당 `$0.05`를 정하는데 **강제 방법이 없어 목표로만** 남아 있었다.
여기 상수 셋이 **한 쿼리**를 막고, 요청 한도(``API_SPEC §13.2`` `chat` 버킷)가
**시간당 총액**을 막는다.

⚠️ :data:`MAX_TOOL_CALLS_PER_TURN`이 가장 중요하다 — **비용 폭주의 실제 경로는
모델이 도구를 잘못 골라 왕복을 반복하는 것**이다. 토큰 상한만 걸면 한 번의 응답은
작아도 왕복 횟수가 곱해진다.

## 키가 없으면 챗봇만 죽는다

``PRD §16.2`` 장애 격리와 같은 방향이다. ``SIGNUP_*``처럼 앱 기동을 막지 않는다 —
챗봇은 실험 기능(MAY)이고, 그것 때문에 계산·보고가 못 뜨면 격리가 아니다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

#: 응답 토큰 상한. 한 응답의 출력 비용을 산수로 고정한다 (`PRD §16.1` 가드 1).
MAX_OUTPUT_TOKENS = 1024

#: 한 턴에서 허용하는 도구 호출 횟수 (`PRD §16.1` 가드 2).
#:
#: ⚠️ **비용 폭주의 실제 경로다.** 모델이 도구를 잘못 골라 왕복을 반복하면 토큰
#: 상한이 걸려 있어도 총액이 횟수만큼 곱해진다. 3회면 「선박을 찾고 → 계산하고 →
#: 비교한다」가 한 턴에 들어간다.
MAX_TOOL_CALLS_PER_TURN = 3

#: 모델에 실어 보내는 대화 이력의 턴 수 (`PRD §16.1` 가드 3).
#:
#: 대화가 길어질수록 입력 토큰이 누적된다. 6턴이면 「묻고 답하고」 세 번이다.
MAX_HISTORY_TURNS = 6

#: 공급자 이름 — `Q4` 결정.
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_FAKE = "fake"

#: 키를 읽는 환경변수. **커밋 금지** — 서버 `.env`에 둔다.
#:
#: ⚠️ 아래 :func:`api_key`가 이 상수를 쓰지 않고 **리터럴로 읽는다.**
#: ``tests/test_compose_env_wiring.py``가 소스에서 ``environ.get("리터럴")``을 훑어
#: `.env.example`과 대조하는데, **상수를 넣으면 그 가드가 이 변수를 못 본다** —
#: 본보기에 없는 변수가 조용히 생긴다. 이 상수는 **문서용**이며 검사가 둘의 일치를
#: 확인한다.
API_KEY_ENV = "LLM_API_KEY"

#: `Q4` 결정 — Claude Haiku 4.5.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class LLMError(RuntimeError):
    """LLM 호출 실패. **숨기지 않고 그대로 올린다** — ``weather``·``ais``와 같은 규약."""


class LLMUnavailableError(LLMError):
    """키가 없어 챗봇을 쓸 수 없다.

    ⚠️ **앱 기동을 막지 않는다.** 이 오류는 챗봇 요청에서만 난다 (``PRD §16.2``).
    """


@dataclass(frozen=True)
class ToolCall:
    """모델이 고른 도구 한 번.

    :param name: 도구 이름. **인자는 감사 로그에 해시로만 남는다** (`Q19`).
    :param id: 공급자가 붙인 호출 식별자.

    ## ``id``가 왜 필요한가

    Anthropic Messages API는 도구 왕복을 **짝**으로 요구한다 — 모델의 ``tool_use``
    블록을 그대로 되돌려 보내고, 같은 ``tool_use_id``를 단 ``tool_result``로 답해야
    한다. 그 짝을 맞추는 것이 이 값이다.

    공급자에 따라 없을 수 있어 기본값을 둔다(``FakeProvider``가 그렇다).
    """

    name: str
    arguments: dict[str, object] = field(default_factory=dict)
    id: str = ""


@dataclass(frozen=True)
class LLMResponse:
    """한 번의 모델 호출 결과.

    ``tool_calls``가 비어 있으면 최종 응답이고, 있으면 도구를 부른 뒤 다시 물어야 한다.
    """

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


class LLMProvider(Protocol):
    """공급자. 구현체는 **바깥과 말하는 것만** 한다.

    도구 선택·응답 조립은 ``services``가 맡는다 — 그래야 공급자를 바꿔도
    오케스트레이션이 그대로 남는다(`Q4` 모델 교체 용이성).
    """

    async def complete(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> LLMResponse:
        """대화를 넘기고 응답 하나를 받는다.

        :param messages: ``{"role": ..., "content": ...}`` 목록. ``content``는
            **문자열이거나 블록 목록**이다 — 도구 왕복이 블록을 요구한다
            (:class:`ToolCall` 참조). **호출부가 이미 화이트리스트를 통과시킨 것**
            이어야 한다 — 이 계층은 필터하지 않는다.
        """
        ...


class FakeProvider:
    """검사용 결정적 공급자 (`Q6` ⓐ).

    미리 정한 응답을 **순서대로** 돌려준다. 무엇을 받았는지 남겨 두어, 검사가
    「화이트리스트를 지나온 것만 넘어왔는가」를 확인할 수 있다.

    **바깥으로 나가지 않는다.** CI에서 이것만 쓰므로 과금도 비결정성도 없다.
    """

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[list[dict[str, object]]] = []

    async def complete(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        if not self._responses:
            return LLMResponse(text="")
        return self._responses.pop(0)


def api_key() -> str | None:
    """설정된 키. 없으면 ``None``."""
    # 리터럴로 읽는다 — 위 `API_KEY_ENV` 주석 참조.
    value = os.environ.get("LLM_API_KEY", "").strip()
    return value or None


def is_enabled() -> bool:
    """챗봇을 쓸 수 있는가.

    **앱 기동 판정에 쓰지 않는다** — 챗봇 요청 처리에서만 본다 (``PRD §16.2``).
    """
    return api_key() is not None
