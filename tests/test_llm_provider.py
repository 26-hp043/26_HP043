"""Anthropic 공급자의 메시지 변환 (`#121` · IT-CHAT-034~039).

**바깥과 말하지 않는다** — 여기서 보는 것은 요청 본문을 만드는 규칙이다. 이 규칙이
틀리면 400이 나는데, 그 실패는 **운영에서만** 드러난다(오케스트레이션 검사는
``FakeProvider``를 쓰므로 지나간다). 그래서 따로 잠근다.
"""

from __future__ import annotations

import json

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


def test_stop_reason_is_carried_not_judged() -> None:
    """IT-CHAT-057 — 공급자는 ``stop_reason``을 **옮기기만** 한다.

    무엇을 폐기할지는 ``services/chat.py``가 정한다 — 공급자가 판정하면 정책이
    두 곳에 생기고, 모델을 바꿀 때 함께 옮겨야 한다(`Q4` 교체 용이성).
    """
    assert _parse({"content": [], "stop_reason": "max_tokens"}).stop_reason == "max_tokens"
    assert _parse({"content": []}).stop_reason == ""


async def test_tool_round_trip_matches_the_documented_protocol() -> None:
    """IT-CHAT-053 — ⚠️ 도구 왕복이 **벤더 규격 그대로** 나간다.

    Anthropic Messages API는 짝을 요구한다 — 모델의 ``tool_use`` 블록을 **그대로
    되돌려 보내고**, 같은 ``tool_use_id``를 단 ``tool_result``로 답해야 한다.

    종전에는 도구 결과를 **평범한 `user` 문장**으로 보냈다. 오류가 나지는 않지만
    모델이 **자기가 도구를 불렀다는 것을 모른 채** 데이터만 보고, 같은 도구를 다시
    부를 수 있다. 「실제 모델이 도구를 제대로 고르는가」는 검사할 수 없으므로,
    **요청 본문이 규격과 같은지**를 대신 잠근다.

    ⚠️ 이 검사가 없으면 틀린 모양이 **키를 넣는 날 처음** 드러난다.
    """
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["messages"] = json.loads(request.content)["messages"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": "네."}]})

    conversation = [
        {"role": "user", "content": "등급 알려줘"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "찾아보겠습니다."},
                {"type": "tool_use", "id": "toolu_1", "name": "search_vessel", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"},
            ],
        },
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await AnthropicProvider(key="k", client=client).complete(messages=conversation)

    sent = seen["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]  # type: ignore[union-attr]
    tool_use = sent[1]["content"][1]  # type: ignore[index]
    tool_result = sent[2]["content"][0]  # type: ignore[index]
    assert tool_use["type"] == "tool_use"
    assert tool_result["type"] == "tool_result"
    # 짝을 맞추는 것이 이 id다 — 어긋나면 API가 요청을 거절한다.
    assert tool_result["tool_use_id"] == tool_use["id"]


def test_tool_use_id_survives_parsing() -> None:
    """IT-CHAT-054 — 응답의 ``tool_use`` id를 **잃지 않는다**.

    이 값을 흘리면 다음 요청의 ``tool_result``가 짝을 잃는다. ``ToolCall.id``의
    기본값이 빈 문자열이라 **조용히 빈 채로 나갈 수 있다** — 그래서 단언한다.
    """
    response = _parse(
        {"content": [{"type": "tool_use", "id": "toolu_9", "name": "x", "input": {}}]}
    )
    assert response.tool_calls[0].id == "toolu_9"


def test_block_contents_are_not_merged_across_messages() -> None:
    """IT-CHAT-055 — ⚠️ **블록 목록은 합치지 않는다**.

    ``_merge_consecutive``는 이력이 어긋났을 때를 위한 방어인데, 도구 왕복의
    블록까지 합치면 ``tool_use``·``tool_result`` 짝이 깨진다. 문자열 둘일 때만 잇는다.
    """
    merged = _merge_consecutive(
        [
            {"role": "user", "content": "질문"},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": "{}"}],
            },
        ]
    )
    assert len(merged) == 2
    assert isinstance(merged[1]["content"], list)


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


# ── #1535 주소·모델·인증 방식 환경변수화 · 자리표시자 ──────────────────────────


@pytest.fixture
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_AUTH_SCHEME"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.mark.parametrize("value", ["", "   ", "-", " - "])
def test_blank_or_placeholder_key_means_disabled(_clean_llm_env, value: str) -> None:
    """`#1535` — 자리표시자 ``-``는 **빈 값과 같이 꺼짐**이다.

    GitHub 시크릿은 비워 둘 수 없어 운영에 ``-``를 넣어 두었다. 이것을 키로 읽으면
    질문마다 외부 호출이 인증 실패로 끝나고, 화면은 그것을 미리 알 수 없다.
    """
    from cii_platform.llm.provider import api_key, is_enabled

    _clean_llm_env.setenv("LLM_API_KEY", value)
    assert api_key() is None
    assert is_enabled() is False


def test_unknown_auth_scheme_disables_the_chatbot(_clean_llm_env) -> None:
    """`#1535` — 모르는 인증 방식은 **기본값으로 고쳐 읽지 않고 끈다.**

    고쳐 읽으면 운영자가 적은 것과 다른 헤더로 키가 외부에 나간다.
    """
    from cii_platform.llm.provider import auth_scheme, is_enabled

    _clean_llm_env.setenv("LLM_API_KEY", "k")
    _clean_llm_env.setenv("LLM_AUTH_SCHEME", "basic")
    assert auth_scheme() is None
    assert is_enabled() is False


async def test_defaults_keep_the_previous_anthropic_request(_clean_llm_env) -> None:
    """`#1535` — 설정을 비워 두면 **종전과 같은 주소·모델·헤더**로 나간다.

    환경변수화가 기본 동작을 바꾸면, 이 PR의 머지(= 자동 배포)가 곧 운영 챗봇 변경이 된다.
    """
    from cii_platform.llm.provider import DEFAULT_MODEL

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": "네."}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await AnthropicProvider(key="k", client=client).complete(
            messages=[{"role": "user", "content": "질문"}]
        )

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["model"] == DEFAULT_MODEL == "claude-haiku-4-5-20251001"
    headers = seen["headers"]
    assert headers["x-api-key"] == "k"  # type: ignore[index]
    assert "authorization" not in headers  # type: ignore[operator]


async def test_env_moves_the_address_model_and_auth_header(_clean_llm_env) -> None:
    """`#1535` — 주소·모델·인증 방식을 **설정만으로** 바꾼다.

    Anthropic 형식을 내는 다른 공급자(예: Z.ai는 기준 주소 + Bearer로 안내)로 옮길 때
    코드를 고치지 않기 위해서다. 끝의 ``/``는 걷어 경로가 ``//``가 되지 않게 한다.
    """
    _clean_llm_env.setenv("LLM_BASE_URL", "https://llm.example/api/anthropic/")
    _clean_llm_env.setenv("LLM_MODEL", "some-model")
    _clean_llm_env.setenv("LLM_AUTH_SCHEME", "Bearer")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": "네."}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await AnthropicProvider(key="k", client=client).complete(
            messages=[{"role": "user", "content": "질문"}]
        )

    assert seen["url"] == "https://llm.example/api/anthropic/v1/messages"
    assert seen["model"] == "some-model"
    headers = seen["headers"]
    assert headers["authorization"] == "Bearer k"  # type: ignore[index]
    assert "x-api-key" not in headers  # type: ignore[operator]
    assert headers["anthropic-version"] == API_VERSION  # type: ignore[index]


def test_status_path_does_not_spend_the_chat_bucket() -> None:
    """`#1535` — ``GET /chat/status``는 **질문 한도(분당 10)를 깎지 않는다.**

    패널을 열 때마다 부르므로, ``chat`` 버킷에 들면 질문도 하기 전에 429가 난다.
    """
    from cii_platform.api.rate_limit import BUCKET_CHAT, resolve_bucket

    assert resolve_bucket("POST", "/api/v1/chat") == BUCKET_CHAT
    assert resolve_bucket("GET", "/api/v1/chat/status") != BUCKET_CHAT
