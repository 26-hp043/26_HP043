"""정본 변경 이력 행 삭제 검사 (#1498 · `scripts/check_changelog_rows.py`).

`test_doc_cross_refs.py`는 **현재 파일만** 본다. 덮어쓰기와 충돌 해결에서 빠진 행은
이전 상태와 비교해야 보이므로 CI의 `lint` 잡이 이 스크립트를 base 브랜치와 함께 돌린다.
여기서는 그 판정이 두 사고를 실제로 잡는지, 정상 편집을 막지 않는지를 잠근다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_changelog_rows.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_changelog_rows", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_changelog_rows"] = module
    spec.loader.exec_module(module)
    return module


rows = _load()

HEAD = "| 날짜 | 커밋 | 내용 |\n|---|---|---|\n"


def _table(*lines: str) -> str:
    return HEAD + "".join(f"{line}\n" for line in lines)


def test_덮어쓴_행을_잃은_행으로_잡는다():
    """`#1488` — 다음 PR이 마지막 줄 자리에 자기 행을 붙였다. 행 수는 그대로다."""
    base = rows.row_keys(_table("| 2026-09-20 | `#1487` | a |", "| 2026-09-20 | `#1488` | b |"))
    merged = rows.row_keys(_table("| 2026-09-20 | `#1487` | a |", "| 2026-09-20 | `#1489` | c |"))
    assert rows.overwritten(base, merged) == [("2026-09-20", "`#1488`")]


def test_요약_문구를_고치는_것은_막지_않는다():
    """키는 날짜 + 커밋 열이다. 요약 열을 다듬는 PR이 매번 걸리면 가드를 끄게 된다."""
    base = rows.row_keys(_table("| 2026-09-20 | `#1487` | 옛 문구 |"))
    merged = rows.row_keys(_table("| 2026-09-20 | `#1487` | 고친 문구 |"))
    assert rows.overwritten(base, merged) == []


def test_같은_PR의_여러_행은_개수로_센다():
    """``#1081`` ⑼처럼 한 PR이 행을 여럿 갖는다. 하나만 지워도 잡혀야 한다."""
    base = rows.row_keys(_table("| 2026-09-17 | `#1081` | a |", "| 2026-09-17 | `#1081` | b |"))
    merged = rows.row_keys(_table("| 2026-09-17 | `#1081` | a |"))
    assert rows.overwritten(base, merged) == [("2026-09-17", "`#1081`")]


def test_PR_커밋에만_있던_행이_빠지면_잡는다():
    """`#1512` — 행을 싣던 PR의 충돌 해결에서 빠졌다. base에 없던 행이라 1번으로는 안 보인다."""
    seen = set(
        rows.row_keys(_table("| 2026-09-21 | `#1510` | a |", "| 2026-09-21 | `#1512` | b |"))
    )
    merged = rows.row_keys(_table("| 2026-09-21 | `#1510` | a |"))
    assert rows.dropped_in_pr(seen, merged) == [("2026-09-21", "`#1512`")]


@pytest.mark.parametrize("commit", ["`#___`", "`#<PR>`", "", "—"])
def test_채우지_않은_행은_대상이_아니다(commit):
    """번호로 채워지며 「사라지는」 것은 정상이다. 남은 것은 `test_doc_cross_refs.py`가 잡는다."""
    assert rows.row_keys(_table(f"| 2026-09-21 | {commit} | a |")) == Counter()


def test_변경_이력이_아닌_표_행은_세지_않는다():
    text = _table("| 머리 | 값 |", "| `test_x.py` | 3 |", "| 2026-09-21 | `0f59999` | 해시 행 |")
    assert rows.row_keys(text) == Counter({("2026-09-21", "`0f59999`"): 1})


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_실제_git_이력에서_두_사고를_모두_잡는다(tmp_path):
    """스크립트가 base와 PR 커밋을 실제로 읽는지 — 순수 함수만 보면 배선이 빠져도 통과한다."""
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |", "| 2026-09-20 | `#1488` | b |"))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")

    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(
        _table(
            "| 2026-09-20 | `#1487` | a |",
            "| 2026-09-20 | `#1488` | b |",
            "| 2026-09-21 | `#1512` | c |",
        )
    )
    _git(tmp_path, "commit", "-qam", "행을 싣는다")
    # 충돌 해결에서 #1512가 빠지고, 덮어쓰기로 #1488도 사라진 상태
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |", "| 2026-09-21 | `#1513` | d |"))
    _git(tmp_path, "commit", "-qam", "충돌 해결")

    problems = rows.check(tmp_path, "main")
    assert any("base에 있던 행" in p and "#1488" in p for p in problems)
    assert any("커밋에 있던 행" in p and "#1512" in p for p in problems)
    assert rows.main(["--base", "main", "--root", str(tmp_path)]) == 1


def test_정상_PR은_통과한다(tmp_path):
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |"))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(_table("| 2026-09-20 | `#1487` | 고친 문구 |", "| 2026-09-21 | `#1514` | b |"))
    _git(tmp_path, "commit", "-qam", "행 추가")

    assert rows.check(tmp_path, "main") == []
    assert rows.main(["--base", "main", "--root", str(tmp_path)]) == 0
