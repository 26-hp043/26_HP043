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
_ALIASES = (_ROOT / "frontend" / "src" / "styles" / "tokens.css").read_text(encoding="utf-8")

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


def _explicit_dark() -> str:
    """``:root[data-theme='dark']`` 블록 본문 — 다크는 **두 곳**에 적힌다."""
    media = _TOKENS.index("@media (prefers-color-scheme: dark)", _TOKENS.index(":root {"))
    return _TOKENS[_TOKENS.index(":root[data-theme='dark']", media) :]


def _doc_neutral_table() -> list[tuple[str, str, str, str]]:
    """`§2.2` 표 — (별칭, 생성 토큰, 라이트, 다크). 별칭이 없는 행은 빈 문자열.

    별칭 열이 ``—``인 행(`--surface-popover`)도 받는다 — 그 면은 `§0.2` 제약 6이
    문자 대비를 재는 **네 면**의 하나라서, 별칭이 없어도 값이 맞아야 한다.
    """
    section = _DOC[_DOC.index("### 2.2 중립") : _DOC.index("### 2.3")]
    rows = re.findall(
        r"^\| (?:`(--[\w-]+)`|—) \| `(--[\w-]+)` \| `(#[0-9a-fA-F]{6})` \| `(#[0-9a-fA-F]{6})` \|",
        section,
        re.M,
    )
    return [(a or "", gen, light.lower(), dark.lower()) for a, gen, light, dark in rows]


def _section_2_2() -> str:
    return _DOC[_DOC.index("### 2.2 중립") : _DOC.index("### 2.3")]


def test_section_2_2_table_was_actually_read():
    """표를 못 읽으면 아래 대조가 **빈 목록으로 통과**한다 — 그것부터 막는다.

    ⚠️ **「몇 줄 이상」으로 두지 않는다.** 처음에는 ``>= 10``이었는데, 돌연변이로
    한 행의 모양만 바꿔 보니 **파서가 그 행을 잃고도 초록**이었다(나머지 열이
    남으므로). `#2150`이 `§3` 표에서 겪은 「한 줄만 어긋나면 초록」과 같은 꼴이다.
    그래서 **표에 있는 행 수와 읽은 행 수가 같은지**를 본다 — 한 줄이 시야에서
    빠지면 그 자리에서 붉어진다.
    """
    lines = [line for line in _section_2_2().splitlines() if line.startswith("|")]
    present = len(lines) - 2  # 머리줄 · 구분줄
    rows = _doc_neutral_table()
    assert len(rows) == present, (
        f"§2.2 표의 행은 {present}개인데 {len(rows)}개만 읽혔다 — "
        "읽히지 않은 행은 아래 대조를 통째로 빠져나간다."
    )
    assert present >= 10, f"§2.2 표가 너무 짧다: {present}행"


def test_section_2_2_table_matches_the_generated_tokens():
    """표 값 = 생성 토큰(라이트 · 다크). 다크는 **두 블록 모두**와 견준다."""
    light, media_dark = _blocks()
    explicit_dark = _explicit_dark()
    adrift = []
    for _, gen, doc_light, doc_dark in _doc_neutral_table():
        name = gen.removeprefix("--")
        real = (_token(light, name), _token(media_dark, name), _token(explicit_dark, name))
        if (doc_light, doc_dark, doc_dark) != real:
            adrift.append(f"{gen}: 문서 {doc_light}/{doc_dark} ≠ 코드 {real}")
    assert adrift == [], "§2.2 표가 생성 토큰과 갈렸다:\n" + "\n".join(adrift)


def test_section_2_2_aliases_point_at_the_named_generated_token():
    """표의 **두 열이 서로 갈리지 않게** — 별칭이 적힌 그 생성 토큰을 가리킨다.

    값만 대조하면 별칭이 **같은 값을 가진 다른 토큰**으로 옮겨 가도 통과한다.
    `#1169`가 겪은 결함이 그 꼴이었다 — `--color-border-control`이 기준을 넘기면서도
    문자 토큰(`--text-muted`)을 빌려 쓰고 있었고, 대비 검사만으로는 잡히지 않았다.
    """
    adrift = []
    for alias, gen, _, _ in _doc_neutral_table():
        if not alias:
            continue
        match = re.search(rf"{re.escape(alias)}:\s*var\(\s*(--[\w-]+)\s*\)", _ALIASES)
        if match is None:
            adrift.append(f"{alias}: tokens.css에 선언이 없다")
        elif match.group(1) != gen:
            adrift.append(f"{alias}: 표는 {gen}, 코드는 {match.group(1)}")
    assert adrift == [], "§2.2 표의 별칭 열이 코드와 갈렸다:\n" + "\n".join(adrift)


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
