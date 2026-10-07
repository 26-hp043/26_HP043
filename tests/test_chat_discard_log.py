"""폐기 기록 한 줄 (`#1985`).

케이스: IT-CHAT-073 ~ IT-CHAT-076 · IT-CHAT-082 · IT-CHAT-083 (`TEST_PLAN §3.18`)

## 무엇을 지키는가

운영 챗봇이 답을 폐기하면 **어느 경로로 폐기됐는지**를 점검에서 되짚을 수 있어야 한다.
`#1535`가 폐기 경고를 남기게 했지만 **일곱 경로 중 하나**(No-Compute)만이었고, 나머지는
운영에서 「답이 저장되지 않았다」는 사실만 남았다 — 감사 로그로는 여섯 종류를 가를 수 없다.

## 실려도 되는 것과 안 되는 것

이 줄은 **공개 저장소의 Actions 로그**로 나간다(`ops.yml task=inspect`). 그래서
`PRD §16.3.1`대로 **답 본문 · 질문 · 사용자 · IP를 싣지 않는다.** 실리는 것은 폐기 종류 ·
세션 · 부른 도구 이름과, 그 자체로 사람을 가리키지 않는 부가값(막힌 수치)뿐이다.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml

from cii_platform.llm import anthropic
from cii_platform.llm.anthropic import AnthropicProvider
from cii_platform.llm.provider import LLMError
from cii_platform.services import chat

#: 로그 줄을 고르는 접두어 — `ops.yml`이 같은 문자열로 grep한다.
SOURCE = Path(chat.__file__).read_text(encoding="utf-8")
OPS = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ops.yml").read_text(
    encoding="utf-8"
)


def _discard_calls() -> list[str]:
    """``_result(..., discarded=True, ...)`` 호출들의 원문."""
    return [
        call.group(0)
        for call in re.finditer(r"_result\((?:[^()]|\([^()]*\))*\)", SOURCE, re.S)
        if "discarded=True" in call.group(0)
    ]


def test_every_discard_path_names_its_kind_and_session() -> None:
    """IT-CHAT-073 — 폐기 경로 **전부**가 종류와 세션을 남긴다.

    경로가 하나 늘 때 기록을 잊는 것을 막는다. 잊어도 **화면은 깨지지 않으므로**
    발견이 늦다 — `#1535`가 하나만 남기고 여섯을 빠뜨린 것이 그 형태다.
    """
    calls = _discard_calls()
    assert len(calls) >= 7, f"폐기 자리를 찾지 못했다: {len(calls)}건"
    for call in calls:
        assert re.search(r'discard_kind="[a-z-]+"', call), f"폐기 종류가 없다:\n{call}"
        assert "chat_session_id=chat_session_id" in call, f"세션이 없다:\n{call}"


def test_the_six_kinds_are_all_used() -> None:
    """IT-CHAT-074 — 이슈가 센 여섯 종류가 모두 쓰인다.

    수치 검증 · 시간 상한 · 공급자 오류 · 거절 · 잘림 · 도구 상한. 자리는 일곱이지만
    도구 상한이 두 곳(모델이 한 번에 넘길 때 · 누적이 넘을 때)이라 종류는 여섯이다.
    """
    kinds = {
        match.group(1)
        for call in _discard_calls()
        for match in [re.search(r'discard_kind="([a-z-]+)"', call)]
        if match
    }
    assert kinds == {
        "no-compute",
        "turn-timeout",
        "provider-error",
        "refusal",
        "truncated",
        "tool-budget",
    }, kinds


def test_the_line_carries_kind_session_and_tools_only(caplog) -> None:
    """IT-CHAT-075 — 줄에 **본문·질문·사용자가 섞이지 않는다**.

    답 본문을 첫 인자로 주고도 로그에는 나오지 않아야 한다 — 봉투의 ``answer``와 로그가
    같은 자리에서 만들어지므로 실수로 섞일 수 있는 지점이다.
    """
    session_id = uuid4()
    secret = "이 문장은 사용자에게만 보이는 답 본문입니다"
    with caplog.at_level(logging.WARNING, logger=chat.__name__):
        chat._result(
            secret,
            ["lookup_regulation"],
            discarded=True,
            discard_kind="refusal",
            chat_session_id=session_id,
        )

    assert len(caplog.records) == 1
    line = caplog.records[0].getMessage()
    assert line.startswith(chat.DISCARD_LOG_PREFIX)
    assert "refusal" in line
    assert str(session_id) in line
    assert "lookup_regulation" in line
    # 본문은 싣지 않는다.
    assert secret not in line


def test_an_all_user_numbers_discard_does_not_read_as_blank(caplog) -> None:
    """IT-CHAT-080 (`#1973` 폐기 후속) — 막힌 수가 **전부 사용자 수**면 그렇게 적는다.

    수치 검증은 막힌 수가 하나 이상일 때만 폐기한다. 호출부가 사용자가 친 수를 빼고 나면 목록이
    빌 수 있는데, 그때 「막힌 수치 」로 빈칸을 두거나 「(없음)」으로 적으면 **막힌 수 없이
    폐기됐다**로 읽힌다.
    """
    with caplog.at_level(logging.WARNING, logger=chat.__name__):
        envelope = chat._result(
            "폐기",
            [],
            discarded=True,
            discard_kind="no-compute",
            chat_session_id=uuid4(),
            blocked_numbers=[],
        )

    line = caplog.records[0].getMessage()
    assert "막힌 수치 (사용자가 친 수만" in line, line
    assert "막힌 수치 (없음)" not in line
    assert envelope[chat._DISCARD_AUDIT_KEY]["blocked_numbers"] == []


def test_success_does_not_log(caplog) -> None:
    """IT-CHAT-075 — 폐기가 아니면 한 줄도 남기지 않는다(로그가 성공으로 덮이지 않는다)."""
    with caplog.at_level(logging.WARNING, logger=chat.__name__):
        chat._result("정상 답", [], discarded=False)
    assert caplog.records == []


def test_ops_inspect_greps_the_same_prefix() -> None:
    """IT-CHAT-076 — 점검 단계가 **같은 접두어**를 본다.

    접두어를 바꾸면 점검이 조용히 아무것도 못 찾는다 — 그때 「폐기가 없었다」로 읽히는
    것이 가장 나쁜 실패다. 양쪽을 한 검사로 묶는다.
    """
    assert chat.DISCARD_LOG_PREFIX in OPS, "ops.yml이 폐기 접두어로 로그를 고르지 않는다"


def test_ops_inspect_also_greps_the_provider_failure_prefix() -> None:
    """IT-CHAT-082 (`#2289`) — 점검이 **공급자 실패 줄**의 접두어도 본다.

    폐기 줄에는 종류(`provider-error`)만 있고 원인(상태 코드 · 예외 이름)은 별도 경고 줄에만
    있다. 접두어가 어긋나면 그 줄이 조용히 빠져 원인을 볼 길이 다시 없어진다.
    """
    # 문자열이 들어 있는지만 보면 주석이나 깨진 패턴(`-F`에 `\\|`)으로도 통과한다. 점검 단계의
    # **grep 명령을 그대로 꺼내 표본 로그에 돌려** 두 줄이 다 골라지고 다른 줄은 빠지는지 본다.
    step = next(
        s
        for s in yaml.safe_load(OPS)["jobs"]["ops"]["steps"]
        if s.get("name") == "챗봇 폐기·공급자 실패 (app-01)"
    )
    grep_line = next(line for line in step["run"].splitlines() if "grep -F" in line)
    argv = shlex.split(grep_line.strip().removeprefix("|").removesuffix("\\").strip())
    discard = f"WARNING cii_platform.services.chat {chat.DISCARD_LOG_PREFIX}(provider-error)"
    failure = f"WARNING cii_platform.llm.anthropic {anthropic.FAILURE_LOG_PREFIX} (HTTP 401)"
    other = "INFO uvicorn.access 200 GET /api/v1/health"
    picked = subprocess.run(
        argv, input="\n".join([other, discard, failure]) + "\n", capture_output=True, text=True
    ).stdout.splitlines()
    assert picked == [discard, failure], picked


def _failing_transport(error: Exception | int) -> httpx.MockTransport:
    marker = "본문표지-질문-키-주소"

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(error, int):
            return httpx.Response(error, json={"error": {"message": marker}})
        raise error

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (400, "(HTTP 400)"),
        (httpx.ReadTimeout("본문표지-질문-키-주소 https://example.invalid/v1"), "(ReadTimeout)"),
    ],
)
async def test_provider_failure_line_carries_only_status_or_exception_name(
    error: Exception | int, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    """IT-CHAT-083 (`#2289`) — 공급자 실패 줄은 접두어 + 상태 코드 또는 예외 이름뿐이다.

    이 줄은 공개 Actions 로그로 나간다. 응답 본문 · 예외 메시지(주소가 붙을 수 있다)가
    섞이지 않아야 한다. HTTP 오류 갈래와 예외(시간 초과) 갈래를 모두 본다.
    """
    async with httpx.AsyncClient(transport=_failing_transport(error)) as client:
        provider = AnthropicProvider(key="test-key", client=client)
        with (
            caplog.at_level(logging.WARNING, logger=anthropic.__name__),
            pytest.raises(LLMError),
        ):
            await provider.complete(messages=[{"role": "user", "content": "질문"}])

    lines = [record.getMessage() for record in caplog.records]
    assert lines == [f"{anthropic.FAILURE_LOG_PREFIX} {expected}"], lines
    assert "본문표지" not in lines[0]
