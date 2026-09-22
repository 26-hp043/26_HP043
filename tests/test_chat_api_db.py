"""챗봇 엔드포인트 끝에서 끝까지 (`#121` · IT-CHAT-024~033).

``FakeProvider``를 끼워 **외부 모델 없이** 오케스트레이션 전부를 검사한다 — CI가
바깥과 말하면 과금되고 비결정적이 된다(``llm/provider.py`` 머리말).

## 여기서만 잡히는 것

가드 하나하나는 ``test_llm_guard.py``가 본다. 이 파일이 보는 것은 **가드가 실제
경로에 꽂혀 있는가**다. 함수가 있어도 부르지 않으면 아무것도 막지 못한다 — `#121`의
가장 큰 위험이 그것이다.

``app_fresh_engine``(NullPool) + 커밋 기반 — TestClient 포털 루프와 fixture 루프의
연결 충돌을 피한다(``conftest`` 참조).
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from cii_platform.api.main import app
from cii_platform.api.routes.chat import get_provider
from cii_platform.db.types import JSONText, UuidText
from cii_platform.llm.provider import FakeProvider, LLMResponse, ToolCall
from cii_platform.services import chat as chat_service
from cii_platform.services.chat import (
    DISCARDED_MESSAGE,
    DISCLAIMER,
    REFUSAL_MESSAGE,
    TOOL_BUDGET_MESSAGE,
    TRUNCATED_MESSAGE,
)

_BASE = "https://testserver"


def _use(provider: FakeProvider) -> None:
    app.dependency_overrides[get_provider] = lambda: provider


async def _cleanup() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    app.dependency_overrides.pop(get_provider, None)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(
            text(
                "DELETE FROM chat_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM audit_log"))
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
        await s.commit()
    await get_engine().dispose()


def _login(client: TestClient) -> dict[str, str]:
    assert client.post("/api/v1/auth/dev-login").status_code == 200
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def test_plain_answer_carries_the_canonical_disclaimer(migrated_db, app_fresh_engine):
    """IT-CHAT-024 — 도구를 부르지 않는 답도 **면책을 달고 나간다**.

    ``PRD §6.3`` 챗봇 행의 문구와 **글자 그대로** 같은지 본다. 화면과 정본이 다른
    말을 하면 면책이 면책 구실을 못 한다.
    """
    _use(FakeProvider([LLMResponse(text="등급은 화면에서 확인하실 수 있습니다.")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post("/api/v1/chat", json={"message": "안녕하세요"}, headers=headers)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["disclaimer"] == DISCLAIMER
            assert data["discarded"] is False
            assert data["tool_calls"] == []
            assert data["session_id"]
    finally:
        await _cleanup()


async def test_the_response_keys_are_exactly_what_the_contract_lists(migrated_db, app_fresh_engine):
    """`API_SPEC §15.1` 응답 표 ↔ **실제 `data` 키 집합** (`#1365`).

    종전 계약 검사는 **값 몇 개만** 보았다 — 그래서 표에 없는 키가 늘어도 통과했고,
    실제로 `tool_output_count`가 그렇게 실려 나가고 있었다. 「빠진 키」는 화면이
    깨져서 드러나지만 **「늘어난 키」는 아무 데서도 드러나지 않는다.**

    키 이름을 정본에서 읽지 않고 여기 적는 이유는, `§15.1` 표가 `data.` 접두를
    쓰는 산문 표라 기계가 읽으면 설명 문장의 백틱까지 키로 잡기 때문이다. 대신
    **표와 이 목록이 갈리면 리뷰에서 보이도록** 한자리에 모아 둔다.
    """
    contract = {
        "session_id",
        "answer",
        "disclaimer",
        "tool_calls",
        "discarded",
        "vessel_resolved",
    }
    _use(FakeProvider([LLMResponse(text="등급은 화면에서 확인하실 수 있습니다.")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post("/api/v1/chat", json={"message": "안녕하세요"}, headers=headers)

            assert response.status_code == 200
            assert set(response.json()["data"]) == contract
    finally:
        await _cleanup()


async def test_a_discarded_turn_carries_the_same_keys(migrated_db, app_fresh_engine):
    """**폐기한 턴도 키가 같다** (`#1365`).

    폐기 경로는 `_result(...)`를 여러 자리에서 따로 부른다 — 한 자리만 고치면
    「어떤 답은 키가 다른」 상태가 된다. 화면은 그 차이를 모르고 읽는다.
    """
    _use(FakeProvider([LLMResponse(text="attained CII는 4.98입니다.")]))  # 도구 없이 수치
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post("/api/v1/chat", json={"message": "등급은?"}, headers=headers)

            data = response.json()["data"]
            assert data["discarded"] is True, data
            assert set(data) == {
                "session_id",
                "answer",
                "disclaimer",
                "tool_calls",
                "discarded",
                "vessel_resolved",
            }
    finally:
        await _cleanup()


async def test_disclaimer_matches_the_prd_table(migrated_db, app_fresh_engine):
    """IT-CHAT-025 — 면책 문구가 ``PRD §6.3`` 표에서 온 것인지 **문서와 대조**한다.

    상수를 고치면서 정본을 잊는 것을 막는다. 사람이 눈으로 대조할 종류가 아니다.
    """
    from pathlib import Path

    prd = (Path(__file__).resolve().parents[1] / "PRD.md").read_text(encoding="utf-8")
    assert f"`{DISCLAIMER}`" in prd


async def test_tool_call_result_reaches_the_answer(migrated_db, app_fresh_engine):
    """IT-CHAT-026 — 도구를 부르고 **그 결과로** 답을 만든다.

    모델이 인용한 수치가 도구 응답에 있으므로 수학 가드를 통과한다.
    """
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=(ToolCall(name="search_vessel", arguments={"name": "DEMO"}),)),
            LLMResponse(text="조건에 맞는 선박을 찾았습니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat", json={"message": "DEMO 선박 찾아줘"}, headers=headers
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["tool_calls"] == ["search_vessel"]
            assert data["discarded"] is False
    finally:
        await _cleanup()


async def test_search_vessel_never_sends_names_to_the_model(migrated_db, app_fresh_engine):
    """IT-CHAT-027 — ⚠️ **선박명이 모델에게 가지 않는다** (``PRD §16.3.1``).

    ``FakeProvider``가 받은 메시지를 그대로 들고 있으므로, **실제로 나간 것**을 본다.
    도구 응답에 척수만 들어 있는지 확인한다 — 이름이 섞이면 화이트리스트가 도구
    하나로 뚫린다.
    """
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=(ToolCall(name="search_vessel", arguments={"name": "DEMO"}),)),
            LLMResponse(text="찾았습니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            assert (
                client.post(
                    "/api/v1/chat", json={"message": "DEMO 찾아줘"}, headers=headers
                ).status_code
                == 200
            )

        # 두 번째 호출의 메시지에 도구 응답이 `tool_result` 블록으로 실려 있다.
        sent = provider.calls[-1]
        results = [
            block
            for message in sent
            if isinstance(message["content"], list)
            for block in message["content"]
            if block.get("type") == "tool_result"
        ]
        assert results, sent
        body = json.loads(results[-1]["content"])
        assert set(body["result"]) == {"matched"}

        # ⚠️ **`tool_result`에만** 단언한다. 「DEMO」는 사용자가 친 문장과 모델이
        # 그로부터 만든 `tool_use` 인자에도 있는데, 둘 다 `PRD §16.3.1`이 「보내도
        # 되는 것」 첫 행으로 **대상 밖**에 둔 값이다(본인 입력). 우리가 붙이는 것은
        # `tool_result`뿐이고, 거기에 이름이 섞이면 화이트리스트가 뚫린다.
        assert "DEMO" not in json.dumps(results, ensure_ascii=False, default=str)
    finally:
        await _cleanup()


async def test_tool_round_trip_is_sent_as_a_pair(migrated_db, app_fresh_engine):
    """IT-CHAT-056 — ⚠️ 오케스트레이션이 **짝으로** 만든다.

    ``IT-CHAT-053``은 공급자가 받은 것을 그대로 보내는지 본다. 이 검사는 **누가 그
    모양을 만드는가** — ``services/chat.py``가 모델의 ``tool_use``를 되돌려 넣고
    ``tool_result``로 답하는지 — 를 본다.

    둘이 다 필요하다. 종전 코드는 도구 결과를 **평범한 `user` 문장**으로 보냈는데,
    공급자 검사만 있으면 그 상태로도 통과한다(공급자는 받은 대로 보내기 때문이다).
    """
    provider = FakeProvider(
        [
            LLMResponse(
                text="찾아보겠습니다.",
                tool_calls=(ToolCall(name="search_vessel", arguments={"name": "A"}, id="toolu_7"),),
            ),
            LLMResponse(text="찾았습니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            assert (
                client.post(
                    "/api/v1/chat", json={"message": "A 찾아줘"}, headers=headers
                ).status_code
                == 200
            )

        sent = provider.calls[-1]
        # 모델의 `tool_use`가 assistant 턴으로 되돌아가 있다.
        assistant = [m for m in sent if m["role"] == "assistant"]
        uses = [
            block
            for m in assistant
            if isinstance(m["content"], list)
            for block in m["content"]
            if block.get("type") == "tool_use"
        ]
        assert len(uses) == 1, sent
        assert uses[0]["id"] == "toolu_7"

        # 그 바로 뒤 user 턴이 같은 id의 `tool_result`다.
        results = [
            block
            for m in sent
            if m["role"] == "user" and isinstance(m["content"], list)
            for block in m["content"]
            if block.get("type") == "tool_result"
        ]
        assert len(results) == 1, sent
        assert results[0]["tool_use_id"] == "toolu_7"
    finally:
        await _cleanup()


async def test_fabricated_number_is_discarded(migrated_db, app_fresh_engine):
    """IT-CHAT-028 — ⚠️ **모델이 지어낸 수치가 나가지 않는다** (`Q20` · ``PRD §16.3``).

    도구를 부르지 않았는데 수치를 말하면 **버린다.** 200을 내되 ``discarded``로
    사실을 드러낸다(``API_SPEC §15.2``).
    """
    _use(FakeProvider([LLMResponse(text="attained CII는 4.98입니다.")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat", json={"message": "지금 수치 알려줘"}, headers=headers
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["discarded"] is True
            assert data["answer"] == DISCARDED_MESSAGE
            assert data["disclaimer"] == DISCLAIMER
    finally:
        await _cleanup()


async def test_discarded_answer_is_not_stored(migrated_db, app_fresh_engine):
    """IT-CHAT-029 — 버린 답은 **이력에도 남지 않는다**.

    남기면 다음 턴이 그것을 근거로 삼는다 — 한 번의 지어냄이 대화 전체로 번진다.
    """
    _use(FakeProvider([LLMResponse(text="required CII는 5.04입니다.")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            assert (
                client.post("/api/v1/chat", json={"message": "알려줘"}, headers=headers).status_code
                == 200
            )

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            roles = (
                await s.execute(text('SELECT "role" FROM chat_message ORDER BY sent_at'))
            ).scalars()
            assert list(roles) == ["USER"]
    finally:
        await _cleanup()


async def test_truncated_answer_is_discarded(migrated_db, app_fresh_engine):
    """IT-CHAT-058 — ⚠️ **출력 상한에서 잘린 답을 보이지 않는다**.

    문장 중간에서 끊긴 설명은 **뜻이 뒤집힐 수 있다**(「등급은 C가 아니라」에서
    끊기면). 그런데 화면은 그것을 **완성된 답으로** 그린다.

    벤더 문서는 `max_tokens`를 올리거나 이어 받으라고 적지만 **둘 다 하지 않는다** —
    출력 상한은 `PRD §16.1` 가드 1이고, 이어 받는 것은 왕복을 늘려 가드 2와 부딪힌다.
    """
    _use(FakeProvider([LLMResponse(text="등급은 C가 아니라", stop_reason="max_tokens")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post("/api/v1/chat", json={"message": "설명해줘"}, headers=headers)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["discarded"] is True
            assert data["answer"] == TRUNCATED_MESSAGE
    finally:
        await _cleanup()


async def test_truncated_tool_call_is_not_executed(migrated_db, app_fresh_engine):
    """IT-CHAT-059 — ⚠️ **잘린 응답으로는 도구도 돌리지 않는다**.

    잘린 `tool_use` 블록은 **인자까지 잘려** 있을 수 있다(벤더 문서). 그대로 돌리면
    **엉뚱한 값으로 계산**하고, ⚠️ **그 결과는 수학 검증을 통과한다** — 도구가 실제로
    낸 값이기 때문이다. 가드가 못 잡는 자리라 여기서 막는다.
    """
    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=(ToolCall(name="search_vessel", arguments={"name": "A"}, id="t1"),),
                stop_reason="max_tokens",
            )
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            data = client.post("/api/v1/chat", json={"message": "찾아줘"}, headers=headers).json()[
                "data"
            ]
            assert data["discarded"] is True
            # 도구를 **부르지 않았다**.
            assert data["tool_calls"] == []
    finally:
        await _cleanup()


async def test_refusal_is_reported_without_inventing_a_reason(migrated_db, app_fresh_engine):
    """IT-CHAT-060 — 모델이 거절하면 **사유를 지어내지 않는다**.

    「왜 거절했는지」는 우리가 모른다. 추측해 적으면 그것이 곧 지어낸 말이다.
    """
    _use(FakeProvider([LLMResponse(text="", stop_reason="refusal")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            data = client.post("/api/v1/chat", json={"message": "..."}, headers=headers).json()[
                "data"
            ]
            assert data["discarded"] is True
            assert data["answer"] == REFUSAL_MESSAGE
    finally:
        await _cleanup()


async def test_tool_budget_stops_the_turn(migrated_db, app_fresh_engine):
    """IT-CHAT-030 — 도구 호출 상한을 넘으면 **거기서 끊는다** (``PRD §16.1`` 가드 2).

    ⚠️ 비용 폭주의 실제 경로다 — 모델이 도구를 잘못 골라 왕복을 반복하면 토큰
    상한이 걸려 있어도 총액이 횟수만큼 곱해진다.
    """
    call = LLMResponse(tool_calls=(ToolCall(name="search_vessel", arguments={"name": "A"}),))
    _use(FakeProvider([call, call, call, call, call]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post("/api/v1/chat", json={"message": "계속 찾아"}, headers=headers)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["discarded"] is True
            assert data["answer"] == TOOL_BUDGET_MESSAGE
            assert len(data["tool_calls"]) <= 3
    finally:
        await _cleanup()


async def test_every_turn_is_audited(migrated_db, app_fresh_engine):
    """IT-CHAT-031 — 메시지와 도구 호출이 **감사 로그에 남는다** (`#120` 완료 기준).

    본문은 남지 않는다 — 해시와 길이만이다(`Q8`). 본문은 ``chat_message``에 있고
    90일 뒤 지워진다.
    """
    _use(
        FakeProvider(
            [
                LLMResponse(
                    tool_calls=(ToolCall(name="search_vessel", arguments={"name": "DEMO"}),)
                ),
                LLMResponse(text="찾았습니다."),
            ]
        )
    )
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            assert (
                client.post(
                    "/api/v1/chat", json={"message": "DEMO 찾아줘"}, headers=headers
                ).status_code
                == 200
            )

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            rows = (
                (
                    await s.execute(
                        text(
                            'SELECT "action", details_json FROM audit_log '
                            'WHERE "action" LIKE \'CHAT_%\' ORDER BY "timestamp"'
                            # raw SQL에는 컬럼 타입이 붙지 않아 `JSONText`의 result
                            # processor가 돌지 않는다 — 문자열이 온다 (`#1058`).
                        ).columns(details_json=JSONText())
                    )
                )
                .mappings()
                .all()
            )
            actions = [row["action"] for row in rows]
            assert actions.count("CHAT_MESSAGE") == 2
            assert "CHAT_TOOL_CALL" in actions
            for row in rows:
                # 본문도 인자도 그대로 남지 않는다.
                assert "DEMO" not in json.dumps(row["details_json"], ensure_ascii=False)
    finally:
        await _cleanup()


async def test_another_users_session_is_not_found(migrated_db, app_fresh_engine):
    """IT-CHAT-032 — 남의 대화는 **404**다 (``API_SPEC §15.4``).

    403은 「있지만 네 것이 아니다」를 알려 주어, id를 바꿔 가며 남의 대화가 존재하는지
    알아낼 수 있게 한다.
    """
    _use(FakeProvider([LLMResponse(text="네.")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat",
                json={
                    "message": "안녕",
                    "session_id": "00000000-0000-4000-8000-000000000000",
                },
                headers=headers,
            )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup()


async def test_history_window_always_starts_with_a_question(migrated_db, app_fresh_engine):
    """IT-CHAT-061 — ⚠️ 이력 창이 **질문부터 시작한다**.

    ``list_messages(limit=…)``는 **최근 N건**을 준다. 대화가 `U A U A …`로 쌓이므로
    N이 짝수면 **4번째 질문부터 창이 답변으로 시작한다.**

    .. code-block:: text

        3번째 질문   U A U A U        창 = U A U A U
        4번째 질문   U A U A U A U    창 =   A U A U A U   ← 답변으로 시작

    그 창은 **질문이 잘려 나간 답변**으로 대화를 연다. 모델은 무엇에 대한 답인지
    모른 채 그것을 맥락으로 삼는다 — 수치를 인용하는 제품에서 특히 나쁘다.

    네 번을 주고받아 그 지점을 실제로 지난다.
    """
    _use(FakeProvider([LLMResponse(text=f"{i}번째 답입니다.") for i in range(1, 6)]))
    provider = app.dependency_overrides[get_provider]()
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            session_id = None
            for i in range(1, 5):
                body = {"message": f"{i}번째 질문"}
                if session_id:
                    body["session_id"] = session_id
                data = client.post("/api/v1/chat", json=body, headers=headers).json()["data"]
                session_id = data["session_id"]

        sent = provider.calls[-1]
        # 첫 줄은 역할 지시문이고, 그다음이 대화의 시작이다.
        assert sent[0]["role"] == "system"
        assert sent[1]["role"] == "user", [m["role"] for m in sent]
    finally:
        await _cleanup()


async def test_history_is_kept_across_turns(migrated_db, app_fresh_engine):
    """IT-CHAT-033 — ``session_id``를 다시 주면 **이전 대화를 싣고** 부른다 (`#121`)."""
    _use(FakeProvider([LLMResponse(text="첫 답입니다."), LLMResponse(text="둘째 답입니다.")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            first = client.post("/api/v1/chat", json={"message": "첫 질문"}, headers=headers)
            session_id = first.json()["data"]["session_id"]
            second = client.post(
                "/api/v1/chat",
                json={"message": "둘째 질문", "session_id": session_id},
                headers=headers,
            )
            assert second.status_code == 200
            assert second.json()["data"]["session_id"] == session_id

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            count = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM chat_message WHERE session_id = :sid"
                        # 응답의 `session_id`는 대시 36자, 저장 형식은 hex 32자다. 타입을
                        # 붙이지 않으면 **오류가 아니라 0건**이 온다 (`#1058`).
                    ).bindparams(bindparam("sid", type_=UuidText())),
                    {"sid": session_id},
                )
            ).scalar_one()
            assert count == 4
    finally:
        await _cleanup()


async def test_search_resolution_carries_into_the_next_tool_and_response(
    migrated_db, app_fresh_engine
):
    """#1242 — 고유 일치 검색 → 같은 턴의 계산 도구가 그 선박으로 돈다 + 응답 표시.

    데모 선박 이름은 전부 「샘플」을 포함한다 — 고유 키워드로 쓴다. 계산 도구는
    귀속이 없으면 「어느 선박인지 먼저 정해야 합니다」 error를 내므로, 결과가 나왔다는
    것 자체가 귀속이 흘렀다는 증거다.
    """
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=(ToolCall(name="search_vessel", arguments={"name": "로로"}),)),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="calc_voyage_cii",
                        arguments={
                            "distance_nm": 1000,
                            "speed_kn": 12,
                            "fuel_ton": 100,
                            "fuel_type": "HFO",
                        },
                    ),
                )
            ),
            LLMResponse(text="계산했습니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat", json={"message": "로로 여객선 CII 계산해줘"}, headers=headers
            )
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            assert data["tool_calls"] == ["search_vessel", "calc_voyage_cii"]
            # 두 번째 도구의 오류 봉투가 아니라 실제 계산이 돌았다 — 대화 귀속이 흘렀다.
            assert "어느 선박인지" not in json.dumps(data, ensure_ascii=False)
            assert data["vessel_resolved"] is True
            assert "vessel_id" not in data, "식별자가 응답에 실렸다 — 16.3.1 위반"
    finally:
        await _cleanup()


async def test_no_vessel_anywhere_reports_unresolved(migrated_db, app_fresh_engine):
    """#1242 — 어디에도 선박이 없으면 `vessel_resolved: false` — 계산 도구는 안내 error."""
    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="calc_voyage_cii",
                        arguments={
                            "distance_nm": 1000,
                            "speed_kn": 12,
                            "fuel_ton": 100,
                            "fuel_type": "HFO",
                        },
                    ),
                )
            ),
            LLMResponse(text="선박을 먼저 정해야 한다고 안내했습니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat", json={"message": "CII 계산해줘"}, headers=headers
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["vessel_resolved"] is False
    finally:
        await _cleanup()


async def test_screen_vessel_wins_over_session_vessel(migrated_db, app_fresh_engine):
    """IT-CHAT-062 (#1243) — 세션에 A가 있어도 요청이 B면 B로 계산하고 세션은 A 그대로."""
    from cii_platform.db.repositories import chat as chat_repo
    from cii_platform.db.session import get_sessionmaker

    provider = FakeProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="calc_voyage_cii",
                        arguments={
                            "distance_nm": 1000,
                            "speed_kn": 12,
                            "fuel_ton": 100,
                            "fuel_type": "HFO",
                        },
                    ),
                )
            ),
            LLMResponse(text="계산했습니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            first = client.post("/api/v1/chat", json={"message": "대화 시작"}, headers=headers)
            assert first.status_code == 200
            session_id = first.json()["data"]["session_id"]

            async with get_sessionmaker()() as db:
                # A(로로 여객선)를 세션 귀속으로, B(벌크선 30,000)를 요청값으로 쓴다.
                ids = dict(
                    (
                        await db.execute(
                            text(
                                "SELECT name, CAST(id AS CHAR(32)) FROM vessel "
                                "WHERE name LIKE '%로로%' OR name LIKE '%30,000 DWT)%'"
                            )
                        )
                    ).all()
                )
                roro_name = next(n for n in ids if "로로" in n)
                bulk_name = next(n for n in ids if "30,000" in n)
                await chat_repo.set_vessel(
                    db, session_id=UUID(session_id), vessel_id=UUID(ids[roro_name])
                )
                await db.commit()
                bulk_id = ids[bulk_name]

            resp = client.post(
                "/api/v1/chat",
                json={
                    "message": "이 선박 CII 계산해줘",
                    "session_id": session_id,
                    "vessel_id": bulk_id,
                },
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["vessel_resolved"] is True

            # 세션 귀속은 A 그대로 — 요청값이 세션을 덮어쓰지 않는다(#1243 정정).
            async with get_sessionmaker()() as db:
                row = await chat_repo.get_session_row(db, session_id=UUID(session_id))
                assert str(row.vessel_id).replace("-", "") == ids[roro_name], (
                    "요청값이 세션 귀속을 덮어썼다"  # hex 32 vs 대시 36 표기 차이만 제외
                )
    finally:
        await _cleanup()


async def test_found_vessel_survives_to_the_next_turn(migrated_db, app_fresh_engine):
    """IT-CHAT-063 (#1243) — 1턴에서 찾은 선박이 2턴에서 vessel_id 없이도 계산된다."""
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=(ToolCall(name="search_vessel", arguments={"name": "로로"}),)),
            LLMResponse(text="찾았습니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            first = client.post(
                "/api/v1/chat", json={"message": "로로 여객선 찾아줘"}, headers=headers
            )
            session_id = first.json()["data"]["session_id"]
            assert first.json()["data"]["vessel_resolved"] is True

            _use(
                FakeProvider(
                    [
                        LLMResponse(
                            tool_calls=(
                                ToolCall(
                                    name="calc_voyage_cii",
                                    arguments={
                                        "distance_nm": 1000,
                                        "speed_kn": 12,
                                        "fuel_ton": 100,
                                        "fuel_type": "HFO",
                                    },
                                ),
                            )
                        ),
                        LLMResponse(text="계산했습니다."),
                    ]
                )
            )
            second = client.post(
                "/api/v1/chat",
                json={"message": "그 선박 CII 계산해줘", "session_id": session_id},
                headers=headers,
            )
            assert second.status_code == 200
            data = second.json()["data"]
            assert data["tool_calls"] == ["calc_voyage_cii"]
            assert "어느 선박인지" not in json.dumps(data, ensure_ascii=False)
            assert data["vessel_resolved"] is True
    finally:
        await _cleanup()


async def test_follow_up_question_can_cite_the_previous_answer(migrated_db, app_fresh_engine):
    """IT-CHAT-064 (#1244) — 2턴 답이 1턴 수치를 인용해도 폐기되지 않는다."""
    provider = FakeProvider(
        [
            # 1턴 — 검색으로 선박을 정하고(#1243) 계산한다(로로 여객선 실측: 12.456).
            LLMResponse(tool_calls=(ToolCall(name="search_vessel", arguments={"name": "로로"}),)),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="calc_voyage_cii",
                        arguments={
                            "distance_nm": 1000,
                            "speed_kn": 12,
                            "fuel_ton": 100,
                            "fuel_type": "HFO",
                        },
                    ),
                )
            ),
            LLMResponse(text="attained CII는 12.456이고 등급은 A입니다."),
        ]
    )
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            first = client.post(
                "/api/v1/chat", json={"message": "계산 결과 알려줘"}, headers=headers
            )
            # 1턴이 폐기됐으면 이 검사의 전제가 무너진다 — 먼저 잠근다.
            assert first.json()["data"]["discarded"] is False, first.text
            session_id = first.json()["data"]["session_id"]

            # 2턴 — 도구 없이 **이전 답의 수치를 그대로** 인용한다(#1244).
            _use(FakeProvider([LLMResponse(text="네, attained CII는 12.456이 맞습니다.")]))
            second = client.post(
                "/api/v1/chat",
                json={"message": "그 수치가 맞나요?", "session_id": session_id},
                headers=headers,
            )
            data = second.json()["data"]
            assert data["discarded"] is False, f"이전 답의 수치 인용이 폐기됐다: {data['answer']}"
    finally:
        await _cleanup()


async def test_user_numbers_do_not_become_verified(migrated_db, app_fresh_engine):
    """#1244 — user 메시지의 수는 허용 집합에 들어가지 않는다.

    사용자가 지어낸 수를 모델이 되풀이하면 그것이 「검증된 답」이 되므로 폐기다.
    프롬프트 규칙과 이력 인용 허용(#1244)이 만나 가장 흔해질 경로다.
    """
    _use(FakeProvider([LLMResponse(text="네, 7.3이 맞습니다.")]))
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            resp = client.post(
                "/api/v1/chat",
                json={"message": "내 CII가 7.3인데 맞나요?"},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["data"]["discarded"] is True, "사용자가 친 수가 검증을 통과했다"
    finally:
        await _cleanup()


async def test_slow_provider_is_discarded_within_the_turn_budget(
    migrated_db, app_fresh_engine, monkeypatch
):
    """IT-CHAT-065 (#1245) — 상한을 넘는 턴은 discarded로 끝난다.

    운영 상한(45초)을 그대로 쓰면 검사가 45초를 기다린다 — 주입 예산(0.05초)으로
    줄인다. 느린 공급자는 실제로 자는 것으로 재현한다.
    """

    class SlowProvider:
        async def complete(self, *, messages, **_k):  # noqa: ANN001, ANN003
            await asyncio.sleep(0.3)
            raise AssertionError("예산 안에 끊기지 못했다")

    _use(SlowProvider())  # type: ignore[arg-type]
    # 운영 상한(45초)을 그대로 두면 검사가 45초를 기다린다 — 기본값만 짧게.
    monkeypatch.setattr(chat_service, "TURN_TIMEOUT_SECONDS", 0.05)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            resp = client.post(
                "/api/v1/chat",
                json={"message": "느리게 답해줘"},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["discarded"] is True
            assert "초과" in data["answer"], "무엇이 일어났는지 말하지 않는다"
            assert data["disclaimer"], "폐기에도 면책은 붙는다(#121 완료 기준)"
    finally:
        await _cleanup()


async def test_turn_budget_default_comes_from_the_provider_constant():
    """#1245 — 운영 기본 예산은 provider의 상수 그대로다(주입이 새 경로를 못 만든다).

    느린 경로 검사는 예산을 0.05초로 패치해서 본다 — 그 탓에 「기본값이 실제로
    45초」는別도 잠가야 한다. 상한의 성질만 본다(45초를 기다리지 않는다):
    공급자 상수와 같고, 최악 경로(2분)보다 작다.
    """
    from cii_platform.llm.provider import TURN_TIMEOUT_SECONDS

    assert chat_service.TURN_TIMEOUT_SECONDS == TURN_TIMEOUT_SECONDS
    assert 0 < TURN_TIMEOUT_SECONDS < 30.0 * 4, "최악 경로보다 커지면 가드가 아니다"


async def test_status_needs_login_and_answers_a_boolean(migrated_db, app_fresh_engine, monkeypatch):
    """`#1535` · ``API_SPEC §15.7`` — 로그인이 필요하고 ``available`` 불린 **하나만** 낸다.

    화면은 패널을 여는 순간 이것을 부른다. 키 값이나 꺼진 이유가 실리면 사용자가
    고칠 수 없는 운영 정보가 화면으로 나간다.
    """
    monkeypatch.delenv("LLM_AUTH_SCHEME", raising=False)
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.get("/api/v1/chat/status").status_code == 401

            _login(client)
            monkeypatch.setenv("LLM_API_KEY", "-")
            off = client.get("/api/v1/chat/status")
            assert off.status_code == 200
            assert off.json()["data"] == {"available": False}

            monkeypatch.setenv("LLM_API_KEY", "real-looking-key")
            on = client.get("/api/v1/chat/status")
            assert on.json()["data"] == {"available": True}
            assert "real-looking-key" not in on.text
    finally:
        await _cleanup()


async def test_placeholder_key_is_503_not_an_outbound_call(
    migrated_db, app_fresh_engine, monkeypatch
):
    """`#1535` — 자리표시자 키로 질문하면 **외부를 부르지 않고 503**이다.

    종전에는 ``-``를 키로 보내 인증 실패 → ``discarded``로 끝나며 질문만 이력에 쌓였다.
    """
    monkeypatch.setenv("LLM_API_KEY", "-")
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post("/api/v1/chat", json={"message": "안녕하세요"}, headers=headers)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "CHAT_UNAVAILABLE"
    finally:
        await _cleanup()
