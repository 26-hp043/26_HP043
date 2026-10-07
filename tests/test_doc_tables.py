"""정본 마크다운 표가 GitHub에서 한 표로 렌더되는 구조인지 검증 (#2137).

## 무엇을 막는가

표가 **렌더되지 않는 구조 결함**이 정본 네 곳에서 한꺼번에 드러났다.

    DB_SCHEMA §2.1       표 중간에 빈 줄과 인용블록이 끼어 뒤 행이 머리 없이 표 밖으로 나갔다
    TEST_PLAN §3.24      머리 없는 행 넷이 다른 표(§3.27) 뒤에 떨어져 있었다
    TEST_PLAN §14.2      한 줄에 두 행이 붙어 있었다
    API_SPEC §14.6       행 다섯이 `||`로 시작해 열이 한 칸씩 밀렸다

문서는 빌드되지 않아 아무것도 깨지지 않는다 — 읽는 사람의 화면에서만 표가 사라진다.
기존 가드는 표를 보지 않는다(`test_doc_cross_refs.py`는 참조, `test_testplan_sync.py`는
수치).

## 규칙 — GFM이 열을 읽는 방식

- 열은 **이스케이프되지 않은 `|`** 마다 갈린다. **코드 스팬 `` `a | b` `` 안의 `|`도
  열 구분**이다 — 셀에 `|`를 쓰려면 `\\|`로 적는다.
- 머리행보다 **셀이 많은** 행은 넘친 셀이 렌더에서 **버려진다.** 적은 행은 빈 칸으로
  채워지므로 구조 결함이 아니다(검사하지 않는다).
- 표는 **머리행 + 구분행**(`|---|---|`)으로 시작하고 `|` 행이 이어지는 동안만 표다.
  중간에 빈 줄이나 인용블록이 끼면 표가 끝나고, 뒤 행은 머리 없는 문단이 된다.

## 검사하지 않는 것

코드펜스 안은 건너뛴다. 인용블록(`>`) 안의 표는 보지 않는다. 셀 **내용**이 맞는지는
보지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_CANON = (
    "PRD.md",
    "TECH_SPEC.md",
    "API_SPEC.md",
    "DB_SCHEMA.md",
    "TEST_PLAN.md",
    "UIFLOW.md",
    "DESIGN_SYSTEM.md",
    "AGENTS.md",
)

_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_SEPARATOR = re.compile(r"^\|?:?-+:?(\|:?-+:?)*\|?$")


def _cell_count(row: str) -> int:
    body = row.strip()[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return len(_UNESCAPED_PIPE.split(body))


def _is_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_separator(line: str) -> bool:
    return bool(_SEPARATOR.match(line.replace(" ", "")))


def table_defects(lines: list[str]) -> list[tuple[int, str]]:
    """(줄 번호, 유형) 목록. 코드펜스 안은 건너뛴다."""
    defects: list[tuple[int, str]] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence or not _is_row(line):
            i += 1
            continue

        end = i
        while end < len(lines) and _is_row(lines[end]):
            end += 1
        block = lines[i:end]

        if len(block) < 2 or not _is_separator(block[1]):
            defects.append((i + 1, "머리행·구분행 없는 표 행"))
        else:
            width = _cell_count(block[0])
            if _cell_count(block[1]) != width:
                defects.append((i + 2, "구분행 열 수가 머리행과 다르다"))
            for offset, row in enumerate(block[2:], start=i + 3):
                if _cell_count(row) > width:
                    defects.append((offset, f"머리행({width}열)보다 셀이 많다"))
        for offset, row in enumerate(block, start=i + 1):
            if row.lstrip().startswith("||"):
                defects.append((offset, "`||`로 시작하는 행"))

        # 표 뒤 빈 줄·인용블록을 건너뛴 자리에서 머리 없는 행이 이어지면 표가 끊긴 것이다.
        nxt = end
        while nxt < len(lines) and (lines[nxt].strip() == "" or lines[nxt].startswith(">")):
            nxt += 1
        if nxt > end and nxt < len(lines) and _is_row(lines[nxt]):
            after = lines[nxt + 1] if nxt + 1 < len(lines) else ""
            if not _is_separator(after):
                defects.append((end + 1, f"표가 끊겼다 — {nxt + 1}행이 머리 없이 이어진다"))
        i = end
    return defects


def _scan(name: str) -> list[str]:
    lines = (_ROOT / name).read_text(encoding="utf-8").splitlines()
    return [f"{name}:{no} · {kind}" for no, kind in table_defects(lines)]


def test_검사기가_깨진_표_네_형태를_잡는다() -> None:
    """검사기가 죽으면 아래 검사가 조용히 통과한다 — 알려진 결함 형태로 먼저 확인한다."""
    head = ["| a | b |", "|---|---|", "| 1 | 2 |"]
    broken_by_quote = head + ["", "> 인용", "| 3 | 4 |"]
    two_rows_on_one_line = head + ["| 3 | 4 | 5 | 6 |"]
    double_pipe = head + ["|| 3 | 4 |"]
    code_span_pipe = head + ["| `x | y` | 4 |"]
    headerless = ["| 3 | 4 |", "| 5 | 6 |"]

    assert table_defects(head) == []
    assert any("끊겼다" in kind for _, kind in table_defects(broken_by_quote))
    assert any("셀이 많다" in kind for _, kind in table_defects(two_rows_on_one_line))
    assert any("`||`" in kind for _, kind in table_defects(double_pipe))
    assert any("셀이 많다" in kind for _, kind in table_defects(code_span_pipe))
    assert any("머리행" in kind for _, kind in table_defects(headerless))
    # 코드펜스 안은 보지 않는다 — 규칙을 설명하는 예시가 가드에 걸리면 안 된다.
    assert table_defects(["```", *double_pipe, "```"]) == []
    # 새 표는 머리·구분행이 있으면 앞 표 뒤에 빈 줄을 두고 이어져도 된다.
    assert table_defects(head + ["", *head]) == []


def test_정본_표가_한_표로_렌더되는_구조다() -> None:
    offenders = [item for name in _CANON for item in _scan(name)]

    assert not offenders, (
        "GitHub에서 표가 깨져 렌더되는 구조입니다 — 표 중간의 빈 줄·인용블록은 표 뒤로, "
        "셀 안의 `|`(코드 스팬 포함)는 `\\|`로, 한 줄에 붙은 행은 나누세요 (#2137):\n  "
        + "\n  ".join(offenders)
    )
