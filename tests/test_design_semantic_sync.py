"""`DESIGN_SYSTEM §2.3` 시맨틱 색 ↔ 생성 토큰 · 제약 2 대조 (#1881).

## 무엇을 막는가

`§2.3` 표는 `#1022`(PR #1195 · #1200)로 생성 토큰(`tokens.generated.css`)과 맞춰졌는데, 같은
문서의 제약 2 선언 · `§4.3` 증감 표기 · `§15` CSS 예시는 **옛 사본**(Success `#2f855a` ·
Danger `#c53030`)을 들고 있었다. 선언은 「문서 안의 값끼리」 비교해 통과를 선언한 상태였다.
값의 소유는 Figma → 생성 파일이다(`§0.2`). 표가 그 값과 다르거나, 제약 2(등급 색과 겹치지
않는다)가 깨지거나, 옛 사본이 다시 나타나면 여기서 실패한다.

DB 없이 파일만 읽는다. 케이스: (`TEST_PLAN §14.5` 정의 없음 — 문서·토큰 동기화 가드)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DOC = (_ROOT / "DESIGN_SYSTEM.md").read_text(encoding="utf-8")
_TOKENS = (_ROOT / "frontend" / "src" / "styles" / "tokens.generated.css").read_text(
    encoding="utf-8"
)

_ROLES = ("info", "success", "warning", "danger")
_GRADES = ("a", "b", "c", "d", "e")

#: 옛 사본 — `#1022` 전의 라이트 Success · Danger.
_OLD_HEX = ("#2f855a", "#c53030")
#: 옛 사본이 **기록으로** 남아도 되는 줄의 표지 — 개정·정정·해소의 이력이다.
_HISTORY_MARKERS = ("해소 기록", "개정 이력", "낡은 사본", "종전 표 값")


def _blocks() -> tuple[str, str]:
    """라이트(`:root` 첫 블록) · 다크(`@media` 안 블록) 본문.

    머리 주석에도 ``@media (prefers-color-scheme: dark)`` 글자가 있으므로 **``:root {`` 뒤에서**
    찾는다 — 앞에서부터 찾으면 주석을 경계로 잡아 라이트 블록이 빈다.
    """
    start = _TOKENS.index(":root {")
    media = _TOKENS.index("@media (prefers-color-scheme: dark)", start)
    explicit_dark = _TOKENS.index(":root[data-theme='dark']", media)
    return _TOKENS[start:media], _TOKENS[media:explicit_dark]


def _token(block: str, name: str) -> str:
    match = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}});", block)
    assert match, f"생성 토큰에 --{name}이 없다"
    return match.group(1).lower()


def _doc_table() -> dict[str, tuple[str, str]]:
    """`§2.3` 표 — 역할 → (라이트, 다크)."""
    section = _DOC[_DOC.index("### 2.3 시맨틱") : _DOC.index("### 2.4")]
    rows = re.findall(
        r"^\| (Info|Success|Warning|Danger) \| `(#[0-9a-fA-F]{6})` \| `(#[0-9a-fA-F]{6})` \|",
        section,
        re.M,
    )
    return {role.lower(): (light.lower(), dark.lower()) for role, light, dark in rows}


def test_section_2_3_table_matches_the_generated_tokens():
    """표 값 = `tokens.generated.css`의 `--semantic-*`(라이트 · 다크)."""
    light, dark = _blocks()
    table = _doc_table()
    assert set(table) == set(_ROLES), f"§2.3 표에서 읽은 역할: {sorted(table)}"
    for role in _ROLES:
        assert table[role] == (
            _token(light, f"semantic-{role}"),
            _token(dark, f"semantic-{role}"),
        ), role


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_no_semantic_color_equals_a_grade_fill(mode):
    """`§0.2` 제약 2 — 시맨틱 4색이 등급 fill과 같은 값이 아니다(생성 토큰으로 실측)."""
    block = dict(zip(("light", "dark"), _blocks(), strict=True))[mode]
    semantic = {role: _token(block, f"semantic-{role}") for role in _ROLES}
    fills = {grade: _token(block, f"cii-{grade}-fill") for grade in _GRADES}
    clashes = [(r, g) for r, v in semantic.items() for g, f in fills.items() if v == f]
    assert clashes == [], f"{mode}: 시맨틱과 등급 fill이 같은 값 — {clashes}"


def test_old_copies_appear_only_in_history_lines():
    """옛 사본(`#2f855a` · `#c53030`)은 변경 이력·정정·해소 기록 줄에만 남는다."""
    offending = [
        f"{number}: {line[:80]}"
        for number, line in enumerate(_DOC.splitlines(), start=1)
        if any(old in line.lower() for old in _OLD_HEX)
        and not line.startswith("| 20")
        and not any(marker in line for marker in _HISTORY_MARKERS)
    ]
    assert offending == [], "옛 시맨틱 hex가 기록 밖에 있다:\n" + "\n".join(offending)
