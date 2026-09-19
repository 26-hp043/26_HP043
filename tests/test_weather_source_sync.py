"""``weather_snapshot.source`` 값 정본 사슬 드리프트 가드 (#968).

## 무엇이 문제였나

어댑터(`weather/open_meteo.py`)는 두 엔드포인트가 모두 응답하면 한 행에 합쳐 저장하고
출처를 ``open_meteo_marine+forecast``로 적는다 — **정상 경로의 기본값**이다. 그런데
`TECH_SPEC §7.1`·`DB_SCHEMA §2.13`의 값 목록은 3값(`open_meteo_marine` ·
`open_meteo_forecast` · `sample`)뿐이어서, 저장되는 행의 대부분이 **정본에 없는 값**을
갖고 있었다(`#968`). 이 컬럼에는 집행 CHECK·트리거가 없어(`DB_SCHEMA §7.4`) DB가
알려 주지도 않았다.

## 무엇을 검사하나

```
코드 상수 SOURCE_*  ──⊆──▶  TECH_SPEC §7.1 값 표 (정본)  ──==──▶  DB_SCHEMA §2.13 source 행
```

1. 어댑터가 저장할 수 있는 모든 ``SOURCE_*`` 상수가 `TECH_SPEC §7.1` 표에 있다
2. `DB_SCHEMA §2.13` `source` 행이 그 표와 같은 집합을 적는다 (사본이 낡지 않는다)

**뜻(설명 열)까지는 대조하지 않는다.** 어느 쪽에만 있는 값이 없다는 것만 본다 —
그것이 `#968`을 만든 종류의 드리프트다. `test_warning_codes_sync.py`와 같은 틀이다.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "src" / "cii_platform" / "weather" / "open_meteo.py"

#: ``SOURCE_X = "value"`` 꼴 — 값은 소문자·밑줄·``+``만 쓴다.
_CONST = re.compile(r'^SOURCE_[A-Z_]+\s*=\s*"([a-z][a-z_+]*)"', re.MULTILINE)

#: `TECH_SPEC §7.1` 값 표의 첫 열 — ``| `value` | 뜻 |``
_ROW = re.compile(r"^\|\s*`([a-z][a-z_+]*)`\s*\|")

#: `DB_SCHEMA §2.13` ``source`` 행 안의 백틱 값.
_BACKTICKED = re.compile(r"`([a-z][a-z_+]*)`")


def _section(doc: str, start: str, end: str) -> str:
    text = (ROOT / doc).read_text(encoding="utf-8")
    i = text.index(start)
    return text[i : text.index(end, i)]


def _sources_in_adapter() -> set[str]:
    """어댑터가 실제로 저장할 수 있는 출처 값."""
    return set(_CONST.findall(ADAPTER.read_text(encoding="utf-8")))


def _tech_spec_sources() -> set[str]:
    section = _section("TECH_SPEC.md", "### 7.1", "### 7.2")
    return {m.group(1) for line in section.split("\n") if (m := _ROW.match(line))}


def _db_schema_sources() -> set[str]:
    section = _section("DB_SCHEMA.md", "### 2.13", "### 2.14")
    row = next(line for line in section.split("\n") if line.startswith("| `source` |"))
    # ``| `source` | VARCHAR(50) | NOT NULL | 설명 |`` — 값은 설명 열에만 있다.
    description = row.split("|")[4]
    return set(_BACKTICKED.findall(description))


def test_sections_are_parsed_at_all():
    """정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다 — 그것부터 막는다."""
    assert len(_sources_in_adapter()) >= 3
    assert len(_tech_spec_sources()) >= 3
    assert len(_db_schema_sources()) >= 3


def test_every_adapter_source_is_in_tech_spec():
    """어댑터가 저장하는 출처가 정본 표(`TECH_SPEC §7.1`)에 전부 있다.

    정상 경로 기본값(``open_meteo_marine+forecast``)이 빠져 있던 것이 `#968`이다.
    """
    missing = sorted(_sources_in_adapter() - _tech_spec_sources())
    assert not missing, f"TECH_SPEC §7.1 값 표에 없는 source: {missing}"


def test_db_schema_row_matches_the_canonical_table():
    """`DB_SCHEMA §2.13` `source` 행(사본)이 정본과 같은 집합을 적는다.

    이 컬럼은 DB가 강제하지 않으므로(`DB_SCHEMA §7.4`) 문서가 어긋나도 아무것도
    깨지지 않는다 — 그래서 여기서 본다.
    """
    tech = _tech_spec_sources()
    db = _db_schema_sources()
    assert not sorted(tech - db), f"정본에만 있다(DB_SCHEMA 행이 낡았다): {sorted(tech - db)}"
    assert not sorted(db - tech), f"DB_SCHEMA 행에만 있다: {sorted(db - tech)}"
