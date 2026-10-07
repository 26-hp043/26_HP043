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
        encoding="utf-8",
    ).stdout


def test_실제_git_이력에서_두_사고를_모두_잡는다(tmp_path):
    """스크립트가 base와 PR 커밋을 실제로 읽는지 — 순수 함수만 보면 배선이 빠져도 통과한다."""
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(
        _table("| 2026-09-20 | `#1487` | a |", "| 2026-09-20 | `#1488` | b |"), encoding="utf-8"
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")

    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(
        _table(
            "| 2026-09-20 | `#1487` | a |",
            "| 2026-09-20 | `#1488` | b |",
            "| 2026-09-21 | `#1512` | c |",
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-qam", "행을 싣는다")
    # 충돌 해결에서 #1512가 빠지고, 덮어쓰기로 #1488도 사라진 상태
    doc.write_text(
        _table("| 2026-09-20 | `#1487` | a |", "| 2026-09-21 | `#1513` | d |"), encoding="utf-8"
    )
    _git(tmp_path, "commit", "-qam", "충돌 해결")

    problems = rows.check(tmp_path, "main")
    assert any("base에 있던 행" in p and "#1488" in p for p in problems)
    assert any("커밋에 있던 행" in p and "#1512" in p for p in problems)
    assert rows.main(["--base", "main", "--root", str(tmp_path)]) == 1


def test_정상_PR은_통과한다(tmp_path):
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |"), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(
        _table("| 2026-09-20 | `#1487` | 고친 문구 |", "| 2026-09-21 | `#1514` | b |"),
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-qam", "행 추가")

    assert rows.check(tmp_path, "main") == []
    assert rows.main(["--base", "main", "--root", str(tmp_path)]) == 0


def _rebase_conflict_repo(tmp_path: Path, *, keep_own_row: bool) -> tuple[str, str]:
    """PR과 main이 같은 표 끝에 행을 붙이고, PR을 리베이스해 충돌을 푼 저장소.

    돌려주는 것은 (리베이스 전 PR head, 리베이스 후 HEAD).
    """
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |"), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")

    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(
        _table("| 2026-09-20 | `#1487` | a |", "| 2026-09-22 | `#1582` | pr |"), encoding="utf-8"
    )
    _git(tmp_path, "commit", "-qam", "PR 행")
    before = _git(tmp_path, "rev-parse", "HEAD").strip()

    _git(tmp_path, "checkout", "-q", "main")
    doc.write_text(
        _table("| 2026-09-20 | `#1487` | a |", "| 2026-09-21 | `#1579` | main |"), encoding="utf-8"
    )
    _git(tmp_path, "commit", "-qam", "main 행")

    # 리베이스 대신 결과를 직접 만든다 — main 위에 PR 커밋 하나(충돌 해결 결과).
    _git(tmp_path, "checkout", "-qB", "pr", "main")
    kept = ["| 2026-09-20 | `#1487` | a |", "| 2026-09-21 | `#1579` | main |"]
    if keep_own_row:
        kept.append("| 2026-09-22 | `#1582` | pr |")
    doc.write_text(_table(*kept), encoding="utf-8")
    (tmp_path / "other.txt").write_text("PR의 다른 변경", encoding="utf-8")
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
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |"), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "pr")
    doc.write_text(
        _table(
            "| 2026-09-20 | `#1487` | a |",
            "| 2026-09-22 | `#1606` | 하나 |",
            "| 2026-09-22 | `#1606` ⑵ | 둘 |",
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-qam", "행 둘")
    doc.write_text(
        _table("| 2026-09-20 | `#1487` | a |", "| 2026-09-22 | `#1606` | 하나 |"), encoding="utf-8"
    )
    _git(tmp_path, "commit", "-qam", "충돌 해결에서 하나가 빠짐")

    problems = rows.check(tmp_path, "main")
    assert any("커밋에 있던 행" in p and "#1606" in p for p in problems)


def test_더한_행은_부모에_없던_키만_그_시점의_개수로_센다():
    """`#2286` — 트리 전부가 아니라 더한 행만. 값은 늘어난 수가 아니라 그 시점의 행 수다."""
    parent = rows.row_keys(
        _table("| 2026-10-01 | `#2080` | 옛 main |", "| 2026-10-02 | `#2100` | a |")
    )
    commit = rows.row_keys(
        _table(
            "| 2026-10-01 | `#2080` | 옛 main |",
            "| 2026-10-02 | `#2100` | a |",
            "| 2026-10-03 | `#2100` ⑵ | b |",
        )
    )
    assert rows.added_rows(commit, [parent]) == Counter({("#2100",): 2})
    assert rows.added_rows(parent, [parent]) == Counter()


def test_머지_커밋은_어느_부모에도_없던_행만_더한_것으로_본다():
    """`#2286` — `main`을 끌어온 머지에서 `main` 쪽 행은 이 PR이 더한 것이 아니다."""
    ours = rows.row_keys(
        _table("| 2026-10-01 | `#2080` | 옛 main |", "| 2026-10-05 | `#2290` | pr |")
    )
    theirs = rows.row_keys(_table("| 2026-10-01 | `#2259` | 고친 main |"))
    merge = rows.row_keys(
        _table("| 2026-10-01 | `#2259` | 고친 main |", "| 2026-10-05 | `#2290` | pr |")
    )
    assert rows.added_rows(merge, [ours, theirs]) == Counter()
    invented = rows.row_keys(
        _table("| 2026-10-01 | `#2259` | 고친 main |", "| 2026-10-06 | `#2291` | 새 |")
    )
    assert rows.added_rows(invented, [ours, theirs]) == Counter({("#2291",): 1})


_OLD_MAIN = ("| 2026-10-01 | `#2080` | 이슈 번호로 적힌 행 |",)
_NEW_MAIN = (
    "| 2026-10-01 | `#2259` | PR 번호로 고친 행 |",
    "| 2026-10-06 | `#2284` | main의 새 행 |",
)
_OWN_ROW = "| 2026-10-05 | `#2290` | pr |"


def _stale_base_repo(tmp_path: Path, *, pr_adds_row: bool, merged_rows: tuple[str, ...]) -> None:
    """옛 `main` 위의 PR을, 그 뒤 커밋 열이 고쳐진 `main`과 **머지 커밋으로** 합친 저장소.

    `gh pr update-branch`(리베이스 아님)가 만드는 모양이다. ``merged_rows``가 머지 결과의
    변경 이력이다 — 충돌 해결을 흉내 내려고 직접 적는다.
    """
    doc = tmp_path / "API_SPEC.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table(*_OLD_MAIN), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "옛 main")

    _git(tmp_path, "checkout", "-qb", "pr")
    (tmp_path / "uv.lock").write_text("정본이 아닌 변경", encoding="utf-8")
    if pr_adds_row:
        doc.write_text(_table(*_OLD_MAIN, _OWN_ROW), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "PR 커밋")

    _git(tmp_path, "checkout", "-q", "main")
    doc.write_text(_table(*_NEW_MAIN), encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "커밋 열을 고치고 새 행을 싣는다")

    _git(tmp_path, "checkout", "-q", "pr")
    _git(tmp_path, "merge", "-q", "--no-commit", "--no-ff", "-s", "ours", "main")
    doc.write_text(_table(*merged_rows), encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "main을 끌어온다")
    assert len(_git(tmp_path, "rev-list", "--merges", "main..HEAD").split()) == 1


def test_정본을_건드리지_않은_PR은_옛_base_위에_있어도_통과한다(tmp_path):
    """`#2286` — Dependabot `#2230`·`#2231`. 옛 커밋의 트리에 든 옛 `main` 행은 PR의 행이 아니다."""
    _stale_base_repo(tmp_path, pr_adds_row=False, merged_rows=_NEW_MAIN)
    assert rows.check(tmp_path, "main") == []
    assert rows.main(["--base", "main", "--root", str(tmp_path)]) == 0


def test_옛_base_위에서_행을_더한_PR도_자기_행이_남으면_통과한다(tmp_path):
    """`#2286` — 정본을 바꾼 커밋이라도 그 트리의 옛 `main` 행까지 PR의 행으로 세지 않는다."""
    _stale_base_repo(tmp_path, pr_adds_row=True, merged_rows=(*_NEW_MAIN, _OWN_ROW))
    assert rows.check(tmp_path, "main") == []


def test_머지_커밋의_충돌_해결에서_자기_행이_빠지면_잡는다(tmp_path):
    """`#1512` — 이 검사가 있는 이유다. 더한 행만 세도 PR이 더한 행은 그대로 센다."""
    _stale_base_repo(tmp_path, pr_adds_row=True, merged_rows=_NEW_MAIN)
    problems = rows.check(tmp_path, "main")
    assert [p for p in problems if "커밋에 있던 행" in p] == [
        "API_SPEC.md: 이 PR의 커밋에 있던 행이 머지 결과에서 빠졌습니다 — #2290"
    ]
    assert not any("#2080" in p for p in problems)


def test_머지_커밋의_충돌_해결에서_main의_행이_빠지면_1번이_잡는다(tmp_path):
    """`#2286` — 2번이 세지 않게 된 행(끌어온 `main`의 행)은 1번의 몫이다. 빈틈이 생기지 않는다."""
    _stale_base_repo(tmp_path, pr_adds_row=True, merged_rows=(_NEW_MAIN[0], _OWN_ROW))
    assert rows.check(tmp_path, "main") == ["API_SPEC.md: base에 있던 행이 사라졌습니다 — #2284"]


def test_실제_git_이력에서_두_커밋에_나눠_실은_행_중_하나가_빠지면_잡는다(tmp_path):
    """`#1607` × `#2286` — 커밋마다 늘어난 수(1)만 세면 최댓값이 1에 머물러 못 본다."""
    doc = tmp_path / "TEST_PLAN.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-20 | `#1487` | a |"), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "pr")
    one = ("| 2026-09-20 | `#1487` | a |", "| 2026-09-22 | `#1606` | 하나 |")
    doc.write_text(_table(*one), encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "첫 행")
    doc.write_text(_table(*one, "| 2026-09-22 | `#1606` ⑵ | 둘 |"), encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "둘째 행")
    doc.write_text(_table(*one), encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "충돌 해결에서 하나가 빠짐")

    problems = rows.check(tmp_path, "main")
    assert any("커밋에 있던 행" in p and "#1606" in p for p in problems)


def test_두_번_최신화한_PR의_첫_머지가_끌어온_행을_PR의_행으로_세지_않는다(tmp_path):
    """`#2286` — `#2231` 두 번째 갱신의 모양. 머지 커밋은 **부모 전부**와 견줘야 한다.

    첫 머지가 `main`의 ``#2080`` 행을 끌어오고, 그 뒤 `main`이 그 행의 커밋 열을 고친다.
    첫 부모(PR 쪽)하고만 견주면 첫 머지가 ``#2080``을 스스로 더한 것으로 읽힌다. 머지는
    흉내가 아니라 실제 ``git merge``다 — PR이 정본을 건드리지 않아 충돌이 없다.
    """
    doc = tmp_path / "API_SPEC.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    doc.write_text(_table("| 2026-09-30 | `#2070` | a |"), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "갈라지는 자리")

    _git(tmp_path, "checkout", "-qb", "pr")
    (tmp_path / "uv.lock").write_text("정본이 아닌 변경", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "PR 커밋")

    _git(tmp_path, "checkout", "-q", "main")
    doc.write_text(
        _table("| 2026-09-30 | `#2070` | a |", "| 2026-10-01 | `#2080` | 이슈 번호로 적힌 행 |"),
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-qam", "이슈 번호로 행을 싣는다")
    _git(tmp_path, "checkout", "-q", "pr")
    _git(tmp_path, "merge", "-q", "--no-ff", "-m", "첫 최신화", "main")

    _git(tmp_path, "checkout", "-q", "main")
    doc.write_text(
        _table("| 2026-09-30 | `#2070` | a |", "| 2026-10-01 | `#2259` | PR 번호로 고친 행 |"),
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-qam", "커밋 열을 고친다")
    _git(tmp_path, "checkout", "-q", "pr")
    _git(tmp_path, "merge", "-q", "--no-ff", "-m", "두 번째 최신화", "main")

    assert len(_git(tmp_path, "rev-list", "--merges", "main..HEAD").split()) == 2
    assert "#2259" in doc.read_text(encoding="utf-8")
    assert rows.check(tmp_path, "main") == []
