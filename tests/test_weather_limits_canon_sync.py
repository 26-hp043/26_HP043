"""Hs↔BN 표와 적용 한계 ↔ 산식·구현 (`#1345`).

## 왜 필요한가

`TECH_SPEC §3.3.2`는 산식(`BN = round(3.5 × √Hs)`)을 **바로 위에 적어 두고도** 표는
어림값으로 채워져 있었다. 그래서 두 가지가 어긋났다.

* 「BN > 8 **(Hs > ~7m)**」 — 실제 상한은 **5.898 m**
* 「1.5 – 3.0 m → BN 4–5」 — 실제로는 **2.470 m부터 BN 6**

**운영자·시연자가 「7 m까지는 된다」고 믿고 6 m 파고를 넣으면 그 자리에서 422를 받는다.**

## 무엇을 단언하는가

표를 손으로 베끼지 않는다 — **산식을 돌려 얻은 경계**와 문서의 숫자를 맞춘다. 산식이
바뀌면 표가 틀렸다는 사실이 **여기서 먼저** 드러난다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cii_platform.calc.weather import MAX_BEAUFORT_NUMBER, beaufort_number

TECH_SPEC = Path(__file__).resolve().parents[1] / "TECH_SPEC.md"

#: 표를 훑는 범위와 눈금. 0.001 m는 문서가 적는 소수 셋째 자리와 같다.
_STEP = 0.001
_MAX_HS = 8.0


def _first_hs_for(beaufort: int) -> float:
    """그 BN이 처음 나오는 Hs — **산식에서** 얻는다."""
    for i in range(int(_MAX_HS / _STEP) + 1):
        hs = round(i * _STEP, 3)
        if beaufort_number(hs) == beaufort:
            return hs
    raise AssertionError(f"BN {beaufort}가 0~{_MAX_HS} m 안에 없다")


def _documented_rows() -> dict[int, float]:
    """`§3.3.2`의 「BN | Hs 하한」 표를 읽는다."""
    text = TECH_SPEC.read_text(encoding="utf-8")
    start = text.index("**위 식에서 그대로 뽑은 경계**")
    block = text[start : text.index("> **적용 한계**", start)]
    rows = re.findall(r"^\|\s*(\d+)\s*\|\s*\*{0,2}([\d.]+)\*{0,2}\s*\|", block, re.MULTILINE)
    return {int(bn): float(hs) for bn, hs in rows}


def test_the_table_was_read_at_all() -> None:
    """빈 dict이면 아래 검사가 **아무것도 대조하지 않고** 통과한다."""
    assert len(_documented_rows()) >= 10


@pytest.mark.parametrize("beaufort", range(11))
def test_each_row_matches_the_formula(beaufort: int) -> None:
    documented = _documented_rows()

    assert documented[beaufort] == _first_hs_for(beaufort)


def test_the_stated_limit_is_the_first_hs_outside_the_model() -> None:
    """「적용 한계」 문장의 숫자도 **산식에서** 나와야 한다.

    표만 맞추고 문장을 두면 **읽는 사람은 문장을 읽는다.**
    """
    text = TECH_SPEC.read_text(encoding="utf-8")
    limit = _first_hs_for(MAX_BEAUFORT_NUMBER + 1)

    assert f"{limit:.3f}" in text, f"적용 한계 {limit:.3f} m가 문서에 없다"

    # 종전 어림값이 **단정으로** 남아 있지 않은지 본다. ⚠️ 정정 각주가 옛 문장을
    # **인용하는 것은 정상**이므로 `#1345`를 함께 적은 줄은 제외한다 — `#1339`의
    # README 검사와 같은 규칙이다(인용부호 밖의 단정만 찾는다).
    stale = [
        line
        for line in text.splitlines()
        if ("Hs > ~7m" in line or "Hs > ~7 m" in line) and "#1345" not in line
    ]

    assert not stale, f"종전 어림값이 남아 있다: {stale}"


def test_the_limit_row_says_it_refuses_rather_than_falling_back() -> None:
    """`§3.6`이 `§12.1`·`API_SPEC §1.4`·구현과 같은 말을 하는지 (`#1345`).

    종전에는 그 행만 「경고 표시 후 NONE 모델 fallback」이라 적었다 — **기상 조회
    실패와 성질이 다르다**: 그쪽은 날씨를 모르는 것이고, 여기는 날씨를 알고 있으며
    그 값이 모델의 유효 범위 밖이다.
    """
    text = TECH_SPEC.read_text(encoding="utf-8")
    start = text.index("### 3.6 한계 및 주의사항")
    section = text[start : text.index("\n---", start)]
    row = next(line for line in section.splitlines() if line.startswith("| **BN > 8**"))

    assert "MODEL_BREAKDOWN_ERROR" in row
    assert "422" in row
    assert "fallback" not in row
