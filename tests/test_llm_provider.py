"""Anthropic 공급자의 메시지 변환 (`#121` · IT-CHAT-034~039).

**바깥과 말하지 않는다** — 여기서 보는 것은 요청 본문을 만드는 규칙이다. 이 규칙이
틀리면 400이 나는데, 그 실패는 **운영에서만** 드러난다(오케스트레이션 검사는
``FakeProvider``를 쓰므로 지나간다). 그래서 따로 잠근다.
"""

from __future__ import annotations

import httpx
import pytest

from cii_platform.llm.anthropic import (
    API_VERSION,
    AnthropicProvider,
    _merge_consecutive,
    _parse,
    _split_system,
)
from cii_platform.llm.provider import MAX_OUTPUT_TOKENS, LLMError, LLMUnavailableError


def test_system_is_lifted_out_of_the_message_array() -> None:
    """IT-CHAT-034 — Anthropic은 ``system``을 **별도 필드**로 받는다.

    배열에 남겨 보내면 400이다. 오케스트레이션은 역할 하나로 다루는 편이 단순하므로
    여기서 갈라 준다 — 공급자 규격을 서비스가 알 필요는 없다.
    """
    system, rest = _split_system(
        [
            {"role": "system", "content": "규칙"},
            {"role": "user", "content": "질문"},
        ]
    )
    assert system == "규칙"
    assert rest == [{"role": "user", "content": "질문"}]


def test_consecutive_same_roles_are_merged() -> None:
    """IT-CHAT-035 — ⚠️ ``user``가 연달아 오면 합친다.

    도구 응답을 ``user``로 되돌려 넣기 때문에(``services/chat.py``) 실제로 생기는
    모양이다. Anthropic은 역할이 번갈아야 한다고 요구한다.
    """
    merged = _merge_consecutive(
        [
            {"role": "user", "content": "질문"},
            {"role": "user", "content": "{도구 응답}"},
            {"role": "assistant", "content": "답"},
        ]
    )
    assert merged == [
        {"role": "user", "content": "질문\n{도구 응답}"},
        {"role": "assistant", "content": "답"},
    ]


def test_parse_takes_text_and_tool_calls_together() -> None:
    """IT-CHAT-036 — 한 응답에 **텍스트와 도구 호출이 함께** 올 수 있다.

    모델이 「찾아보겠습니다」라고 말하며 도구를 부르는 경우다. 한쪽만 읽으면 그 말이
    사라지거나 도구가 불리지 않는다.
    """
    response = _parse(
        {
            "content": [
                {"type": "text", "text": "찾아보겠습니다."},
                {"type": "tool_use", "name": "search_vessel", "input": {"name": "DEMO"}},
            ]
        }
    )
    assert response.text == "찾아보겠습니다."
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search_vessel"
    assert response.tool_calls[0].arguments == {"name": "DEMO"}


async def test_request_carries_the_output_cap_and_version_header() -> None:
    """IT-CHAT-037 — 출력 상한을 **매 호출에 싣는다** (``PRD §16.1`` 가드 1).

    기본값에 기대면 공급자가 기본을 올렸을 때 비용이 조용히 커진다.
    """
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = __import__("json").loads(request.content)
        seen["version"] = request.headers.get("anthropic-version")
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "네."}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AnthropicProvider(key="test-key", client=client)
        response = await provider.complete(
            messages=[{"role": "system", "content": "규칙"}, {"role": "user", "content": "질문"}]
        )

    assert response.text == "네."
    body = seen["body"]
    assert body["max_tokens"] == MAX_OUTPUT_TOKENS  # type: ignore[index]
    assert body["system"] == "규칙"  # type: ignore[index]
    assert seen["version"] == API_VERSION
    assert seen["key"] == "test-key"


async def test_http_failure_becomes_an_llm_error_without_the_body() -> None:
    """IT-CHAT-038 — 실패는 ``LLMError``다. **본문을 문구에 싣지 않는다.**

    오류 본문에 요청이 그대로 실려 오는 경우가 있어, 그것을 로그에 넣으면 전송
    금지 값이 로그로 샌다(``PRD §16.3.1``).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "vessel_name DEMO-1 invalid"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AnthropicProvider(key="test-key", client=client)
        with pytest.raises(LLMError) as caught:
            await provider.complete(messages=[{"role": "user", "content": "질문"}])

    assert "DEMO-1" not in str(caught.value)
    assert "400" in str(caught.value)


async def test_missing_key_is_unavailable_not_a_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IT-CHAT-039 — 키가 없으면 ``LLMUnavailableError``다 (``API_SPEC §15.4`` 503).

    일반 실패와 나누는 이유는 **사람이 할 일이 다르기** 때문이다 — 이쪽은 설정을
    채우는 것이고, 저쪽은 다시 시도하는 것이다.
    """
    # 환경에 키가 있으면 생성자가 그것을 집는다 — 검사가 환경에 기대지 않게 지운다.
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    provider = AnthropicProvider(key=None)
    with pytest.raises(LLMUnavailableError):
        await provider.complete(messages=[{"role": "user", "content": "질문"}])
