"""챗봇 도구 6종 (`#121` · `Q9` ⓐ · `#1533` · `#1703`).

## 쓰기 도구를 넣지 않는다

`#121` 본문은 ``create_voyage``를 도구 목록에 적었으나 **빼기로 정했다**(`Q9`).

- 실험 기능(MAY)이 **데이터를 만드는 경로**를 갖는 것은 ``PRD §16.2`` 장애 격리
  정신과 어긋난다. 챗봇이 죽었을 때 **「만들다 만 항차」**가 남으면 격리가 아니다.
- 항차 생성은 입력이 많다. 자연어로 받으면 **오입력 위험이 화면보다 크다** —
  화면이 더 나은 도구인 작업이다.
- 필요해지면 나중에 도구를 더하는 건 쉽다. 반대로 **잘못 만들어진 항차를 되돌리는
  것은 사용자 일**이다.

## ⚠️ 봉투와 도메인 값을 가른다

``services/llm_guard.filter_outbound``는 **도메인 값**에만 건다. 도구 응답의 구조
봉투(``ok``·``error``·``tool``)는 화이트리스트 대상이 **아니다** — 그것까지 목록에
넣으면 ``PRD §16.3.1``이 「선사 기밀을 막는 목록」이 아니라 「응답 스키마」가 되고,
목록의 뜻이 흐려진다.

경계는 하나다 — **선박·항차·연료·조직에서 온 값은 전부 도메인**이고 필터를 지난다.
봉투에는 **우리가 만든 상수만** 담는다. ⚠️ **오류 문구도 마찬가지다** — 도메인 오류의
원문에는 식별자가 흔히 들어 있어, 그대로 넘기면 화이트리스트가 오류 경로로 뚫린다
(아래 :data:`_ERROR_TEXT`). 이 규칙을 어기면(봉투에 선박명을 넣으면)
화이트리스트가 통째로 무의미해지므로, ``tests/test_chat_tools_db.py``가 그것을 막는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.errors import CalculationError, NotFoundError, ParameterError, ValidationError
from cii_platform.services.llm_guard import filter_outbound
from cii_platform.services.simulation_clock import current_regulation_year
from cii_platform.validation.bounds import MAX_REGULATION_YEAR, MIN_REGULATION_YEAR

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: 도구 이름 — `Q9` 확정 4종.
TOOL_SEARCH_VESSEL = "search_vessel"
TOOL_CALC_VOYAGE_CII = "calc_voyage_cii"
TOOL_COMPARE_SCENARIOS = "compare_scenarios"
#: `#1534`(결정요청 v6 `D-32`) — 이 도구는 몬테카를로 확률이 아니라 **결정론
#: 연말 예상**(확정 실적 + 잔여 계획, `PRD §3.3` ⑶)을 낸다. 종전 이름
#: ``run_annual_simulation``이 `PRD §12`의 확률 시뮬레이션을 가리키고 있었다.
TOOL_PROJECT_YEAR_END = "project_year_end"
#: `#1533`(결정요청 v6 `D-31` 가안) — **화면이 방금 낸 결과**를 저장된 실행에서 읽는다.
#:
#: 다른 계산 도구는 그 자리에서 **새로 계산**한다. 입력이 조금만 달라도 화면과 다른 수가
#: 나오고, 확률(몬테카를로)은 다시 돌리면 화면과 같아질 수 없다. 면책 문구(``PRD §6.3``)가
#: 말하는 「BlueLog의 계산 결과」를 **화면과 같은 수로** 인용하는 경로가 이것이다.
TOOL_EXPLAIN_SCREEN_RESULT = "explain_screen_result"
#: `#1703`(`#122` 결정 · 결정요청 v3 `E-1` 안 「나」) — **규제 기준값 표**를 출처와 함께 읽는다.
#:
#: PDF 검색(RAG)을 하지 않기로 했다(`PRD §21`). 값의 출처를 사람이 원문 대조로 적재한
#: 표 하나로 둔다 — 이 도구는 그 행을 **그대로 인용**할 뿐 계산하지 않는다
#: (``PRD §20 O-12`` No-Compute).
TOOL_LOOKUP_REGULATION = "lookup_regulation"

TOOL_NAMES: tuple[str, ...] = (
    TOOL_SEARCH_VESSEL,
    TOOL_CALC_VOYAGE_CII,
    TOOL_COMPARE_SCENARIOS,
    TOOL_PROJECT_YEAR_END,
    TOOL_EXPLAIN_SCREEN_RESULT,
    TOOL_LOOKUP_REGULATION,
)

_YEAR_DEFAULT_TOOLS = frozenset(
    {TOOL_CALC_VOYAGE_CII, TOOL_COMPARE_SCENARIOS, TOOL_PROJECT_YEAR_END, TOOL_LOOKUP_REGULATION}
)


def tool_schemas() -> list[dict[str, object]]:
    """모델에게 주는 도구 목록.

    **설명은 한국어로 적는다** — 사용자가 한국어로 묻고, 모델이 도구를 고르는 근거가
    이 설명이다. 영어로 적으면 한 번 더 번역해 판단하게 된다.
    """
    return [
        {
            "name": TOOL_SEARCH_VESSEL,
            "description": (
                "선박을 이름으로 찾아 이 대화에서 쓸 수 있게 한다. "
                "⚠️ 선박명·IMO·식별자는 돌려주지 않는다 — 몇 척을 찾았는지만 알려 준다. "
                "찾은 선박이 1척이면 이 대화에서 계속 쓴다. "
                "여러 척이면 화면에서 골라야 한다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "선박 이름 일부"}},
                "required": ["name"],
            },
        },
        {
            "name": TOOL_CALC_VOYAGE_CII,
            "description": (
                "한 항차의 CII를 추정한다(기능①). 거리·속도·연료를 받아 attained/required와 "
                "등급을 돌려준다. 연료량·유종을 사용자가 말하지 않았으면 비워 두고 부른다 — "
                "선박 등록값으로 추정한다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "distance_nm": {"type": "number", "description": "항해 거리(해리)"},
                    "speed_kn": {"type": "number", "description": "평균 속력(노트)"},
                    "fuel_type": {
                        "type": "string",
                        "description": "유종 코드 (예: HFO). 모르면 비운다 — 선박 기본 유종",
                    },
                    "fuel_ton": {
                        "type": "number",
                        "description": "연료 소모량(톤). 모르면 비운다 — 선박 기준 소모량으로 추정",
                    },
                    "regulation_year": {"type": "integer", "description": "규제 연도"},
                },
                "required": ["distance_nm", "speed_kn"],
            },
        },
        {
            "name": TOOL_COMPARE_SCENARIOS,
            "description": (
                "속도 시나리오 셋을 비교한다(기능②). "
                "⚠️ 어느 쪽이 더 낫다고 말하지 않는다 — 수치만 돌려준다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "current_speed_kn": {"type": "number"},
                    "fuel_type": {"type": "string"},
                    "direct_distance_nm": {"type": "number"},
                    "base_daily_foc_ton": {"type": "number"},
                    "regulation_year": {"type": "integer"},
                    # `#2561` — 선체·추진 상태 보정 %. 사용자가 말했을 때만 보낸다. 비우면
                    # 선박 제원값(없으면 0%)으로 계산한다.
                    "hull_condition_percent": {
                        "type": "number",
                        "description": (
                            "선체·추진 상태 보정 % (파울링이면 +, 선체 청소·프로펠러 연마면 −). "
                            "모르면 비운다 — 선박 등록값"
                        ),
                    },
                },
                "required": ["current_speed_kn", "fuel_type"],
            },
        },
        {
            "name": TOOL_PROJECT_YEAR_END,
            "description": (
                "올해 누적 CII(ytd)와 연말 예상 등급(year_end_projection)을 함께 낸다. "
                "연말 예상은 확정된 실적에 남은 계획 항차를 더해 외삽하는 결정론 계산이며, "
                "확률이 아니다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"regulation_year": {"type": "integer"}},
                "required": [],
            },
        },
        {
            "name": TOOL_EXPLAIN_SCREEN_RESULT,
            "description": (
                "사용자가 화면에서 방금 낸 계산 결과(항차 CII 추정 · 속도 시나리오 비교 · "
                "연간 시뮬레이션)를 저장된 기록에서 그대로 읽는다. 새로 계산하지 않는다. "
                "「이 결과」·「방금 결과」·「화면의 값」을 물으면 먼저 이 도구를 쓴다. "
                "연간 시뮬레이션이면 목표 달성 확률과 등급별 확률도 준다. "
                "화면이 결과를 넘기지 않았으면 오류를 돌려준다."
            ),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": TOOL_LOOKUP_REGULATION,
            "description": (
                "규제 기준값 표를 읽는다 — 선종의 기준선(a · c · 조건식), 규제 연도의 감축률(Z), "
                "선종의 등급 경계(d1~d4), 연료의 CF. 각 행의 출처(source_ref, 예: MEPC.353(78))를 "
                "함께 준다. 값을 답할 때는 반드시 출처를 함께 말한다. 결의안 본문의 해설이나 "
                "G5 보정계수는 표에 없다 — 그때는 IMO 원문을 보라고 답한다. "
                "선종을 말하지 않으면 이 대화의 선박 선종을 쓴다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ship_type": {
                        "type": "string",
                        "description": "선종 코드 (예: BULK_CARRIER, LNG_CARRIER)",
                    },
                    # `#1973` ④ — 연도를 묻지 않았는데 한 해를 골라 넣으면 그 해의 감축률을
                    # 올해 값처럼 말하게 된다. 비우면 `_regulation_year`가 올해로 본다.
                    "regulation_year": {
                        "type": "integer",
                        "description": (
                            "규제 연도 — 사용자가 연도를 말하지 않았으면 비워 둔다(올해 값을 준다)"
                        ),
                    },
                    "fuel_code": {"type": "string", "description": "연료 코드 (예: HFO)"},
                },
                "required": [],
            },
        },
    ]


def _regulation_year(arguments: dict[str, object]) -> int:
    """모델이 연도를 말하지 않으면 **올해**로 본다.

    상수로 박지 않는다 — 해가 바뀌면 틀린 해를 계산하고, 그 사실이 화면 어디에도
    드러나지 않는다. ``cii_current``가 ``current_regulation_year``(한국 달력의 해, `#2131`)로
    같은 판단을 한다.
    """
    raw = arguments.get("regulation_year")
    if raw is None:
        return current_regulation_year(datetime.now(UTC))
    try:
        return int(raw)  # type: ignore[arg-type]
    except (ValueError, TypeError, OverflowError) as exc:
        # `#1334` ⑴ — 「2026년」처럼 오면 `ValueError`다. 종전에는 500이 됐다.
        # 무한대(`Infinity`)는 `OverflowError`다 (`#2493`) — 같은 인자 오류로 답한다.
        raise ToolArgumentError("regulation_year") from exc


def envelope(
    tool: str,
    *,
    result: dict[str, object] | None = None,
    error: str | None = None,
    kind: str | None = None,
    fuel_basis: str | None = None,
) -> str:
    """도구 응답을 봉투에 담아 **문자열**로 만든다.

    문자열로 만드는 이유 — 수학 검증 가드(``verify_numbers``)가 **도구 응답의 수치를
    문자열에서 찾는다.** 구조를 유지한 채 넘기면 가드가 볼 수 있는 형태가 아니다.

    ``result``는 :func:`~cii_platform.services.llm_guard.filter_outbound`를 **이미
    지난 값**이어야 한다 — 이 함수는 필터하지 않는다(봉투의 책임이 아니다).
    """
    body: dict[str, object] = {"tool": tool, "ok": error is None}
    # `#1533` — 저장된 결과의 종류(``calculation_run.calculation_type``의 네 상수 중 하나).
    # 우리가 정한 코드값이라 봉투에 둔다 — 도메인 값이 아니다.
    if kind is not None:
        body["kind"] = kind
    # `#2395` — 항차 도구가 연료를 선박 등록값으로 채웠는가(:data:`FUEL_BASIS_VESSEL_REFERENCE`).
    # ``kind``와 같이 우리가 정한 코드값이다 — 모델은 답에 「등록값 기준 추정」을 밝힌다.
    if fuel_basis is not None:
        body["fuel_basis"] = fuel_basis
    if error is not None:
        body["error"] = error
    if result is not None:
        body["result"] = result
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


#: API 응답 필드명 → ``PRD §16.3.1`` 화이트리스트 이름.
#:
#: ⚠️ **이름이 갈려 있다.** 정본은 개념 이름(``rating``·``next_boundary_gap``)으로
#: 적혀 있고 API 응답은 구현 이름(``estimated_rating``·
#: ``next_worse_boundary_margin_ratio``)을 쓴다. **경계에서 맞춘다** — 화이트리스트를
#: 넓히는 쪽은 고르지 않았다. 목록에 구현 이름을 더하면 *같은 값이 두 이름으로* 허용
#: 목록에 남고, 나중에 API 필드명을 바꿀 때 정본까지 따라 바뀌어야 한다.
_PUBLISH_MAP: dict[str, str] = {
    "attained_cii": "attained_cii",
    "required_cii": "required_cii",
    "rating": "rating",
    "estimated_rating": "rating",
    "risk_level": "risk_level",
    "next_worse_boundary_margin_ratio": "next_boundary_gap",
    # `#2392` — 실적 ÷ 기준. 화면 제안 질문 「기준 CII 대비 몇 %」가 이 값을 묻는다. 없으면
    # 모델이 직접 나누고, 그 답은 No-Compute 가드에 폐기된다(10-09 운영).
    "ratio_to_required": "ratio_to_required",
    # `#1533` — 연간 시뮬레이션 저장 결과. ``projected_*``는 연말 예상이라 화면이 같은
    # 자리에 「연말 예상」으로 보여 준다 — 모델에게는 ``kind``가 그 맥락을 준다.
    "projected_attained_cii": "attained_cii",
    "projected_rating": "rating",
    "target_rating": "target_rating",
    "target_success_probability": "target_success_probability",
    "rating_probabilities": "rating_probabilities",
    # `#2395` — 시나리오 행과 항차 계산이 **질문이 묻는 값**을 직접 싣는다. 없으면 모델이
    # 속력·거리로 소요시간을 나누거나 CO₂를 짐작하고, 그 답은 No-Compute 가드에 폐기된다
    # (10-17 결정 2). ⚠️ 연료량(``fuel_ton``)·연료 종류(``fuel_type``)는 ``PRD §16.3.1``
    # 「보내지 않는 것」이라 여기에 두지 않는다 — 대응표에 없으면 ``_publishable``이 줍지 않는다.
    "scenario_type": "scenario_type",
    "distance_nm": "distance_nm",
    "speed_kn": "speed_kn",
    "duration_hours": "duration_hours",
    "co2_emission_ton": "co2_emission_ton",
}


#: 도구가 내보내는 값 — **모든 도구가 같은 묶음을 쓴다.**
#:
#: 도구마다 다른 묶음을 고르면 「이 도구는 위험도를 주고 저 도구는 안 준다」가 되어
#: 모델이 없는 값을 찾다가 왕복을 더 쓴다(``PRD §16.1`` 가드 2 · 호출 상한).
_RESULT_KEYS: tuple[str, ...] = (
    "attained_cii",
    "required_cii",
    "rating",
    "estimated_rating",
    "risk_level",
    "next_worse_boundary_margin_ratio",
    "ratio_to_required",
)


#: `#2395` — 시나리오 행이 더 싣는 값: 종류·속력·거리·소요시간·CO₂.
#:
#: 「속도를 낮추면 얼마나 걸리고 CO₂는 얼마인가」가 묻는 값이 이것이다. 종전에는 CII 묶음만
#: 넘겨 모델이 속력·거리로 시간을 직접 나눴고, 그 답은 수치 가드에 폐기됐다(10-17 결정 2).
#: 공통 묶음(:data:`_RESULT_KEYS`)에 넣지 않는 것은 **시나리오 행에만 있는 값**이기 때문이다.
_SCENARIO_KEYS: tuple[str, ...] = (
    *_RESULT_KEYS,
    "scenario_type",
    "speed_kn",
    "distance_nm",
    "duration_hours",
    "co2_emission_ton",
)

#: `#2395` — 항차 CII 도구가 더 싣는 값: 거리·속력. 모델이 보낸 입력을 되돌려 주는 것이라
#: 새 정보는 아니지만, 없으면 「이 항차(5,000nm · 12kn)는…」처럼 조건을 되짚는 답도 버려진다.
_VOYAGE_KEYS: tuple[str, ...] = (*_RESULT_KEYS, "distance_nm", "speed_kn")


#: `#2392` — 기준 대비 비율. 화면은 백분율로 보여 준다(``_with_screen_percent``).
_RATIO_KEY = "ratio_to_required"

#: 비율로 내려가는 값 — 화면은 **백분율로 보여 준다**.
_GAP_KEY = "next_boundary_gap"
#: `#1533` — 확률 값도 0~1 비율로 저장돼 있고 화면은 백분율로 보여 준다.
_PROBABILITY_KEY = "target_success_probability"
_RATING_PROBABILITIES_KEY = "rating_probabilities"

#: `#1533` — 연간 시뮬레이션 저장 결과에서 내보내는 값(``deterministic`` · ``monte_carlo``
#: · 최상위 ``risk_level``을 한 층으로 모은 뒤의 이름).
_ANNUAL_KEYS: tuple[str, ...] = (
    "projected_attained_cii",
    "projected_rating",
    "risk_level",
    "target_rating",
    "target_success_probability",
    "rating_probabilities",
)

#: 화면의 백분율 자릿수 (`DESIGN_SYSTEM §4.1` · ``DISPLAY_DIGITS.percent`` = 1).
_PERCENT_QUANTUM = Decimal("0.1")


def _with_screen_percent(value: object) -> object:
    """비율 값에 **화면 표기를 덧붙인다** (`#1334` ⑵).

    ``"0.012345"`` → ``"0.012345 (1.2%)"``

    ## 왜 필요한가

    수치 가드(``verify_numbers``)는 도구 응답 **문자열**에서 수치를 찾는다. 화면은
    ``formatPercent(marginRatio)``로 ``1.2%``를 쓰는데 도구는 ``0.012345``만
    줬으므로, 모델이 **화면과 같은 표기로 답하면 폐기됐다**(실측).

    ``_rounded_forms``가 같은 문제를 이미 한 번 겪었다 — *「화면과 같은 자릿수로
    말할 수 없으면 면책이 거짓이 된다」*(``PRD §6.3``). **자릿수는 고쳤는데 단위는
    고치지 않은 것**이라, 같은 해법을 쓴다.

    ## 왜 새 키를 만들지 않는가

    ``PRD §16.3.1`` 화이트리스트는 **키 이름**을 검사한다. 키를 늘리면 *같은 값이 두
    이름으로* 허용 목록에 남는다 — :data:`_PUBLISH_MAP` 주석이 이름 문제에서 이미
    기각한 형태다. 값 하나에 두 표기를 담으면 화이트리스트를 건드리지 않는다.

    ## 왜 가드를 넓히지 않는가

    가드가 ×100 표기를 **무조건** 허용하면 도구가 ``0.07``을 준 답에서 ``7%``도
    통과한다 — **다른 뜻의 수**다. 가드의 원칙은 「막을 것은 표기가 아니라
    **출처**」(``IT-CHAT-008``)이고, 여기서 바꾸는 것은 **출처 쪽**이다.
    """
    try:
        ratio = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):  # pragma: no cover - 문자열 수치만 온다
        return value
    percent = (ratio * 100).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
    return f"{value} ({percent}%)"


def _with_baseline_difference(value: object) -> object:
    """기준 대비 비율에 **화면 백분율과 기준과의 차**를 덧붙인다 (`#2395` 결정 2).

    ``"0.98000"`` → ``"0.98000 (98.0% · 기준 대비 -2.0%p · 기준보다 2.0%p 낮음)"``

    ``"1.77623"`` → ``"1.77623 (177.6% · 기준 대비 +77.6%p · 기준보다 77.6%p 높음)"``

    ## 왜 필요한가

    화면 제안 질문 「연말 예상 값은 기준 CII 대비 몇 %인가요?」에 사람은 「기준보다 2.0%
    낮습니다」로 답한다. 도구가 ``98.0%``만 주면 ``2.0``은 **모델이 뺀 수**라 수치 가드에
    폐기됐다(10-17 결정 2). 가드는 그대로 두고 **출처 쪽**이 그 수를 싣는다 —
    :func:`_with_screen_percent`와 같은 판단이고, 같은 값에 표기를 덧붙이므로 키를 늘리지
    않는다.

    ## 차는 화면 백분율에서 뺀다

    ``(ratio × 100).quantize() − 100``이다. ``(ratio × 100 − 100).quantize()``로 하면
    ``ROUND_HALF_UP``이 음수를 0에서 먼 쪽으로 올려 ``97.95`` → 화면 ``98.0%``인데 차는
    ``-2.1``이 된다 — **한 문장 안의 두 수가 서로 맞지 않는다.**

    부호 있는 표기(``-2.0``)와 크기(``2.0``)를 함께 싣는 것은 모델이 어느 쪽으로 말해도
    같은 값이어서다. 수치 가드의 ``-``는 부호로 읽히므로(``llm_guard._NUMBER``) 둘은 다른
    토큰이다.
    """
    try:
        ratio = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):  # pragma: no cover - 문자열 수치만 온다
        return value
    percent = (ratio * 100).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
    gap = percent - 100
    if gap < 0:
        difference = f"기준 대비 {gap}%p · 기준보다 {-gap}%p 낮음"
    elif gap > 0:
        difference = f"기준 대비 +{gap}%p · 기준보다 {gap}%p 높음"
    else:
        difference = f"기준 대비 {abs(gap)}%p · 기준과 같음"
    return f"{value} ({percent}% · {difference})"


def _publishable(payload: dict[str, object], keys: tuple[str, ...]) -> dict[str, object]:
    """응답에서 화이트리스트 대상 값만 뽑아 **이름을 맞춘 뒤** 필터를 태운다.

    :param keys: **API 응답 쪽 필드명**. :data:`_PUBLISH_MAP`이 정본 이름으로 옮긴다.

    필터를 마지막에 거는 것이 중요하다 — 옮긴 뒤에 걸어야 ``filter_outbound``가
    **실제로 나가는 이름**을 본다. 옮기기 전에 걸면 통과한 이름과 나가는 이름이 달라
    가드가 헛돈다.
    """
    picked = {
        _PUBLISH_MAP[key]: payload[key]
        for key in keys
        if key in _PUBLISH_MAP and payload.get(key) is not None
    }
    gap = picked.get(_GAP_KEY)
    if gap is not None:
        picked[_GAP_KEY] = _with_screen_percent(gap)
    # `#2395` — 기준 대비 비율은 백분율에 **기준과의 차**까지 덧붙인다.
    ratio = picked.get(_RATIO_KEY)
    if ratio is not None:
        picked[_RATIO_KEY] = _with_baseline_difference(ratio)
    # `#1533` — 확률도 화면은 백분율로 보여 준다(``_with_screen_percent`` 머리말과 같은 이유).
    probability = picked.get(_PROBABILITY_KEY)
    if probability is not None:
        picked[_PROBABILITY_KEY] = _with_screen_percent(probability)
    by_rating = picked.get(_RATING_PROBABILITIES_KEY)
    if isinstance(by_rating, dict):
        picked[_RATING_PROBABILITIES_KEY] = {
            str(grade): _with_screen_percent(value) for grade, value in sorted(by_rating.items())
        }
    return filter_outbound(picked)


#: 도메인 오류 → **우리가 만든 고정 문구**.
#:
#: ⚠️ **원문을 그대로 넘기면 화이트리스트가 오류 경로로 뚫린다** (2026-09-13 실측).
#:
#: .. code-block:: text
#:
#:     {"error": "선박을 찾을 수 없습니다: 3d56c710-089e-4299-95b3-e48650318d45", ...}
#:                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#:     `PRD §16.3.1`이 `vessel_id`를 **전송 금지**로 둔 값이 그대로 외부 모델로 갔다.
#:
#: 도메인 오류 문구는 식별자를 흔히 담는다 — ``vessel_id``·``voyage_id``·
#: ``ship_type``·연료 코드·항만명이 전부 후보다. **어느 문구가 안전한지 목록으로
#: 관리하는 것은 성립하지 않는다** — 새 오류가 생길 때마다 검토가 필요하고, 빠뜨리면
#: 조용히 샌다(전송은 되돌릴 수 없다).
#:
#: 그래서 **종류별 고정 문구**로 바꾼다. 봉투의 원칙(「우리가 만든 상수만 담는다」)이
#: 오류 칸에도 그대로 선다.
#:
#: **잃는 것** — 구체성이다. 「속력은 1.0 이상이어야 합니다」가 「입력값이 올바르지
#: 않습니다」가 된다. 감수하는 이유는 ⑴ 화면 폼은 여전히 구체적 문구를 그대로 받고
#: (이 경로는 챗봇 전용이다) ⑵ 챗봇의 입력은 **모델이 만든 것**이라 사용자가 고칠
#: 값이 아니며 ⑶ 좁게 시작해 넓히는 것이 반대보다 쉽다(`#120` 화이트리스트와 같은 판단).
class ToolArgumentError(Exception):
    """모델이 보낸 도구 인자를 읽을 수 없다 (`#1334` ⑴).

    **밖으로 나가는 것은 고정 문구 하나**다(:data:`_ERROR_TEXT`) — 어느 인자가
    잘못됐는지도 말하지 않는다. 인자 이름은 모델이 스스로 보낸 것이라 유출은
    아니지만, 문구를 인자마다 만들면 **오류 문구가 값을 실어 나르는 경로**가 하나
    더 생긴다(`#1310`이 화이트리스트가 오류 경로로 뚫린 것을 고쳤다).
    """


def _required_decimal(arguments: dict[str, object], key: str) -> Decimal:
    """필수 숫자 인자. **없거나 숫자가 아니면 봉투로 되돌린다.**"""
    if key not in arguments or arguments[key] is None:
        raise ToolArgumentError(key)
    try:
        return Decimal(str(arguments[key]))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ToolArgumentError(key) from exc


def _optional_decimal(arguments: dict[str, object], key: str) -> Decimal | None:
    """선택 숫자 인자. 없으면 ``None``, **있는데 읽히지 않으면 오류**다.

    읽히지 않는 값을 ``None``으로 삼키면 모델이 보낸 조건이 **조용히 사라진다** —
    그 답은 사용자가 물은 것과 다른 계산의 결과가 된다.
    """
    if key not in arguments or arguments[key] is None:
        return None
    try:
        return Decimal(str(arguments[key]))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ToolArgumentError(key) from exc


def _required_text(arguments: dict[str, object], key: str) -> str:
    if key not in arguments or arguments[key] is None:
        raise ToolArgumentError(key)
    return str(arguments[key])


_ERROR_TEXT: tuple[tuple[type[Exception], str], ...] = (
    (NotFoundError, "요청하신 대상을 찾을 수 없습니다."),
    (ParameterError, "그 조건에 필요한 규정 파라미터가 없습니다."),
    (CalculationError, "이 조건으로는 계산할 수 없습니다."),
    (ValidationError, "입력값이 올바르지 않습니다. 숫자 범위를 확인해 주세요."),
    # `#1334` ⑴ — 모델이 인자를 빼거나 「약 100」·「2026년」처럼 보내는 경우.
    # 종전에는 `KeyError`·`InvalidOperation`·`ValueError`가 잡히지 않아 **턴 전체가
    # 500으로 끊겼고**, 롤백으로 방금 저장한 질문까지 사라졌다.
    (
        ToolArgumentError,
        "도구에 넘길 값이 빠졌거나 숫자로 읽히지 않습니다. 숫자만 넣어 다시 시도해 주세요.",
    ),
)


#: 규제연도가 조회 범위 밖일 때의 정해진 문장 (`#2480`). 서비스까지 내려가면 도구마다
#: 답이 갈린다 — 어떤 도구는 「입력값이 올바르지 않습니다」, 어떤 도구는 「규정 파라미터가
#: 없습니다」, 조회는 ``ok: true``에 빈 값이다. 사용자에게는 같은 사정이므로 한 문장으로 답한다.
_YEAR_OUT_OF_RANGE_TEXT = (
    f"규제연도는 {MIN_REGULATION_YEAR}~{MAX_REGULATION_YEAR} 사이로 물어 주세요."
)


def _year_out_of_range(arguments: dict[str, object]) -> bool:
    """모델이 넘긴 규제연도가 정수로 읽히면서 조회 범위 밖인가.

    정수로 읽히지 않는 값은 여기서 다루지 않는다 — 기존 ``ToolArgumentError`` 경로가 맡는다.
    """
    raw = arguments.get("regulation_year")
    if raw is None or isinstance(raw, bool):
        return False
    try:
        year = int(raw)  # type: ignore[arg-type]
    except (ValueError, TypeError, OverflowError):
        return False
    return not MIN_REGULATION_YEAR <= year <= MAX_REGULATION_YEAR


def _error_text(exc: Exception) -> str:
    """예외 → 고정 문구. **원문을 쓰지 않는다.**

    순서가 있다 — ``ValidationError``를 마지막에 둔다. 하위 클래스 관계가 생기더라도
    더 좁은 것이 먼저 잡히게 한다.
    """
    for kind, text in _ERROR_TEXT:
        if isinstance(exc, kind):
            return text
    # 여기 오면 `run_tool`의 except 절과 이 표가 갈린 것이다 — 그래도 원문은 안 쓴다.
    return "요청을 처리할 수 없습니다."


@dataclass(frozen=True)
class ToolOutcome:
    """도구 하나의 결과 (#1243).

    ``envelope``은 모델에게 가는 봉투 그대로, ``resolved_vessel_id``는 검색의 고유
    일치가 정한 선박 — **호출부(턴 루프)만** 알고 모델에게는 나가지 않는다.
    """

    envelope: str
    resolved_vessel_id: UUID | None = None
    #: 이 도구가 **실제로 읽어 모델에게 준** 저장된 계산 실행의 id (`#2099`) — 감사 로그
    #: ``CHAT_TOOL_CALL``이 ``calculation_run_id``로 싣는다. 읽지 않은 도구는 ``None``.
    calculation_run_id: UUID | None = None


async def run_tool(
    session: AsyncSession,
    *,
    name: str,
    arguments: dict[str, object],
    vessel_id: object | None,
    chat_session_id: UUID | None = None,
    vessel_locked: bool = False,
    screen_run_id: UUID | None = None,
    current_year: int | None = None,
    current_year_only: bool = False,
) -> ToolOutcome:
    """도구 하나를 실행하고 **봉투에 담은 문자열**을 돌려준다.

    :param vessel_id: 이 대화가 고른 선박. ``search_vessel``이 정하거나 화면이 준다.
        **모델에게는 넘기지 않는다** — 식별자는 화이트리스트 밖이다.
    :param chat_session_id: 검색의 고유 일치를 **세션 귀속으로 저장**하는 경로
        (#1242). 없으면(단위 검사 등) 저장 없이 결과만 낸다.
    :param vessel_locked: 이 턴에 **화면이 ``vessel_id``를 넘겼다**는 표시 — 세션
        귀속이 화면값을 덮어쓰지 않는다(``API_SPEC §15.1`` 우선순위).
    :param screen_run_id: 이 턴에 화면이 넘긴 ``calculation_run_id`` (`#1533`).
        **모델에게는 넘기지 않는다** — 모델은 「화면의 결과를 읽어라」만 고른다.

    ## 실패를 자연어로 돌려주지 않는다

    오류는 **봉투의 ``error``**로 간다. 모델이 그것을 읽고 사용자에게 설명한다 —
    서버가 문장을 만들면 같은 말을 두 곳에서 쓰게 된다(`#121` 「에러 처리: API 호출
    실패 시 자연어로 안내」).
    """
    if name not in TOOL_NAMES:
        return ToolOutcome(envelope(name, error="알 수 없는 도구입니다."))

    # 채팅 턴이 확정한 한국 달력 해를 연도 미지정 도구에도 전달한다. 모델 입력과 도구
    # 실행 사이에 자정 경계를 넘어도 같은 '올해'를 쓴다 (#2355).
    if (
        current_year is not None
        and name in _YEAR_DEFAULT_TOOLS
        and (current_year_only or arguments.get("regulation_year") is None)
    ):
        arguments = {**arguments, "regulation_year": current_year}

    # `#2480` — 범위 밖 해는 서비스로 내려가지 않고 정해진 문장으로 답한다.
    if name in _YEAR_DEFAULT_TOOLS and _year_out_of_range(arguments):
        return ToolOutcome(envelope(name, error=_YEAR_OUT_OF_RANGE_TEXT))

    try:
        if name == TOOL_SEARCH_VESSEL:
            return await _search_vessel(
                session,
                arguments,
                chat_session_id=chat_session_id,
                vessel_locked=vessel_locked,
            )
        if name == TOOL_EXPLAIN_SCREEN_RESULT:
            explained = await _explain_screen_result(session, screen_run_id, vessel_id)
            # `#2099` — 결과를 실제로 모델에게 준 경우(`ok`)에만 그 실행을 인용한 것으로 남긴다.
            cited = screen_run_id if json.loads(explained).get("ok") else None
            return ToolOutcome(explained, calculation_run_id=cited)
        if name == TOOL_LOOKUP_REGULATION:
            # 선박 없이도 돈다 — 선종을 말하면 표를 읽는 데 선박은 필요 없다.
            return ToolOutcome(await _lookup_regulation(session, arguments, vessel_id))
        if vessel_id is None:
            return ToolOutcome(envelope(name, error="어느 선박인지 먼저 정해야 합니다."))
        if name == TOOL_CALC_VOYAGE_CII:
            return ToolOutcome(await _calc_voyage_cii(session, arguments, vessel_id))
        if name == TOOL_COMPARE_SCENARIOS:
            return ToolOutcome(await _compare_scenarios(session, arguments, vessel_id))
        return ToolOutcome(await _project_year_end(session, arguments, vessel_id))
    except (
        ValidationError,
        NotFoundError,
        ParameterError,
        CalculationError,
        ToolArgumentError,
    ) as exc:
        # ⚠️ **원문을 넘기지 않는다.** 아래 `_ERROR_TEXT` 주석 참조.
        return ToolOutcome(envelope(name, error=_error_text(exc)))


#: `search_vessel`이 한 번에 조회하는 건수. 넘치면 척수를 단정하지 않는다 (`#2099`).
_SEARCH_VESSEL_LIMIT = 5


async def _search_vessel(
    session: AsyncSession,
    arguments: dict[str, object],
    *,
    chat_session_id: UUID | None = None,
    vessel_locked: bool = False,
) -> ToolOutcome:
    """⚠️ **이름·식별자를 돌려주지 않는다.** 몇 척인지만 말한다.

    ``PRD §16.3.1``이 선박명·IMO·선박 ID를 전송 금지로 둔다. 검색 결과를 그대로
    돌려주면 **그 금지가 도구 하나로 뚫린다.** 선박을 고르는 것은 서버가 하고, 모델은
    「찾았다」만 안다.

    결과의 귀속은 **호출부(턴 루프)**가 정한다(#1243) — 여기는 ``resolved_vessel_id``로
    알려 주기만 한다. 고유 일치만 정한다. 둘 이상이 걸리면 **화면에서 고르라는 오류
    봉투**를 낸다(#1242의 「모델이 키워드를 좁힌다」에서 변경 — 애매한 것을 몰래
    고르지 않는다는 규율은 그대로). 화면이 ``vessel_id``를 넘긴 턴(``vessel_locked``)은
    귀속을 내지 않는다 — 화면값이 항상 더 최신이다.
    """
    from cii_platform.services import vessel as vessel_service

    keyword = str(arguments.get("name") or "").strip()
    if not keyword:
        return ToolOutcome(envelope(TOOL_SEARCH_VESSEL, error="찾을 이름을 알려 주세요."))
    rows, page_meta = await vessel_service.list_vessels(
        session, search=keyword, limit=_SEARCH_VESSEL_LIMIT
    )
    if len(rows) >= 2:
        # `#2099` — `len(rows)`는 한 쪽(5건)으로 자른 길이다. 더 있으면(`has_more`) 정확한
        # 척수를 모르므로 「5척」이라 말하지 않고 「5척 이상」이라 말한다.
        count = f"{len(rows)}척 이상" if page_meta.get("has_more") else f"{len(rows)}척"
        return ToolOutcome(
            envelope(
                TOOL_SEARCH_VESSEL,
                error=f"{count}이 일치합니다. 화면에서 선박을 고른 뒤 다시 물어봐 주세요.",
            )
        )
    resolved = UUID(str(rows[0]["id"])) if len(rows) == 1 and not vessel_locked else None
    return ToolOutcome(
        envelope(TOOL_SEARCH_VESSEL, result={"matched": len(rows)}),
        resolved_vessel_id=resolved,
    )


#: `#2395` — 항차 도구가 연료를 선박 등록값으로 채웠다는 표시. 봉투의 코드값이다.
FUEL_BASIS_VESSEL_REFERENCE = "vessel_reference"

#: 연료량을 받지 못했고 선박 등록값으로도 추정할 수 없을 때의 정해진 문장.
_NO_FUEL_TEXT = (
    "선박에 기준 연료 소모량·기준 속력·기본 유종이 모두 등록돼 있지 않아 연료량을 추정할 수 "
    "없습니다. 연료 종류와 연료량을 알려 주세요."
)


async def _calc_voyage_cii(
    session: AsyncSession, arguments: dict[str, object], vessel_id: object
) -> str:
    from cii_platform.services.voyage_cii import (
        FuelUseInput,
        VoyageCiiInput,
        estimate_voyage_cii,
    )

    distance_nm = _required_decimal(arguments, "distance_nm")
    speed_kn = _required_decimal(arguments, "speed_kn")
    fuel_ton = _optional_decimal(arguments, "fuel_ton")
    fuel_type = arguments.get("fuel_type")
    basis: str | None = None
    # `#2395` — 예시 질문(「부산–싱가포르 2,300해리를 12노트로」)은 연료를 말하지 않는다.
    # 종전에는 연료량이 필수라 모델이 계산하지 못하고 되물었다. 빠진 값은 `PRD §11.4` 2단계
    # (선박 기준 소모량 × cubic speed model)와 선박 기본 유종으로 채운다 — 화면 시나리오
    # 비교(`scenario_compare._resolve_base_daily_foc`)가 이미 쓰는 우선순위다.
    if fuel_ton is None or fuel_type is None:
        estimated = await _vessel_fuel(session, vessel_id, distance_nm, speed_kn)
        if estimated is None:
            return envelope(TOOL_CALC_VOYAGE_CII, error=_NO_FUEL_TEXT)
        default_type, default_ton = estimated
        if fuel_type is None:
            fuel_type = default_type
        if fuel_ton is None:
            fuel_ton = default_ton
        basis = FUEL_BASIS_VESSEL_REFERENCE

    payload = VoyageCiiInput(
        vessel_id=vessel_id,  # type: ignore[arg-type]
        regulation_year=_regulation_year(arguments),
        distance_nm=distance_nm,
        speed_kn=speed_kn,
        fuel_uses=(FuelUseInput(fuel_type=str(fuel_type), fuel_ton=fuel_ton),),
    )
    # `#1334` ⑷ — **저장하지 않는다.** 이 모듈 머리말의 「쓰기 도구를 넣지 않는다」를
    # 읽기 도구가 어기고 있었다(`calculation_run`은 지울 수 없다).
    response = await estimate_voyage_cii(session, payload, persist=False)
    data = response.get("data") or {}
    # `#2395` — 응답 ``data``에는 속력이 없다(거리만 에코한다). 모델이 보낸 속력을 같은
    # 숫자 형태로 되돌려 준다 — 거리 에코(``float``)와 표기를 맞춘다.
    published_from = {**data, "speed_kn": float(payload.speed_kn)}  # type: ignore[dict-item]
    return envelope(
        TOOL_CALC_VOYAGE_CII,
        result=_publishable(published_from, _VOYAGE_KEYS),
        fuel_basis=basis,
    )


async def _vessel_fuel(
    session: AsyncSession, vessel_id: object, distance_nm: Decimal, speed_kn: Decimal
) -> tuple[str, Decimal] | None:
    """선박 등록값으로 (기본 유종, 추정 연료량)을 낸다 — 하나라도 없으면 ``None``.

    연료량은 ``PRD §11.4.1`` cubic speed model이다(기상 보정 없음). 값이 모델에게 나가지
    않는다 — 연료량·연료 종류는 ``PRD §16.3.1`` 「보내지 않는 것」이다.
    """
    from cii_platform.calc.fuel_estimator import estimate_fuel_ton
    from cii_platform.db.models.vessel import Vessel

    vessel = await session.get(Vessel, vessel_id)
    if vessel is None:
        raise NotFoundError("선박을 찾을 수 없습니다.")
    base = vessel.reference_daily_foc_ton
    reference_speed = vessel.reference_speed_kn
    fuel_type = vessel.default_fuel_type
    if not fuel_type or base is None or reference_speed is None:
        return None
    if Decimal(base) <= 0 or Decimal(reference_speed) <= 0:
        return None
    try:
        fuel_ton = estimate_fuel_ton(
            distance_nm=distance_nm,
            speed_kn=speed_kn,
            reference_speed_kn=Decimal(reference_speed),
            base_daily_foc_ton=Decimal(base),
        )
    except ValueError as exc:
        raise ToolArgumentError("speed_kn") from exc
    return str(fuel_type), fuel_ton


def _hull_condition_argument(arguments: dict[str, object]) -> Decimal | None:
    """선체 상태 보정 % 인자 — 화면 요청과 **같은 범위**를 본다 (`#2561`).

    도구 경로는 Pydantic 스키마를 거치지 않으므로, 범위 밖 값이 계산까지 가면 화면에서는
    422인 입력이 챗봇에서는 숫자를 낸다. 범위 밖이면 인자 오류로 되돌린다.
    """
    from cii_platform.validation.bounds import HULL_CONDITION_PERCENT

    value = _optional_decimal(arguments, "hull_condition_percent")
    if value is None:
        return None
    if not HULL_CONDITION_PERCENT["ge"] <= value <= HULL_CONDITION_PERCENT["le"]:
        raise ToolArgumentError("hull_condition_percent")
    return value


async def _compare_scenarios(
    session: AsyncSession, arguments: dict[str, object], vessel_id: object
) -> str:
    from cii_platform.services.scenario_compare import ScenarioCompareInput, compare_scenarios

    payload = ScenarioCompareInput(
        vessel_id=vessel_id,  # type: ignore[arg-type]
        regulation_year=_regulation_year(arguments),
        current_speed_kn=_required_decimal(arguments, "current_speed_kn"),
        fuel_type=_required_text(arguments, "fuel_type"),
        direct_distance_nm=_optional_decimal(arguments, "direct_distance_nm"),
        base_daily_foc_ton=_optional_decimal(arguments, "base_daily_foc_ton"),
        hull_condition_percent=_hull_condition_argument(arguments),
    )
    # `#1334` ⑷ — 저장하지 않는다. 위와 같은 이유다.
    response = await compare_scenarios(session, payload, persist=False)
    scenarios = (response.get("data") or {}).get("scenarios") or []  # type: ignore[union-attr]
    # ⚠️ 시나리오를 **순위로 정렬하지 않는다** — 순위화는 No-Advice 금지 항목이다.
    return envelope(
        TOOL_COMPARE_SCENARIOS,
        result={"scenarios": [_publishable(row, _SCENARIO_KEYS) for row in scenarios]},
    )


async def _project_year_end(
    session: AsyncSession, arguments: dict[str, object], vessel_id: object
) -> str:
    from cii_platform.services.cii_current import get_current_cii

    # ⚠️ ``data``에는 ``vessel_name``이 들어 있다 — **통째로 넘기지 않는다.**
    # ⑶ 블록만 꺼내 필터를 태운다.
    data, _meta = await get_current_cii(
        session,
        vessel_id,  # type: ignore[arg-type]
        year=_regulation_year(arguments),
    )
    year_end = data.get("year_end_projection") or {}
    if not isinstance(year_end, dict) or not year_end.get("data_available"):
        # 못 낸 사유는 **코드 그대로** 넘긴다. 서버가 문장을 만들지 않는다.
        reason = (year_end or {}).get("reason") if isinstance(year_end, dict) else None
        return envelope(
            TOOL_PROJECT_YEAR_END,
            error=f"연말 예상을 낼 수 없습니다 (사유 코드: {reason or 'UNKNOWN'}).",
        )
    # `#1533` — 올해 누적(⑴ ``ytd``)도 함께 넘긴다. 실시간 CII 화면이 크게 보여 주는 값이
    # 이것인데 종전에는 ⑶ 블록만 넘겨 「왜 지금 E야?」에 답할 수 없었다. 결정론 계산이라
    # 같은 선박·연도로 다시 불러도 화면과 같은 값이다(결정 코멘트 `D-31`).
    ytd = data.get("ytd")
    result: dict[str, object] = {"year_end_projection": _publishable(year_end, _RESULT_KEYS)}
    if isinstance(ytd, dict) and ytd.get("data_available"):
        result["ytd"] = _publishable(ytd, _RESULT_KEYS)
    return envelope(TOOL_PROJECT_YEAR_END, result=result)


#: `#1533` — 저장 결과를 읽었는데 설명할 값이 없을 때(``#443`` 이전 연간 실행 등).
_SCREEN_RESULT_EMPTY = (
    "이 결과에는 설명에 쓸 값이 저장돼 있지 않습니다. 화면에서 다시 계산해 주세요."
)


async def _explain_screen_result(
    session: AsyncSession, screen_run_id: UUID | None, vessel_id: object | None
) -> str:
    """화면이 넘긴 실행의 **저장된 결과**를 읽는다 (`#1533` · ``API_SPEC §15.1``).

    ## 새로 계산하지 않는다

    저장된 ``result_json``을 그대로 읽는다. 다시 계산하면 그 사이 규정 파라미터가 바뀌었을
    때 화면과 다른 값이 나온다 — ``get_annual_simulation``이 다시 계산하지 않는 것과 같은
    이유다.

    ## 선박이 다르면 읽지 않는다

    화면 상단의 선박(``vessel_id``)과 실행의 선박이 다르면 오류다. 사용자는 상단의 배를
    보며 묻는데, 다른 배의 결과로 답하면 **맞는 수로 틀린 설명**이 된다. 상단 선박이
    없으면(선박 없이 연 화면) 실행의 선박을 따지지 않는다 — 식별자는 어차피 나가지 않는다.
    """
    from cii_platform.db.models.calculation_run import CalculationRun

    if screen_run_id is None:
        return envelope(
            TOOL_EXPLAIN_SCREEN_RESULT,
            error="화면에서 넘겨받은 계산 결과가 없습니다. 화면에서 먼저 계산해 주세요.",
        )
    run = await session.get(CalculationRun, screen_run_id)
    if run is None:
        raise NotFoundError("계산 결과를 찾을 수 없습니다.")
    if vessel_id is not None and str(run.vessel_id) != str(vessel_id):
        return envelope(
            TOOL_EXPLAIN_SCREEN_RESULT,
            error="화면의 계산 결과와 상단에서 고른 선박이 다릅니다. 선박을 확인해 주세요.",
        )

    kind = str(run.calculation_type)
    stored = run.result_json if isinstance(run.result_json, dict) else {}
    if kind == "SCENARIO":
        rows = stored.get("scenarios") or []
        if not rows:
            return envelope(TOOL_EXPLAIN_SCREEN_RESULT, error=_SCREEN_RESULT_EMPTY, kind=kind)
        # ⚠️ 저장 순서 그대로 — 순위로 정렬하지 않는다(No-Advice).
        return envelope(
            TOOL_EXPLAIN_SCREEN_RESULT,
            # `#2395` — 화면의 시나리오 결과도 비교 도구와 같은 값을 싣는다. 같은 질문이
            # 화면에서 오든 도구로 오든 답할 수 있는 값이 달라지지 않게 한다.
            result={"scenarios": [_publishable(row, _SCENARIO_KEYS) for row in rows]},
            kind=kind,
        )
    if kind.startswith("ANNUAL_"):
        flat: dict[str, object] = {}
        for block in ("deterministic", "monte_carlo"):
            section = stored.get(block)
            if isinstance(section, dict):
                flat.update(section)
        if stored.get("risk_level") is not None:
            flat["risk_level"] = stored["risk_level"]
        published = _publishable(flat, _ANNUAL_KEYS)
        if not published:
            return envelope(TOOL_EXPLAIN_SCREEN_RESULT, error=_SCREEN_RESULT_EMPTY, kind=kind)
        return envelope(TOOL_EXPLAIN_SCREEN_RESULT, result=published, kind=kind)
    published = _publishable(stored, _RESULT_KEYS)
    if not published:
        return envelope(TOOL_EXPLAIN_SCREEN_RESULT, error=_SCREEN_RESULT_EMPTY, kind=kind)
    return envelope(TOOL_EXPLAIN_SCREEN_RESULT, result=published, kind=kind)


#: `#1703` — 표에서 **모델에게 보내는 칸**. 판본·활성 여부·생성 시각은 뺀다 — 모델이 쓸 곳이
#: 없고, 보내지 않는 것이 기본이다(``PRD §16.3.1`` 「좁게 시작한다」).
_REFERENCE_LINE_FIELDS = ("condition_expr", "capacity_rule", "a_raw", "c", "source_ref")
_BOUNDARY_FIELDS = ("condition_expr", "capacity_basis", "d1", "d2", "d3", "d4", "source_ref")


def _pick(row: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {key: row.get(key) for key in fields}


def _grade_ranges(row: dict[str, object]) -> dict[str, str]:
    """등급별 구간을 **완성된 문장**으로 — 「앞 경계 초과 · 자기 경계 이하」 (`#1973` 후속).

    프롬프트 규칙만으로는 모델이 방향을 뒤집었다 — 규칙을 고친 뒤에도 운영 답이 「D: 1.0600배
    이상, 1.1800배 미만」이었다(09-28). 모델에게 방향을 **추론하게 두지 않고** 옮겨 적을 문장을
    준다. 경계값과 정확히 같으면 더 우수한 등급이다(``PRD §3.3.6`` ·
    ``rating_engine.determine_rating``의 ``<=``).

    **새 값이 아니다.** 같은 행의 d1~d4(저장된 자릿수 그대로의 문자열)를 조립할 뿐이라 수치
    검증(`llm_guard`)이 대조하는 숫자도 같다. 하나라도 비면 문장을 만들지 않는다 — 빈칸을
    채워 넣으면 없는 경계를 말하게 된다.

    ## 백분율 표기를 함께 싣는다 (`#1973` 폐기 후속)

    「1.0600배」를 사람은 흔히 「106%」로 말한다. 도구가 배수만 주면 그 표기가 수치 검증에
    막혀 **맞는 답이 폐기된다** — :func:`_with_screen_percent`가 계산 결과에서 이미 겪은
    문제라 같은 해법(값 하나에 화면 자릿수의 백분율을 덧붙인다)을 쓴다. 가드를 넓히지 않고
    **출처 쪽**을 바꾼다.
    """
    d1, d2, d3, d4 = (row.get(key) for key in ("d1", "d2", "d3", "d4"))
    if None in (d1, d2, d3, d4):
        return {}

    def ratio(value: object) -> str:
        percent = (Decimal(str(value)) * 100).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
        return f"{value}배({percent}%)"

    return {
        "A": f"{ratio(d1)} 이하",
        "B": f"{ratio(d1)} 초과 ~ {ratio(d2)} 이하",
        "C": f"{ratio(d2)} 초과 ~ {ratio(d3)} 이하",
        "D": f"{ratio(d3)} 초과 ~ {ratio(d4)} 이하",
        "E": f"{ratio(d4)} 초과",
    }


async def _lookup_regulation(
    session: AsyncSession, arguments: dict[str, object], vessel_id: object | None
) -> str:
    """규제 기준값 표를 **적재된 그대로** 읽는다 (`#1703`).

    값은 전부 ``services/parameters.py``의 기존 조회 서비스(``API_SPEC §7``)에서 온다 —
    설정 화면의 「규제 기준값」 절이 보여 주는 것과 같은 행이다. 같은 값이 화면과 챗봇에서
    달라질 자리를 만들지 않는다.

    ## 선종을 말하지 않으면 대화의 선박 선종

    ``vessel_id``가 있으면 그 선박의 ``ship_type``을 쓴다. 선종 코드는 규제 분류이지 선박을
    식별하지 않지만, **응답에 싣지는 않는다** — 모델은 사용자가 물은 맥락으로 이미 안다.

    ## 모르는 선종은 오류다

    빈 결과로 돌려주면 「그 선종의 값이 없다」와 「오타」가 구분되지 않는다
    (``_validate_ship_type``과 같은 판단). ``ValidationError``는 고정 문구로 바뀐다.
    """
    from cii_platform.services import parameters as param_service

    ship_type = arguments.get("ship_type")
    if ship_type is None and vessel_id is not None:
        from cii_platform.db.models.vessel import Vessel

        vessel = await session.get(Vessel, vessel_id)
        ship_type = getattr(vessel, "ship_type", None)
    if ship_type is None:
        return envelope(
            TOOL_LOOKUP_REGULATION,
            error="어느 선종의 기준값인지 알려 주세요(예: 벌크선).",
        )
    ship_type = str(ship_type).strip().upper()
    year = _regulation_year(arguments)

    lines = await param_service.list_reference_lines(session, ship_type=ship_type)
    boundaries = await param_service.list_rating_boundaries(session, ship_type=ship_type)
    years = await param_service.list_regulation_years(session)
    reduction = next((row for row in years if row.get("year") == year), None)

    result: dict[str, object] = {
        "reference_lines": [_pick(row, _REFERENCE_LINE_FIELDS) for row in lines],
        # 구간 문장은 행 안에 싣는다 — 외부 전송 화이트리스트(`llm_guard`)는 최상위 키를 보며
        # `rating_boundaries`는 이미 허용돼 있다. 담는 값이 바뀌므로 `PRD §16.3.1` 각주에 적었다.
        "rating_boundaries": [
            {**_pick(row, _BOUNDARY_FIELDS), "grade_ranges": _grade_ranges(row)}
            for row in boundaries
        ],
        # 표에 없는 연도면 **None**으로 둔다 — 가까운 연도의 값을 대신 주면 다른 해의 감축률을
        # 그 해의 것으로 말하게 된다.
        #
        # `#1973` 폐기 후속 — 모델은 물은 해 말고도 「2023년 5%」처럼 **다른 해의 감축률**을
        # 곧잘 덧붙이는데, 도구가 한 해만 주면 그 수가 수치 검증에 막혀 답 전체가 폐기된다.
        # 규제연도 표 전체를 **연도와 짝지어** 행 안에 싣는다(`grade_ranges`와 같은 자리 —
        # 화이트리스트는 최상위 키를 보고 `reduction_factor`는 이미 허용돼 있다).
        "reduction_factor": (
            None
            if reduction is None
            else {
                "year": reduction.get("year"),
                "z_factor_percent": reduction.get("z_factor_percent"),
                "source_ref": reduction.get("source_ref"),
                "by_year": [
                    {
                        "year": row.get("year"),
                        "z_factor_percent": row.get("z_factor_percent"),
                        "source_ref": row.get("source_ref"),
                    }
                    for row in years
                ],
            }
        ),
    }
    fuel_code = arguments.get("fuel_code")
    if fuel_code is not None:
        code = str(fuel_code).strip().upper()
        fuels = await param_service.list_fuel_types(session)
        fuel = next((row for row in fuels if str(row.get("code")).upper() == code), None)
        if fuel is None:
            raise NotFoundError("연료 종류를 찾을 수 없습니다.")
        result["fuel_cf"] = {
            "fuel_code": fuel.get("code"),
            "cf": fuel.get("cf"),
            "source_ref": fuel.get("source_ref"),
        }
    return envelope(TOOL_LOOKUP_REGULATION, result=filter_outbound(result))
