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
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TEST_PLAN = _ROOT / "TEST_PLAN.md"
_TESTS_DIR = _ROOT / "tests"
_SRC_DIR = _ROOT / "src"

#: 케이스 ID 문법. ``UT-RISK-003B``처럼 뒤에 알파벳이 붙는 변형이 있다(#172 재배정).
_ID = re.compile(r"\b((?:UT|IT|AT|PT|SEC|A11Y)-[A-Z0-9]+-\d+[A-Z]?)\b")

#: ``§14.5``의 표에서 쓰는 범위 표기 — ``UT-WX-001`~`005`` 형태.
_RANGE = re.compile(r"`([A-Z0-9-]+)-(\d+)`\s*~\s*`?(\d+)`?")


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
    """테스트·구현 코드에 실제로 박혀 있는 ID."""
    files = [p for p in _TESTS_DIR.rglob("*.py") if p.name != Path(__file__).name]
    files += list(_SRC_DIR.rglob("*.py"))
    return set(_ID.findall(_text_of(files)))


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
