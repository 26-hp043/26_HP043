"""예시 질문 「올해 연말 예상 등급」의 바로 답 (`#2289` · 2026-10-09 결정).

같은 질문의 응답이 공급자 사정으로 7~45초를 오가고 턴 시간 초과로 폐기되기도 했다.
계산은 1초 안에 끝나므로 이 예시 질문은 **외부 모델을 부르지 않고** 연말 예상 도구의
결과로 바로 답한다. 여기서 보는 것은 셋이다.

1. 선박이 정해져 있으면 모델을 **한 번도 부르지 않는다** (``FakeProvider.calls``가 빈다).
2. 답이 AI의 해설처럼 보이지 않는다 — 첫 줄이 「계산 결과를 그대로」라고 말한다.
3. 선박이 없거나 다른 질문이면 **종전 모델 경로**로 간다.

``app_fresh_engine``(NullPool) + 커밋 기반 — ``test_chat_api_db.py``와 같은 구성이다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app
from cii_platform.api.routes.chat import get_provider
from cii_platform.db.demo_seed import VESSEL_ID_BULK
from cii_platform.llm.provider import FakeProvider, LLMResponse
from cii_platform.services.chat import (
    DIRECT_ANSWER_LEAD,
    DIRECT_ANSWER_NOTE,
    YEAR_END_EXAMPLE_QUESTION,
    _year_end_text,
    is_year_end_example,
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


async def _tool_call_rows() -> int:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        return (
            await s.execute(
                text("SELECT COUNT(*) FROM audit_log WHERE \"action\" = 'CHAT_TOOL_CALL'")
            )
        ).scalar_one()


async def test_the_example_question_is_answered_without_calling_the_model(
    migrated_db, app_fresh_engine
):
    """선박이 정해진 예시 질문 — 모델 호출 0회 · 도구 하나 · 정해진 첫 줄."""
    provider = FakeProvider([])
    _use(provider)
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            response = client.post(
                "/api/v1/chat",
                json={"message": YEAR_END_EXAMPLE_QUESTION, "vessel_id": str(VESSEL_ID_BULK)},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            data = response.json()["data"]
        assert provider.calls == [], "예시 질문인데 외부 모델을 불렀다"
        assert data["discarded"] is False
        assert data["tool_calls"] == ["project_year_end"]
        assert data["vessel_resolved"] is True
        lines = data["answer"].split("\n")
        # 계산 결과를 AI의 해설처럼 꾸미지 않는다 — 첫 줄이 그 사실을 말한다.
        assert lines[0] == DIRECT_ANSWER_LEAD
        assert any(line.startswith("· 연말 예상: CII ") for line in lines)
        assert lines[-1] == DIRECT_ANSWER_NOTE
        # 모델 경로와 같은 감사 기록을 남긴다.
        assert await _tool_call_rows() == 1
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
    """바로 답은 예시 질문 한 문장뿐이다 — 뜻이 비슷한 다른 문장까지 넓히지 않는다."""
    provider = FakeProvider([LLMResponse(text="화면에서 확인하실 수 있습니다.")])
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
        assert data["answer"] == "화면에서 확인하실 수 있습니다."
    finally:
        await _cleanup()


def test_only_spacing_may_differ_from_the_example_question():
    assert is_year_end_example(YEAR_END_EXAMPLE_QUESTION)
    assert is_year_end_example("  올해 연말 예상 등급은  어떻게 되나요? ")
    assert not is_year_end_example("올해 연말 예상 등급은 어떻게 되나요")
    assert not is_year_end_example("작년 연말 예상 등급은 어떻게 되나요?")


def test_the_answer_rounds_to_the_screen_digits_and_keeps_the_year_to_date_first():
    """화면 CII 자릿수(3)로 반올림하고, 올해 누적을 연말 예상보다 먼저 싣는다(``PRD §3.3``)."""
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
    assert lines[1] == "· 올해 누적: CII 6.538 · C등급"
    assert lines[2] == "· 연말 예상: CII 6.912 · D등급 (기준 CII 6.001)"


def test_no_rating_means_no_direct_answer():
    """연말 예상의 등급이 없으면 바로 답하지 않는다 — 호출부가 모델 경로로 넘긴다."""
    assert _year_end_text({"year_end_projection": {"attained_cii": "6.9"}}) is None
    assert _year_end_text({}) is None
