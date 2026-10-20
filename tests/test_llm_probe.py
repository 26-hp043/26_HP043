"""챗봇 공급자 응답 시간 측정기(`cii_platform.llm.probe`)를 고정한다 (`#2395` 결정 1).

측정은 운영 서버에서 외부 공급자를 부르는 일이라 여기서 재현하지 않는다. 대신 가짜
전송(``httpx.MockTransport``) 위에서 ⑴ 운영 첫 호출과 같은 입력을 싣는지 ⑵ 실패도
표본으로 남기는지 ⑶ **답 본문을 출력에 싣지 않는지** ⑷ 호출 규모의 상한을 본다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 운영 도구 회귀 테스트)
"""

from __future__ import annotations

import json

import httpx
import pytest

from cii_platform.llm import probe
from cii_platform.llm.provider import MAX_OUTPUT_TOKENS
from cii_platform.services.chat import SYSTEM_PROMPT
from cii_platform.services.chat_tools import tool_schemas

#: 가짜 공급자가 돌려주는 답 글자 — 이 글자가 표에 나오면 본문이 샌 것이다
SECRET_ANSWER = "재화중량톤수는-본문-노출-표지"


def _reply(model: str = "glm-5.3-flash") -> dict[str, object]:
    return {
        "model": model,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1800, "output_tokens": 120},
        "content": [
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": SECRET_ANSWER},
        ],
    }


async def _run(handler, models: list[str], runs: int = 1) -> list[probe.Case]:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        return await probe.run_probe(
            models, runs, client=client, endpoint="https://llm.test/v1/messages",
            headers={"x-api-key": "k"}, pause=0,
        )  # fmt: skip


async def test_sends_the_same_input_as_the_first_chat_call() -> None:
    """지시문·도구 정의·출력 상한이 챗봇 첫 호출과 같고, 변형은 `thinking`만 다르다."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_reply())

    await _run(handler, ["glm-a"])
    assert len(bodies) == len(probe.VARIANTS) * len(probe.QUESTIONS)
    for body in bodies:
        assert body["system"] == SYSTEM_PROMPT
        assert body["tools"] == tool_schemas()
        assert body["max_tokens"] == MAX_OUTPUT_TOKENS
        assert body["model"] == "glm-a"
        assert [m["content"] for m in body["messages"]] in ([q] for _, q in probe.QUESTIONS)
    assert sum("thinking" in b for b in bodies) == len(probe.QUESTIONS)
    assert all(b["thinking"] == {"type": "disabled"} for b in bodies if "thinking" in b)


async def test_runs_every_case_in_rounds_one_call_at_a_time() -> None:
    """모델 × 변형 × 질문을 한 바퀴씩 돈다.

    한 모델을 몰아 재면 시간대 차이가 모델 차이로 읽힌다.
    """
    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        order.append(json.loads(request.content)["model"])
        return httpx.Response(200, json=_reply())

    cases = await _run(handler, ["m1", "m2"], runs=2)
    per_round = 2 * len(probe.VARIANTS) * len(probe.QUESTIONS)
    assert len(order) == 2 * per_round
    assert order[:per_round] == order[per_round:]
    assert all(len(c.samples) == 2 for c in cases)


async def test_failures_are_samples_not_exceptions() -> None:
    """429·연결 끊김은 측정을 멈추지 않고 그 이름으로 남는다 — 재시도하지 않는다."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": SECRET_ANSWER})
        if calls == 2:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=_reply())

    cases = await _run(handler, ["m"])
    statuses = [s.status for c in cases for s in c.samples]
    assert statuses[:2] == ["429", "ReadTimeout"]
    assert calls == len(statuses)  # 다시 부르지 않았다


async def test_report_carries_numbers_and_served_model_but_never_the_answer() -> None:
    """응답의 `model`·토큰 수·블록은 남고, 답 글자와 오류 본문은 표에 나오지 않는다 (공개 로그)."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, text=SECRET_ANSWER)
        return httpx.Response(200, json=_reply("glm-5.3-flash"))

    cases = await _run(handler, ["glm-4.7"])
    sample = cases[1].samples[0]
    assert sample.served_model == "glm-5.3-flash"
    assert (sample.input_tokens, sample.output_tokens) == (1800, 120)
    assert sample.blocks == ("thinking", "text")
    text = "\n".join(probe.report(cases))
    assert SECRET_ANSWER not in text
    assert "glm-5.3-flash" in text and "500×1" in text


def test_report_counts_calls_over_the_production_limit() -> None:
    """운영 상한(30초)을 넘긴 호출 수를 따로 센다 — 실패한 호출도 센다."""
    case = probe.Case(model="m", variant="default", question="tool", samples=[
        probe.Sample(elapsed=12.0, status="200"),
        probe.Sample(elapsed=31.0, status="200"),
        probe.Sample(elapsed=90.0, status="ReadTimeout"),
    ])  # fmt: skip
    row = probe.report([case])[1].split()
    assert row[3] == "2/3"
    assert row[7] == "2"  # >30s 열


def test_nearest_rank_matches_bench_rule() -> None:
    values = [float(v) for v in range(1, 21)]
    assert probe.nearest_rank(values, 0.5) == 10.0
    assert probe.nearest_rank(values, 0.95) == 19.0
    assert probe.nearest_rank([7.0], 0.95) == 7.0


def test_parse_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "glm-4.5-flash")
    assert probe.parse_models("") == ["glm-4.5-flash"]
    assert probe.parse_models(" glm-5.3 , glm-5.3,glm-5.3-flash[1m] ") == [
        "glm-5.3",
        "glm-5.3-flash[1m]",
    ]
    for bad in ("glm 5", "x';rm", "a" * 41):
        with pytest.raises(ValueError):
            probe.parse_models(bad)


@pytest.mark.parametrize(
    "argv",
    [
        ["--runs", "0"],
        ["--runs", str(probe.MAX_RUNS + 1)],
        ["--models", "bad model"],
        ["--models", ",".join(f"m{i}" for i in range(8)), "--runs", str(probe.MAX_RUNS)],
    ],
)
def test_main_refuses_before_calling(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """형식·규모가 틀리면 한 번도 부르지 않고 2로 끝난다 — 넷째는 호출 상한(160 > 120)."""
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(probe, "_main", _must_not_run)
    assert probe.main(argv) == 2


def test_main_without_key_does_not_call(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert probe.main(["--models", "m", "--runs", "1"]) == 2
    assert "LLM_API_KEY" in capsys.readouterr().out


async def _must_not_run(*_args: object) -> int:
    raise AssertionError("부르면 안 된다")
