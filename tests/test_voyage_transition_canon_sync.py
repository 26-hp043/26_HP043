"""항차 상태 전환 ↔ `PRD §8.1` 상태도 ↔ `API_SPEC §3.5` 표 (`#1328`).

## 왜 필요한가

세 곳이 같은 것을 말하는데 **아무도 대조하지 않았다.** 실제로 `DRAFT → CANCELLED`가
코드(`services/voyage._TRANSITIONS`)와 **화면**(`voyageRules.ts`)에는 있고 정본 둘에는
없었다 — 문서를 보고 만든 클라이언트·검사는 **422를 기대**한다.

어느 쪽이 틀렸다고 단정하지 않는다. **갈렸다는 사실 자체**를 드러내는 것이 이 검사의
일이고, 무엇을 정본으로 삼을지는 사람이 정한다.

## 무엇을 읽는가

- `PRD §8.1`의 mermaid ``A --> B: label`` 줄
- `API_SPEC §3.5` 전환 표의 ``| A → B | …`` 행 — 상태가 아니라 policy에 걸리는
  마지막 행은 화살표가 없어 자연히 빠진다
"""

from __future__ import annotations

import re
from pathlib import Path

from cii_platform.services.voyage import _TRANSITIONS

ROOT = Path(__file__).resolve().parents[1]

#: 상태 이름의 모양 — 표의 설명 문장과 구분한다.
_STATUS = r"[A-Z_]+"


def _code_pairs() -> set[tuple[str, str]]:
    return {(src, dst) for src, dsts in _TRANSITIONS.items() for dst in dsts}


def _prd_block() -> str:
    text = (ROOT / "PRD.md").read_text(encoding="utf-8")
    start = text.index("### 8.1 항차 상태 모델")
    return text[start : text.index("```", text.index("```mermaid", start) + 3)]


def _mermaid_pairs(block: str) -> set[tuple[str, str]]:
    """``A --> B: label`` 줄만 읽는다.

    `[*] --> DRAFT`(시작 표시)는 상태 전환이 아니다 — 왼쪽이 상태 이름 모양이 아니고
    라벨(``:``)도 없어 정규식에 걸리지 않는다.
    """
    return set(re.findall(rf"^\s*({_STATUS})\s*-->\s*({_STATUS})\s*:", block, re.MULTILINE))


def _prd_pairs() -> set[tuple[str, str]]:
    return _mermaid_pairs(_prd_block())


def _api_spec_pairs() -> set[tuple[str, str]]:
    text = (ROOT / "API_SPEC.md").read_text(encoding="utf-8")
    start = text.index("#### 상태 전환 규칙")
    block = text[start : text.index("#### status ×", start)]
    return set(re.findall(rf"^\|\s*({_STATUS})\s*→\s*({_STATUS})\s*\|", block, re.MULTILINE))


def test_시작_표시를_전환으로_읽지_않는다() -> None:
    """파서가 `[*] --> DRAFT`를 전환으로 세면 아래 비교가 늘 어긋난다.

    ⚠️ 종전에는 ``("*", "DRAFT") not in _prd_pairs()``였다 — 정규식 ``[A-Z_]+``는 ``*``를
    **잡을 수 없으므로** 그 쌍은 어떤 파서에서도 나오지 않는다(`#2142`). 시작·끝 표시가
    실제로 있는 표본을 읽혀, **양쪽이 모두 상태 이름인 줄만** 남는지 본다.
    """
    sample = "    [*] --> DRAFT\n    DRAFT --> PLANNED: 계획 확정\n    CANCELLED --> [*]\n"
    assert _mermaid_pairs(sample) == {("DRAFT", "PLANNED")}

    # 정본에 시작 표시가 실제로 있고, 읽은 쌍에는 상태 이름만 있다.
    assert "[*] -->" in _prd_block(), "PRD 상태도에 시작 표시가 없다 — 이 검사의 전제가 사라졌다"
    known = {name for pair in _code_pairs() for name in pair}
    assert {name for pair in _prd_pairs() for name in pair} <= known


def test_읽은_전환이_비어_있지_않다() -> None:
    """빈 집합이면 아래 두 검사가 **양쪽 다 비어도** 통과한다."""
    assert len(_code_pairs()) >= 8
    assert len(_prd_pairs()) >= 8
    assert len(_api_spec_pairs()) >= 8


def test_PRD_상태도가_코드와_같다() -> None:
    assert _prd_pairs() == _code_pairs()


def test_API_SPEC_표가_코드와_같다() -> None:
    assert _api_spec_pairs() == _code_pairs()
