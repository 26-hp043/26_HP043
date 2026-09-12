"""챗봇 가드 둘 — 전송 화이트리스트와 수학 검증 (`#120`).

두 가드가 ``PRD §20 O-12`` 3대 봉쇄 원칙 중 둘을 **코드로** 만든다.

=============  ========================================  ==================
 원칙           무엇을 막나                                 여기의 구현
=============  ========================================  ==================
 No-Recall      선사 기밀이 외부 LLM으로 나가는 것            :func:`filter_outbound`
 No-Compute     LLM이 수치를 지어내거나 계산하는 것           :func:`verify_numbers`
=============  ========================================  ==================

**프롬프트로는 「검증」이 성립하지 않는다.** 모델에게 「계산하지 마라」고 적어 두는
것과, 응답의 수치가 도구 응답에 실제로 있었는지 대조하는 것은 다른 일이다. 가드가
코드에 있으면 **모델을 바꿔도 원칙이 유지된다**(`Q4` 모델 교체).
"""

from __future__ import annotations

import re

#: 외부 LLM으로 내보내도 되는 키 (``PRD §16.3.1`` · `Q7` ⓐ).
#:
#: ⚠️ **정본과 이 집합이 어긋나면 안 된다.** ``tests/test_llm_guard.py``가 `PRD`
#: 표를 읽어 대조한다 — 한쪽만 고치면 거기서 걸린다.
OUTBOUND_WHITELIST: frozenset[str] = frozenset(
    {
        # 계산 결과 수치
        "attained_cii",
        "required_cii",
        "rating",
        "risk_level",
        "next_boundary_gap",
        # 코드 값
        "warning_code",
        "grade",
    }
)

#: 내보내면 안 되는 것 — 문서용 목록이다 (``PRD §16.3.1`` 「보내지 않는 것」).
#:
#: **필터는 이 목록을 보지 않는다.** 화이트리스트에 없으면 전부 막히므로 이쪽은
#: 검사와 문서가 서로를 가리키게 하는 용도다 — 금지 목록으로 거르면 **여기 적지 않은
#: 새 필드가 그냥 통과한다.**
OUTBOUND_FORBIDDEN_EXAMPLES: frozenset[str] = frozenset(
    {
        "vessel_name",
        "imo_number",
        "vessel_id",
        "departure_port_name",
        "arrival_port_name",
        "fuel_ton",
        "fuel_type",
        "company_name",
        "user_id",
    }
)


class OutboundFieldError(ValueError):
    """화이트리스트에 없는 키를 내보내려 했다.

    ⚠️ **조용히 떨어뜨리지 않고 오류로 만든다.** 떨어뜨리면 나중에 추가된 필드가
    아무도 모르게 새어 나가고, 그 사실을 알아챌 방법이 없다 (``PRD §16.3.1``).
    """


class NumberFabricationError(ValueError):
    """응답의 수치가 도구 응답에 없다 — LLM이 지어냈거나 계산했다."""


def filter_outbound(payload: dict[str, object]) -> dict[str, object]:
    """외부 LLM에 실을 값을 거른다 (``PRD §16.3.1`` MUST).

    :raises OutboundFieldError: 화이트리스트에 없는 키가 있으면.

    **화이트리스트 방식이다** — 금지 목록으로 거르면 목록에 적지 않은 새 필드가
    그냥 통과한다. 우리가 나중에 필드를 늘릴 때 **기본값이 「막힘」**이어야 한다.

    사용자가 채팅창에 직접 친 문장은 이 함수를 지나지 않는다 — **사용자 본인의
    입력**이라 화이트리스트의 대상이 아니다(``§16.3.1`` 「보내도 되는 것」 1행).
    """
    unknown = sorted(set(payload) - OUTBOUND_WHITELIST)
    if unknown:
        raise OutboundFieldError(
            "외부 LLM에 보낼 수 없는 필드입니다: "
            + ", ".join(unknown)
            + f" (허용: {', '.join(sorted(OUTBOUND_WHITELIST))} · PRD §16.3.1)"
        )
    return dict(payload)


#: 응답에서 수치를 뽑는 패턴.
#:
#: 부호·천 단위 쉼표·소수점을 받는다. **백분율 기호나 단위는 잡지 않는다** — 숫자
#: 부분만 비교 대상이고, 단위는 도구 응답에 문자열로 없을 수 있다.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

#: 대조에서 빼는 값.
#:
#: 연도(2024~2030)와 한 자리 수는 **문장에 자연스럽게 섞인다** — 「3가지」·「2026년」
#: 같은 것까지 도구 응답에 있어야 한다고 요구하면 가드가 정상 응답을 막는다.
#: ⚠️ 등급 경계·비율처럼 **판단에 쓰이는 수치는 전부 두 자리 이상**이라 빠지지 않는다.
_IGNORED_LITERALS: frozenset[str] = frozenset(
    {str(n) for n in range(10)} | {str(y) for y in range(2019, 2041)}
)


def extract_numbers(text: str) -> list[str]:
    """문장에서 수치를 뽑아 **정규화**한다.

    천 단위 쉼표를 떼고, 소수점 뒤 의미 없는 0을 떼어 비교 가능한 형태로 만든다 —
    도구가 ``"4.98"``을 주고 모델이 ``"4.980"``이라 쓰면 **같은 값**이다.
    """
    found: list[str] = []
    for raw in _NUMBER.findall(text):
        token = raw.replace(",", "")
        if token in _IGNORED_LITERALS:
            continue
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        found.append(token)
    return found


def _tool_output_numbers(tool_outputs: list[str]) -> set[str]:
    numbers: set[str] = set()
    for output in tool_outputs:
        numbers.update(extract_numbers(output))
    return numbers


def verify_numbers(answer: str, tool_outputs: list[str]) -> None:
    """응답의 모든 수치가 도구 응답에 **문자열로** 있었는지 대조한다 (No-Compute).

    :raises NumberFabricationError: 하나라도 없으면.

    ## 왜 문자열 대조인가

    ``#120`` 완료 기준이 *「LLM이 수학을 직접 수행하지 않음(**테스트로 검증**)」*이다.
    「수학을 했는지」를 직접 볼 수는 없으므로, **결과가 어디서 왔는지**로 판정한다 —
    도구가 준 값이면 있고, 모델이 만든 값이면 없다.

    ## 파생 수치도 금지다

    도구가 ``4.98``과 ``5.05``를 줬을 때 모델이 ``0.07``(차)을 쓰면 **막힌다.**
    빼기도 계산이기 때문이다. 필요한 파생값은 **도구가 내려주어야 한다** —
    ``next_boundary_gap``이 그래서 응답 필드에 있다.

    ## 불일치는 폐기다

    호출부는 이 오류를 받으면 **응답을 버리고 오류를 낸다.** ``PRD §16.2`` 장애
    격리와 같은 방향이다 — **챗봇이 틀린 말을 하느니 말을 하지 않는 쪽**이 안전하다.
    """
    available = _tool_output_numbers(tool_outputs)
    fabricated = [n for n in extract_numbers(answer) if n not in available]
    if fabricated:
        raise NumberFabricationError(
            "응답에 도구 결과로 설명되지 않는 수치가 있습니다: "
            + ", ".join(sorted(set(fabricated)))
            + " (No-Compute · PRD §20 O-12)"
        )
