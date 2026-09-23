"""이슈 #445 · `README` 문서 구조 표와 정본 헤더 버전의 동기화 검증.

**막으려는 것은 문서가 낡는 것 자체가 아니라, 낡은 것이 보이지 않는 상태다.**

`AGENTS §4`가 «`README.md`는 각 문서의 최신 버전과 상태를 **항상** 반영한다»고
규정하는데, 2026-08-17 시점에 **7종 중 6종이 어긋나 있었다.**

    API_SPEC    README v1.7   실제 v1.16    9판
    UIFLOW      README v2.0   실제 v2.3     3판
    TECH_SPEC   README v1.4   실제 v1.6     2판
    DB_SCHEMA   README v1.12  실제 v1.14    2판
    PRD         README v4.2   실제 v4.3     1판
    TEST_PLAN   README v1.6   실제 v1.7     1판

README를 처음 여는 사람이 **9판 낡은 API 명세를 최신으로 믿는다.**

## 왜 사람이 아니라 CI가 지키는가

같은 규칙이 `AGENTS`에 이미 적혀 있는데도 6번 어긋났다. 규칙 자체가 그 사실을 알고
있다 — 「추가를 빠뜨려도 **CI가 잡아주지 않으므로** 같은 PR 안에서 처리한다」. 그
전제를 없앤다.

`test_testplan_sync`가 테스트 파일 인벤토리에 대해 같은 일을 하는 선례다.

## 무엇을 강제하고 무엇을 강제하지 않는가

강제하는 것은 **`README` ↔ 각 문서 헤더의 버전 일치** 하나다. `AGENTS §4`가 규정한
것이 그것이기 때문이다.

각 문서 헤더의 **상위 문서 참조**(예: `TECH_SPEC`의 「상위: `PRD.md` v4.0」)는 여기서
강제하지 않는다. 그 값은 「그 판본을 기준으로 내용을 맞췄다」는 뜻이라, 내용 대조 없이
숫자만 올리면 **하지 않은 확인을 했다고 적는 것**이 된다.

문서 버전을 올렸다면
--------------------
`README.md` 문서 구조 표의 해당 행에서 ``**v1.16**`` 처럼 굵게 적힌 버전을 함께
고친다. 표기는 굵게(``**v1.16**``)든 아니든(``v1.16``) 무방하다 — 이 검사는 행에서
**첫 번째로 나오는 버전 토큰**을 읽는다.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_README = _ROOT / "README.md"

#: 검사 대상 정본. `README` 문서 구조 표에 행이 있어야 하고 헤더에 버전이 있어야 한다.
CANONICAL_DOCS: tuple[str, ...] = (
    "PRD.md",
    "TECH_SPEC.md",
    "API_SPEC.md",
    "DB_SCHEMA.md",
    "TEST_PLAN.md",
    "AGENTS.md",
    "DESIGN_SYSTEM.md",
    "UIFLOW.md",
)

#: 헤더 표의 버전 행. ``| 버전 | v4.3 Implementation PRD |`` 처럼 뒤에 설명이 붙는
#: 경우가 있어 **버전 토큰만** 뽑는다.
_HEADER_VERSION = re.compile(r"^\|\s*버전\s*\|\s*(v[0-9]+(?:\.[0-9]+)*)", re.MULTILINE)

#: `README` 행에서 첫 버전 토큰. ``**v1.16**`` · ``v1.16`` 둘 다 받는다.
_README_VERSION = re.compile(r"\*{0,2}(v[0-9]+(?:\.[0-9]+)*)\*{0,2}")


def _header_version(doc: str) -> str:
    """정본 헤더가 선언한 버전."""
    text = (_ROOT / doc).read_text(encoding="utf-8")
    match = _HEADER_VERSION.search(text)
    assert match is not None, f"{doc} 헤더에 `| 버전 | vX.Y |` 행이 없다 (AGENTS §4)"
    return match.group(1)


def _readme_rows() -> dict[str, str]:
    """`README` 문서 구조 표에서 문서명 → 적혀 있는 버전."""
    rows: dict[str, str] = {}
    for line in _README.read_text(encoding="utf-8").splitlines():
        name = re.match(r"^\|\s*\[`([^`]+\.md)`\]", line)
        if name is None:
            continue
        version = _README_VERSION.search(line.split("|")[2])
        if version is not None:
            rows[name.group(1)] = version.group(1)
    return rows


def test_every_canonical_doc_is_listed_in_readme():
    """정본이 표에 아예 빠져 있으면 버전 대조 자체가 불가능하다."""
    listed = _readme_rows()
    missing = [doc for doc in CANONICAL_DOCS if doc not in listed]
    assert not missing, (
        f"README 문서 구조 표에 없다: {', '.join(missing)}. "
        "AGENTS §4 — 정본을 추가하면 README 표에 행을 함께 추가한다."
    )


def test_readme_reflects_the_current_document_versions():
    """**이 파일의 본체**다 — `AGENTS §4`의 「항상 반영한다」를 CI가 지킨다."""
    listed = _readme_rows()
    drift = [
        f"{doc}: README {listed[doc]} ≠ 실제 {_header_version(doc)}"
        for doc in CANONICAL_DOCS
        if doc in listed and listed[doc] != _header_version(doc)
    ]
    assert not drift, "README가 낡았다 (AGENTS §4):\n  " + "\n  ".join(drift)


def _readme_changelog_rows() -> list[str]:
    """`README` 「변경 이력」 절의 표 행."""
    text = _README.read_text(encoding="utf-8")
    start = text.index("## 변경 이력")
    return [line for line in text[start:].splitlines() if line.startswith("| 20")]


def test_readme_changelog_records_every_current_version():
    """표의 **현재 판본마다** README 변경 이력에 그 문서·판본을 적은 행이 있다 (#1779).

    위 검사는 표의 **최종 상태**만 본다. 그래서 문서 구조 표는 고치고 이 문서 자신의 변경
    이력 행은 싣지 않은 PR이 일곱 건 쌓였다(`DB_SCHEMA` v1.32~v1.34 · `DESIGN_SYSTEM` v2.23 ·
    v2.25~v2.27 · `UIFLOW` v2.17). 판본을 올리는 PR마다 이 검사가 그 판본의 행을 요구한다.
    """
    rows = _readme_changelog_rows()
    missing = []
    for doc in CANONICAL_DOCS:
        stem = doc.removesuffix(".md")
        version = _header_version(doc)
        # `v2.2`가 `v2.27`에 걸리지 않게 뒤에 숫자·점+숫자가 이어지지 않는 것만 센다.
        # 문서 이름과 판본이 **가까이**(40자 안) 붙어 있어야 그 문서의 행으로 센다 — 여러 문서를
        # 나열하는 행이 다른 문서의 판본으로 이 검사를 통과시키지 않게 한다.
        pattern = re.compile(
            rf"\b{re.escape(stem)}(?:\.md)?\b[^|]{{0,40}}?{re.escape(version)}(?![0-9]|\.[0-9])"
        )
        if not any(pattern.search(row) for row in rows):
            missing.append(f"{doc} {version}")
    assert not missing, (
        "README 변경 이력에 현재 판본의 행이 없다 (AGENTS §4 · §4.1): "
        + ", ".join(missing)
        + ". 문서 구조 표를 고친 PR이 이 README 변경 이력에도 자기 행을 싣는다."
    )


def test_readme_version_is_the_first_token_in_the_row():
    """검사 방식 자체의 회귀 방지.

    행 안에 이슈 번호·다른 문서 버전이 섞여 있어도 **그 문서의 버전**을 읽어야 한다.
    잘못 읽으면 이 검사가 조용히 통과하면서 아무것도 지키지 않게 된다.
    """
    sample = "| [`X.md`](./X.md) | 설명 (**v9.9**, 어쩌고 #123 + 저쩌고 v1.1) | ✅ |"
    assert _README_VERSION.search(sample.split("|")[2]).group(1) == "v9.9"
