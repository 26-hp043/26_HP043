"""변경 이력 커밋 열 재매핑 대조 (#2269 · `scripts/verify_changelog_remap.py`).

#2269 첫 PR은 커밋 열의 이슈 번호를 PR 번호로 고치며 삭제 검사를 라벨로 끈다. 그 공백을
메우는 대조가 **커밋 열만 매핑표대로 바뀐 경우만** 통과시키는지 잠근다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_changelog_remap.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_changelog_remap", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_changelog_remap"] = module
    spec.loader.exec_module(module)
    return module


remap = _load()

HEAD = "# 문서\n\n| 날짜 | 커밋 | 내용 |\n|---|---|---|\n"
BASE = HEAD + "| 2026-09-10 | `#816` | 가 |\n| 2026-09-11 | `#930` ⑵ | 나 |\n"
#: 정상 적용 — 커밋 열의 이슈 번호만 PR 번호로, 꼬리(``⑵``)는 그대로.
WORK = HEAD + "| 2026-09-10 | `#836` | 가 |\n| 2026-09-11 | `#970` ⑵ | 나 |\n"
MAP = [
    ("A.md", 5, "2026-09-10", "`#816`", "`#836`"),
    ("A.md", 6, "2026-09-11", "`#930` ⑵", "`#970` ⑵"),
]


def _run(work: str, mapping=MAP) -> list[str]:
    problems, changes = remap.compare("A.md", BASE, work)
    return problems + remap.match_map(changes, mapping)


def test_매핑표대로_커밋_열만_바뀌면_통과한다():
    assert _run(WORK) == []


def test_이_PR의_행_하나를_끝에_더해도_통과한다():
    assert _run(WORK + "| 2026-10-16 | `#___` | 이 PR |\n") == []


def test_요약을_한_글자라도_바꾸면_잡는다():
    problems = _run(WORK.replace("| 나 |", "| 너 |"))
    assert "커밋 열 밖이 바뀌었습니다" in problems[0]
    assert "2026-09-11" in problems[0]


def test_매핑표와_다른_번호로_바꾸면_잡는다():
    """삭제 검사로는 못 보던 경우다 — 행은 그대로 있고 번호만 엉뚱하다."""
    problems = _run(WORK.replace("`#836`", "`#837`"))
    assert any("매핑표에 없는 커밋 열 변경" in p and "`#837`" in p for p in problems)
    assert any("적용되지 않았습니다" in p and "`#836`" in p for p in problems)


def test_행을_지우면_잡는다():
    problems = _run(HEAD + "| 2026-09-10 | `#836` | 가 |\n")
    assert "2 → 1" in problems[0]


def test_행을_둘_더하면_잡는다():
    problems = _run(WORK + "| 2026-10-16 | `#___` | 하나 |\n| 2026-10-16 | `#___` | 둘 |\n")
    assert "2 → 4" in problems[0]


def test_행을_중간에_끼우면_잡는다():
    """끝이 아닌 자리에 더하면 그 뒤 행의 짝이 어긋난다."""
    work = WORK.replace("| 2026-09-11 |", "| 2026-10-16 | `#___` | 끼움 |\n| 2026-09-11 |")
    assert any("커밋 열 밖이 바뀌었습니다" in p for p in _run(work))


def test_매핑표의_행이_적용되지_않으면_잡는다():
    problems = _run(WORK.replace("`#970` ⑵", "`#930` ⑵"))
    assert problems == [
        "A.md: 매핑표의 행이 적용되지 않았습니다 — base 6행(2026-09-11) `#930` ⑵ → `#970` ⑵"
    ]


def test_같은_날_같은_이슈_번호의_두_행이_새_번호를_맞바꾸면_잡는다():
    """키에 base 줄이 없으면 개수가 같아 통과하던 경우다(#2269 리뷰)."""
    base = HEAD + "| 2026-09-13 | `#513` | 가 |\n| 2026-09-13 | `#513` | 나 |\n"
    good = HEAD + "| 2026-09-13 | `#1057` | 가 |\n| 2026-09-13 | `#1066` | 나 |\n"
    swapped = HEAD + "| 2026-09-13 | `#1066` | 가 |\n| 2026-09-13 | `#1057` | 나 |\n"
    mapping = [
        ("A.md", 5, "2026-09-13", "`#513`", "`#1057`"),
        ("A.md", 6, "2026-09-13", "`#513`", "`#1066`"),
    ]

    def run(work: str) -> list[str]:
        problems, changes = remap.compare("A.md", base, work)
        return problems + remap.match_map(changes, mapping)

    assert run(good) == []
    assert any("매핑표에 없는 커밋 열 변경" in p for p in run(swapped))


def test_행_순서를_바꾸면_잡는다():
    a, b = "| 2026-09-10 | `#836` | 가 |\n", "| 2026-09-11 | `#970` ⑵ | 나 |\n"
    assert _run(HEAD + b + a) != []


def test_변경_이력이_아닌_표_행은_세지_않는다():
    text = "| 머리 | 값 |\n| `test_x.py` | 3 |\n| 2026-07-04 | `0f59999` | 해시 행 |\n"
    assert [row.commit.strip() for row in remap.table_rows(text)] == ["`0f59999`"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_git_base와_작업_트리를_견줘_종료_코드를_낸다(tmp_path, capsys):
    """CI에서 도는 그대로 — base 리비전의 파일과 작업 트리를 견주고 매핑표 TSV를 읽는다."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "PRD.md").write_text(BASE, encoding="utf-8")
    _git(tmp_path, "add", "PRD.md")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "PRD.md").write_text(WORK + "| 2026-10-16 | `#___` | 이 PR |\n", encoding="utf-8")
    tsv = tmp_path / "map.tsv"
    lines = ["문서\t줄\t날짜\t원래 커밋 열\t새 커밋 열\t근거 커밋 sha\tPR 제목"]
    lines += [f"PRD.md\t{line}\t{date}\t{old}\t{new}\t-\t-" for _, line, date, old, new in MAP]
    tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    argv = ["--base", "HEAD", "--map", str(tsv), "--root", str(tmp_path)]

    assert remap.main(argv) == 0

    tsv.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # 매핑 한 행 누락
    assert remap.main(argv) == 1
    assert "매핑표에 없는 커밋 열 변경" in capsys.readouterr().out
