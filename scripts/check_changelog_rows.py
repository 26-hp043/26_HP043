#!/usr/bin/env python3
"""정본 변경 이력 행이 PR에서 사라지지 않았는지 본다 (#1498).

## 왜 필요한가

여덟 정본은 끝에 **변경 이력 표**를 두고, 커밋 열에 PR 번호를 적는다(`AGENTS §4.1`).
그 행이 한 세션에서 **세 번** 사라졌다.

=============  ================================================================
 `#1488`        다음 PR이 표의 마지막 줄 **자리에** 자기 행을 붙여 덮어썼다
 `#1489`        초안 이름표 ``#<PR>``이 커밋 열에 그대로 들어갔다
 `#1512`        그 행을 싣던 PR(`#1513`)의 **충돌 해결에서** 빠졌다
=============  ================================================================

둘째는 `tests/test_doc_cross_refs.py`가 잡는다(커밋 열이 ``#숫자``인지). 첫째와 셋째는
**현재 파일만 보는 검사로는 원리상 볼 수 없다** — 덮어쓰면 행 수가 그대로이고, 빠진
행은 참조가 아니라 **없는 것**이다. 비교할 이전 상태가 있어야 한다.

## 무엇을 보는가

행을 ``(날짜, 커밋 열)``로 식별한다. 요약 문구는 고쳐도 되므로 키에 넣지 않는다.

1. **base → 머지 결과**에서 줄어든 행 — 덮어쓰기(`#1488`)
2. **PR의 어느 커밋에든 있었는데** 머지 결과에 없는 행 — 충돌 해결에서 빠짐(`#1512`).
   base에 없던 행이라 1번으로는 안 보인다

같은 PR이 행을 여럿 가질 수 있어(``#1081`` ⑼처럼) 1번은 **개수로** 센다.

커밋 열이 아직 채워지지 않은 행(``#___`` · ``#<PR>`` · 빈 칸)은 대상이 아니다 — 그런 행이
번호로 바뀌며 「사라지는」 것은 정상이고, 남아 있는 것은 `test_doc_cross_refs.py`가 잡는다.

## 일부러 지울 때

PR에 ``changelog-row-removal`` 라벨을 붙이고 CI를 다시 돌린다(`ci.yml`). 머지된 이력을
지우는 일은 드물고, 그렇게 할 때는 **리뷰어가 보는 자리에** 흔적이 남아야 한다.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

#: 변경 이력 표를 가진 정본 — `tests/test_doc_cross_refs.py`의 ``TARGETS``와 같다.
DOCS: tuple[str, ...] = (
    "UIFLOW.md",
    "DESIGN_SYSTEM.md",
    "PRD.md",
    "TECH_SPEC.md",
    "API_SPEC.md",
    "DB_SCHEMA.md",
    "TEST_PLAN.md",
    "AGENTS.md",
)

#: ``| 2026-09-21 | `#1512` | …`` — 날짜와 커밋 열.
_ROW = re.compile(r"^\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|(?P<commit>[^|]*)\|")
#: 커밋 열이 가리킬 수 있는 것 — PR·이슈 번호 또는 커밋 해시.
_REFERENCE = re.compile(r"#[0-9]+|`[0-9a-f]{7,40}`")
#: ``#`` 뒤에 숫자가 오지 않는 자리 — 아직 채우지 않은 칸.
_PLACEHOLDER = re.compile(r"#(?![0-9])")

Key = tuple[str, str]


def row_keys(text: str) -> Counter[Key]:
    """문서의 변경 이력 행을 ``(날짜, 커밋 열)`` 키로 센다. 채우지 않은 행은 뺀다."""
    keys: Counter[Key] = Counter()
    for line in text.splitlines():
        matched = _ROW.match(line)
        if not matched:
            continue
        commit = matched.group("commit").strip()
        if _PLACEHOLDER.search(commit) or not _REFERENCE.search(commit):
            continue
        keys[(matched.group("date"), commit)] += 1
    return keys


def overwritten(base: Counter[Key], merged: Counter[Key]) -> list[Key]:
    """base보다 머지 결과에서 줄어든 행 — 덮어쓰기."""
    return sorted((base - merged).elements())


def dropped_in_pr(seen: set[Key], merged: Counter[Key]) -> list[Key]:
    """PR 커밋 어딘가에 있었는데 머지 결과에 없는 행 — 충돌 해결에서 빠짐."""
    return sorted(key for key in seen if merged[key] == 0)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _show(root: Path, rev: str, path: str) -> str:
    """그 시점의 파일. 없던 파일이면 빈 문서로 본다."""
    try:
        return _git(root, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return ""


def check(root: Path, base: str) -> list[str]:
    """위반 목록. 비어 있으면 통과다."""
    commits = _git(root, "rev-list", f"{base}..HEAD").split()
    problems: list[str] = []
    for doc in DOCS:
        path = root / doc
        if not path.exists():
            continue
        merged = row_keys(path.read_text(encoding="utf-8"))
        for date, commit in overwritten(row_keys(_show(root, base, doc)), merged):
            problems.append(f"{doc}: base에 있던 행이 사라졌습니다 — {date} {commit}")

        seen: set[Key] = set()
        for rev in commits:
            seen.update(row_keys(_show(root, rev, doc)))
        for date, commit in dropped_in_pr(seen, merged):
            problems.append(
                f"{doc}: 이 PR의 커밋에 있던 행이 머지 결과에서 빠졌습니다 — {date} {commit}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="비교할 base 리비전 (예: origin/main)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    problems = check(args.root, args.base)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(
            "변경 이력 행은 지우지 않습니다(`AGENTS §4.1`). 충돌 해결에서 빠졌다면 되살리고, "
            "일부러 지운 것이면 PR에 `changelog-row-removal` 라벨을 붙인 뒤 CI를 다시 돌리세요."
        )
        return 1
    print(f"변경 이력 행 {len(DOCS)}개 문서 확인 — 사라진 행 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
