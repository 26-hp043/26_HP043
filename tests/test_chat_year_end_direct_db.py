"""예시 질문 「올해 연말 예상 등급」 — 도구를 먼저, 모델은 한 번만 (`#2289` · 10-09 결정).

종전 경로는 모델을 두 번 기다린다(어느 도구를 부를지 · 결과로 문장 쓰기). 같은 질문의 응답이
7~45초를 오가고 턴 시간 초과로 폐기되기도 했다. 이 예시 질문은 서버가 ``project_year_end``를
먼저 돌리고 **문장 쓰기 한 번만** 모델에게 묻는다. 여기서 보는 것은 넷이다.

1. 선박이 정해져 있으면 모델을 **정확히 한 번** 부르고 **도구 정의를 보내지 않는다**.
2. 답은 모델이 쓴 문장 그대로다 — 서버가 문장을 바꾸지 않는다.
3. 모델이 늦거나 · 실패하거나 · 도구에 없는 수치를 쓰면 **계산 결과 문장으로 대신 답하고**
   마지막 줄에 그 사실을 적는다. 오류로 끝나지 않는다.
4. 선박이 없거나 다른 문장이면 **종전 모델 경로**로 간다.

``app_fresh_engine``(NullPool) + 커밋 기반 — ``test_chat_api_db.py``와 같은 구성이다.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.api.routes.chat import get_provider
from cii_platform.db.demo_seed import VESSEL_ID_BULK
from cii_platform.llm.provider import FakeProvider, LLMError, LLMResponse
from cii_platform.services import chat as chat_service
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
    """받은 ``tools``까지 남긴다 — 바로 경로가 도구 정의를 보내지 않는지 본다."""

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


async def test_the_model_is_called_once_without_tools_and_writes_the_answer(
    migrated_db, app_fresh_engine
):
    """모델 호출 1회 · 도구 정의 없음 · 도구 결과가 메시지에 실림 · 답은 모델 문장 그대로."""
    provider = _RecordingProvider([LLMResponse(text=_MODEL_TEXT)])
    try:
        data = _ask_example(provider)
        assert len(provider.calls) == 1, "모델을 두 번 이상 불렀다"
        assert provider.tools_sent == [None], "도구 정의를 보냈다 — 보내는 양이 줄지 않는다"
        sent = " ".join(str(m["content"]) for m in provider.calls[0])
        assert "project_year_end" in sent, "도구 결과가 모델에게 가지 않았다"
        # 결과만 건네면 모델이 결론 한 줄로 끝낸다(10-09 운영) — 근거·가정을 쓰라고 지시한다.
        assert "근거" in sent and "가정" in sent and "3~5문장" in sent
        assert data["answer"] == _MODEL_TEXT
        assert data["discarded"] is False
        assert data["tool_calls"] == ["project_year_end"]
        assert data["vessel_resolved"] is True
        assert await _tool_call_rows() == 1
    finally:
        await _cleanup()


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
