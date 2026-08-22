"""연간 CII 시뮬레이터 검증 (PRD §12, #63).

DB 없이 돈다 — ``calc`` 계층이라 이미 읽어 온 값만 받는다.

이 엔진의 위험은 **재현성과 방향**에 있다.

* **재현성** — 동일 seed·동일 입력이면 등급별 확률이 bit-exact로 같아야 한다
  (``AC-F3-002``). 이게 깨지면 「이 seed로 다시 실행」 버튼이 거짓말이 된다.
* **방향** — 연료가 늘면 CII는 **나빠져야** 한다. 부호가 뒤집히면 화면이 정반대를
  말하고, 값이 그럴듯해서 드러나지 않는다.
* **경계** — ``PRD §12.8``이 지목한 예외 8종. 목표 E 거부·잔여 항차 상한 등.

케이스: UT-CII-008 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cii_platform.calc.annual_simulation import (
    DEFAULT_PROFILE,
    RATINGS,
    WARNING_MANY_VOYAGES,
    WARNING_NO_COMPLETED,
    WARNING_NO_REMAINING,
    WARNING_RUNS_CLAMPED,
    WARNING_SENSITIVITY_OAT,
    WARNING_SENSITIVITY_SPEED_SKIPPED,
    WARNING_TARGET_RATING_D,
    CompletedTotals,
    DistributionProfile,
    RemainingVoyage,
    TriangularBand,
    analyze_sensitivity,
    project_deterministic,
    rng_metadata,
    simulate_annual,
)
from cii_platform.calc.rating_engine import DVector

CF = 3.114
CAPACITY = Decimal("50000")
REQUIRED = Decimal("5.0")
D_VECTOR = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))
SEED = 12345

# 50,000 DWT 벌크선 — 5,000 nm · 400 t 확정, 3,000 nm · 250 t 짜리 잔여 4항차.
COMPLETED = CompletedTotals(co2_g=400 * CF * 1e6, distance_nm=5000.0)


def _voyage(**over) -> RemainingVoyage:
    fields = {
        "distance_nm": 3000.0,
        "fuel_ton": 250.0,
        "cf": CF,
        "speed_kn": 14.0,
        "reference_speed_kn": 14.0,
        "base_daily_foc_ton": 30.0,
    }
    fields.update(over)
    return RemainingVoyage(**fields)


REMAINING = [_voyage() for _ in range(4)]


def _simulate(**over):
    kwargs = {
        "completed": COMPLETED,
        "remaining": REMAINING,
        "transport_capacity": CAPACITY,
        "required_cii": REQUIRED,
        "d_vector": D_VECTOR,
        "target_rating": "C",
        "seed": SEED,
    }
    kwargs.update(over)
    return simulate_annual(**kwargs)


def _project(**over):
    kwargs = {
        "completed": COMPLETED,
        "remaining": REMAINING,
        "transport_capacity": CAPACITY,
        "required_cii": REQUIRED,
        "d_vector": D_VECTOR,
    }
    kwargs.update(over)
    return project_deterministic(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 결정론 예측 — PRD §12.3 · AC-F3-001
# ─────────────────────────────────────────────────────────────────────────────


def test_deterministic_projection_combines_completed_and_planned():
    """`(completed_M + planned_M) / (completed_W + planned_W)`."""
    result = _project()

    expected_co2 = Decimal(str(COMPLETED.co2_g)) + Decimal(str(4 * 250 * CF * 1e6))
    expected_distance = Decimal("5000") + Decimal("12000")
    expected = expected_co2 / (CAPACITY * expected_distance)
    assert float(result.attained_cii) == pytest.approx(float(expected), rel=1e-12)
    assert result.rating in RATINGS


def test_deterministic_uses_no_randomness():
    """난수를 쓰지 않으므로 몇 번을 불러도 같다 (`PRD §12.3`)."""
    assert _project().attained_cii == _project().attained_cii


def test_planned_only_when_no_completed_record():
    """`AC-F3-005` 인접 — 누적 실적이 없어도 잔여 계획만으로 예측한다."""
    result = _project(completed=CompletedTotals(co2_g=0.0, distance_nm=0.0))
    assert result.attained_cii > 0


def test_completed_only_when_no_remaining_plan():
    """`AC-F3-004` — 잔여 계획이 없으면 확정 실적만으로 연말 값을 낸다."""
    result = _project(remaining=[])
    assert result.planned_distance_nm == Decimal(0)
    # 확정분만 남으므로 그 자체가 연말 값이다.
    assert float(result.attained_cii) == pytest.approx(
        COMPLETED.co2_g / (float(CAPACITY) * COMPLETED.distance_nm), rel=1e-12
    )


def test_zero_total_distance_is_rejected():
    """`PRD §12.8` — `completed_W + planned_W = 0`이면 계산 중단."""
    with pytest.raises(ValueError, match="거리가 없어"):
        _project(completed=CompletedTotals(co2_g=0.0, distance_nm=0.0), remaining=[])


def test_non_positive_capacity_is_rejected():
    with pytest.raises(ValueError, match="transport_capacity"):
        _project(transport_capacity=Decimal(0))


# ─────────────────────────────────────────────────────────────────────────────
# 재현성 — PRD §12.4.3 · AC-F3-002
# ─────────────────────────────────────────────────────────────────────────────


def test_same_seed_reproduces_identical_probabilities():
    """**이 이슈의 완료 기준**이다 — 동일 seed → 동일 결과 (bit-exact).

    깨지면 「이 seed로 다시 실행」 버튼이 거짓말이 된다.
    """
    first = _simulate()
    second = _simulate()

    assert first.rating_probabilities == second.rating_probabilities
    assert first.target_success_probability == second.target_success_probability
    assert (first.p10, first.p50, first.p90) == (second.p10, second.p50, second.p90)


def test_different_seed_gives_a_different_sample():
    """같은 결과가 나오면 seed가 실제로 쓰이지 않는다는 뜻이다."""
    assert _simulate(seed=SEED).p50 != _simulate(seed=SEED + 1).p50


def test_rng_metadata_records_what_reproduction_needs():
    """`NEP 19` — Generator는 버전 간 bit-for-bit 호환을 보장하지 않는다.

    seed만으로는 부족하다. 값이 재현되지 않을 때 **환경이 달라서인지 코드가 바뀌어
    서인지** 가를 수 있어야 한다.
    """
    meta = _simulate().rng_metadata

    assert meta["seed"] == SEED
    assert meta["generator"] == "PCG64DXSM"
    for key in ("num_runs", "numpy_version", "python_version", "platform", "model_version"):
        assert meta[key], key


def test_rng_metadata_is_pure():
    """진단용이라 부작용이 없어야 한다 — 같은 인자면 같은 값."""
    assert rng_metadata(SEED, 5000) == rng_metadata(SEED, 5000)


# ─────────────────────────────────────────────────────────────────────────────
# 확률 집계 — PRD §12.4.2 · §12.5 · AC-F3-003
# ─────────────────────────────────────────────────────────────────────────────


def test_rating_probabilities_sum_to_one():
    total = sum(_simulate().rating_probabilities.values())
    # 소수 4자리 반올림(`§12.4.3`) 때문에 정확히 1이 아닐 수 있다.
    assert abs(total - Decimal(1)) <= Decimal("0.0005")


def test_target_probability_is_the_cumulative_sum():
    """`PRD §12.5` — 목표가 B면 **A와 B의 합**이다. 「목표 등급 이상」이 성공이다."""
    result = _simulate(target_rating="B")
    expected = result.rating_probabilities["A"] + result.rating_probabilities["B"]
    assert abs(result.target_success_probability - expected) <= Decimal("0.0002")


def test_target_c_includes_a_and_b():
    result = _simulate(target_rating="C")
    expected = sum(result.rating_probabilities[r] for r in ("A", "B", "C"))
    assert abs(result.target_success_probability - expected) <= Decimal("0.0002")


def test_probabilities_are_rounded_to_four_places():
    """`PRD §12.4.3` [ORACLE-C-1]."""
    for value in _simulate().rating_probabilities.values():
        assert -value.as_tuple().exponent <= 4


def test_percentiles_are_ordered():
    result = _simulate()
    assert result.p10 <= result.p50 <= result.p90


# ─────────────────────────────────────────────────────────────────────────────
# 방향 — 값이 그럴듯한데 부호만 틀리는 것이 가장 위험하다
# ─────────────────────────────────────────────────────────────────────────────


def test_more_fuel_makes_cii_worse():
    """CII는 **낮을수록 좋다.** 연료가 늘면 값이 커져야 한다."""
    heavy = [_voyage(fuel_ton=300.0) for _ in range(4)]
    assert _project(remaining=heavy).attained_cii > _project().attained_cii


def test_more_distance_at_same_intensity_does_not_worsen():
    """같은 강도로 더 가는 것은 CII를 악화시키지 않는다 — 분자·분모가 함께 는다."""
    longer = [_voyage(distance_nm=6000.0, fuel_ton=500.0) for _ in range(4)]
    base = _project().attained_cii
    # 확정분과의 혼합비만 달라지므로 큰 차이가 나면 안 된다.
    assert abs(_project(remaining=longer).attained_cii - base) < base * Decimal("0.1")


def test_worse_plan_lowers_the_target_probability():
    heavy = [_voyage(fuel_ton=320.0) for _ in range(4)]
    assert (
        _simulate(remaining=heavy).target_success_probability
        < _simulate().target_success_probability
    )


# ─────────────────────────────────────────────────────────────────────────────
# 예외 처리 — PRD §12.8
# ─────────────────────────────────────────────────────────────────────────────


def test_target_rating_e_is_rejected():
    """`PRD §12.8` — 「목표 등급 E는 의미 있는 분석이 아닙니다」."""
    with pytest.raises(ValueError, match="목표 등급 E"):
        _simulate(target_rating="E")


def test_target_rating_d_warns_but_proceeds():
    """거부가 아니라 경고다 — 위험 구간이지만 물어볼 수 있는 질문이다."""
    result = _simulate(target_rating="D")
    assert WARNING_TARGET_RATING_D in result.warnings
    assert result.target_success_probability >= 0


def test_unknown_target_rating_is_rejected():
    with pytest.raises(ValueError, match="목표 등급"):
        _simulate(target_rating="Z")


def test_too_many_remaining_voyages_is_refused():
    """`PRD §12.8` — 200건 초과는 거부(DoS 방지)."""
    with pytest.raises(ValueError, match="초과"):
        _simulate(remaining=[_voyage() for _ in range(201)])


def test_many_voyages_warns_below_the_limit():
    result = _simulate(remaining=[_voyage() for _ in range(150)], runs=1000)
    assert WARNING_MANY_VOYAGES in result.warnings


def test_runs_are_clamped_not_refused():
    """`PRD §12.8` — 「최대값으로 제한하고 안내」. 거부가 아니다."""
    high = _simulate(runs=999_999)
    assert high.runs == 10_000
    assert WARNING_RUNS_CLAMPED in high.warnings

    low = _simulate(runs=5)
    assert low.runs == 1_000
    assert WARNING_RUNS_CLAMPED in low.warnings


def test_no_completed_record_is_reported():
    result = _simulate(completed=CompletedTotals(co2_g=0.0, distance_nm=0.0))
    assert WARNING_NO_COMPLETED in result.warnings


def test_no_remaining_plan_is_reported():
    """`AC-F3-004` — 확정 실적만으로 산출하되 그 사실을 알린다."""
    result = _simulate(remaining=[])
    assert WARNING_NO_REMAINING in result.warnings
    # 잔여가 없으면 변동이 없어 분포가 한 점이다.
    assert result.p10 == result.p90


# ─────────────────────────────────────────────────────────────────────────────
# 삼각분포 가드 — PRD §12.4.1 [ORACLE]
# ─────────────────────────────────────────────────────────────────────────────


def test_bounds_are_reordered_when_the_profile_is_wrong():
    """`min ≤ mode ≤ max`를 위반한 파라미터가 들어와도 계산을 죽이지 않는다.

    시뮬레이션 하나가 파라미터 오타로 통째로 실패하는 것보다, 물리적으로 성립하는
    범위로 좁히는 편이 낫다.
    """
    broken = TriangularBand(min_factor=1.5, max_factor=0.5)  # 뒤집힘
    left, mode, right = broken.bounds(100.0)
    assert left <= mode <= right


def test_simulation_survives_a_broken_profile():
    broken = DistributionProfile(
        distance=TriangularBand(min_factor=1.5, max_factor=0.5),
        fuel=TriangularBand(min_factor=2.0, max_factor=0.1),
    )
    result = _simulate(profile=broken, runs=1000)
    assert sum(result.rating_probabilities.values()) > 0


def test_default_profile_matches_the_prd_table():
    """`PRD §12.4.1` 표 — 임의로 다시 쓰지 않는다."""
    assert (DEFAULT_PROFILE.distance.min_factor, DEFAULT_PROFILE.distance.max_factor) == (
        0.97,
        1.05,
    )
    assert (DEFAULT_PROFILE.fuel.min_factor, DEFAULT_PROFILE.fuel.max_factor) == (0.90, 1.15)


def test_per_voyage_sampling_not_a_single_multiplier():
    """항차마다 독립으로 뽑아야 **항차가 많을수록 합계 변동이 줄어든다.**

    합계에 배수를 한 번만 곱하면 항차 40건짜리와 1건짜리가 같은 변동폭을 갖는다.
    """
    one = _simulate(remaining=[_voyage(distance_nm=12000.0, fuel_ton=1000.0)], runs=5000)
    many = _simulate(
        remaining=[_voyage(distance_nm=300.0, fuel_ton=25.0) for _ in range(40)], runs=5000
    )

    assert (many.p90 - many.p10) < (one.p90 - one.p10)


# ─────────────────────────────────────────────────────────────────────────────
# 민감도 — PRD §12.6
# ─────────────────────────────────────────────────────────────────────────────


def _sens():
    return analyze_sensitivity(
        completed=COMPLETED,
        remaining=REMAINING,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
    )


def test_sensitivity_covers_the_prd_levers():
    entries, _ = _sens()
    variables = {e.variable for e in entries}
    assert {"fuel", "distance", "speed", "voyage_count"} <= variables


def test_sensitivity_fuel_direction():
    entries, _ = _sens()
    down = next(e for e in entries if e.variable == "fuel" and e.change == "-10%")
    up = next(e for e in entries if e.variable == "fuel" and e.change == "+10%")
    assert down.attained_cii < up.attained_cii


def test_sensitivity_speed_uses_the_cubic_model():
    """속도만 바꾸고 연료를 그대로 두면 CII가 변하지 않아 지렛대가 무의미해진다.

    `fuel ∝ speed² × distance`라 +1kn은 연료를 늘리고 CII를 악화시켜야 한다.
    """
    entries, _ = _sens()
    slower = next(e for e in entries if e.variable == "speed" and e.change == "-1kn")
    faster = next(e for e in entries if e.variable == "speed" and e.change == "+1kn")
    assert slower.attained_cii < faster.attained_cii


def test_sensitivity_skips_speed_when_specs_are_missing():
    """제원이 없으면 임의 기본값을 넣지 않는다 — 화면은 안 깨지고 값만 틀린다.

    ⚠️ **값이 같다는 단언만으로는 부족하다** (#630). 종전 이 테스트는 그것만 보고
    통과했고, 그래서 **건너뛴 사실을 아무도 알리지 않는 상태**가 그대로 남았다.
    속도 항목이 기준과 같게 나오면 사용자는 그것을 「감속해도 CII가 변하지 않는다」로
    읽는다 — **계산하지 못한 것과 효과가 0인 것을 구분할 수 없다.**

    그래서 경고를 함께 단언한다.
    """
    bare = [_voyage(reference_speed_kn=None, base_daily_foc_ton=None) for _ in range(4)]
    entries, warnings = analyze_sensitivity(
        completed=COMPLETED,
        remaining=bare,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
    )
    speeds = [e for e in entries if e.variable == "speed"]
    # 항목은 남되 값이 기준과 같다 — 바뀐 것이 없다.
    assert len({e.attained_cii for e in speeds}) == 1
    # 바뀐 것이 없다는 사실 자체를 알린다.
    assert WARNING_SENSITIVITY_SPEED_SKIPPED in warnings


def test_sensitivity_does_not_warn_when_specs_are_present():
    """제원이 다 있으면 경고를 붙이지 않는다 (#630).

    이 단언이 없으면 경고를 **항상** 붙이는 구현도 위 테스트를 통과한다. 그러면
    경고가 늘 떠 있어 아무 정보도 주지 않는다.
    """
    _, warnings = _sens()
    assert WARNING_SENSITIVITY_SPEED_SKIPPED not in warnings


def test_sensitivity_warns_when_only_some_voyages_lack_specs():
    """일부만 빠져도 알린다 (#630).

    전부 빠졌을 때만 알리면, 열 건 중 아홉 건이 건너뛴 경우가 **조용히 지나간다.**
    그때 속도 민감도는 기준과 다르게 나오므로 「계산됐다」로 읽히지만, 실제 효과의
    십분의 일만 반영된 값이다.
    """
    mixed = [_voyage(), _voyage(reference_speed_kn=None, base_daily_foc_ton=None)]
    _, warnings = analyze_sensitivity(
        completed=COMPLETED,
        remaining=mixed,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
    )
    assert WARNING_SENSITIVITY_SPEED_SKIPPED in warnings


def test_sensitivity_always_warns_about_interaction():
    """`PRD §12.8` — one-at-a-time이라 변수 간 상호작용은 포함되지 않는다."""
    _, warnings = _sens()
    assert WARNING_SENSITIVITY_OAT in warnings


def test_sensitivity_survives_a_lever_that_breaks_the_math():
    """항차 1건에서 -1이면 거리가 0이 된다 — 그 줄만 건너뛰고 나머지는 낸다."""
    entries, _ = analyze_sensitivity(
        completed=CompletedTotals(co2_g=0.0, distance_nm=0.0),
        remaining=[_voyage()],
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
    )
    assert entries  # 전부 죽지 않았다
    assert not [e for e in entries if e.variable == "voyage_count" and e.change == "-1"]
