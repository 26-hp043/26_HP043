"""챗봇 오케스트레이션 (`#121`).

자연어 → 도구 선택 → API 호출 → 자연어 응답. **가드는 이 경로의 양 끝에 선다.**

```
사용자 문장 ─► 모델 ─► 도구 선택 ─► 서버가 실행 ─► [화이트리스트] ─► 모델 ─► 응답
                                                                          │
                                                                   [수학 검증]
                                                                          │
                                                             통과 ─► 저장·반환
                                                             실패 ─► 폐기·오류
```

## 서버가 문장을 만들지 않는다

오류도 **봉투에 담아 모델에게 준다**(`chat_tools.envelope`). 서버가 문장을 만들면
같은 말을 두 곳에서 쓰게 되고, 말투가 갈린다.

## 폐기가 기본값이다

수학 검증(``verify_numbers``)에 걸리면 **응답을 버린다.** ``PRD §16.2`` 장애 격리와
같은 방향이다 — **챗봇이 틀린 말을 하느니 말을 하지 않는 쪽**이 안전하다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING

from cii_platform.db.models.chat import ROLE_ASSISTANT, ROLE_USER
from cii_platform.db.repositories import chat as chat_repo
from cii_platform.llm.provider import (
    MAX_HISTORY_TURNS,
    MAX_TOOL_CALLS_PER_TURN,
    STOP_REFUSAL,
    STOP_TRUNCATED,
    TURN_TIMEOUT_SECONDS,
    LLMError,
)
from cii_platform.services import audit
from cii_platform.services.chat_explain import glossary_prompt
from cii_platform.services.chat_tools import run_tool, tool_schemas
from cii_platform.services.llm_guard import NumberFabricationError, verify_numbers

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.db.models.chat import ChatMessage
    from cii_platform.llm.provider import LLMProvider

#: 응답을 폐기했을 때 사용자에게 나가는 문구.
#:
#: **무엇이 잘못됐는지 말하되 추측하지 않는다** — 「수치가 맞지 않는다」는 사실이고,
#: 「모델이 계산했다」는 추측이다.
DISCARDED_MESSAGE = (
    "답변에서 계산 결과로 설명되지 않는 수치가 나와 답변을 보내지 않았습니다. "
    "화면의 계산 결과를 확인해 주세요."
)

#: 도구 호출 상한에 걸렸을 때.
TOOL_BUDGET_MESSAGE = "한 번에 처리하기에 너무 많은 조회가 필요합니다. 질문을 나눠서 물어봐 주세요."

#: ⚠️ 응답이 **출력 상한에서 잘렸을 때**.
#:
#: 벤더 문서는 `max_tokens`를 올리거나 이어 받으라고 적지만 **둘 다 하지 않는다** —
#: 출력 상한은 ``PRD §16.1`` 가드 1이고, 이어 받는 것은 왕복을 늘려 가드 2와 부딪힌다.
#:
#: **잘린 답을 그대로 보이지 않는다.** 문장 중간에서 끊긴 설명은 뜻이 뒤집힐 수 있고
#: (「등급은 C가 아니라」에서 끊기면), 화면은 그것을 완성된 답으로 그린다.
TRUNCATED_MESSAGE = "답변이 길어 중간에서 끊겼습니다. 질문을 나눠서 물어봐 주세요."

#: 모델이 답하기를 거절했을 때. **사유를 지어내지 않는다.**
REFUSAL_MESSAGE = "이 질문에는 답변하지 않았습니다. 다르게 물어봐 주세요."

#: 모든 응답에 붙는 면책 (``PRD §6.3`` 챗봇 행 · `#120` 완료 기준).
#:
#: ⚠️ **정본과 같아야 한다.** ``tests/test_chat_orchestration.py``가 `PRD` 표를 읽어
#: 대조한다 — 문구가 갈리면 화면과 정본이 다른 말을 한다.
DISCLAIMER = (
    "이 답변은 화면의 계산 결과를 풀어 쓴 것입니다. "
    "규제 판단의 근거가 아니며, 최종 확인은 IMO 규제 원문을 따릅니다."
)

#: 모델에게 주는 역할 지시.
#:
#: **No-Advice를 프롬프트로도 적는다** — 코드 가드가 최종 방어지만, 모델이 애초에
#: 권고를 만들지 않으면 폐기가 줄어든다. **가드를 프롬프트로 대신하지는 않는다.**
_RULES = (
    "당신은 선박 탄소집약도지수(CII) 도구의 설명 도우미입니다.\n"
    "- 수치는 **도구가 돌려준 값** 또는 **이전 답변에 이미 쓴 값**만 인용하십시오. "
    "직접 계산하거나 어림하지 마십시오.\n"
    "- 더하기·빼기도 계산입니다. 도구가 주지 않은 수는 쓰지 마십시오.\n"
    "- 시나리오에 순위를 매기거나 「더 낫다·최적」 같은 비교 표현을 쓰지 마십시오.\n"
    "- 행동을 제안하지 마십시오. 사용자가 직접 요청한 계산만 도구로 실행하십시오.\n"
    "- 등급에 「보통」·「불량」 같은 형용사를 붙이지 마십시오. 아래 풀이의 말만 쓰십시오.\n"
    "- 규정 번호나 연도 같은 수를 지어내지 마십시오.\n"
    "- 선박명·IMO 번호는 답변에 쓰지 마십시오.\n"
    "- 한국어로 간결하게 답하십시오."
)

#: 역할 지시 + 용어 풀이 (`#123`).
#:
#: **풀이를 매 호출에 싣는다.** 도구로 만들면 용어를 물을 때마다 왕복이 한 번 더
#: 들고, 왕복이 비용 폭주의 실제 경로다(``PRD §16.1`` 가드 2). 풀이는 정적이고
#: 짧아 프롬프트에 두는 편이 싸다.
SYSTEM_PROMPT = f"{_RULES}\n\n{glossary_prompt()}"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _from_a_question(history: Sequence[ChatMessage]) -> list[ChatMessage]:
    """이력 창이 **질문부터 시작하게** 자른다.

    ## 왜 필요한가

    ``list_messages(limit=…)``는 **최근 N건**을 준다. 대화가 ``U A U A …``로 쌓이므로
    N이 짝수면 **4번째 질문부터 창이 답변으로 시작한다.**

    .. code-block:: text

        3번째 질문   U A U A U        창 = U A U A U      ← 질문으로 시작
        4번째 질문   U A U A U A U    창 =   A U A U A U  ← ⚠️ 답변으로 시작

    그 창은 **질문이 잘려 나간 답변**으로 대화를 연다. 모델은 무엇에 대한 답인지
    모른 채 그것을 맥락으로 삼는다 — 수치를 인용하는 제품에서 특히 나쁘다.

    벤더 문서도 *"Our models are trained to operate on alternating user and assistant
    conversational turns"* 로 적는다. (API가 이 창을 거절하는지는 문서에서 확인하지
    못했다 — 거절하지 않더라도 위 이유로 고칠 값어치가 있다.)

    ## 자르는 쪽을 고른 이유

    ``limit``을 홀수로 두는 대안은 **폐기가 섞이면 다시 어긋난다** — 버려진 답은
    저장되지 않아(``answer`` 참조) ``U U A U``처럼 쌓이는 자리가 생긴다. 창의 **앞을
    보고 자르는** 쪽이 그런 경우까지 덮는다.
    """
    start = 0
    while start < len(history) and history[start].role != ROLE_USER:
        start += 1
    return list(history[start:])


#: #1245 — 턴 시간 초과 문구. 무엇이 일어났는지만 말한다(다른 폐기 문구의 원칙).
TURN_TIMEOUT_MESSAGE = "응답 시간이 초과되어 답변을 보내지 않았습니다. 다시 물어봐 주세요."


async def answer(
    session: AsyncSession,
    *,
    provider: LLMProvider,
    chat_session_id: UUID,
    user_id: str | None,
    question: str,
    vessel_id: UUID | None = None,
    ip_address: str | None = None,
    turn_timeout: float | None = None,
) -> dict[str, object]:
    """한 턴을 처리한다 — **시간 상한으로 감싸서**(#1245).

    최악 경로(LLM 30초 × 도구 왕복 4회 ≈ 2분)가 DB 세션·커넥션을 쥐던 것을
    :data:`TURN_TIMEOUT_SECONDS`에서 끊는다. 초과 시 사용자 메시지는 이미 저장돼
    있고 답만 없는 것은 ``#121`` 폐기 정책과 같은 모양이다(라우트의 ``commit()``
    경로가 그대로 탄다). ``turn_timeout``은 검사가 짧은 예산을 넣는 주입점이다.
    """
    budget = TURN_TIMEOUT_SECONDS if turn_timeout is None else turn_timeout
    try:
        async with asyncio.timeout(budget):
            return await _answer_turn(
                session,
                provider=provider,
                chat_session_id=chat_session_id,
                user_id=user_id,
                question=question,
                vessel_id=vessel_id,
                ip_address=ip_address,
            )
    except TimeoutError:
        return _result(TURN_TIMEOUT_MESSAGE, [], discarded=True, vessel_resolved=False)


async def _answer_turn(
    session: AsyncSession,
    *,
    provider: LLMProvider,
    chat_session_id: UUID,
    user_id: str | None,
    question: str,
    vessel_id: UUID | None = None,
    ip_address: str | None = None,
) -> dict[str, object]:
    """한 턴의 본문 — :func:`answer`의 시간 상한 안에서 돈다.

    :returns: ``{"answer": ..., "disclaimer": ..., "tool_calls": [...], "discarded": bool}``

    ## 도구 호출 상한이 비용을 막는다

    :data:`MAX_TOOL_CALLS_PER_TURN`을 넘기면 **거기서 끊는다**. 모델이 도구를 잘못
    골라 왕복을 반복하는 것이 비용 폭주의 실제 경로다(``PRD §16.1`` 가드 2).
    """
    await chat_repo.add_message(
        session, session_id=chat_session_id, role=ROLE_USER, content=question
    )
    await audit.record_chat_message(
        session,
        user_id=user_id,
        session_id=chat_session_id,
        role=ROLE_USER,
        content=question,
        ip_address=ip_address,
    )

    # #1243 — 선박 결정 규칙: 요청 vessel_id(화면) > 세션 귀속(검색이 정한 것).
    # 🔴 요청값은 세션에 싣지 않는다(#1242에서 정정) — 세션 귀속은 **검색의 고유
    # 일치만** 쓴다. 화면은 그 턴에서만 이기고, 세션의 「검색이 정한 배」를 화면이
    # 조용히 덮어쓰지 않게 한다(요청이 오지 않은 다음 턴의 대답이 달라지면 안 된다).
    session_row = await chat_repo.get_session_row(session, session_id=chat_session_id)
    effective_vessel: UUID | None = vessel_id or getattr(session_row, "vessel_id", None)

    history = await chat_repo.list_messages(
        session, session_id=chat_session_id, limit=MAX_HISTORY_TURNS
    )
    messages: list[dict[str, object]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [
        {"role": "user" if row.role == ROLE_USER else "assistant", "content": row.content}
        for row in _from_a_question(history)
    ]

    tool_outputs: list[str] = []
    used_tools: list[str] = []
    reply = ""

    for _ in range(MAX_TOOL_CALLS_PER_TURN + 1):
        try:
            response = await provider.complete(messages=messages, tools=tool_schemas())
        except LLMError as exc:
            # 공급자 실패는 숨기지 않되 **챗봇 안에서 끝난다** (`PRD §16.2`).
            return _result(str(exc), used_tools, discarded=True)

        if response.stop_reason == STOP_REFUSAL:
            return _result(REFUSAL_MESSAGE, used_tools, discarded=True)

        # ⚠️ **잘린 응답으로는 도구도 돌리지 않는다.** `tool_use` 블록의 **인자가
        # 잘려** 있을 수 있어(벤더 문서), 그대로 돌리면 **엉뚱한 값으로 계산한다** —
        # 그리고 그 결과는 수학 검증을 통과한다(도구가 실제로 낸 값이므로).
        if response.stop_reason in STOP_TRUNCATED:
            return _result(TRUNCATED_MESSAGE, used_tools, discarded=True)

        if not response.tool_calls:
            reply = response.text
            break

        if len(used_tools) + len(response.tool_calls) > MAX_TOOL_CALLS_PER_TURN:
            return _result(
                TOOL_BUDGET_MESSAGE,
                used_tools,
                discarded=True,
                vessel_resolved=effective_vessel is not None,
            )

        # ⚠️ **도구 왕복은 짝으로 보낸다** (`Anthropic Messages API` 규격).
        #
        # 모델의 `tool_use` 블록을 그대로 되돌려 보내고, 같은 `tool_use_id`를 단
        # `tool_result`로 답해야 한다. 종전에는 도구 결과를 **평범한 `user` 문장**으로
        # 보냈다 — 그러면 모델이 **자기가 도구를 불렀다는 것을 모른 채** 데이터만 보고,
        # 같은 도구를 다시 부를 수 있다.
        assistant_blocks: list[dict[str, object]] = []
        if response.text:
            assistant_blocks.append({"type": "text", "text": response.text})
        assistant_blocks += [
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            for call in response.tool_calls
        ]
        messages.append({"role": "assistant", "content": assistant_blocks})

        results: list[dict[str, object]] = []
        for call in response.tool_calls:
            # 같은 턴의 search_vessel이 고유 일치를 정했으면 **이 자리에서** 귀속을
            # 저장하고 다음 도구가 즉시 그 선박을 쓴다(#1243 — ToolOutcome).
            outcome = await run_tool(
                session,
                name=call.name,
                arguments=call.arguments,
                vessel_id=effective_vessel,
                chat_session_id=chat_session_id,
                vessel_locked=vessel_id is not None,
            )
            if outcome.resolved_vessel_id is not None and vessel_id is None:
                await chat_repo.set_vessel(
                    session, session_id=chat_session_id, vessel_id=outcome.resolved_vessel_id
                )
                effective_vessel = outcome.resolved_vessel_id
            output = outcome.envelope
            tool_outputs.append(output)
            used_tools.append(call.name)
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": output})
            await audit.record_chat_tool_call(
                session,
                user_id=user_id,
                session_id=chat_session_id,
                tool_name=call.name,
                arguments_digest=_digest(call.arguments),
                ip_address=ip_address,
            )
        messages.append({"role": "user", "content": results})
    else:
        return _result(TOOL_BUDGET_MESSAGE, used_tools, discarded=True)

    try:
        prior_answers = [
            row.content for row in _from_a_question(history) if row.role == ROLE_ASSISTANT
        ]
        verify_numbers(reply, tool_outputs, prior_answers=prior_answers)
    except NumberFabricationError:
        # ⚠️ **폐기한다.** 저장도 하지 않는다 — 틀린 답을 이력에 남기면 다음 턴이
        # 그것을 근거로 삼는다.
        return _result(
            DISCARDED_MESSAGE,
            used_tools,
            discarded=True,
            vessel_resolved=effective_vessel is not None,
        )

    await chat_repo.add_message(
        session, session_id=chat_session_id, role=ROLE_ASSISTANT, content=reply
    )
    await audit.record_chat_message(
        session,
        user_id=user_id,
        session_id=chat_session_id,
        role=ROLE_ASSISTANT,
        content=reply,
        ip_address=ip_address,
    )
    return _result(
        reply,
        used_tools,
        discarded=False,
        vessel_resolved=effective_vessel is not None,
    )


def _result(
    text: str,
    used_tools: list[str],
    *,
    discarded: bool,
    vessel_resolved: bool = False,
) -> dict[str, object]:
    return {
        "answer": text,
        # 면책은 **폐기했을 때도** 붙는다 — 「모든 응답에 disclaimer」가 완료 기준이다.
        "disclaimer": DISCLAIMER,
        # 실행한 도구 이름만 싣는다. **개수를 따로 싣지 않는다** (`#1365`) —
        # 종전에 있던 `tool_output_count`는 `len(tool_calls)`와 **늘 같았고**
        # (출력과 이름이 같은 자리에서 함께 쌓인다) `API_SPEC §15.1` 표에도
        # 없었다. 같은 값을 두 이름으로 내보내면 둘이 갈릴 자리가 생긴다.
        "tool_calls": list(used_tools),
        "discarded": discarded,
        # #1242 — 서버가 이 대화의 선박을 알고 있는가. **식별자 자체는 안 싣는다**
        # (`PRD §16.3.1` — 모델에게 가는 값이 아니라 화면에게 가는 값이다).
        "vessel_resolved": vessel_resolved,
    }
