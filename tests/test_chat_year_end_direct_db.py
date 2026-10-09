"""예시 질문 「올해 연말 예상 등급」 — 도구를 먼저, 모델은 한 번만 (`#2289` · 10-09 결정).

종전 경로는 모델을 두 번 기다린다(어느 도구를 부를지 · 결과로 문장 쓰기). 같은 질문의 응답이
7~45초를 오가고 턴 시간 초과로 폐기되기도 했다. 이 예시 질문은 서버가 ``project_year_end``를
먼저 돌리고 **문장 쓰기 한 번만** 모델에게 묻는다. 여기서 보는 것은 넷이다.

1. 선박이 정해져 있으면 모델을 **정확히 한 번** 부르고, 그 호출은 **종전 경로의 두 번째
   호출과 같은 메시지**다(`#2289` 후속 — 답 형식을 종전과 같게. #2388의 평문 한 덩어리 ·
   도구 정의 없음은 답을 결론 한 줄로 만들었다).
2. 답은 모델이 쓴 문장 그대로다 — 서버가 문장을 바꾸지 않는다.
3. 모델이 늦거나 · 실패하거나 · 도구에 없는 수치를 쓰면 **계산 결과 문장으로 대신 답하고**
   마지막 줄에 그 사실을 적는다. 오류로 끝나지 않는다.
4. 선박이 없거나 다른 문장이면 **종전 모델 경로**로 간다.

``app_fresh_engine``(NullPool) + 커밋 기반 — ``test_chat_api_db.py``와 같은 구성이다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.api.routes.chat import get_provider
from cii_platform.db.demo_seed import VESSEL_ID_BULK
from cii_platform.llm.provider import FakeProvider, LLMError, LLMResponse, ToolCall
from cii_platform.services import chat as chat_service
from cii_platform.services import cii_current
from cii_platform.services.chat import (
    DIRECT_ANSWER_NOTE,
    DIRECT_FALLBACK_NOTE,
    YEAR_END_EXAMPLE_QUESTION,
    _year_end_text,
    is_year_end_example,
)

_BASE = "https://testserver"
_MODEL_TEXT = "선택하신 선박의 올해 연말 예상은 화면의 실시간 CII에서 자세히 보실 수 있습니다."


class _RecordingProvider(FakeProvider):
    """받은 ``tools``까지 남긴다 — 바로 경로가 종전 경로와 같은 도구 정의를 보내는지 본다."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__(responses)
        self.tools_sent: list[object] = []

    async def complete(self, *, messages, tools=None):  # type: ignore[override]
        self.tools_sent.append(tools)
        return await super().complete(messages=messages, tools=tools)


class _SlowProvider(FakeProvider):
    async def complete(self, *, messages, tools=None):  # type: ignore[override]
        self.calls.append([dict(m) for m in messages])
        await asyncio.sleep(2)
        return LLMResponse(text=_MODEL_TEXT)


class _FailingProvider(FakeProvider):
    async def complete(self, *, messages, tools=None):  # type: ignore[override]
        self.calls.append([dict(m) for m in messages])
        raise LLMError("공급자 실패")


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


def _ask_example(provider: FakeProvider) -> dict[str, object]:
    _use(provider)
    with TestClient(app, base_url=_BASE) as client:
        headers = _login(client)
        response = client.post(
            "/api/v1/chat",
            json={"message": YEAR_END_EXAMPLE_QUESTION, "vessel_id": str(VESSEL_ID_BULK)},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]


async def _tool_call_rows() -> int:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        return (
            await s.execute(
                text("SELECT COUNT(*) FROM audit_log WHERE \"action\" = 'CHAT_TOOL_CALL'")
            )
        ).scalar_one()


async def test_the_model_is_called_once_and_writes_the_answer(migrated_db, app_fresh_engine):
    """모델 호출 1회 · 도구 결과는 ``tool_result`` 블록으로 · 답은 모델 문장 그대로."""
    provider = _RecordingProvider([LLMResponse(text=_MODEL_TEXT)])
    try:
        data = _ask_example(provider)
        assert len(provider.calls) == 1, "모델을 두 번 이상 불렀다"
        assert provider.tools_sent[0], "종전 경로와 달리 도구 정의를 보내지 않았다"
        tool_use, tool_result = provider.calls[0][-2:]
        assert tool_use["role"] == "assistant"
        assert tool_use["content"][0]["type"] == "tool_use"
        assert tool_use["content"][0]["name"] == "project_year_end"
        assert tool_result["content"][0]["type"] == "tool_result"
        assert tool_result["content"][0]["tool_use_id"] == tool_use["content"][0]["id"]
        # 서버가 덧붙인 지시문이 없다 — 답을 정하는 것은 종전과 같은 시스템 지시뿐이다.
        assert "10문장 이내" not in " ".join(str(m["content"]) for m in provider.calls[0])
        assert data["answer"] == _MODEL_TEXT
        assert data["discarded"] is False
        assert data["tool_calls"] == ["project_year_end"]
        assert data["vessel_resolved"] is True
        assert await _tool_call_rows() == 1
    finally:
        await _cleanup()


def _without_tool_use_id(messages: list[dict[str, object]]) -> list[object]:
    """``tool_use`` id만 지운 사본 — 모델이 붙인 id와 서버가 붙인 id는 다를 수밖에 없다."""
    out: list[object] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, list):
            content = [
                {k: v for k, v in block.items() if k not in ("id", "tool_use_id")}
                for block in content
            ]
        out.append({"role": m["role"], "content": content})
    return out


async def test_the_one_call_is_the_same_as_the_second_call_of_the_model_path(
    migrated_db, app_fresh_engine, monkeypatch
):
    """🔴 바로 경로의 한 번 호출 = 종전 경로가 도구 결과를 받은 뒤의 호출 (`#2289` 후속).

    사용자가 원한 것은 10-09 14시대(종전 경로) 답의 **형식**이다. 형식은 모델이 받는 입력이
    정한다 — 그 입력이 메시지 하나·도구 정의 하나까지 같은지 본다. 빠지는 것은 「어느 도구를
    부를지」의 첫 왕복뿐이어야 한다.

    ## 두 경로가 같은 시각을 본다

    진행 중 항차가 있으면 올해 누적(``ytd``)이 **기준 시각에 따라 움직인다.** 두 경로를
    차례로 부르면 그 사이 몇 초가 흘러 마지막 자리가 갈린다(`8.328928` 대 `8.328929` ·
    `#2403`). 이 테스트가 보는 것은 입력의 **형식**이지 시각이 아니므로, 기준 시각을 한 값으로
    고정해 두 호출이 같은 값을 받게 한다.
    """
    frozen = datetime.now(UTC)
    resolve = cii_current.resolve_as_of
    monkeypatch.setattr(
        cii_current, "resolve_as_of", lambda as_of: resolve(frozen if as_of is None else as_of)
    )

    direct = _RecordingProvider([LLMResponse(text=_MODEL_TEXT)])
    try:
        _ask_example(direct)
    finally:
        await _cleanup()

    monkeypatch.setattr(chat_service, "is_year_end_example", lambda _q: False)
    model_path = _RecordingProvider(
        [
            LLMResponse(
                tool_calls=(ToolCall(name="project_year_end", arguments={}, id="toolu_m1"),),
                stop_reason="tool_use",
            ),
            LLMResponse(text=_MODEL_TEXT),
        ]
    )
    try:
        data = _ask_example(model_path)
        assert data["answer"] == _MODEL_TEXT
    finally:
        await _cleanup()

    assert len(model_path.calls) == 2
    assert _without_tool_use_id(direct.calls[0]) == _without_tool_use_id(model_path.calls[1])
    assert direct.tools_sent[0] == model_path.tools_sent[1]


async def test_a_fabricated_number_falls_back_to_the_calculated_sentence(
    migrated_db, app_fresh_engine
):
    """도구에 없는 수치를 쓴 답은 내보내지 않는다 — 계산 결과 문장으로 대신 답한다."""
    provider = FakeProvider([LLMResponse(text="연말 예상 CII는 98.765입니다.")])
    try:
        data = _ask_example(provider)
        assert "98.765" not in data["answer"]
        assert data["answer"].split("\n")[-1] == DIRECT_FALLBACK_NOTE
        assert data["discarded"] is False
        assert data["tool_calls"] == ["project_year_end"]
    finally:
        await _cleanup()


async def test_a_slow_model_falls_back_instead_of_timing_out(
    migrated_db, app_fresh_engine, monkeypatch
):
    """제한 시간을 넘기면 기다리지 않고 대체 답 — 「답을 드리지 못했습니다」로 끝나지 않는다."""
    monkeypatch.setattr(chat_service, "DIRECT_MODEL_TIMEOUT_SECONDS", 0.05)
    try:
        data = _ask_example(_SlowProvider())
        assert data["answer"].split("\n")[-1] == DIRECT_FALLBACK_NOTE
        assert data["discarded"] is False
    finally:
        await _cleanup()


async def test_a_provider_error_falls_back_to_the_calculated_sentence(
    migrated_db, app_fresh_engine
):
    try:
        data = _ask_example(_FailingProvider())
        assert data["answer"].split("\n")[-1] == DIRECT_FALLBACK_NOTE
        assert data["discarded"] is False
    finally:
        await _cleanup()


async def test_without_a_vessel_the_example_question_goes_to_the_model(
    migrated_db, app_fresh_engine
):
    """선박이 없으면 계산할 대상이 없다 — 종전처럼 모델이 선박을 묻는다."""
    provider = FakeProvider([LLMResponse(text="선박을 먼저 골라 주세요.")])
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat", json={"message": YEAR_END_EXAMPLE_QUESTION}, headers=headers
            )
            assert response.status_code == 200, response.text
            data = response.json()["data"]
        assert len(provider.calls) == 1
        assert data["tool_calls"] == []
        assert data["answer"] == "선박을 먼저 골라 주세요."
    finally:
        await _cleanup()


async def test_another_question_about_the_same_vessel_still_goes_to_the_model(
    migrated_db, app_fresh_engine
):
    """이 경로는 예시 질문 한 문장뿐이다 — 뜻이 비슷한 다른 문장까지 넓히지 않는다."""
    provider = _RecordingProvider([LLMResponse(text="화면에서 확인하실 수 있습니다.")])
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat",
                json={"message": "연말 등급 알려줘", "vessel_id": str(VESSEL_ID_BULK)},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            data = response.json()["data"]
        assert len(provider.calls) == 1
        assert provider.tools_sent[0], "종전 경로인데 도구 정의를 보내지 않았다"
        assert data["answer"] == "화면에서 확인하실 수 있습니다."
    finally:
        await _cleanup()


def test_only_spacing_may_differ_from_the_example_question():
    assert is_year_end_example(YEAR_END_EXAMPLE_QUESTION)
    assert is_year_end_example("  올해 연말 예상 등급은  어떻게 되나요? ")
    assert not is_year_end_example("올해 연말 예상 등급은 어떻게 되나요")
    assert not is_year_end_example("작년 연말 예상 등급은 어떻게 되나요?")


def test_the_fallback_rounds_to_the_screen_digits_and_says_it_was_not_written_by_ai():
    """화면 CII 자릿수(3)로 반올림 · 올해 누적을 먼저(``PRD §3.3``) · 마지막 줄이 대체 답 표시."""
    reply = _year_end_text(
        {
            "ytd": {"attained_cii": "6.5381665", "rating": "C"},
            "year_end_projection": {
                "attained_cii": "6.9124999",
                "required_cii": "6.0005",
                "rating": "D",
            },
        }
    )
    assert reply is not None
    lines = reply.split("\n")
    assert lines[0] == "선택하신 선박의 올해 연말 예상 등급은 D등급입니다."
    assert lines[1] == (
        "올해 지금까지의 누적 CII는 6.538로 C등급이며, 남은 계획 항차를 계획대로 운항하면 "
        "연말 CII는 6.912로 예상됩니다. 연말 기준 CII는 6.001입니다."
    )
    assert lines[2] == DIRECT_ANSWER_NOTE
    assert lines[3] == DIRECT_FALLBACK_NOTE


def test_no_rating_means_no_direct_path():
    """연말 예상의 등급이 없으면 이 경로를 타지 않는다 — 호출부가 종전 모델 경로로 넘긴다."""
    assert _year_end_text({"year_end_projection": {"attained_cii": "6.9"}}) is None
    assert _year_end_text({}) is None
