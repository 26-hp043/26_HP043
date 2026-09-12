"""Anthropic Messages API 공급자 (`#121` · `Q4` 확정).

## SDK를 쓰지 않고 ``httpx``로 부른다

의존성을 더하지 않는다. 이 계층이 하는 일은 **한 엔드포인트에 POST 한 번**이고,
``weather``·``geocode``가 이미 같은 방식이다 — 저장소에 HTTP 클라이언트가 둘일
이유가 없다.

SDK를 쓰면 얻는 것(재시도·스트리밍·타입)이 있지만, ⑴ 재시도는 **비용 가드와
충돌**한다(`PRD §16.1`: 한 쿼리 `$0.05`). 실패를 조용히 두 번 더 부르면 상한이
뜻을 잃는다. ⑵ 스트리밍은 `Q10` ⓑ에서 **쓰지 않기로** 했다(일반 응답 + 로딩 표시).
⑶ 타입은 이 파일 하나가 감당할 범위다.

## 실패를 삼키지 않는다

``LLMError``로 올린다. 챗봇 라우트가 그것을 받아 **챗봇 안에서** 끝낸다 —
계산·보고 경로는 이 모듈을 부르지 않는다(``PRD §16.2`` 장애 격리).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from cii_platform.llm.provider import (
    DEFAULT_MODEL,
    MAX_OUTPUT_TOKENS,
    LLMError,
    LLMResponse,
    LLMUnavailableError,
    ToolCall,
    api_key,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Messages API.
ENDPOINT = "https://api.anthropic.com/v1/messages"

#: 버전 헤더 — Anthropic이 요구한다.
API_VERSION = "2023-06-01"

#: 호출 타임아웃(초).
#:
#: 기상 조회(5초)보다 길다 — 모델은 **생성**을 하므로 초 단위가 다르다. 그렇다고
#: 무한히 기다리지 않는다: 화면이 로딩 표시를 띄우고 있고(`Q10` ⓑ), 30초를 넘기면
#: 사용자는 이미 떠났다.
TIMEOUT_SECONDS = 30.0


def _split_system(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    """``system`` 역할을 본문에서 떼어낸다.

    Anthropic은 ``system``을 **메시지 배열이 아니라 별도 필드**로 받는다. 배열에
    남겨 보내면 400이다. 오케스트레이션은 역할 하나로 다루는 편이 단순하므로
    **여기서 갈라 준다** — 공급자 규격을 서비스가 알 필요는 없다.
    """
    system = "\n".join(m["content"] for m in messages if m.get("role") == "system") or None
    rest = [m for m in messages if m.get("role") != "system"]
    return system, rest


def _merge_consecutive(messages: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """같은 역할이 이어지면 하나로 합친다.

    ⚠️ 도구 응답을 ``user``로 되돌려 넣기 때문에(``services/chat.py``) **``user``가
    연달아 두 번** 오는 일이 생긴다. Anthropic은 역할이 번갈아야 한다고 요구한다.

    합치지 않고 ``assistant`` 빈 메시지를 끼우는 대안은 고르지 않았다 — 빈 응답이
    이력에 남아 다음 호출의 입력 토큰을 늘리고, 모델이 그것을 「대답하지 못한 것」으로
    읽는다.
    """
    merged: list[dict[str, str]] = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1]["content"] = f"{merged[-1]['content']}\n{message['content']}"
        else:
            merged.append(dict(message))
    return merged


def _parse(payload: dict[str, Any]) -> LLMResponse:
    """응답 본문에서 텍스트와 도구 호출을 뽑는다.

    한 응답에 **텍스트와 도구 호출이 함께** 올 수 있다(모델이 「찾아보겠습니다」라고
    말하며 도구를 부르는 경우). 둘 다 담아 올린다 — 호출부가 도구 호출이 있는지로
    분기한다.
    """
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            arguments = block.get("input")
            calls.append(
                ToolCall(
                    name=str(block.get("name") or ""),
                    arguments=dict(arguments) if isinstance(arguments, dict) else {},
                )
            )
    return LLMResponse(text="\n".join(p for p in text_parts if p).strip(), tool_calls=tuple(calls))


class AnthropicProvider:
    """``LLMProvider`` 구현체.

    :param key: 쓰지 않으면 ``LLM_API_KEY``를 읽는다.
    :param model: 기본값은 `Q4`가 정한 Claude Haiku 4.5.
    """

    def __init__(
        self,
        *,
        key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._key = key or api_key()
        self._model = model
        self._client = client

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
    ) -> LLMResponse:
        if not self._key:
            raise LLMUnavailableError("챗봇이 설정되지 않았습니다 (LLM_API_KEY 없음).")

        system, rest = _split_system(messages)
        body: dict[str, Any] = {
            "model": self._model,
            # ⚠️ 출력 상한을 **매 호출에 싣는다** (`PRD §16.1` 가드 1). 기본값에
            # 기대면 공급자가 기본을 올렸을 때 비용이 조용히 커진다.
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": _merge_consecutive(rest),
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools

        headers = {
            "x-api-key": self._key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

        try:
            if self._client is not None:
                response = await self._client.post(ENDPOINT, json=body, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    response = await client.post(ENDPOINT, json=body, headers=headers)
            response.raise_for_status()
            return _parse(response.json())
        except httpx.HTTPStatusError as exc:
            # 상태 코드만 남긴다 — 본문에 요청이 그대로 실려 오는 경우가 있어
            # 로그에 넣으면 전송 금지 값이 로그로 샐 수 있다.
            status = exc.response.status_code
            raise LLMError(f"챗봇 응답을 받지 못했습니다 (HTTP {status}).") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LLMError("챗봇 응답을 받지 못했습니다.") from exc
