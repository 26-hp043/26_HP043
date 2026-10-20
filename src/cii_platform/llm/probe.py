"""챗봇 공급자 응답 시간 측정 (`#2395` 결정 1) — ``python -m cii_platform.llm.probe``.

운영에서 예시 질문 둘이 공급자 지연으로 버려졌다(부산–싱가포르 `provider-error` ·
벌크선 등급 경계 `turn-timeout`). 한도(모델 호출 30초 · 턴 45초)는 그대로 두고, **첫 응답
시간을 줄일 수 있는지**를 운영 서버에서 잰다. 이 모듈이 재는 것은 셋이다.

- 모델마다의 응답 시간 분포 — 같은 키·같은 주소로 ``--models``의 모델을 차례로 부른다.
- ``thinking`` 끄기의 효과 — Anthropic 형식의 ``"thinking": {"type": "disabled"}``를
  실은 요청을 같은 횟수만큼 함께 보낸다. 공급자가 받는지부터 이 측정이 확인한다.
- 실제로 답한 모델 — 응답의 ``model`` 필드를 그대로 찍는다. 요청한 ID가 다른 모델로
  돌려 보내지는지 여기서 드러난다.

## 운영 호출과 같은 입력을 싣는다

지시문은 :data:`cii_platform.services.chat.SYSTEM_PROMPT`, 도구 정의는
:func:`cii_platform.services.chat_tools.tool_schemas`, 출력 상한은
:data:`~cii_platform.llm.provider.MAX_OUTPUT_TOKENS` — 챗봇 첫 호출이 싣는 것 그대로다.
질문은 화면 예시 질문 꼴의 **고정 문장**이다. 사용자 질문이나 DB 값은 싣지 않는다.

## 재시도하지 않고, 30초에서 끊지 않는다

공급자 구현(:class:`~cii_platform.llm.anthropic.AnthropicProvider`)은 과부하 응답을 한 번
다시 부르고 30초에서 끊는다. 여기서는 **한 번 부른 그대로** 재고 상한을
:data:`PROBE_TIMEOUT_SECONDS`로 둔다 — 30초를 넘는 응답이 몇 초에 오는지가 이 측정이
알고 싶은 것이다. 30초를 넘긴 건수는 따로 센다.

## 로그에 내보내는 것

Actions 로그는 공개다. **응답 본문(답 글자·도구 인자)은 찍지 않는다.** 찍는 것은 시간 ·
상태 코드나 예외 이름 · 응답의 ``model``·``stop_reason`` · 토큰 수 · 블록 종류뿐이다.
키·주소는 찍지 않는다.

호출은 **하나씩 차례로** 보낸다. 플랜의 동시 호출 한도에 걸리면 지연이 아니라 429를
재게 된다.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from cii_platform.llm.anthropic import API_VERSION, MESSAGES_PATH, TIMEOUT_SECONDS
from cii_platform.llm.provider import (
    AUTH_SCHEME_BEARER,
    MAX_OUTPUT_TOKENS,
    api_key,
    auth_scheme,
    base_url,
    model_name,
)

#: 한 호출의 상한(초). 운영 상한(``TIMEOUT_SECONDS`` 30초)보다 길게 두어 넘친 응답의
#: 실제 시간을 본다.
PROBE_TIMEOUT_SECONDS = 90.0

#: 호출 사이 대기(초) — 동시 호출 한도와 분당 한도를 건드리지 않게.
PAUSE_SECONDS = 1.0

#: 한 번 실행의 호출 상한. 모델 넷이면 변형 둘 × 질문 둘 × 3회(기본) = 48회다.
#: 상한까지 불러도 한 호출 10초 안팎이면 ``ops.yml``의 작업 시간(30분) 안에 끝난다.
MAX_CALLS = 120

#: 모델마다·변형마다·질문마다 부르는 횟수의 상한.
MAX_RUNS = 10

#: 모델 ID로 받는 글자. 공급자 문서의 ``glm-5.3-flash[1m]`` 같은 접미사까지 받는다.
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-\[\]]{1,40}$")

#: 고정 질문 — (이름, 문장). 화면 예시 질문 꼴이다.
#:
#: ``glossary``는 도구 없이 답하는 질문, ``tool``은 첫 응답이 도구 호출인 질문이다. 운영에서
#: 버려진 두 질문이 이 두 꼴이다.
QUESTIONS: tuple[tuple[str, str], ...] = (
    ("glossary", "DWT가 뭐야?"),
    ("tool", "부산에서 싱가포르까지 12노트로 가면 항차 CII가 어떻게 돼?"),
)

#: ``thinking`` 변형 — (이름, 요청에 더할 필드).
VARIANTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("default", {}),
    ("no-think", {"thinking": {"type": "disabled"}}),
)


@dataclass(frozen=True)
class Sample:
    """한 호출의 결과. **본문은 들고 있지 않는다.**"""

    elapsed: float
    status: str  # "200" · "429" · "ReadTimeout" 같은 상태 코드나 예외 이름
    served_model: str = ""
    stop_reason: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    blocks: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "200"


@dataclass
class Case:
    """모델 하나 × 변형 하나 × 질문 하나."""

    model: str
    variant: str
    question: str
    samples: list[Sample] = field(default_factory=list)


def parse_models(raw: str) -> list[str]:
    """쉼표로 나눈 모델 ID. 비면 설정된 모델 하나다. 형식이 틀리면 ``ValueError``."""
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        return [model_name()]
    for model in models:
        if not MODEL_ID_PATTERN.fullmatch(model):
            raise ValueError(f"모델 ID 형식이 아니다: {model!r}")
    # 순서는 지키고 중복만 걷는다
    return list(dict.fromkeys(models))


def nearest_rank(values: list[float], q: float) -> float:
    """정렬한 표본의 ``ceil(q × n)``번째 (`calc.bench`와 같은 규칙)."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _headers(key: str, scheme: str) -> dict[str, str]:
    # 공급자 구현(`AnthropicProvider._headers`)과 같은 헤더다
    headers = {"anthropic-version": API_VERSION, "content-type": "application/json"}
    if scheme == AUTH_SCHEME_BEARER:
        headers["authorization"] = f"Bearer {key}"
    else:
        headers["x-api-key"] = key
    return headers


def request_body(model: str, question: str, extra: dict[str, Any]) -> dict[str, Any]:
    """챗봇 첫 호출과 같은 꼴의 요청 본문."""
    # 지연 가져오기 — 서비스 계층을 끌어오면 DB 모듈까지 따라온다. 측정 때만 필요하다.
    from cii_platform.services.chat import SYSTEM_PROMPT
    from cii_platform.services.chat_tools import tool_schemas

    return {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": question}],
        "tools": tool_schemas(),
        **extra,
    }


async def call_once(
    client: httpx.AsyncClient,
    endpoint: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> Sample:
    """한 번 부르고 잰다. 실패도 표본이다 — 올리지 않는다."""
    started = time.monotonic()
    try:
        response = await client.post(endpoint, json=body, headers=headers)
    except httpx.HTTPError as exc:
        return Sample(elapsed=time.monotonic() - started, status=type(exc).__name__)
    elapsed = time.monotonic() - started
    if response.status_code != 200:
        return Sample(elapsed=elapsed, status=str(response.status_code))
    try:
        payload = response.json()
    except ValueError:
        return Sample(elapsed=elapsed, status="BadJSON")
    usage = payload.get("usage") or {}
    content = payload.get("content") or []
    return Sample(
        elapsed=elapsed,
        status="200",
        served_model=str(payload.get("model") or ""),
        stop_reason=str(payload.get("stop_reason") or ""),
        input_tokens=usage.get("input_tokens") if isinstance(usage, dict) else None,
        output_tokens=usage.get("output_tokens") if isinstance(usage, dict) else None,
        blocks=tuple(str(b.get("type")) for b in content if isinstance(b, dict)),
    )


async def run_probe(
    models: list[str],
    runs: int,
    *,
    client: httpx.AsyncClient,
    endpoint: str,
    headers: dict[str, str],
    pause: float = PAUSE_SECONDS,
) -> list[Case]:
    """모델 × 변형 × 질문마다 ``runs``회. 한 바퀴씩 돌려 시간대 차이를 고르게 나눈다."""
    cases = [
        Case(model=m, variant=v, question=q)
        for m in models
        for v, _ in VARIANTS
        for q, _ in QUESTIONS
    ]
    extras = dict(VARIANTS)
    texts = dict(QUESTIONS)
    for round_no in range(runs):
        for case in cases:
            if round_no or case is not cases[0]:
                await asyncio.sleep(pause)
            body = request_body(case.model, texts[case.question], extras[case.variant])
            case.samples.append(await call_once(client, endpoint, headers, body))
    return cases


def report(cases: list[Case]) -> list[str]:
    """표 한 벌. 시간은 성공한 호출만으로 낸다."""
    lines = [
        f"{'model':<20} {'variant':<9} {'question':<9} {'ok':>5} "
        f"{'p50 s':>7} {'p95 s':>7} {'max s':>7} {'>30s':>5} "
        f"{'in tok':>7} {'out tok':>7}  served · stop · 실패",
    ]
    for case in cases:
        ok = [s for s in case.samples if s.ok]
        times = [s.elapsed for s in ok]
        over = sum(1 for s in case.samples if s.elapsed > TIMEOUT_SECONDS)
        ins = [s.input_tokens for s in ok if isinstance(s.input_tokens, int)]
        outs = [s.output_tokens for s in ok if isinstance(s.output_tokens, int)]
        served = ",".join(sorted({s.served_model for s in ok if s.served_model})) or "-"
        stops = ",".join(f"{k}×{n}" for k, n in Counter(s.stop_reason for s in ok).items()) or "-"
        fails = (
            ",".join(
                f"{k}×{n}" for k, n in Counter(s.status for s in case.samples if not s.ok).items()
            )
            or "-"
        )
        lines.append(
            f"{case.model:<20} {case.variant:<9} {case.question:<9} "
            f"{len(ok):>2}/{len(case.samples):<2} "
            f"{_fmt(nearest_rank(times, 0.5) if times else None):>7} "
            f"{_fmt(nearest_rank(times, 0.95) if times else None):>7} "
            f"{_fmt(max(times) if times else None):>7} {over:>5} "
            f"{_avg(ins):>7} {_avg(outs):>7}  {served} · {stops} · {fails}"
        )
    return lines


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _avg(values: list[int]) -> str:
    return "-" if not values else f"{sum(values) / len(values):.0f}"


async def _main(models: list[str], runs: int) -> int:
    key = api_key()
    scheme = auth_scheme()
    if not key or scheme is None:
        print("LLM_API_KEY 또는 LLM_AUTH_SCHEME이 설정되지 않아 잴 수 없다.")
        return 2
    endpoint = base_url() + MESSAGES_PATH
    print(f"측정 시각 {datetime.now(UTC).isoformat(timespec='seconds')} (UTC)")
    print(
        f"모델 {len(models)}개 × 변형 {len(VARIANTS)} × 질문 {len(QUESTIONS)} × {runs}회 · "
        f"차례로 · 호출 사이 {PAUSE_SECONDS:.0f}초 · "
        f"한 호출 상한 {PROBE_TIMEOUT_SECONDS:.0f}초 · 재시도 없음"
    )
    print()
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        cases = await run_probe(
            models, runs, client=client, endpoint=endpoint, headers=_headers(key, scheme)
        )
    for line in report(cases):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cii_platform.llm.probe")
    parser.add_argument("--models", default="", help="쉼표로 나눈 모델 ID (비우면 LLM_MODEL)")
    parser.add_argument("--runs", type=int, default=3, help=f"경우마다 횟수 (1~{MAX_RUNS})")
    args = parser.parse_args(argv)
    try:
        models = parse_models(args.models)
    except ValueError as exc:
        print(exc)
        return 2
    if not 1 <= args.runs <= MAX_RUNS:
        print(f"--runs는 1~{MAX_RUNS}이다.")
        return 2
    calls = len(models) * len(VARIANTS) * len(QUESTIONS) * args.runs
    if calls > MAX_CALLS:
        print(f"호출 {calls}회는 상한 {MAX_CALLS}회를 넘는다 — 모델이나 횟수를 줄인다.")
        return 2
    return asyncio.run(_main(models, args.runs))


if __name__ == "__main__":
    raise SystemExit(main())
