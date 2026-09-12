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

import json

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.api.routes.chat import get_provider
from cii_platform.llm.provider import FakeProvider, LLMResponse, ToolCall
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
                await s.execute(text("SELECT role FROM chat_message ORDER BY sent_at"))
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
                            "SELECT action, details_json FROM audit_log "
                            "WHERE action LIKE 'CHAT_%' ORDER BY \"timestamp\""
                        )
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
                    text("SELECT count(*) FROM chat_message WHERE session_id = :sid"),
                    {"sid": session_id},
                )
            ).scalar_one()
            assert count == 4
    finally:
        await _cleanup()
