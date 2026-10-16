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

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

# TYPE_CHECKING 블록에 두면 안 된다 — FastAPI가 의존성 시그니처를 런타임에 해석한다
# (``routes/calculations.py`` 같은 주석 참조).
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.rate_limit import audit_client_ip
from cii_platform.api.schemas.chat import ChatRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import get_current_user, require_csrf
from cii_platform.auth.tour_policy import is_tour_user
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.repositories import chat as chat_repo
from cii_platform.db.session import get_session
from cii_platform.errors import ChatUnavailableError, NotFoundError
from cii_platform.llm import health
from cii_platform.llm.anthropic import AnthropicProvider
from cii_platform.llm.provider import LLMProvider, is_enabled
from cii_platform.services import audit as audit_svc
from cii_platform.services.chat import DISCLAIMER
from cii_platform.services.chat import answer as answer_question
from cii_platform.services.chat import favorite as favorite_answer
from cii_platform.services.chat import favorites as list_favorites
from cii_platform.services.chat import history as chat_history
from cii_platform.services.chat import unfavorite as unfavorite_answer

router = APIRouter(tags=["chat"])


def get_provider() -> LLMProvider:
    """쓸 공급자. **검사가 갈아 끼우는 지점이다.**

    키가 없으면 여기서 끊는다 — 오케스트레이션을 시작하고 사용자 메시지를 저장한
    뒤에 실패하면, 답이 없는 질문만 이력에 쌓인다.
    """
    if not is_enabled():
        raise ChatUnavailableError("챗봇을 사용할 수 없습니다. 관리자에게 문의해 주세요.")
    # `#2289` — 공급자가 연속으로 실패해 막아 둔 동안은 외부를 부르지 않는다. 설정이 없는
    # 것과 달리 관리자가 고칠 일이 아니라 문구를 가른다. 조건은 `/chat/status`의
    # `available: false`와 같다(`API_SPEC §15.4` · `§15.7`).
    if health.is_blocked():
        raise ChatUnavailableError(
            "챗봇이 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요."
        )
    return health.TrackedProvider(AnthropicProvider())


def get_probe_provider_factory() -> Callable[[], LLMProvider]:
    """차단 뒤 시험 요청을 보낼 공급자를 만드는 함수. **검사가 갈아 끼우는 지점이다.**

    결과를 세는 포장(``TrackedProvider``)을 씌우지 않는다 — 시험의 성패는
    ``health.run_probe``가 직접 판정한다.
    """
    return AnthropicProvider


@router.get("/chat/status")
async def chat_status(
    request: Request,
    _user: Annotated[AppUser, Depends(get_current_user)],
    probe_factory: Annotated[Callable[[], LLMProvider], Depends(get_probe_provider_factory)],
) -> dict[str, object]:
    """챗봇을 지금 쓸 수 있는가 (``API_SPEC §15.7`` · `#1535`).

    화면이 패널을 여는 순간 부른다 — 종전에는 질문을 보내 503을 받아야만 알았다.

    ## 불린 하나만 낸다

    키 값도, 꺼진 이유(키 없음 · 자리표시자 · 인증 방식 오류)도 내지 않는다. 이유는
    운영자의 일이고 사용자가 고칠 수 없다 — 화면이 할 일은 「지금은 쓸 수 없다」를
    먼저 보이는 것뿐이다.

    ## 한도 버킷은 ``chat``이 아니다

    ``CHAT_PATHS``는 ``/chat`` 하나다. 패널을 열 때마다 부르는 조회가 질문 한도(분당
    10)를 깎으면 사용자는 질문도 하기 전에 429를 만난다 — 기본 버킷에 둔다.

    ## 공급자를 기다리지 않는다 (`#2289`)

    설정이 있어도 공급자가 연속으로 실패해 막아 둔 동안은 거짓이다. 차단 뒤 시험할
    차례가 됐으면 시험 요청을 **백그라운드로 시작만** 하고, 이 응답은 지금까지 확인된
    상태를 낸다 — 시험 결과는 다음 조회에 반영된다.
    """
    state = getattr(request, "state", None)
    enabled = is_enabled()
    if enabled:
        health.start_probe_if_due(probe_factory)
    return {
        "data": {"available": enabled and not health.is_blocked()},
        "meta": {
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }


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
        # `#1632` — **만료된 대화도 없는 대화다.** 청소(`purge_expired`)는 주기 실행이 아니라
        # 수동(`ops.yml purge`)이라, 그 사이에 만료된 대화로 외부 모델을 부르고 메시지를
        # 쌓을 수 있었다. 남의 대화와 같은 404로 답한다 — 다른 코드를 두면 「있었지만
        # 만료됐다」가 새어 존재 여부를 알린다.
        if (
            chat_session is None
            or chat_session.user_id != user.id
            or chat_repo.is_expired(chat_session)
        ):
            raise NotFoundError("대화를 찾을 수 없습니다.")

    # ⚠️ **여기서 `LLMUnavailableError`를 잡지 않는다** (`#1365`).
    #
    # 종전에 `except LLMUnavailableError → ChatUnavailableError(503)`가 있었으나
    # **도달할 수 없었다** — `services/chat.py`가 상위 타입 `LLMError`를 먼저 잡아
    # `discarded=True`로 200을 낸다(`API_SPEC §15.2` 「외부 모델 호출이 실패했다」).
    # 잡히지 않는 `except`는 **그 경로가 있다고 읽히게** 만든다.
    #
    # 503이 나는 자리는 위 `get_provider()` 하나다 — `LLM_API_KEY` 미설정(`§15.4`).
    result = await answer_question(
        session,
        provider=provider,
        chat_session_id=chat_session.id,
        user_id=str(user.id),
        question=payload.message,
        vessel_id=payload.vessel_id,
        calculation_run_id=payload.calculation_run_id,
        ip_address=audit_client_ip(request),
    )

    await session.commit()

    state = getattr(request, "state", None)
    return {
        "data": {"session_id": str(chat_session.id), **result},
        "meta": {
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }


@router.get("/chat/sessions/{session_id}/messages")
async def chat_session_messages(
    request: Request,
    session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AppUser, Depends(get_current_user)],
) -> dict[str, object]:
    """저장된 대화를 다시 불러온다 (``API_SPEC §15.8`` · `#1981`).

    화면이 **새로고침 뒤** 탭에 기억해 둔 대화 번호로 부른다 — 종전에는 질문·답이 서버에
    90일 남아 있어도 닿을 길이 없었다(챗봇 API는 질의·상태·삭제 셋뿐이었다).

    ## 남의 대화·만료 대화는 404다

    ``POST /chat``과 **같은 조건, 같은 코드**다 — 403이나 410을 두면 「있지만 네 것이
    아니다」·「있었지만 만료됐다」가 새어 존재 여부를 알린다. 로그아웃 뒤 다른 계정으로
    들어온 탭이 앞 계정의 번호를 들고 와도 여기서 끊긴다.

    ## 둘러보기 계정에는 언제나 404다

    둘러보기(``auth/tour_policy.py``)는 ``GET``을 통과시키지만 **공유 계정**이라 「본인
    대화」가 성립하지 않는다 — 정책 도입 전에 남은 대화가 있으면 방문자 누구에게나 보이게
    된다. 그래서 주인 확인과 별개로 여기서 끊는다. 지금은 ``POST /chat``이 막혀 새 대화가
    생기지 않지만, 그 사실에 기대지 않는다.

    ## 한도 버킷은 ``chat``이 아니다

    ``GET /chat/status``와 같은 이유(`#1535`) — 패널을 열 때 부르는 조회가 질문 한도를
    깎으면 안 된다. 기본 버킷에 든다.
    """
    if is_tour_user(user):
        raise NotFoundError("대화를 찾을 수 없습니다.")
    chat_session = await chat_repo.get_session_row(session, session_id=session_id)
    if (
        chat_session is None
        or chat_session.user_id != user.id
        or chat_repo.is_expired(chat_session)
    ):
        raise NotFoundError("대화를 찾을 수 없습니다.")

    messages = await chat_history(session, chat_session_id=chat_session.id)

    state = getattr(request, "state", None)
    return {
        "data": {
            "session_id": str(chat_session.id),
            "messages": messages,
            # 면책은 조회에도 붙는다 — 화면이 되살린 답 아래에 같은 문구를 다시 세운다.
            "disclaimer": DISCLAIMER,
        },
        "meta": {
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_chat_session(
    request: Request,
    session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AppUser, Depends(get_current_user)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    """대화 하나를 지운다 (``API_SPEC §15.6`` · `#1330`).

    ``PRD §16.3``이 「GDPR 유사 삭제 요청 지원」을 적는데 **응할 경로가 없었다** —
    지우는 것은 90일 만료 일괄 삭제뿐이었고, 사용자가 「이 대화를 지워 달라」고 하면
    **기다리라는 말밖에 할 수 없었다.**

    ## 남의 대화는 404다

    ``POST /chat``이 조회에서 쓰는 규칙과 같다. 403은 「있지만 네 것이 아니다」를
    알려 주어 id를 바꿔 가며 **남의 대화가 존재하는지** 알아낼 수 있게 한다.
    주인 조건은 ``DELETE``문 자체에 들어가므로(``chat_repo.delete_one``) 먼저 조회해
    확인하는 갈래가 없다 — 조건을 두 곳에 적지 않는다.

    ## 메시지는 따라 지워진다

    ``chat_message.session_id``가 ``ON DELETE CASCADE``다. 세션만 지우고 메시지가
    남으면 **「지웠다」가 거짓**이 된다.
    """
    deleted = await chat_repo.delete_one(session, session_id=session_id, user_id=user.id)
    if not deleted:
        raise NotFoundError("대화를 찾을 수 없습니다.")

    await audit_svc.record_chat_delete(
        session,
        user_id=str(user.id),
        session_id=session_id,
        ip_address=audit_client_ip(request),
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/chat/favorites")
async def chat_favorites(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AppUser, Depends(get_current_user)],
) -> dict[str, object]:
    """내 즐겨찾기 답 목록 (``API_SPEC §15.9`` · `#2405`).

    최근에 단 것부터 **전부**이고(건수 상한 없음 — 화면이 이 번호로 별을 칠한다), 만료된
    대화의 것은 뺀다.

    ## 둘러보기 계정에는 언제나 빈 목록이다

    ``GET``이라 둘러보기 정책(``auth/tour_policy.py``)을 통과한다. 공유 계정이라 「내
    즐겨찾기」가 성립하지 않으므로 대화 불러오기(``§15.8``)의 404와 같은 이유로 여기서
    끊는다 — 목록은 「없음」이 정상 상태라 404가 아니라 빈 목록이다.
    """
    items = [] if is_tour_user(user) else await list_favorites(session, user_id=user.id)

    state = getattr(request, "state", None)
    return {
        "data": {"favorites": items},
        "meta": {
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }


@router.put("/chat/messages/{message_id}/favorite")
async def favorite_chat_message(
    request: Request,
    message_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AppUser, Depends(get_current_user)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """답 한 건에 별을 단다 (``API_SPEC §15.9`` · `#2405`).

    이미 달려 있으면 시각을 바꾸지 않고 같은 200이다. 남의 것·만료·질문 행·없는 번호는
    모두 같은 404다. 감사 기록은 남기지 않는다(결정 4 — 자료를 바꾸지 않는 보기 설정이다).
    둘러보기 계정의 쓰기는 정책 미들웨어가 어시스턴트 전용 403으로 먼저 막는다.
    """
    data = await favorite_answer(session, message_id=message_id, user_id=user.id)
    await session.commit()

    state = getattr(request, "state", None)
    return {
        "data": data,
        "meta": {
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }


@router.delete("/chat/messages/{message_id}/favorite", status_code=204)
async def unfavorite_chat_message(
    message_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AppUser, Depends(get_current_user)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    """답의 별을 뗀다 (``API_SPEC §15.9`` · `#2405`). 달려 있지 않아도 같은 204다."""
    await unfavorite_answer(session, message_id=message_id, user_id=user.id)
    await session.commit()
    return Response(status_code=204)
