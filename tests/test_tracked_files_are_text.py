"""추적 중인 소스 파일에 제어문자가 섞이는 것을 막는다 (#575).

## 왜 필요한가

``#572`` 작업에서 ``frontend/src/features/not-underway/periodRules.ts``에 **실제 NUL
바이트**가 소스로 들어 있던 것을 발견했다. 중복 키의 구분자를 이스케이프가 아니라
문자 그대로 넣은 결과였다. 런타임 동작에는 문제가 없었으나 두 가지가 깨졌다.

- PR에서 diff가 ``Bin 4819 -> 7335 bytes``로만 보여 **리뷰할 수 없다**
- ``grep``이 그 파일을 건너뛴다. 검색이 조용히 0건을 내므로 **「없다」와 「못 읽었다」가
  구분되지 않는다** — 실제로 함수가 있는데 없는 줄 알고 작업했다

``.gitattributes``(#575)가 **diff를 보이게** 만들지만, 유입 자체를 막지는 못한다.
증상이 조용하다는 것이 이 결함의 핵심이므로 **들어오는 자리에 신호를 둔다.**

## 무엇을 검사하나

추적 파일 중 **텍스트로 다루기로 한 확장자**만 본다. 실제 바이너리(이미지·폰트 등)는
NUL을 갖는 것이 정상이므로 건너뛴다. 목록에 없는 확장자도 건너뛴다 — 새 바이너리
형식이 들어올 때 이 테스트가 먼저 깨지면 원인을 잘못 짚게 된다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]

#: 텍스트로 다루기로 한 확장자. ``.gitattributes``의 ``diff`` 목록과 같은 집합이다.
TEXT_SUFFIXES = frozenset(
    {
        ".ts",
        ".tsx",
        ".mjs",
        ".py",
        ".pyi",
        ".css",
        ".html",
        ".json",
        ".jsonc",
        ".md",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".sh",
        ".sql",
        ".csv",
        ".svg",
        ".mako",
        ".txt",
    }
)

#: 확장자가 없지만 텍스트인 파일.
TEXT_NAMES = frozenset({"Dockerfile", ".env.example", ".gitignore", ".dockerignore"})


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    files = []
    for rel in out.split("\0"):
        if not rel:
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            files.append(path)
    return files


def test_tracked_source_files_have_no_nul_byte():
    """소스에 NUL이 섞이면 git이 그 파일을 바이너리로 보고 diff·grep이 막힌다."""
    files = _tracked_text_files()
    # 검사 대상이 0건이면 위 필터가 잘못된 것이다. 조용히 통과시키지 않는다.
    assert len(files) > 100, f"검사 대상이 너무 적다 ({len(files)}건) — 필터를 확인할 것"

    offenders = [str(path.relative_to(REPO_ROOT)) for path in files if b"\x00" in path.read_bytes()]

    assert not offenders, (
        "소스에 NUL 바이트가 있습니다. git이 이 파일을 바이너리로 보아 "
        "PR diff가 보이지 않고 grep도 건너뜁니다 (#572 · #575).\n"
        "문자 그대로 넣지 말고 이스케이프(\\u0000)로 적으십시오:\n  " + "\n  ".join(offenders)
    )


def test_gitattributes_lists_the_text_suffixes():
    """``.gitattributes``와 위 목록이 갈리지 않게 한다.

    두 곳이 어긋나면 **한쪽만 아는 확장자**가 생긴다. 그 파일은 NUL 검사는 받는데
    diff는 바이너리로 보이거나, 반대가 된다.
    """
    text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    declared = {
        line.split()[0].removeprefix("*")
        for line in text.splitlines()
        if line.strip() and not line.startswith("#") and line.split()[0].startswith("*.")
    }

    missing = TEXT_SUFFIXES - declared
    assert not missing, f".gitattributes에 없는 확장자: {sorted(missing)}"


#: 풀리지 않은 병합 표시. ``git merge``·``rebase``가 충돌 자리에 넣는 줄 머리다
#: (``|||||||``는 ``merge.conflictStyle=diff3``의 공통 조상 표시).
#:
#: ``=======``는 **줄 전체가 그것일 때만** 센다 — Markdown의 setext 제목 밑줄도 같은
#: 모양이지만, 이 저장소의 추적 파일에는 그런 줄이 0건이다(2026-09-20 실측). 생기면
#: 이 검사가 먼저 알려 주므로 그때 오탐 규칙을 정한다.
MERGE_MARKER_PREFIXES = ("<<<<<<< ", ">>>>>>> ", "||||||| ")
MERGE_MARKER_LINES = frozenset({"<<<<<<<", ">>>>>>>", "=======", "|||||||"})


def test_tracked_text_files_have_no_merge_markers():
    """병합 표시가 커밋되면 문서가 그 자리에서 조용히 깨진다 (#1309).

    ``TEST_PLAN.md`` 변경 이력 표 한가운데에 ``>>>>>>> origin/`` 한 줄이 커밋돼
    있었다(PR ``#1259``). 표가 그 줄에서 끊겨 뒤의 행들이 문단으로 렌더됐는데
    **어떤 검사도 실패하지 않았다** — 표 행과 참조를 보는 가드는 표가 아닌 줄을
    건너뛴다. ``#1286``(빈 PR 번호)과 같은 유형이다: 검사가 멀쩡한데 문서만 깨져 있다.
    """
    files = _tracked_text_files()
    assert len(files) > 100, f"검사 대상이 너무 적다 ({len(files)}건) — 필터를 확인할 것"

    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.startswith(MERGE_MARKER_PREFIXES) or line.rstrip() in MERGE_MARKER_LINES:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line[:40]}")

    assert not offenders, (
        "풀리지 않은 병합 표시가 커밋돼 있습니다 (#1309). 충돌을 풀 때 표시 줄을 "
        "지우지 않은 것입니다 — 그 줄을 지우고 앞뒤 내용이 맞는지 확인하십시오:\n  "
        + "\n  ".join(offenders)
    )
