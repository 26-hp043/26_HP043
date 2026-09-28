"""데이터 점검 사유 코드 정본 사슬 드리프트 가드 (#2019).

## 무엇이 문제였나

사유 코드는 서버 여러 곳에서 만들어지고, 화면이 한국어로 옮긴다.

```
calc/data_quality.py      ANOMALY_*       ┐
services/fleet_summary.py UNAVAILABLE_*   │
services/ytd_cii.py       SUBSTITUTION_*  ├─▶ ISSUE_CODES ─▶ API_SPEC §2.16 ◀── REASON_TEXT
services/data_quality.py  UNAVAILABLE_*   │   (서버 한 자리)   (정본)            (copy.ts)
                          IMPACT_*        ┘
```

화면은 모르는 코드를 **코드 그대로** 보인다(``copy.ts`` ``reasonText``). 빈칸보다 낫다는
판단은 맞지만, 그 폴백이 조용해서 서버가 코드를 하나 늘려도 **아무 검사도 실패하지
않았다.** 실제로 ``FUEL_NO_RECORD``(`#1095`)는 서버와 화면에는 있는데 정본 표에만 빠져 있었다.

## 무엇을 검사하나

1. 만드는 곳의 상수가 모두 :data:`ISSUE_CODES` · :data:`IMPACT_REASONS`에 있다 — 새 상수를
   만들고 모으는 자리를 빠뜨리면 걸린다
2. :data:`ISSUE_CODES`가 ``API_SPEC §2.16`` 심각도 표의 ``codes`` 열과 **심각도마다** 같다
3. :data:`IMPACT_REASONS`가 ``§2.16`` ``cii_impact_reason`` 행과 같다

화면 ↔ ``§2.16``은 ``frontend/src/features/data-quality/reasonCodes.sync.test.ts``가 본다.

## 리포트는 대상이 아니다

``reports/labels.py``의 ``table.get(code, code)``는 **이 코드들을 옮기지 않는다.** 리포트의
「제출 전 자체 점검」 절(``services/report.py``)은 대체 계산·진행 중·실적 확정 전 **건수**만
적고 사유 코드를 인쇄하지 않는다. 리포트가 옮기는 경고 코드는
``tests/test_warning_codes_sync.py``가 이미 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

from cii_platform.services.data_quality import IMPACT_REASONS, ISSUE_CODES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "cii_platform"

#: 코드를 만드는 곳 — 파일마다 **사유 코드 상수의 이름 모양**.
_PRODUCERS: dict[str, re.Pattern[str]] = {
    "calc/data_quality.py": re.compile(r'^ANOMALY_[A-Z0-9_]+\s*=\s*"([A-Z0-9_]+)"', re.M),
    "services/fleet_summary.py": re.compile(r'^UNAVAILABLE_[A-Z0-9_]+\s*=\s*"([A-Z0-9_]+)"', re.M),
    "services/ytd_cii.py": re.compile(r'^SUBSTITUTION_AXIS_[A-Z0-9_]+\s*=\s*"([A-Z0-9_]+)"', re.M),
    "services/data_quality.py": re.compile(
        r'^(?:UNAVAILABLE|IMPACT)_[A-Z0-9_]+\s*=\s*"([A-Z0-9_]+)"', re.M
    ),
}

#: ``| `SEVERITY` | 화면 | 판정 | codes |`` 행.
_SEVERITY_ROW = re.compile(r"^\|\s*`([A-Z_]+)`\s*\|[^|]*\|[^|]*\|([^|]*)\|\s*$")
#: 칸 안의 코드 — ``FUEL:<유종>``의 ``<유종>``처럼 열린 값은 앞머리만 남긴다.
_CODE = re.compile(r"`([A-Z][A-Z0-9_]+(?::[A-Z0-9_]+)?)(?::<[^>]+>)?`")


def _section_2_16() -> str:
    text = (ROOT / "API_SPEC.md").read_text(encoding="utf-8")
    start = text.index("### 2.16")
    return text[start : text.index("\n### ", start + 10)]


def _spec_issue_codes() -> dict[str, set[str]]:
    section = _section_2_16()
    table = section[section.index("**`issues[].severity`**") :]
    found: dict[str, set[str]] = {}
    for line in table.split("\n"):
        if match := _SEVERITY_ROW.match(line):
            found[match.group(1)] = set(_CODE.findall(match.group(2)))
    return found


def _spec_impact_reasons() -> set[str]:
    row = next(
        line
        for line in _section_2_16().split("\n")
        if line.startswith("| `issues[].cii_impact_reason` |")
    )
    return set(_CODE.findall(row.split("|")[2]))


def test_spec_table_is_readable() -> None:
    """파서가 표를 놓치면 아래 대조가 빈 집합끼리 통과한다 — 먼저 읽히는지 본다."""
    codes = _spec_issue_codes()
    assert set(codes) == set(ISSUE_CODES)
    assert all(codes.values())
    assert _spec_impact_reasons()


def test_every_producer_constant_is_collected() -> None:
    """만드는 곳의 사유 코드 상수가 한 자리(:data:`ISSUE_CODES`)에 다 모였다."""
    collected = {code.split(":")[0] for codes in ISSUE_CODES.values() for code in codes}
    collected |= set(IMPACT_REASONS)
    for relative, pattern in _PRODUCERS.items():
        produced = set(pattern.findall((SRC / relative).read_text(encoding="utf-8")))
        assert produced, f"{relative}에서 코드를 하나도 읽지 못했다 — 이름 모양이 바뀌었다"
        missing = produced - collected
        assert not missing, f"{relative}가 만드는 코드가 ISSUE_CODES에 없다: {sorted(missing)}"


def test_issue_codes_match_spec() -> None:
    """서버가 내는 코드 = ``API_SPEC §2.16`` 표 — 심각도마다."""
    spec = _spec_issue_codes()
    for severity, codes in ISSUE_CODES.items():
        assert set(codes) == spec[severity], (
            f"{severity}: 서버에만 {sorted(set(codes) - spec[severity])}"
            f" · 정본에만 {sorted(spec[severity] - set(codes))}"
        )


def test_impact_reasons_match_spec() -> None:
    assert set(IMPACT_REASONS) == _spec_impact_reasons()
