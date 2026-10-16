#!/usr/bin/env python3
"""변경 이력 커밋 열의 이슈 번호를 PR 번호로 고친 결과를 매핑표와 대조한다 (#2269).

## 왜 필요한가

`AGENTS §4.1`은 커밋 열에 **PR 번호**를 적게 하는데, 지난 행 가운데 이슈 번호가 적힌 행이
있었다. `#2269` 첫 PR이 그 행들을 문서·줄 단위 매핑표(`docs/changelog_remap_2269.tsv`)대로
고친다.

`scripts/check_changelog_rows.py`는 행을 **커밋 열의 참조**로 알아보므로 번호를 바꾸면
「행이 사라졌다」로 읽는다. 그 PR에서만 삭제 검사를 라벨로 끄고, 그 공백을 이 대조로
메운다 — 삭제 검사가 지키던 것(행이 사라지지 않는다)에 더해 **엉뚱한 번호로 바뀐 행**까지 잡는다.

## 무엇을 보는가

열 문서마다 base와 작업 트리의 변경 이력 표 행을 견준다.

1. 행 수가 같거나 **끝에 정확히 1행** 더해졌다(이 PR 자신의 행 — `AGENTS §4.1`)
2. 그 1행을 빼면 **커밋 열 말고는** 모든 행이 바이트 단위로 같다(순서 포함)
3. 커밋 열이 바뀐 행의 (문서, 날짜, 원래, 새) 값이 매핑표와 정확히 같고, 매핑표의 행이
   전부 적용됐다

#2269 첫 PR 전용이다 — 둘째 PR에서 CI 배선과 함께 걷어 낸다.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

#: 변경 이력 표를 가진 열 문서 (#2269 결정 2).
DOCS: tuple[str, ...] = (
    "UIFLOW.md",
    "DESIGN_SYSTEM.md",
    "PRD.md",
    "TECH_SPEC.md",
    "API_SPEC.md",
    "DB_SCHEMA.md",
    "TEST_PLAN.md",
    "AGENTS.md",
    "README.md",
    "docs/OPERATIONS.md",
)


class Row(NamedTuple):
    """변경 이력 표의 한 행 — 줄 번호와 세 조각(커밋 열 앞 · 커밋 열 · 뒤)."""

    line: int
    head: str
    commit: str
    tail: str

    @property
    def date(self) -> str:
        return self.head.strip("| ").strip()


#: (문서, base 줄, 날짜, 원래 커밋 열, 새 커밋 열) — 커밋 열은 앞뒤 공백을 뺀 값이다.
#: base 줄을 키에 넣는 까닭: 같은 날 같은 이슈 번호를 단 행이 서로 다른 PR로 가는 경우가
#: 열 그룹 넘게 있다(예: `README` 2026-09-13 `#513` 세 행 → `#1057`·`#1065`·`#1066`).
#: 줄 없이 견주면 그 행들끼리 새 번호를 맞바꿔도 개수가 같아 통과한다.
Change = tuple[str, int, str, str, str]


def table_rows(text: str) -> list[Row]:
    """``| 2026-09-21 | `#1512` | …`` 꼴의 행. `check_changelog_rows._ROW`와 같은 기준이다."""
    found: list[Row] = []
    for number, line in enumerate(text.split("\n"), start=1):
        parts = line.split("|", 3)
        if len(parts) < 4 or parts[0] != "":
            continue
        date = parts[1].strip()
        if not (len(date) == 10 and date[4] == "-" and date[7] == "-"):
            continue
        if not (date[:4] + date[5:7] + date[8:]).isdigit():
            continue
        found.append(Row(number, f"|{parts[1]}|", parts[2], f"|{parts[3]}"))
    return found


def compare(doc: str, base: str, work: str) -> tuple[list[str], list[Change]]:
    """한 문서의 위반 목록과 커밋 열이 바뀐 행 목록."""
    before, after = table_rows(base), table_rows(work)
    problems: list[str] = []
    added = len(after) - len(before)
    if added not in (0, 1):
        problems.append(
            f"{doc}: 변경 이력 표 행 수가 {len(before)} → {len(after)}입니다 — "
            "같거나 이 PR의 행 1개만 끝에 더해져야 합니다"
        )
        return problems, []
    # 앞에서부터 짝짓는다 — 더한 행이 끝이 아니면 그 뒤의 짝이 모두 어긋나 아래에서 잡힌다.
    changes: list[Change] = []
    for old, new in zip(before, after, strict=False):
        if (old.head, old.tail) != (new.head, new.tail):
            problems.append(
                f"{doc}: base {old.line}행 → 작업 트리 {new.line}행의 커밋 열 밖이 바뀌었습니다 "
                f"(날짜 {old.date} · 커밋 열 {old.commit.strip()}) — 이 PR은 커밋 열만 고칩니다"
            )
        elif old.commit != new.commit:
            if old.commit.strip() == new.commit.strip():
                problems.append(f"{doc}: {new.line}행 커밋 열의 공백만 바뀌었습니다")
            else:
                changes.append((doc, old.line, old.date, old.commit.strip(), new.commit.strip()))
    return problems, changes


def load_map(path: Path) -> list[Change]:
    """매핑표의 (문서, base 줄, 날짜, 원래, 새)."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        return [
            (row["문서"], int(row["줄"]), row["날짜"], row["원래 커밋 열"], row["새 커밋 열"])
            for row in reader
        ]


def match_map(changes: list[Change], mapping: list[Change]) -> list[str]:
    """바뀐 커밋 열과 매핑표가 정확히 같은지 — 개수까지 견준다."""
    done, want = Counter(changes), Counter(mapping)
    problems = [
        f"{doc}: 매핑표에 없는 커밋 열 변경 — base {line}행({date}) {old} → {new}"
        for doc, line, date, old, new in sorted((done - want).elements())
    ]
    problems += [
        f"{doc}: 매핑표의 행이 적용되지 않았습니다 — base {line}행({date}) {old} → {new}"
        for doc, line, date, old, new in sorted((want - done).elements())
    ]
    return problems


def _show(root: Path, rev: str, path: str) -> str:
    """그 시점의 파일. 없던 파일이면 빈 문서로 본다."""
    try:
        return subprocess.run(
            ["git", "show", f"{rev}:{path}"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    except subprocess.CalledProcessError:
        return ""


def check(root: Path, base: str, mapping: list[Change]) -> tuple[list[str], int]:
    """위반 목록과 바뀐 커밋 열 수. 위반이 비어 있으면 통과다."""
    problems: list[str] = []
    changes: list[Change] = []
    for doc in DOCS:
        path = root / doc
        work = path.read_text(encoding="utf-8") if path.exists() else ""
        found, changed = compare(doc, _show(root, base, doc), work)
        problems += found
        changes += changed
    return problems + match_map(changes, mapping), len(changes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="비교할 base 리비전 (예: origin/main)")
    parser.add_argument("--map", required=True, type=Path, help="매핑표 TSV")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    mapping = load_map(args.root / args.map if not args.map.is_absolute() else args.map)
    problems, changed = check(args.root, args.base, mapping)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(
            f"변경 이력 대조 실패 {len(problems)}건 — 커밋 열은 매핑표"
            f"({args.map})대로만 고치고, 다른 칸과 행 순서는 그대로 둡니다 (#2269)."
        )
        return 1
    print(
        f"변경 이력 {len(DOCS)}개 문서 대조 — 커밋 열 {changed}행이 매핑표 {len(mapping)}행과 "
        "일치, 다른 칸·행 순서 변경 없음"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
