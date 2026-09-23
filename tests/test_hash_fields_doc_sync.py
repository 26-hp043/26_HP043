"""`calc/hash.py`의 해시 입력 키 집합 ↔ `TECH_SPEC §5.3` 대조 (#1344).

세 집합(`INPUT_FIELDS` · `SCENARIO_INPUT_FIELDS` · `ANNUAL_INPUT_FIELDS`)은
**재현성 계약의 단위**다(`TECH_SPEC §5.4` 1항 — 같은 `input_hash` → 같은 결과).
키가 늘거나 줄면 그 계약의 범위 자체가 달라지므로, 문서가 코드보다 뒤처지면
**읽는 사람이 해시에 무엇이 들어가는지 잘못 안다.**

`tests/test_hashing.py`가 이미 **코드 쪽 목록과 순서를 잠그지만**, 그 검사는
문서를 보지 않는다. 실제로 `#796`·`#363`·`#816`·`#756`이 키를 늘리는 동안
`§5.3`의 기능③ 목록은 **일곱 키로 남아 있었다**(실제 열 개) — 코드 잠금만으로는
드러나지 않는 형태다.

⚠️ **이 검사는 문서의 괄호 안을 「키 목록」으로 읽는다.** 즉 `§5.3`에서
``NAME(`a`·`b`·…)`` 형태의 괄호 안에 들어가는 백틱 식별자는 **키뿐이어야 한다**
(이슈 번호 `#123`·절 번호 `§1.2`는 식별자 모양이 아니라 걸러진다). 설명을 덧붙이려면
괄호 밖이나 별도 문단에 적는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cii_platform.calc.hash import (
    ANNUAL_INPUT_FIELDS,
    INPUT_FIELDS,
    SCENARIO_INPUT_FIELDS,
)

TECH_SPEC = Path(__file__).resolve().parents[1] / "TECH_SPEC.md"

#: 백틱 안이 이 모양일 때만 키로 읽는다 — 이슈(`#123`)·절(`§5.3`)은 걸러진다.
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def _section_5_3() -> str:
    text = TECH_SPEC.read_text(encoding="utf-8")
    start = text.index("### 5.3 Input Hash")
    end = text.index("### 5.4 재현성 계약", start)
    return text[start:end]


def _code_block_fields(section: str) -> tuple[str, ...]:
    """`INPUT_FIELDS = [...]` 파이썬 블록에서 키를 순서대로 읽는다."""
    # ⚠️ 닫는 `]`를 `section.index("]")`로 찾으면 주석의 `[EXT-P0-1]`에 먼저 걸린다.
    # 줄머리 들여쓰기 뒤의 `]`만 블록의 끝으로 읽는다.
    block = re.search(r"INPUT_FIELDS = \[(.*?)\n\s*\]", section, re.S)
    assert block is not None, "§5.3의 `INPUT_FIELDS` 코드 블록을 찾지 못했다"
    # ⚠️ 주석 뒤는 버린다 — 키를 주석 처리해도 따옴표는 남아 그대로 읽히면
    # 「목록에서 뺀 것」이 드러나지 않는다.
    live = "\n".join(line.split("#", 1)[0] for line in block.group(1).splitlines())
    return tuple(re.findall(r'"([a-z_][a-z0-9_]*)"', live))


def _parenthesised_fields(section: str, name: str) -> tuple[str, ...]:
    """``\\`NAME\\`(…)`` 괄호 안의 백틱 식별자를 순서대로 읽는다(중복 제거)."""
    marker = f"`{name}`("
    start = section.index(marker) + len(marker)
    depth = 1
    i = start
    while depth:
        if section[i] == "(":
            depth += 1
        elif section[i] == ")":
            depth -= 1
        i += 1
    inside = section[start : i - 1]

    seen: list[str] = []
    for token in re.findall(r"`([^`]+)`", inside):
        if _IDENTIFIER.match(token) and token not in seen:
            seen.append(token)
    return tuple(seen)


def test_기능1_키가_문서_코드블록과_같다() -> None:
    assert _code_block_fields(_section_5_3()) == INPUT_FIELDS


def test_기능2_키가_문서와_같다() -> None:
    documented = _parenthesised_fields(_section_5_3(), "SCENARIO_INPUT_FIELDS")
    assert documented == SCENARIO_INPUT_FIELDS


def test_기능3_키가_문서와_같다() -> None:
    """`#1344` — 이 검사가 없던 동안 문서는 일곱, 코드는 열이었다."""
    documented = _parenthesised_fields(_section_5_3(), "ANNUAL_INPUT_FIELDS")
    assert documented == ANNUAL_INPUT_FIELDS


@pytest.mark.parametrize(
    "field", ["apply_feedback_factor", "as_of", "alternative_fuel", "not_underway"]
)
def test_기능3_선택_키가_선택이라고_적혀_있다(field: str) -> None:
    """**목록에 있다**와 **늘 담긴다**는 다른 명제다.

    끈 실행에 ``False``를, 미명시 실행에 서버 확정 시각을 넣으면 **이미 저장된
    실행 전부의 해시가 바뀐다.** 목록만 맞추고 이 규약을 적지 않으면 다음 사람이
    「목록에 있으니 늘 넣는다」로 읽는다.
    """
    section = _section_5_3()
    convention = section[section.index("선택 키 규약") :]
    assert f"`{field}`" in convention or field in convention


def test_문서가_기능3의_키_수를_말할_때_실제와_같다() -> None:
    """*「넘긴 일곱 키 중…」*처럼 **수를 적은 문장**이 낡지 않게 한다."""
    section = _section_5_3()
    documented = _parenthesised_fields(section, "ANNUAL_INPUT_FIELDS")
    assert len(documented) == len(ANNUAL_INPUT_FIELDS) == 11
