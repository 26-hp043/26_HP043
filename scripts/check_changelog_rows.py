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

행을 **커밋 열이 가리키는 참조의 집합**(``#1512`` · 커밋 해시)으로 식별한다(`#1522`).
요약 문구·날짜·꼬리(``⑵``)는 키에 넣지 않는다 — 이 검사가 지키는 것은 「어떤 PR의 기록이
사라지지 않는다」이고, 날짜 오타 정정이나 꼬리 붙이기는 그 기록을 없애지 않는다. 종전
키 ``(날짜, 커밋 열 원문)``은 그런 정상 편집을 「사라진 행」으로 읽었다.

1. **base → 머지 결과**에서 줄어든 행 — 덮어쓰기(`#1488`)
2. **PR의 어느 커밋에든 있었는데** 머지 결과에 없는 행 — 충돌 해결에서 빠짐(`#1512`).
   base에 없던 행이라 1번으로는 안 보인다

같은 PR이 행을 여럿 가질 수 있어(``#1081`` ⑼처럼) 1번은 **개수로** 센다.

커밋 열이 아직 채워지지 않은 행(``#___`` · ``#<PR>`` · 빈 칸)은 대상이 아니다 — 그런 행이
번호로 바뀌며 「사라지는」 것은 정상이고, 남아 있는 것은 `test_doc_cross_refs.py`가 잡는다.
⚠️ **임시값은 숫자가 아니어야 한다.** 이슈 번호를 적어 두었다가 PR 번호로 고치면 이슈
번호 행이 「사라진 행」으로 잡힌다(`#1519`) — `AGENTS §4.1`.

## 리베이스로 푼 충돌 (`#1522`)

2번은 **PR의 커밋**을 ``base..HEAD``로 읽는다. 충돌을 리베이스로 풀면 옛 커밋이 그 범위에서
사라져, 해결 중에 빠진 행을 볼 수 없다. ``--previous-head``(CI의 ``github.event.before`` —
직전 푸시의 head)를 주면 그 커밋까지 함께 읽는다. 받아 두지 않은 커밋이면 가져와 보고,
그래도 없으면 경고만 남기고 넘어간다.

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

Key = tuple[str, ...]


def row_keys(text: str) -> Counter[Key]:
    """문서의 변경 이력 행을 **커밋 열의 참조 집합** 키로 센다. 채우지 않은 행은 뺀다."""
    keys: Counter[Key] = Counter()
    for line in text.splitlines():
        matched = _ROW.match(line)
        if not matched:
            continue
        commit = matched.group("commit").strip()
        if _PLACEHOLDER.search(commit) or not _REFERENCE.search(commit):
            continue
        keys[tuple(sorted(set(_REFERENCE.findall(commit))))] += 1
    return keys


def overwritten(base: Counter[Key], merged: Counter[Key]) -> list[Key]:
    """base보다 머지 결과에서 줄어든 행 — 덮어쓰기."""
    return sorted((base - merged).elements())


def dropped_in_pr(seen: Counter[Key], merged: Counter[Key]) -> list[Key]:
    """PR 커밋 어딘가에 있었는데 머지 결과에서 줄어든 행 — 충돌 해결에서 빠짐.

    ``seen``은 PR의 각 커밋에서 센 행 수의 **키별 최댓값**이다(`#1607`). 키가 참조
    집합이라(`#1522`) ``#1081`` ⑼·⑽처럼 한 PR의 여러 행이 한 키로 합쳐지므로, 「있었나/
    없나」만 보면 둘 중 하나가 빠진 것을 놓친다 — 개수로 본다.
    """
    return sorted((seen - merged).elements())


def _git(root: Path, *args: str) -> str:
    # `#1665` — Git 출력은 UTF-8이다. `text=True`만 두면 **플랫폼 기본 인코딩**(Windows는
    # CP949)으로 풀어, 한국어 변경 이력이 깨지거나 두 판본이 다른 글자로 읽힌다.
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _show(root: Path, rev: str, path: str) -> str:
    """그 시점의 파일. 없던 파일이면 빈 문서로 본다."""
    try:
        return _git(root, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return ""


def _label(key: Key) -> str:
    return " · ".join(key)


def _previous_commits(root: Path, base: str, previous_head: str | None) -> list[str]:
    """직전 푸시의 head까지의 커밋 — 리베이스 전 커밋을 읽기 위해서다."""
    if not previous_head or set(previous_head) == {"0"}:
        return []
    try:
        _git(root, "cat-file", "-e", f"{previous_head}^{{commit}}")
    except subprocess.CalledProcessError:
        try:
            _git(root, "fetch", "--quiet", "origin", previous_head)
        except subprocess.CalledProcessError:
            print(
                f"::warning::직전 head {previous_head}를 가져오지 못해 "
                "리베이스 전 커밋은 보지 않습니다"
            )
            return []
    return _git(root, "rev-list", f"{base}..{previous_head}").split()


def check(root: Path, base: str, previous_head: str | None = None) -> list[str]:
    """위반 목록. 비어 있으면 통과다."""
    commits = _git(root, "rev-list", f"{base}..HEAD").split()
    commits += _previous_commits(root, base, previous_head)
    problems: list[str] = []
    for doc in DOCS:
        path = root / doc
        if not path.exists():
            continue
        merged = row_keys(path.read_text(encoding="utf-8"))
        for key in overwritten(row_keys(_show(root, base, doc)), merged):
            problems.append(f"{doc}: base에 있던 행이 사라졌습니다 — {_label(key)}")

        seen: Counter[Key] = Counter()
        for rev in commits:
            seen |= row_keys(_show(root, rev, doc))  # 키별 최댓값 (#1607)
        for key in dropped_in_pr(seen, merged):
            problems.append(
                f"{doc}: 이 PR의 커밋에 있던 행이 머지 결과에서 빠졌습니다 — {_label(key)}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="비교할 base 리비전 (예: origin/main)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--previous-head",
        default=None,
        help="직전 푸시의 head (CI의 github.event.before) — 리베이스 전 커밋도 읽는다",
    )
    args = parser.parse_args(argv)

    problems = check(args.root, args.base, args.previous_head)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(
            "변경 이력 행은 지우지 않습니다(`AGENTS §4.1`). 충돌 해결에서 빠졌다면 되살리고, "
            "PR 번호를 받기 전 임시값이었다면 숫자가 아닌 `#___`로 적으세요. "
            "일부러 지운 것이면 PR에 `changelog-row-removal` 라벨을 붙인 뒤 CI를 다시 돌리세요."
        )
        return 1
    print(f"변경 이력 행 {len(DOCS)}개 문서 확인 — 사라진 행 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
