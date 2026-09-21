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
    assert rows.overwritten(base, merged) == [("#1488",)]


def test_요약_문구를_고치는_것은_막지_않는다():
    """키는 커밋 열의 참조다. 요약 열을 다듬는 PR이 매번 걸리면 가드를 끄게 된다."""
    base = rows.row_keys(_table("| 2026-09-20 | `#1487` | 옛 문구 |"))
    merged = rows.row_keys(_table("| 2026-09-20 | `#1487` | 고친 문구 |"))
    assert rows.overwritten(base, merged) == []


def test_같은_PR의_여러_행은_개수로_센다():
    """``#1081`` ⑼처럼 한 PR이 행을 여럿 갖는다. 하나만 지워도 잡혀야 한다."""
    base = rows.row_keys(_table("| 2026-09-17 | `#1081` | a |", "| 2026-09-17 | `#1081` | b |"))
    merged = rows.row_keys(_table("| 2026-09-17 | `#1081` | a |"))
    assert rows.overwritten(base, merged) == [("#1081",)]


def test_PR_커밋에만_있던_행이_빠지면_잡는다():
    """`#1512` — 행을 싣던 PR의 충돌 해결에서 빠졌다. base에 없던 행이라 1번으로는 안 보인다."""
    seen = rows.row_keys(_table("| 2026-09-21 | `#1510` | a |", "| 2026-09-21 | `#1512` | b |"))
    merged = rows.row_keys(_table("| 2026-09-21 | `#1510` | a |"))
    assert rows.dropped_in_pr(seen, merged) == [("#1512",)]


@pytest.mark.parametrize("commit", ["`#___`", "`#<PR>`", "", "—"])
def test_채우지_않은_행은_대상이_아니다(commit):
    """번호로 채워지며 「사라지는」 것은 정상이다. 남은 것은 `test_doc_cross_refs.py`가 잡는다."""
    assert rows.row_keys(_table(f"| 2026-09-21 | {commit} | a |")) == Counter()


def test_변경_이력이_아닌_표_행은_세지_않는다():
    text = _table("| 머리 | 값 |", "| `test_x.py` | 3 |", "| 2026-09-21 | `0f59999` | 해시 행 |")
    assert rows.row_keys(text) == Counter({("`0f59999`",): 1})


def test_base_행의_날짜_오타를_고쳐도_잃은_행이_아니다():
    """`#1522` ⑵ — 날짜 정정은 기록을 없애지 않는다. 종전 키(날짜 포함)는 이것을 막았다."""
    base = rows.row_keys(_table("| 2026-09-20 | `#1500` | a |"))
    merged = rows.row_keys(_table("| 2026-09-21 | `#1500` | a |"))
    assert rows.overwritten(base, merged) == []


def test_커밋_열에_꼬리를_붙여도_잃은_행이_아니다():
    """`#1522` ⑶ — ``#1081`` ⑼처럼 꼬리를 붙이는 것은 같은 PR의 기록이다."""
    base = rows.row_keys(_table("| 2026-09-21 | `#1506` | a |"))
    merged = rows.row_keys(_table("| 2026-09-21 | `#1506` ⑵ | a |"))
    assert rows.overwritten(base, merged) == []


def test_자기_행의_날짜를_고쳐도_빠진_행이_아니다():
    """`#1522` ⑷ — 자정을 넘겨 자기 행 날짜를 고치는 것. 이슈에 없던 네 번째 오탐이다."""
    seen = rows.row_keys(_table("| 2026-09-21 | `#1519` | a |"))
    merged = rows.row_keys(_table("| 2026-09-22 | `#1519` | a |"))
    assert rows.dropped_in_pr(seen, merged) == []


def test_숫자_임시값을_PR_번호로_바꾸면_잡힌다():
    """`#1519` — 이슈 번호를 임시로 적었다가 PR 번호로 고쳤다. **의도된 실패**다.

    참조가 바뀐 것은 기록이 바뀐 것이라 검사는 구분할 수 없다. 임시값은 숫자가 아닌
    ``#___``로 적는다(`AGENTS §4.1`) — 그러면 아래 검사처럼 통과한다.
    """
    seen = rows.row_keys(_table("| 2026-09-21 | `#1516` | a |"))
    merged = rows.row_keys(_table("| 2026-09-21 | `#1519` | a |"))
    assert rows.dropped_in_pr(seen, merged) == [("#1516",)]


def test_같은_PR의_여러_행_중_하나가_빠져도_잡는다():
    """`#1607` — 키가 참조 집합이라 ⑼·⑽이 한 키가 된다. 「있었나」만 보면 하나가 빠져도 통과했다."""
    seen = rows.row_keys(_table("| 2026-09-17 | `#1081` ⑼ | a |", "| 2026-09-17 | `#1081` ⑽ | b |"))
    merged = rows.row_keys(_table("| 2026-09-17 | `#1081` ⑼ | a |"))
    assert rows.dropped_in_pr(seen, merged) == [("#1081",)]


def test_숫자가_아닌_임시값은_PR_번호로_바꿔도_통과한다():
    seen = rows.row_keys(_table("| 2026-09-21 | `#___` | a |"))
    merged = rows.row_keys(_table("| 2026-09-21 | `#1519` | a |"))
    assert rows.dropped_in_pr(seen, merged) == []


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


def _rebase_conflict_repo(tmp_path: Path, *, keep_own_row: bool) -> tuple[str, str]:
    """PR과 main이 같은 표 끝에 행을 붙이고, PR을 리베이스해 충돌을 푼 저장소.

    돌려주는 것은 (리베이스 전 PR head, 리베이스 후 HEAD).
    """
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |"))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")

    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |", "| 2026-09-22 | `#1582` | pr |"))
    _git(tmp_path, "commit", "-qam", "PR 행")
    before = _git(tmp_path, "rev-parse", "HEAD").strip()

    _git(tmp_path, "checkout", "-q", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |", "| 2026-09-21 | `#1579` | main |"))
    _git(tmp_path, "commit", "-qam", "main 행")

    # 리베이스 대신 결과를 직접 만든다 — main 위에 PR 커밋 하나(충돌 해결 결과).
    _git(tmp_path, "checkout", "-qB", "pr", "main")
    kept = ["| 2026-09-20 | `#1487` | a |", "| 2026-09-21 | `#1579` | main |"]
    if keep_own_row:
        kept.append("| 2026-09-22 | `#1582` | pr |")
    doc.write_text(_table(*kept))
    (tmp_path / "other.txt").write_text("PR의 다른 변경")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "PR 행(리베이스됨)")
    return before, _git(tmp_path, "rev-parse", "HEAD").strip()


def test_리베이스_충돌에서_양쪽_행을_남기면_통과한다(tmp_path):
    """2026-09-22 밤 실제로 겪은 모양 — 두 PR이 표 끝에 행을 붙였고 둘 다 남겼다."""
    before, _ = _rebase_conflict_repo(tmp_path, keep_own_row=True)
    assert rows.check(tmp_path, "main", previous_head=before) == []


def test_리베이스_충돌에서_자기_행을_떨어뜨리면_직전_head로_잡는다(tmp_path):
    """`#1522` ⑺ — 리베이스하면 옛 커밋이 ``base..HEAD``에서 사라져 종전 검사는 못 봤다.

    CI가 넘기는 직전 푸시의 head(``github.event.before``)를 함께 읽어야 보인다.
    """
    before, _ = _rebase_conflict_repo(tmp_path, keep_own_row=False)
    assert rows.check(tmp_path, "main") == [], "직전 head 없이는 볼 수 없다 — 이것이 사각이다"
    problems = rows.check(tmp_path, "main", previous_head=before)
    assert any("커밋에 있던 행" in p and "#1582" in p for p in problems)


def test_직전_head가_없거나_0이면_건너뛴다(tmp_path):
    """첫 푸시(opened)에서는 ``github.event.before``가 비어 있거나 0으로 채워져 있다."""
    _rebase_conflict_repo(tmp_path, keep_own_row=True)
    assert rows.check(tmp_path, "main", previous_head="") == []
    assert rows.check(tmp_path, "main", previous_head="0" * 40) == []


def test_실제_git_이력에서_같은_PR의_둘째_행이_빠지면_잡는다(tmp_path):
    """`#1607` — 배선까지: PR 커밋에서 한 번이라도 둘이었으면 머지 결과도 둘이어야 한다."""
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |"))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(
        _table(
            "| 2026-09-20 | `#1487` | a |",
            "| 2026-09-22 | `#1606` | 하나 |",
            "| 2026-09-22 | `#1606` ⑵ | 둘 |",
        )
    )
    _git(tmp_path, "commit", "-qam", "행 둘")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |", "| 2026-09-22 | `#1606` | 하나 |"))
    _git(tmp_path, "commit", "-qam", "충돌 해결에서 하나가 빠짐")

    problems = rows.check(tmp_path, "main")
    assert any("커밋에 있던 행" in p and "#1606" in p for p in problems)
