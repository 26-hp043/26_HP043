"""챗봇 라우트 (``API_SPEC §15`` · `#121`).

**HTTP만 다룬다** (``TECH_SPEC §16.1``) — 도구 선택·가드·저장은
``services.chat``이 한다. 이 모듈에 프롬프트나 화이트리스트가 생기면 계층이
무너진 것이다.

## 공급자를 의존성으로 받는다

검사는 ``FakeProvider``를 끼운다 — CI가 외부 모델을 부르면 과금되고 비결정적이
된다(``llm/provider.py`` 머리말). 그래서 **주입 지점을 라우트에 둔다**:
``app.dependency_overrides``로 갈아 끼울 수 있는 자리가 여기다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

# TYPE_CHECKING 블록에 두면 안 된다 — FastAPI가 의존성 시그니처를 런타임에 해석한다
# (``routes/calculations.py`` 같은 주석 참조).
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.schemas.chat import ChatRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import get_current_user, require_csrf
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.repositories import chat as chat_repo
from cii_platform.db.session import get_session
from cii_platform.errors import ChatUnavailableError, NotFoundError
from cii_platform.llm.anthropic import AnthropicProvider
from cii_platform.llm.provider import LLMProvider, LLMUnavailableError, is_enabled
from cii_platform.services.chat import answer as answer_question

router = APIRouter(tags=["chat"])


def get_provider() -> LLMProvider:
    """쓸 공급자. **검사가 갈아 끼우는 지점이다.**

    키가 없으면 여기서 끊는다 — 오케스트레이션을 시작하고 사용자 메시지를 저장한
    뒤에 실패하면, 답이 없는 질문만 이력에 쌓인다.
    """
    if not is_enabled():
        raise ChatUnavailableError("챗봇을 사용할 수 없습니다. 관리자에게 문의해 주세요.")
    return AnthropicProvider()


@router.post("/chat")
async def chat(
    request: Request,
    payload: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AppUser, Depends(get_current_user)],
    provider: Annotated[LLMProvider, Depends(get_provider)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """질문 하나에 답한다 (``API_SPEC §15.1``).

    ## 남의 대화는 404다

    ``session_id``의 주인이 다르면 **403이 아니라 404**를 낸다. 403은 「있지만 네
    것이 아니다」를 알려 주어, id를 바꿔 가며 **남의 대화가 존재하는지** 알아낼 수
    있게 한다.

    ## ``discarded``여도 200이다

    버리는 것은 사용자 잘못이 아니다 (``API_SPEC §15.2``). 요청은 정상이었고 모델의
    답이 규율을 어겼을 뿐이라, 4xx를 내면 화면이 **고칠 수 없는 입력**을 고치라고
    안내하게 된다.
    """
    if payload.session_id is None:
        chat_session = await chat_repo.create_session(session, user_id=user.id)
    else:
        chat_session = await chat_repo.get_session_row(session, session_id=payload.session_id)
        if chat_session is None or chat_session.user_id != user.id:
            raise NotFoundError("대화를 찾을 수 없습니다.")

    try:
        result = await answer_question(
            session,
            provider=provider,
            chat_session_id=chat_session.id,
            user_id=str(user.id),
            question=payload.message,
            vessel_id=payload.vessel_id,
            ip_address=_client_ip(request),
        )
    except LLMUnavailableError as exc:
        raise ChatUnavailableError(str(exc)) from exc

    await session.commit()

    state = getattr(request, "state", None)
    return {
        "data": {"session_id": str(chat_session.id), **result},
        "meta": {
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }


def _client_ip(request: Request) -> str | None:
    client = getattr(request, "client", None)
    return getattr(client, "host", None)
