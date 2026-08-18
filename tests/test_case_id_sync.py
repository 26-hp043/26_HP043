"""이슈 #447 · 케이스 ID가 어디에도 없는 상태를 막는다.

**막으려는 것은 케이스가 없는 것 자체가 아니라, 없다는 사실이 보이지 않는 상태다.**

이슈의 완료 기준이 `AT-AS-001~004 통과`처럼 케이스 ID로 적힌다. 그런데 2026-08-17
시점에 ``TEST_PLAN``이 정의한 **146개 중 95개가 코드에 흔적이 없었다.** 그 ID를 단
테스트가 없으므로 「통과했다」가 무엇을 뜻하는지 확인할 수 없었고, 그 사실을 알아채려면
사람이 두 문서를 손으로 대조하는 수밖에 없었다.

그래서 모든 케이스 ID를 **셋 중 하나로 반드시 분류**하게 한다.

===========  ==========================================================
 상태         근거
===========  ==========================================================
 대응됨       테스트 코드에 그 ID가 있다
 미대응       ``TEST_PLAN §14.5`` 「미대응」 표에 이유와 함께 적혀 있다
 계획분       ``TEST_PLAN §14.5`` 「계획분」 표에 대응 이슈와 함께 적혀 있다
===========  ==========================================================

어느 것도 아닌 ID가 남으면 여기서 실패한다. **새 케이스를 문서에 적고 테스트를 잊는
경로**와 **테스트에만 있는 유령 ID**를 함께 막는다.

케이스를 새로 추가했다면
------------------------
테스트 모듈 docstring에 한 줄 넣는다.

.. code-block:: text

    케이스: AT-XX-001 · AT-XX-002 (`TEST_PLAN §14.5`)

아직 테스트를 못 쓰겠으면 ``§14.5``의 「미대응」 또는 「계획분」 표에 **이유와 함께**
적는다. 조용히 두는 것만 막는다.

케이스를 설명으로 인용만 하려면 (#498)
--------------------------------------
「이 케이스는 여기서 덮지 않는다」를 적을 때는 같은 줄에 ``NOT-COVERED:``를 붙인다.

.. code-block:: text

    NOT-COVERED: IT-AUDIT-002 — 기능이 없어 #444로 옮겼다

그 줄의 ID는 커버리지 주장으로 세지 않는다. 표시가 없으면 **덮지 않았다고 적은
문장 때문에 「덮었다」로 읽힌다** — 이슈 #498이 이틀 동안 두 번 겪은 일이다.

구현 코드(``src/``)의 인용은 애초에 세지 않는다. ``§14.5``가 「**테스트 코드에**
있다」로 규정하므로 그 범위를 넘지 않는다.
"""

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TEST_PLAN = _ROOT / "TEST_PLAN.md"
_TESTS_DIR = _ROOT / "tests"

#: 케이스 ID 문법. ``UT-RISK-003B``처럼 뒤에 알파벳이 붙는 변형이 있다(#172 재배정).
_ID = re.compile(r"\b((?:UT|IT|AT|PT|SEC|A11Y)-[A-Z0-9]+-\d+[A-Z]?)\b")

#: ``§14.5``의 표에서 쓰는 범위 표기 — ``UT-WX-001`~`005`` 형태.
_RANGE = re.compile(r"`([A-Z0-9-]+)-(\d+)`\s*~\s*`?(\d+)`?")

#: 「여기서 덮지 않는다」 표시 (#498). 이 표시가 있는 **줄**의 ID는 세지 않는다.
#:
#: 줄 단위인 이유 — 파일 단위로 두면 그 파일의 정당한 커버리지 주장까지 함께
#: 사라지고, 블록 단위로 두면 어디서 끝나는지를 다시 규칙으로 정해야 한다.
_NOT_COVERED = re.compile(r"NOT-COVERED\s*:")


def _text_of(paths) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="ignore") for p in paths)


def _defined_ids() -> set[str]:
    """``TEST_PLAN``이 정의한 전체 케이스 ID."""
    return set(_ID.findall(_TEST_PLAN.read_text(encoding="utf-8")))


def _section_14_5() -> str:
    text = _TEST_PLAN.read_text(encoding="utf-8")
    start = text.index("### 14.5 케이스 ID의 소재")
    return text[start : text.index("### 14.6", start)]


def _expand(block: str) -> set[str]:
    """표에서 분류된 ID를 뽑는다. ``A-001`~`005``는 개별 ID로 펼친다.

    **표 행의 첫 칸만 본다.** 설명 칸에도 ID가 나오는데(「`UT-CAP-004·005`가 LNG 하한만
    덮는다」) 그것은 근거이지 분류가 아니다. 전체를 훑으면 **설명에 언급됐다는 이유로
    면제되는** 일이 생긴다.
    """
    ids: set[str] = set()
    for line in block.splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.split("|")[1]
        ids.update(_ID.findall(first_cell))
        for prefix, first, last in _RANGE.findall(first_cell):
            width = len(first)
            ids.update(f"{prefix}-{n:0{width}d}" for n in range(int(first), int(last) + 1))
    return ids


def _excused_ids() -> tuple[set[str], set[str]]:
    """``§14.5``가 「미대응」·「계획분」으로 분류한 ID."""
    section = _section_14_5()
    unmapped_start = section.index("#### 미대응")
    planned_start = section.index("#### 계획분")
    return (
        _expand(section[unmapped_start:planned_start]),
        _expand(section[planned_start:]),
    )


def _ids_in_code() -> set[str]:
    """**테스트 코드**가 커버리지로 주장하는 ID (#498).

    두 가지를 세지 않는다.

    구현 코드(``src/``)
        ``TEST_PLAN §14.5``의 「대응됨」 행은 *「그 ID가 **테스트 코드에** 있다」*로
        규정한다. 종전 구현이 ``src/``까지 훑은 것은 그 문구를 넘어선 것이었고,
        구현 파일이 케이스를 **설명으로 인용**하기만 해도 커버리지 주장이 됐다.
        실제로 ``services/voyage_import.py``가 *「파라미터 import의 ``IT-IMPORT-005``는
        이쪽과 다른 계약이다」*라고 적었다가 그 때문에 CI가 실패했다.

        범위를 좁혀도 **잃는 것이 없다** — 측정 결과 ``src/``에만 있고 ``tests/``에
        없는 ID는 0건이다. 문구에 맞추는 드리프트 정정이다.

    ``NOT-COVERED:``가 붙은 줄
        「이 케이스는 여기서 덮지 않는다」를 적을 자리가 필요하다. 그 자리가 없으면
        우회가 「그 ID를 아예 적지 않는 것」이 되고, 그러면 **테스트가 왜 그 케이스를
        다루지 않는지 설명할 곳이 사라진다** — 게이트가 지키려던 것과 반대 방향이다.
    """
    files = [p for p in _TESTS_DIR.rglob("*.py") if p.name != Path(__file__).name]
    lines = [ln for ln in _text_of(files).splitlines() if not _NOT_COVERED.search(ln)]
    return set(_ID.findall("\n".join(lines)))


def test_every_case_id_is_classified():
    """**이 파일의 본체** — 분류되지 않은 케이스 ID가 남지 않는다."""
    defined = _defined_ids()
    unmapped, planned = _excused_ids()
    in_code = _ids_in_code()

    orphans = sorted(defined - in_code - unmapped - planned)
    assert not orphans, (
        f"어디에도 없는 케이스 ID {len(orphans)}건: {', '.join(orphans)}\n"
        "테스트에 ID를 달거나, TEST_PLAN §14.5의 「미대응」·「계획분」 표에 이유와 함께 적는다."
    )


def test_no_ghost_ids_in_code():
    """코드에만 있고 문서에 없는 ID를 막는다 — 오타는 조용히 통과하면 안 된다."""
    ghosts = sorted(_ids_in_code() - _defined_ids())
    assert not ghosts, (
        f"TEST_PLAN에 없는 케이스 ID가 코드에 있다: {', '.join(ghosts)}. "
        "오타이거나, 문서에 등재하지 않고 만든 케이스다."
    )


def test_excused_ids_are_not_already_covered():
    """면제 목록이 낡는 것을 막는다.

    테스트를 쓴 뒤 표에서 지우지 않으면, 그 ID는 **덮여 있는데도 부채로 남는다.**
    반대 방향의 드리프트라 눈에 띄지 않는다.
    """
    unmapped, planned = _excused_ids()
    in_code = _ids_in_code()
    stale = sorted((unmapped | planned) & in_code)
    assert not stale, (
        f"이미 테스트가 있는데 §14.5 면제 표에 남아 있다: {', '.join(stale)}. 표에서 지운다."
    )


def test_section_14_5_only_lists_real_ids():
    """면제 표에 존재하지 않는 ID를 적어 두는 것도 막는다."""
    unmapped, planned = _excused_ids()
    unknown = sorted((unmapped | planned) - _defined_ids())
    assert not unknown, f"§14.5가 정의되지 않은 ID를 적고 있다: {', '.join(unknown)}"


# ---------------------------------------------------------------------------
# 범위 규칙 자체를 고정한다 (#498)
#
# 위 네 테스트는 **저장소의 현재 상태**를 본다. 아래 셋은 **게이트가 무엇을 세는가**를
# 본다 — 규칙이 조용히 되돌아가면 여기서 잡힌다.
#
# ``_TESTS_DIR``을 임시 디렉토리로 갈아 끼운다. ``tests``는 패키지가 아니라
# 모듈 경로 문자열로는 패치할 수 없어, 이 모듈의 전역을 직접 바꾼다.
# ---------------------------------------------------------------------------

_SELF = sys.modules[__name__]


def _scan(tmp_path, monkeypatch, **files: str) -> set[str]:
    """가짜 tests 디렉토리를 만들어 ``_ids_in_code()``를 돌린다."""
    for name, body in files.items():
        (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
    monkeypatch.setattr(_SELF, "_TESTS_DIR", tmp_path)
    return _ids_in_code()


def test_declaration_line_counts(tmp_path, monkeypatch):
    """평범하게 적힌 ID는 그대로 커버리지 주장이다 — 규칙을 좁힌 것이 아니다."""
    found = _scan(
        tmp_path,
        monkeypatch,
        test_x='"""케이스: UT-CII-001 (`TEST_PLAN §14.5`)"""\n',
    )
    assert "UT-CII-001" in found


def test_not_covered_line_is_excluded(tmp_path, monkeypatch):
    """``NOT-COVERED:``가 붙은 줄의 ID는 세지 않는다.

    이슈 #498이 겪은 것 — 「덮지 않았다」고 적은 문장 때문에 「덮었다」로 읽혔다.
    """
    found = _scan(
        tmp_path,
        monkeypatch,
        test_x=(
            '"""케이스: UT-CII-001 (`TEST_PLAN §14.5`)\n\n'
            "NOT-COVERED: UT-CII-008 — 기능이 없어 #444로 옮겼다\n"
            '"""\n'
        ),
    )
    assert "UT-CII-001" in found, "같은 파일의 정당한 주장까지 사라지면 안 된다"
    assert "UT-CII-008" not in found


def test_src_citations_are_not_coverage(tmp_path, monkeypatch):
    """``tests/`` 밖의 파일은 훑지 않는다 — ``§14.5``는 「**테스트 코드에** 있다」다.

    종전에는 ``src/``도 함께 훑어, 구현 파일이 케이스를 **설명으로 인용**하기만 해도
    커버리지 주장이 됐다(``services/voyage_import.py``의 ``IT-IMPORT-005``).
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mod.py").write_text(
        '"""파라미터 import의 IT-CSV-001은 이쪽과 다른 계약이다."""\n', encoding="utf-8"
    )
    empty_tests = tmp_path / "tests_only"
    empty_tests.mkdir()
    monkeypatch.setattr(_SELF, "_TESTS_DIR", empty_tests)
    assert _ids_in_code() == set()
