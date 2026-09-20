"""속도 분포 ↔ 표본추출 코드 (`#1346`).

## 왜 필요한가

`PRD §12.4.1`은 거리·연료·**속도** 셋을 나란히 삼각분포로 적었지만 엔진은
**거리·연료만** 뽑는다. 코드는 그 사실을 docstring에 적어 두고 「정본 정정이 필요한
지점이며, 임의로 식을 만들지 않았다」로 남겨 두었다 — 그 상태가 오래 갔다.

**`parameters_used`를 보는 사람은 속도 변동이 확률 분포에 들어갔다고 읽는다.**
`simulation_profile.parameters`에 `SPEED` 행이 실려 있고 `parameter_hash`에도
들어가기 때문이다. 「속도 불확실성을 반영했다」는 설명이 사실이 아니게 된다.

`#1346`은 **정본을 구현 쪽으로** 정리했다. `CII = M / (W · Dt)`에 속도가 없어
독립으로 뽑아도 결과가 바뀌지 않고, cubic model로 이으면 **독립 표본추출된 연료와
같은 변동을 두 번 센다**.

## 무엇을 단언하는가

문서 문구만 맞추면 **다음 사람이 코드를 고칠 때 문서가 조용히 낡는다.** 그래서
정본의 주장 셋을 **엔진을 돌려** 확인한다.

* 속도 폭을 바꿔도 결과가 **한 톨도** 바뀌지 않는다 (연료 폭은 바뀐다 — 대조군)
* 그런데도 `SPEED` 행은 `parameters_used`·`parameter_hash`에 **실린다**
* `§12.6` 민감도의 ±1kn은 **프로파일에서 오지 않는다**

케이스: UT-CII-008 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

import inspect
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from cii_platform.calc.annual_simulation import (
    DEFAULT_PROFILE,
    CompletedTotals,
    RemainingVoyage,
    TriangularBand,
    analyze_sensitivity,
    profile_from_rows,
    simulate_annual,
)
from cii_platform.calc.hash import compute_parameter_hash
from cii_platform.calc.rating_engine import DVector
from cii_platform.services.annual_simulation import (
    PARAMETERS_SCHEMA_V1,
    build_parameters_used,
)

ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "PRD.md"
TECH_SPEC = ROOT / "TECH_SPEC.md"

CF = 3.114
CAPACITY = Decimal("50000")
REQUIRED = Decimal("5.0")
D_VECTOR = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))
SEED = 12345

COMPLETED = CompletedTotals(co2_g=400 * CF * 1e6, distance_nm=5000.0)
REMAINING = [
    RemainingVoyage(
        distance_nm=3000.0,
        fuel_ton=250.0,
        cf=CF,
        speed_kn=14.0,
        reference_speed_kn=14.0,
        base_daily_foc_ton=30.0,
    )
    for _ in range(4)
]


def _simulate(profile):
    return simulate_annual(
        completed=COMPLETED,
        remaining=REMAINING,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
        target_rating="C",
        seed=SEED,
        profile=profile,
    )


def _fingerprint(outcome) -> tuple:
    """결과를 값으로 비교한다 — 분위수와 등급 확률 전부."""
    return (
        outcome.p10,
        outcome.p50,
        outcome.p90,
        outcome.mean,
        tuple(sorted(outcome.rating_probabilities.items())),
        outcome.target_success_probability,
    )


# --------------------------------------------------------------------------
# 1. 엔진이 실제로 속도를 쓰지 않는가
# --------------------------------------------------------------------------


def test_speed_width_does_not_move_the_result() -> None:
    """속도 폭을 10배로 늘려도 **한 톨도** 바뀌지 않는다 (`PRD §12.4.1` 각주)."""
    base = _fingerprint(_simulate(DEFAULT_PROFILE))
    wide = _fingerprint(_simulate(replace(DEFAULT_PROFILE, speed_delta_kn=10.0)))

    assert base == wide


def test_fuel_width_does_move_the_result() -> None:
    """대조군. 이게 없으면 위 검사는 **엔진이 죽어 있어도** 통과한다."""
    base = _fingerprint(_simulate(DEFAULT_PROFILE))
    wide = _fingerprint(
        _simulate(replace(DEFAULT_PROFILE, fuel=TriangularBand(min_factor=0.50, max_factor=1.50)))
    )

    assert base != wide


# --------------------------------------------------------------------------
# 2. 그런데도 SPEED 행은 기록·해시에 실린다
# --------------------------------------------------------------------------


def _speed_row(minimum: float, maximum: float):
    return SimpleNamespace(
        variable="SPEED",
        bound_type="DELTA",
        distribution="TRIANGULAR",
        min_value=Decimal(str(minimum)),
        mode_value=Decimal("0.0"),
        max_value=Decimal(str(maximum)),
        floor_value=Decimal("1.0"),
        version="2026.08",
    )


def _parameters_used(rows):
    return build_parameters_used(
        PARAMETERS_SCHEMA_V1,
        regulation=SimpleNamespace(year=2026, z_factor_percent=Decimal("11.0000")),
        reference_line=SimpleNamespace(
            ship_type="BULK_CARRIER",
            capacity_rule="DWT",
            a_decimal=Decimal("4745.000000"),
            c=Decimal("0.622000"),
            source_ref="MEPC.353(78)",
        ),
        rating_boundary=SimpleNamespace(
            ship_type="BULK_CARRIER",
            d1=Decimal("0.8600"),
            d2=Decimal("0.9400"),
            d3=Decimal("1.0600"),
            d4=Decimal("1.1800"),
        ),
        profile_name="DEFAULT",
        profile_rows=rows,
    )


def test_the_speed_row_is_still_carried_into_the_hash() -> None:
    """빼지 않는 이유 — 속도를 표본추출하게 되는 날 **옛 실행과 해시가 겹친다.**

    그러면 값이 다른데 「재현됐다」가 된다. 지금처럼 두면 값이 같은데 재현이
    막히는 **보수적 거부**에 그친다 — 두 오차의 방향이 다르다.
    """
    narrow = _parameters_used([_speed_row(-1.0, 1.0)])
    wide = _parameters_used([_speed_row(-2.0, 2.0)])

    speed_entries = [
        row for row in narrow["simulation_profile"]["parameters"] if row["variable"] == "SPEED"
    ]
    assert speed_entries, "SPEED 행이 parameters_used에서 사라졌다"
    assert compute_parameter_hash(narrow) != compute_parameter_hash(wide)


def test_the_speed_row_reaches_the_profile_but_not_the_bands() -> None:
    """`DELTA` 행은 :class:`TriangularBand`로 옮기지 않는다 — 배수가 아니다."""
    profile = profile_from_rows([_speed_row(-2.0, 2.0)])

    assert profile.speed_delta_kn == 2.0
    assert profile.distance == DEFAULT_PROFILE.distance
    assert profile.fuel == DEFAULT_PROFILE.fuel


# --------------------------------------------------------------------------
# 3. §12.6의 ±1kn은 프로파일에서 오지 않는다
# --------------------------------------------------------------------------


def test_sensitivity_cannot_read_the_profile_at_all() -> None:
    """**서명으로** 못 박는다 (`#1346`).

    종전 주석은 「민감도의 ±1kn이 이 값이다」라고 적었으나 사실이 아니었다.
    호출 모양을 정규식으로 보면 인자 순서가 바뀔 때 놓치므로 서명을 본다.
    """
    assert "profile" not in inspect.signature(analyze_sensitivity).parameters


def test_sensitivity_speed_lever_is_fixed_at_one_knot() -> None:
    """응답 키가 ``speed_minus_1kn``으로 고정이라(`API_SPEC §6.1`) 폭도 고정이다."""
    entries, _ = analyze_sensitivity(
        completed=COMPLETED,
        remaining=REMAINING,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
    )
    speed_changes = {e.change for e in entries if e.variable == "speed"}

    assert speed_changes == {"-1kn", "+1kn"}


# --------------------------------------------------------------------------
# 4. 정본이 같은 말을 하는가
# --------------------------------------------------------------------------


def test_prd_speed_row_says_it_is_not_sampled() -> None:
    text = PRD.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| 속도 | triangular"))

    assert "미표본" in row


def test_prd_pseudocode_no_longer_samples_speed() -> None:
    """의사코드가 표와 따로 논다 — 읽는 사람은 **의사코드를 구현한다.**"""
    text = PRD.read_text(encoding="utf-8")
    line = next(
        line for line in text.splitlines() if line.strip().startswith("sample each remaining")
    )

    assert "speed" not in line


def test_tech_spec_speed_row_says_it_is_not_sampled() -> None:
    text = TECH_SPEC.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| 속도 (kn) |"))

    assert "미표본" in row


def test_no_canon_still_claims_the_spec_is_unresolved() -> None:
    """코드가 남겼던 「정본 정정이 필요한 지점」이 실제로 사라졌는지 본다.

    ⚠️ 정정 각주가 옛 문구를 **인용하는 것은 정상**이므로 `#1346`을 적은 줄은
    제외한다 — `#1345`·`#1339`와 같은 규칙이다.
    """
    source = (ROOT / "src/cii_platform/calc/annual_simulation.py").read_text(encoding="utf-8")
    resolved = re.compile(
        r"정본 정정이 필요|테이블이 생기면|민감도 분석\(``§12\.6``\)의 ±1kn이 이 값"
    )
    stale = [line for line in source.splitlines() if resolved.search(line) and "#1346" not in line]

    assert not stale, f"해소된 문구가 남아 있다: {stale}"
