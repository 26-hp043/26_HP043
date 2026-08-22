"""경고 코드 정본 사슬 드리프트 가드 (#641).

## 무엇이 문제였나

경고 코드는 세 곳에 적혀 있고, 각각이 앞의 것을 전사한다.

```
TECH_SPEC §12.3  ──전사──▶  API_SPEC §1.6  ──전사──▶  frontend WARNING_MESSAGE
   (정본)                      (인용)                      (인용)
```

그런데 기능③(연간 시뮬레이션)이 들어오면서 **아무도 위쪽을 갱신하지 않았다.**

- `TECH_SPEC §12.3` — 코드가 내는 17종 중 **11종 누락**
- `API_SPEC §1.6` — 7종 누락 (`#630`이 해소)
- 화면 `WARNING_MESSAGE` — `§1.6`을 전사한 것이라 같이 비어 **원문 코드가 그대로 노출**

게다가 `§1.6`에만 있고 `§12.3`에 없는 코드가 2종 생겨, `§1.6` 머리의
「`TECH_SPEC §12.3` 정의」라는 인용이 **성립하지 않는 상태**가 됐다.

## 무엇을 검사하나

`AGENTS §3.1`상 `TECH_SPEC`(3위)이 `API_SPEC`(4위)보다 상위이므로 **`§12.3`이 정본**이다.

1. 코드가 내는 모든 `WARNING_*` 상수가 `§12.3`에 있다
2. `§1.6`이 `§12.3`과 같은 코드 집합을 담는다 (전사 관계)

**문구까지는 대조하지 않는다.** 두 표의 메시지 열에 마크다운·괄호 주석이 섞여
있어 정확히 떼어내려면 파서가 필요하고, 그 파서가 깨지면 대조가 조용히
무의미해진다. 여기서는 **어느 쪽에만 있는 코드가 없다**는 것만 본다 — 그것이
`#630`·`#641`을 만든 종류의 드리프트다.

화면(`WARNING_MESSAGE`) ↔ `§1.6`은
``frontend/src/features/voyage-cii/warningMessage.sync.test.ts``가 검사한다.
이 파일과 그 파일이 사슬 전체를 덮는다.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "cii_platform"

#: ``WARNING_X = "CODE"`` 꼴에서 코드 문자열만 뽑는다.
_CONST = re.compile(r'WARNING_[A-Z0-9_]+\s*=\s*"([A-Z][A-Z0-9_]+)"')

#: 표 행의 첫 열 — ``| `CODE` | 조건 | 메시지 |``
_ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|")


def _codes_in_source() -> set[str]:
    """코드가 실제로 내보내는 경고 코드."""
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        found |= set(_CONST.findall(path.read_text(encoding="utf-8")))
    return found


def _codes_in_section(doc: str, start: str, end: str) -> set[str]:
    """문서의 한 절에서 표 첫 열의 코드를 뽑는다."""
    text = (ROOT / doc).read_text(encoding="utf-8")
    i = text.index(start)
    j = text.index(end, i)
    return {m.group(1) for line in text[i:j].split("\n") if (m := _ROW.match(line))}


def _tech_spec_codes() -> set[str]:
    return _codes_in_section("TECH_SPEC.md", "### 12.3", "## 13.")


def _api_spec_codes() -> set[str]:
    return _codes_in_section("API_SPEC.md", "### 1.6", "### 1.7")


def test_sections_are_parsed_at_all():
    """정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다 — 그것부터 막는다."""
    assert len(_tech_spec_codes()) >= 10
    assert len(_api_spec_codes()) >= 10
    assert len(_codes_in_source()) >= 10


def test_every_emitted_code_is_in_tech_spec():
    """코드가 내는 경고가 정본 표(`TECH_SPEC §12.3`)에 전부 있다.

    없으면 화면이 문구를 붙일 수 없어 **원문 코드가 그대로 사용자에게 나간다.**
    """
    missing = sorted(_codes_in_source() - _tech_spec_codes())
    assert not missing, f"TECH_SPEC §12.3에 없는 경고 코드: {missing}"


def test_api_spec_transcribes_tech_spec():
    """`API_SPEC §1.6`이 정본과 같은 집합을 담는다.

    `§1.6` 머리가 「`TECH_SPEC §12.3` 정의」라고 인용하므로, 어느 한쪽에만 있는
    코드가 있으면 그 인용이 거짓이 된다. 실제로 `§1.6`에만 있는 코드가 2종 생겨
    **하위 문서가 상위 문서보다 앞선 상태**가 됐던 것이 `#641`이다.
    """
    tech = _tech_spec_codes()
    api = _api_spec_codes()
    assert not sorted(tech - api), f"§12.3에만 있다: {sorted(tech - api)}"
    assert not sorted(api - tech), f"§1.6에만 있다: {sorted(api - tech)}"
