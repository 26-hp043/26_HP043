"""문서 간 절·화면 참조의 실재 검증 (#583).

## 무엇을 막는가

`DESIGN_SYSTEM`이 **존재한 적도 없는 `UIFLOW` 절**을 6종 참조하고 있었다.

    UIFLOW §1.1 · §2.2 · §3 · §4.3 · §4.5 · §9-3 · §9-4

`#583`이 처음 셋을 잡았고 조사 중 나머지가 드러났다. **전부 한 커밋(`59a0805`,
PR `#463`)에서 들어왔다** — 제목이 `Update`이고 본문이 비어 있어 `#465`가 PR
템플릿을 만들게 한 그 커밋이다. 제목·본문이라는 증상은 `#465`가 고쳤지만,
**내용은 리뷰될 표면이 없어** 없는 절 참조 6종이 그대로 통과했다.

`UIFLOW`는 전 이력에서 최상위 절이 `0`·`1`·`2`뿐이었다. **재번호 드리프트가
아니라 처음부터 없는 절을 가리켜 쓴 것**이므로, 버전 동기화 가드
(`test_doc_version_sync.py`)로는 잡히지 않는다. 참조가 실재하는지를 직접 본다.

## 왜 CI가 지키는가

**문서는 빌드되지 않는다.** 절 번호를 바꾸거나 없는 번호를 적어도 아무것도
깨지지 않고, 그 참조를 따라간 사람이 막힐 때까지 드러나지 않는다. 실제로
`#485` ④⑤(`RegulatoryFlag`·`DataConfidenceBadge`)가 **착수 불가 상태로 멈춰
있었다** — 「표시 임계는 `UIFLOW §4.5`」인데 그 절이 없었다.

## 코드 주석까지 보는 이유

`frontend/src/screens.ts`도 *「`UIFLOW §2.2` 매핑 표에 SCR-002 행이 없다」*로
같은 참조를 쓰고 있었다. `.md`만 스캔하면 이것을 놓친다.

## 무엇을 검사하지 않는가

**참조가 가리키는 내용이 맞는지는 보지 않는다.** 번호가 실재하는지만 본다.
내용 대조는 사람이 한다 — `AGENTS §4.4`가 상위 문서 참조에서 같은 선을 긋는다.

**화면 번호 검사는 `UIFLOW`에만 적용한다.** 화면 번호 체계를 가진 문서가 그것
하나뿐이다. `DESIGN_SYSTEM §16-6`처럼 생긴 것은 화면이 아니라 **§16 미확정 목록의
행 번호**이며(닫힌 항목은 `~~6~~`처럼 취소선이 붙는다) 별개의 번호 체계다. 앞자리
`§16`이 실재하는지는 절 검사가 이미 본다. 두 체계가 같은 `§N-M` 모양을 쓰는 것
자체가 문제이며, 표기 통일은 별건으로 다룬다.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: 참조 대상이 되는 소관 한정 정본 (`AGENTS §3.2`). 이 둘이 서로를 가리키다 어긋났다.
TARGETS: dict[str, str] = {
    "UIFLOW": "UIFLOW.md",
    "DESIGN_SYSTEM": "DESIGN_SYSTEM.md",
}

#: 스캔 대상. 문서뿐 아니라 코드 주석도 같은 참조를 쓴다.
_MD = sorted(_ROOT.glob("*.md"))
_SRC = sorted(p for ext in ("*.ts", "*.tsx") for p in (_ROOT / "frontend" / "src").rglob(ext))

#: ``UIFLOW §2.2`` · ``DESIGN_SYSTEM §4.1`` — 절 참조. 점으로 잇는다.
_SECTION_REF = re.compile(
    r"\b(?P<doc>" + "|".join(TARGETS) + r")(?:\.md)?[ `]{0,3}§\s*(?P<num>[0-9]+(?:\.[0-9]+)*)\b"
)
#: ``` `UIFLOW §2`·`§3` ``` — 앞 참조에 이어 쓴 절. **문서명이 붙지 않는다.**
#:
#: `#583`의 원 이슈가 `grep -oE "UIFLOW §[0-9.]+"`로 훑어 **이 형태를 놓쳤다.**
#: 끊긴 참조가 4건으로 집계됐으나 실제로는 이것을 포함해 더 있었다. 앞 참조가
#: 가리킨 문서를 그대로 물려받아 함께 검사한다(`_continued`).
_CONTINUATION = re.compile(r"[`\s]*[·,]\s*[`\s]*§\s*(?P<num>[0-9]+(?:\.[0-9]+)*)\b")
#: ``UIFLOW §2-4`` · ``UIFLOW 2-10`` — 화면 참조. 하이픈으로 잇는다.
#: ``§`` 유무가 섞여 있어 둘 다 받는다(표기 통일은 별건).
_SCREEN_REF = re.compile(
    r"\b(?P<doc>" + "|".join(TARGETS) + r")(?:\.md)?[ `]{0,3}§?\s*(?P<num>[0-9]+-[0-9]+)\b"
)

#: ``## 📊 2. 계층별 상세 화면`` · ``### 2.2 화면 ↔ 계층 매핑`` — 절 헤딩.
_SECTION_HEAD = re.compile(r"^#{2,4}\s+(?:[^0-9\s]+\s+)?(?P<num>[0-9]+(?:\.[0-9]+)*)[.\s]")
#: 화면 정의 자리 세 가지 — ``### 2-4.`` 헤딩 · ``| **0-1** |`` 표 · ``*   **1-1.`` 목록.
_SCREEN_DEFS = (
    re.compile(r"^#{2,4}\s+(?P<num>[0-9]+-[0-9]+)\."),
    re.compile(r"^\|\s*\*\*(?P<num>[0-9]+(?:-[0-9]+)?)\*\*\s*\|"),
    re.compile(r"^\*\s+\*\*(?P<num>[0-9]+-[0-9]+)\."),
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sections(doc: str) -> set[str]:
    """대상 문서가 실제로 가진 절 번호."""
    found = set()
    for line in _text(_ROOT / TARGETS[doc]).splitlines():
        matched = _SECTION_HEAD.match(line)
        if matched:
            found.add(matched.group("num"))
    return found


def screens(doc: str) -> set[str]:
    """대상 문서가 실제로 정의한 화면 번호."""
    found = set()
    for line in _text(_ROOT / TARGETS[doc]).splitlines():
        for pattern in _SCREEN_DEFS:
            matched = pattern.match(line)
            if matched:
                found.add(matched.group("num"))
    return found


#: 화면 번호 체계를 가진 문서. 위 「무엇을 검사하지 않는가」 참조.
SCREEN_DOCS = ("UIFLOW",)


def _continued(line: str, start: int) -> list[str]:
    """``·§3`` 처럼 문서명 없이 이어 붙은 절 번호. 끊길 때까지 따라간다."""
    found = []
    position = start
    while True:
        # `re`에 `\G`가 없어 `match(line, pos)`로 시작 위치를 직접 고정한다.
        matched = _CONTINUATION.match(line, position)
        if matched is None:
            return found
        found.append(matched.group("num"))
        position = matched.end()


def _scan(pattern: re.Pattern[str], *, follow: bool = False) -> list[tuple[str, int, str, str]]:
    """``(파일, 행, 대상문서, 번호)``. 대상 문서가 자기 자신을 가리키는 것은 뺀다."""
    hits = []
    for path in [*_MD, *_SRC]:
        name = path.relative_to(_ROOT).as_posix()
        for number, line in enumerate(_text(path).splitlines(), 1):
            for matched in pattern.finditer(line):
                doc = matched.group("doc")
                if path.name == TARGETS[doc]:
                    continue
                hits.append((name, number, doc, matched.group("num")))
                if follow:
                    hits += [(name, number, doc, num) for num in _continued(line, matched.end())]
    return hits


def test_스캔_대상을_읽을_수_있다() -> None:
    """추출기가 깨지면 아래 검사들이 조용히 통과한다 — 그 상태를 먼저 막는다."""
    assert len(_MD) >= 7, f"정본 마크다운을 찾지 못했습니다: {[p.name for p in _MD]}"
    assert _SRC, "frontend/src에서 .ts/.tsx를 찾지 못했습니다."
    assert _scan(_SECTION_REF), "절 참조를 하나도 찾지 못했습니다 — 표기가 바뀌었는지 확인하세요."
    # 이어 쓴 참조 추적이 죽으면 `#583`이 놓친 것과 같은 형태를 다시 놓친다.
    assert _continued("`UIFLOW §2`·`§3` 참조", len("`UIFLOW §2")) == ["3"], (
        "이어 쓴 절 참조(`·§N`) 추적이 깨졌습니다."
    )

    # UIFLOW는 최상위 절 0·1·2와 그 하위 절을 가진다.
    assert {"0", "1", "2"} <= sections("UIFLOW"), (
        f"UIFLOW 절 추출이 깨졌습니다: {sorted(sections('UIFLOW'))}"
    )
    # 화면은 0 · 0-1~0-4 · 1-1~1-3 · 2-1~2-11로 19개다.
    assert len(screens("UIFLOW")) >= 15, (
        f"UIFLOW 화면 추출이 깨졌습니다: {sorted(screens('UIFLOW'))}"
    )


def test_절_참조가_전부_실재한다() -> None:
    """없는 절을 가리키면 따라간 사람이 막힌다 — `#485` ④⑤가 그렇게 멈춰 있었다."""
    broken = [
        f"{name}:{number}  {doc} §{num}"
        for name, number, doc, num in _scan(_SECTION_REF, follow=True)
        if num not in sections(doc)
    ]

    assert not broken, (
        f"실재하지 않는 절을 가리키는 참조 {len(broken)}건:\n  " + "\n  ".join(broken) + "\n"
        "→ 참조를 현행 절 번호로 고치거나, 대상 문서에 그 절을 신설하거나, "
        "참조를 지우세요. 셋 중 무엇이 맞는지는 소관(`AGENTS §3.2`)이 정합니다 (#583)."
    )


def test_화면_참조가_전부_실재한다() -> None:
    """`UIFLOW §9-3`처럼 화면 번호 자리에 없는 번호를 적는 것을 막는다."""
    broken = [
        f"{name}:{number}  {doc} {num}"
        for name, number, doc, num in _scan(_SCREEN_REF)
        if doc in SCREEN_DOCS and num not in screens(doc)
    ]

    assert not broken, (
        f"실재하지 않는 화면을 가리키는 참조 {len(broken)}건:\n  " + "\n  ".join(broken) + "\n"
        "→ 화면 번호는 재번호하지 않는 것이 원칙입니다(`UIFLOW §2`). "
        "번호가 맞는지 대상 문서에서 확인하세요 (#583)."
    )
