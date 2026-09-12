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

import hashlib
import json
from typing import TYPE_CHECKING

from cii_platform.db.models.chat import ROLE_ASSISTANT, ROLE_USER
from cii_platform.db.repositories import chat as chat_repo
from cii_platform.llm.provider import (
    MAX_HISTORY_TURNS,
    MAX_TOOL_CALLS_PER_TURN,
    LLMError,
)
from cii_platform.services import audit
from cii_platform.services.chat_tools import run_tool, tool_schemas
from cii_platform.services.llm_guard import NumberFabricationError, verify_numbers

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

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
SYSTEM_PROMPT = (
    "당신은 선박 탄소집약도지수(CII) 도구의 설명 도우미입니다.\n"
    "- 수치는 **도구가 돌려준 값만** 인용하십시오. 직접 계산하거나 어림하지 마십시오.\n"
    "- 더하기·빼기도 계산입니다. 도구가 주지 않은 수는 쓰지 마십시오.\n"
    "- 시나리오에 순위를 매기거나 「더 낫다·최적」 같은 비교 표현을 쓰지 마십시오.\n"
    "- 행동을 제안하지 마십시오. 사용자가 직접 요청한 계산만 도구로 실행하십시오.\n"
    "- 선박명·IMO 번호는 답변에 쓰지 마십시오.\n"
    "- 한국어로 간결하게 답하십시오."
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


async def answer(
    session: AsyncSession,
    *,
    provider: LLMProvider,
    chat_session_id: UUID,
    user_id: str | None,
    question: str,
    vessel_id: UUID | None = None,
    ip_address: str | None = None,
) -> dict[str, object]:
    """한 턴을 처리한다.

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

    history = await chat_repo.list_messages(
        session, session_id=chat_session_id, limit=MAX_HISTORY_TURNS
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [
        {"role": "user" if row.role == ROLE_USER else "assistant", "content": row.content}
        for row in history
    ]

    tool_outputs: list[str] = []
    used_tools: list[str] = []
    reply = ""

    for _ in range(MAX_TOOL_CALLS_PER_TURN + 1):
        try:
            response = await provider.complete(messages=messages, tools=tool_schemas())
        except LLMError as exc:
            # 공급자 실패는 숨기지 않되 **챗봇 안에서 끝난다** (`PRD §16.2`).
            return _result(str(exc), tool_outputs, used_tools, discarded=True)

        if not response.tool_calls:
            reply = response.text
            break

        if len(used_tools) + len(response.tool_calls) > MAX_TOOL_CALLS_PER_TURN:
            return _result(TOOL_BUDGET_MESSAGE, tool_outputs, used_tools, discarded=True)

        for call in response.tool_calls:
            output = await run_tool(
                session, name=call.name, arguments=call.arguments, vessel_id=vessel_id
            )
            tool_outputs.append(output)
            used_tools.append(call.name)
            messages.append({"role": "user", "content": output})
            await audit.record_chat_tool_call(
                session,
                user_id=user_id,
                session_id=chat_session_id,
                tool_name=call.name,
                arguments_digest=_digest(call.arguments),
                ip_address=ip_address,
            )
    else:
        return _result(TOOL_BUDGET_MESSAGE, tool_outputs, used_tools, discarded=True)

    try:
        verify_numbers(reply, tool_outputs)
    except NumberFabricationError:
        # ⚠️ **폐기한다.** 저장도 하지 않는다 — 틀린 답을 이력에 남기면 다음 턴이
        # 그것을 근거로 삼는다.
        return _result(DISCARDED_MESSAGE, tool_outputs, used_tools, discarded=True)

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
    return _result(reply, tool_outputs, used_tools, discarded=False)


def _result(
    text: str, tool_outputs: list[str], used_tools: list[str], *, discarded: bool
) -> dict[str, object]:
    return {
        "answer": text,
        # 면책은 **폐기했을 때도** 붙는다 — 「모든 응답에 disclaimer」가 완료 기준이다.
        "disclaimer": DISCLAIMER,
        "tool_calls": list(used_tools),
        "tool_output_count": len(tool_outputs),
        "discarded": discarded,
    }
