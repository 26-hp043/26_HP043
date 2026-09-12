"""챗봇 요청 스키마 (`#121` · ``API_SPEC §12``).

응답은 서비스가 만든 dict를 그대로 내보낸다 — 계산 API와 같은 규약이다
(``schemas/voyage_cii.py`` 머리말). 챗봇 응답의 수치는 **도구 응답에서 온 문자열**
이라, 응답 모델을 두면 재직렬화 과정에서 자릿수가 바뀔 여지가 생긴다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: 한 번에 받는 질문의 최대 길이(글자).
#:
#: ⚠️ **입력 토큰 상한이 여기서 선다.** ``llm/provider.py``의 상수 셋은 출력·왕복·
#: 이력을 막지만 **한 번의 입력 길이는 막지 않는다** — 사용자가 문서를 통째로 붙여
#: 넣으면 그 자체로 비용이다(``PRD §16.1`` 쿼리당 `$0.05`).
MAX_QUESTION_CHARS = 2000


class ChatRequest(BaseModel):
    """``POST /api/v1/chat`` 요청 본문.

    :param session_id: 이어 갈 대화. 없으면 **새로 만든다**.
    :param vessel_id: 화면이 보고 있는 선박. 계산 도구가 이 선박으로 돈다.

    ``extra="forbid"`` — 계산 API와 같은 이유다. 오타 필드를 조용히 무시하면
    사용자가 보낸 값이 반영되지 않은 채 답이 나간다.
    """

    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION_CHARS)]
    session_id: UUID | None = None
    vessel_id: UUID | None = None
