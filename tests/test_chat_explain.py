"""챗봇 용어 풀이 ↔ 정본 (`#123` · IT-CHAT-040~047).

## 이 파일이 막는 것

풀이는 **제품이 사용자에게 하는 말**이다. 정본에 없는 말을 여기서 만들면, 화면과
챗봇이 **같은 것을 다르게** 말하게 된다 — 그리고 그 차이는 화면을 깨뜨리지 않아
발견되지 않는다.

그래서 두 방향으로 잠근다.

=================================  ====================================
 정본에 있는 말을 쓰는가             `PRD`·`DESIGN_SYSTEM` 원문과 대조
 정본에 없는 말을 만들지 않았는가     등급 형용사 금지 · **숫자 금지**
=================================  ====================================

⚠️ **숫자 금지가 가장 실질적이다.** 풀이에 `Reg 28.7`을 적으면 모델이 그것을 답변에
인용하는 순간 ``verify_numbers``가 도구 응답에 없는 수치로 보고 **답변을 통째로
폐기한다.** 그 실패는 「챗봇이 가끔 답을 안 준다」로 나타나 원인을 찾기 어렵다.
"""

from __future__ import annotations

import re
from pathlib import Path

from cii_platform.services.chat import SYSTEM_PROMPT
from cii_platform.services.chat_explain import (
    ATTAINED_VS_REQUIRED,
    BOUNDARY_GAP_MEANING,
    GLOSSARY,
    GRADE_MEANING,
    RISK_MEANING,
    glossary_prompt,
)
from cii_platform.services.llm_guard import extract_numbers

_ROOT = Path(__file__).resolve().parents[1]


def _doc(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def test_direction_comes_from_the_prd() -> None:
    """IT-CHAT-040 — 「낮을수록 우수」가 ``PRD §3.3.6``에서 온 말이다.

    이 방향이 뒤집히면 **나머지 설명이 전부 거꾸로 읽힌다.** 「달성(attained)」이라는
    말 때문에 클수록 좋다고 읽기 쉬운 자리다.
    """
    assert "낮은 CII가 더 우수하다" in _doc("PRD.md")
    assert "낮을수록" in ATTAINED_VS_REQUIRED
    assert "낮을수록" in GRADE_MEANING


def test_boundary_tie_rule_comes_from_the_prd() -> None:
    """IT-CHAT-041 — 「경계값과 같으면 더 우수한 등급」이 정본 규칙이다 (``§3.3.6``)."""
    assert "경계값과 정확히 같은 경우에는 더 우수한 등급으로 판정한다" in _doc("PRD.md")
    assert "경계값과 정확히 같으면 더 우수한 등급" in GRADE_MEANING


def test_regulatory_consequence_is_the_corrective_action_plan() -> None:
    """IT-CHAT-042 — D·E의 귀결은 **운항 제한이 아니라 시정조치계획**이다 (``§3.3.7``).

    ``PRD §3.3.7``이 *"운항 제한·억류·거래 금지 조항은 확인 범위에 존재하지 않는다"*
    고 못박고 **과장 금지**를 규정한다. 챗봇이 「운항이 제한됩니다」라고 말하면 그
    조항을 챗봇 한 곳에서 깬다.
    """
    prd = _doc("PRD.md")
    assert "운항 제한이 아니라 시정조치계획" in prd
    assert "최소 C등급" in prd

    assert "시정조치계획" in GRADE_MEANING
    assert "최소 C등급" in GRADE_MEANING
    # 과장하지 않는다 — 정본이 없다고 적은 말을 쓰지 않는다.
    for forbidden in ("운항 제한", "억류", "거래 금지", "벌금", "입항 금지"):
        assert forbidden not in GRADE_MEANING, forbidden


def test_risk_labels_match_the_design_system() -> None:
    """IT-CHAT-043 — 위험도 라벨이 **화면과 같은 말**이다 (``DESIGN_SYSTEM §2.5 (b)`` 🔒).

    화면이 「높음 HIGH」로 적는데 챗봇이 「위험」이라고 하면 같은 값을 두 이름으로
    부르게 된다.
    """
    assert "낮음 LOW · 보통 MEDIUM · 높음 HIGH · 심각 CRITICAL" in _doc("DESIGN_SYSTEM.md")
    assert "낮음 LOW · 보통 MEDIUM · 높음 HIGH · 심각 CRITICAL" in RISK_MEANING


def test_boundary_gap_says_it_is_the_worsening_direction() -> None:
    """IT-CHAT-044 — 여유가 **악화 방향**임을 말한다 (``DESIGN_SYSTEM §2.5 (b)``).

    필드 이름이 방향을 말해 주지 않아, 적지 않으면 「개선까지 남은 거리」로 읽힌다.
    등급 E에 값이 없다는 것도 함께 말한다 — 비어 있으면 「아직 로딩 중」으로 읽힌다.
    """
    assert "악화 방향" in _doc("DESIGN_SYSTEM.md")
    assert "악화 방향" in BOUNDARY_GAP_MEANING
    assert "E" in BOUNDARY_GAP_MEANING


def test_no_invented_grade_adjectives() -> None:
    """IT-CHAT-045 — ⚠️ 등급에 **형용사를 붙이지 않는다**.

    `#123` 본문 예시는 「C(보통)」·「D(불량)」인데 **그 말은 정본 어디에도 없고**
    화면도 쓰지 않는다(`GradeBadge`는 「등급 C」라고만 적는다). 여기서 만들면 정본에
    없는 제품 문구가 챗봇에서 처음 생긴다(``AGENTS §4.6``).

    「보통」은 위험도 `MEDIUM`의 정본 라벨이라 :data:`RISK_MEANING`에는 정당하게
    들어간다 — 그래서 **등급 풀이만** 본다.
    """
    for adjective in ("보통", "불량", "우수함", "나쁨", "양호"):
        assert adjective not in GRADE_MEANING, adjective


def test_glossary_carries_no_multi_digit_numbers() -> None:
    """IT-CHAT-046 — ⚠️ **두 자리 이상 숫자를 넣지 않는다.**

    풀이에 `Reg 28.7`이나 `20%`를 적으면, 모델이 답변에 인용하는 순간
    ``verify_numbers``가 도구 응답에 없는 수치로 보고 **답변을 통째로 폐기한다.**
    그 실패는 「챗봇이 가끔 답을 안 준다」로 나타나 원인을 찾기 어렵다.

    가드를 느슨하게 푸는 대신 풀이에서 숫자를 뺀다 — 규정 원문 인용은 챗봇의 일이
    아니고, 면책이 이미 「최종 확인은 IMO 규제 원문을 따릅니다」라고 말한다.

    :func:`extract_numbers`를 그대로 쓴다 — **가드가 보는 것과 같은 눈**으로 봐야
    한다. 따로 정규식을 쓰면 둘이 갈릴 수 있다.
    """
    for term, text in GLOSSARY:
        assert not extract_numbers(text), (term, extract_numbers(text))


def test_system_prompt_actually_carries_the_glossary() -> None:
    """IT-CHAT-047 — 풀이가 **실제로 모델에게 간다**.

    모듈만 있고 프롬프트에 꽂히지 않으면 아무 일도 일어나지 않는다 — `#121`에서
    겪은 것과 같은 종류의 위험이다.
    """
    prompt = glossary_prompt()
    assert prompt in SYSTEM_PROMPT
    for term, _text in GLOSSARY:
        assert term in SYSTEM_PROMPT, term
    # 규칙도 남아 있다 — 풀이를 붙이면서 지우지 않았는지.
    assert "도구가 돌려준 값만" in SYSTEM_PROMPT
    # 프롬프트 전체에도 두 자리 수가 없다(위 규칙과 같은 이유).
    assert not re.search(r"\d\d", SYSTEM_PROMPT), SYSTEM_PROMPT
