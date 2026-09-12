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

import platform
import sys
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

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
    _round,
    analyze_sensitivity,
    project_deterministic,
    rng_metadata,
    simulate_annual,
)
from cii_platform.calc.hash import compute_parameter_hash
from cii_platform.calc.rating_engine import DVector
from cii_platform.services.annual_simulation import (
    PARAMETERS_SCHEMA_V1,
    build_parameters_used,
    parameters_schema_version,
)

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


# ── `TECH_SPEC §2.3.1` [ORACLE-S-1] — 계획값 0 이하 거부 (#967) ───────────────


def _voyage(**over) -> RemainingVoyage:
    kwargs = {
        "distance_nm": 3000.0,
        "fuel_ton": 250.0,
        "cf": CF,
        "speed_kn": None,
        "reference_speed_kn": None,
        "base_daily_foc_ton": None,
    }
    kwargs.update(over)
    return RemainingVoyage(**kwargs)


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"distance_nm": 0.0}, id="distance-0"),
        pytest.param({"fuel_ton": 0.0}, id="fuel-0"),
        pytest.param({"distance_nm": -1.0}, id="distance-negative"),
    ],
)
def test_deterministic_projection_rejects_non_positive_plan_values(bad):
    """`TECH_SPEC §2.3.1` — `plan_value <= 0`은 거부다. 조용히 0으로 고정하지 않는다.

    종전 구현은 폭 0 표본으로 받아 넘겼다(`#967`). 거리 0은 분모에 기여하지 않아 결과가
    틀리지는 않지만, 입력 누락이 어디에도 드러나지 않는다. 메시지에 **어느 항차**인지 싣는다.
    """
    remaining = [_voyage(), _voyage(**bad)]
    with pytest.raises(ValueError, match=r"잔여 항차 1의 계획값이 0 이하"):
        _project(remaining=remaining)


def test_monte_carlo_rejects_non_positive_plan_values_before_sampling():
    """결정론과 같은 가드가 Monte Carlo에도 걸린다 — 두 경로가 다른 입력을 받으면 안 된다."""
    with pytest.raises(ValueError, match=r"잔여 항차 0의 계획값이 0 이하"):
        _simulate(remaining=[_voyage(distance_nm=0.0)])


def test_degenerate_band_still_returns_the_plan_value():
    """폭 0 처리(`_sample_band`)는 남는다 — 뒤집힌 파라미터가 셋을 mode로 모으는 경우다.

    계획값 0 거부와 별개의 경로다: 계획값은 양수인데 `min_factor > max_factor`로 폭이 0이 된
    항차는 계획값 그대로가 표본이어야 한다(억지 폭은 근거 없는 변동이다).
    """
    profile = DistributionProfile(
        distance=TriangularBand(min_factor=1.5, mode_factor=1.0, max_factor=0.5),
        fuel=TriangularBand(min_factor=1.5, mode_factor=1.0, max_factor=0.5),
    )
    remaining = [_voyage()]
    result = _simulate(remaining=remaining, profile=profile)
    expected = _project(remaining=remaining)
    # p10·p90은 4자리로 반올림된 Decimal — 폭이 0이면 셋이 같고 결정론 값과 같다.
    assert (
        result.p10
        == result.p90
        == expected.attained_cii.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    )


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

    # 키와 형식은 `TECH_SPEC §2.2.1` 참조 구현 · `§2.2.2` 저장 스키마 그대로다 (#751).
    assert set(meta) == {
        "seed_entropy",
        "bit_generator",
        "numpy_version",
        "python_version",
        "platform",
    }, "rng_metadata 키 집합이 정본과 다르다 (TECH_SPEC §2.2.2)"

    # seed는 int가 아니라 **128-bit hex 문자열**이다 — JSON 정수는 2^53까지만
    # 안전하므로 `API_SPEC §6.1 [ORACLE-S-3 정정]`이 hex 표기를 규정한다.
    assert meta["seed_entropy"] == f"{SEED:#034x}"
    assert int(meta["seed_entropy"], 16) == SEED

    assert meta["bit_generator"] == "PCG64DXSM"
    for key in ("numpy_version", "python_version", "platform"):
        assert meta[key], key

    # `platform.platform()`이다. `sys.platform`("linux")은 커널·아키텍처가 빠지는데,
    # 재현 실패를 「환경이 달라서」로 가를 때 필요한 것이 그쪽이다.
    #
    # **값을 직접 대조한다.** `!= sys.platform`으로는 「옛 값이 아니다」만 알 뿐,
    # 실제로 올바른 값인지는 확인되지 않는다.
    assert meta["platform"] == platform.platform()
    assert meta["platform"] != sys.platform, (
        "`sys.platform`으로 되돌아갔다 — 커널·아키텍처가 빠진다 (#751)"
    )


def test_rng_metadata_is_pure():
    """진단용이라 부작용이 없어야 한다 — 같은 인자면 같은 값.

    ``runs``는 인자에서 뺐다 (#751) — `API_SPEC §6.1`이 ``monte_carlo.runs``를
    **형제 필드**로 두므로 안에도 담으면 같은 값이 응답에 두 번 실린다.
    """
    assert rng_metadata(SEED) == rng_metadata(SEED)


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
    """`PRD §12.4.3` [ORACLE-C-1] — 자릿수가 **정확히** 4다 (`#757`).

    종전에는 ``<= 4``였다. ``round()``가 후행 0을 버려 ``0.0``·``1.0``이 나가도
    통과했다 — `API_SPEC §1.7`이 「4 유효숫자」를 적고 `§6.1` 예시가 `0.0200`을
    드는 것과 다르다.
    """
    for value in _simulate().rating_probabilities.values():
        assert -value.as_tuple().exponent == 4, f"자릿수가 4로 고정되지 않았다: {value}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.00005, "0.0001"),
        (0.12345, "0.1235"),
        # 아래 셋이 은행가 반올림과 갈리는 지점이다 — `round()`는 각각
        # 0.5678 · 0.0001 · 2.0을 낸다.
        (0.56785, "0.5679"),
        (0.00015, "0.0002"),
        (2.00005, "2.0001"),
        # 후행 0 고정 — `round()`는 "0.0"·"1.0"을 낸다.
        (0.0, "0.0000"),
        (1.0, "1.0000"),
    ],
)
def test_round_matches_the_canonical_rounding(raw, expected):
    """`TECH_SPEC §2.4` — Monte Carlo 집계는 **소수 4자리 ROUND_HALF_UP**이다 (`#757`).

    자릿수는 `PRD §12.4.3`이, **반올림 모드는 `TECH_SPEC §2.4`가** 정한다. 종전
    구현은 ``round()``(은행가 반올림)를 써서 정본과 다른 값을 냈다 — 자릿수만 보고
    모드를 놓친 형태다.

    **경계 입력을 값으로 고정한다.** 「4자리다」만 보면 모드가 무엇이든 통과한다.
    """
    assert str(_round(raw)) == expected


def test_round_agrees_with_the_spec_reference_implementation():
    """정본 `§2.4`의 참조 구현과 **같은 값**을 낸다 (`#757`).

    위 검사는 손으로 적은 기대값을 본다. 여기서는 정본에 실린 식을 그대로 옮겨
    돌려 대조한다 — 기대값을 잘못 적었을 때 두 검사가 함께 틀리지 않는다.
    """

    def round_probability(p: float) -> Decimal:
        # `TECH_SPEC §2.4` 참조 구현 그대로.
        return Decimal(str(p)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    for raw in (0.00005, 0.12345, 0.56785, 0.00015, 2.00005, 0.0, 1.0, 0.3333, 0.66665):
        assert _round(raw) == round_probability(raw), raw


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


def _distance_rows(completed):
    entries, _ = analyze_sensitivity(
        completed=completed,
        remaining=REMAINING,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
    )
    down = next(e for e in entries if e.variable == "distance" and e.change == "-5%")
    up = next(e for e in entries if e.variable == "distance" and e.change == "+5%")
    return down.attained_cii, up.attained_cii


def test_distance_lever_moves_fuel_with_distance():
    """거리 ±5%는 **연료를 같은 비율로 함께** 움직인다 (`PRD §12.6` 각주 · #756).

    거리만 늘리면 「같은 연료로 더 갔다」가 되어 CII가 좋아지는 쪽으로만 틀린다. 함께
    움직이면 잔여분만 있을 때 **정확히 같다.**
    거리만 움직이도록 바뀌면 두 값이 약 10% 벌어져 여기서 실패한다.
    """
    down, up = _distance_rows(CompletedTotals(co2_g=0.0, distance_nm=0.0))
    assert abs(down - up) < Decimal("1e-9")


def _completed_at(intensity_ratio: float, distance_nm: float) -> CompletedTotals:
    """잔여분과 강도비가 ``intensity_ratio``인 확정 실적."""
    remaining_intensity = (4 * 250.0 * CF * 1e6) / (4 * 3000.0)
    return CompletedTotals(
        co2_g=remaining_intensity * intensity_ratio * distance_nm, distance_nm=distance_nm
    )


@pytest.mark.parametrize("completed_distance", [0.0, 1000.0, 5000.0, 200_000.0])
def test_distance_lever_is_exactly_zero_when_intensities_match(completed_distance):
    """⚠️ 강도가 같으면 **혼합비와 무관하게 정확히 0**이다 (#756 · 2026-09-13 정정).

    종전 이 자리의 검사는 「**섞인 비율**만큼만 움직인다」를 단언했는데 **메커니즘이
    틀렸다.** 결정하는 것은 혼합비가 아니라 **두 구간의 배출 강도 차이**다.

    대수적으로도 그렇다 — ``C/Cd = R/Rd = k``이면

    .. code-block:: text

        CII(f) = (C + f·R) / (cap·(Cd + f·Rd)) = k·(Cd + f·Rd) / (cap·(Cd + f·Rd)) = k/cap

    로 ``f``가 약분된다. 확정 거리를 0에서 200,000 nm까지 바꿔도 결과가 같아야 한다.

    **이 구분이 화면 문구를 정한다.** 「거의 변하지 않습니다」는 조건부 사실인데 종전
    문구가 무조건으로 적혀 있었고, 실적이 계획에서 벌어져 이 행이 움직이는 날 화면이
    사실과 다른 말을 하게 된다.
    """
    down, up = _distance_rows(_completed_at(1.0, completed_distance))
    assert abs(down - up) < Decimal("1e-9")


def test_distance_lever_moves_when_intensities_diverge():
    """강도가 벌어지면 **움직인다** — 그리고 그 방향이 뜻을 갖는다 (#756).

    잔여 계획이 확정 실적보다 **더 더럽게**(강도비 < 1 → 확정이 더 깨끗) 돌면, 거리를
    늘릴수록 연말 CII가 나빠진다. 「거리 행은 언제나 무의미하다」가 아니라는 것이
    여기서 고정된다.
    """
    down, up = _distance_rows(_completed_at(0.7, 5000.0))
    assert down != up
    # 잔여가 상대적으로 더 더러우므로 거리를 늘리면(+5%) 값이 커진다.
    assert up > down


#: `PRD §12.6` 표의 변수 ↔ 구현 지렛대 이름.
#:
#: ⚠️ **`연료 CF`는 구현이 없다** (`#756` ⑴). 「어느 연료를 대체 후보로 고를지」가
#: 정본에 없어 값을 지어낼 수 없다 — 판정 대기다. 목록에 **사유와 함께** 적어 두고,
#: 아래 검사가 목록과 정확히 대조한다: 새 공백이 생겨도, 채워진 뒤 목록을 안 지워도
#: 실패한다(`#834`·`#594`·`#591`과 같은 방식).
_PRD_LEVERS: dict[str, str | None] = {
    "잔여 항차 평균 속도": "speed",
    "잔여 항차 연료 사용량": "fuel",
    "잔여 항차 거리": "distance",
    "연료 CF": None,  # 미구현 — 대체 연료 선택 근거가 정본에 없다 (#756 ⑴)
    "잔여 항차 1개 취소/추가": "voyage_count",
}


def test_prd_sensitivity_table_matches_the_implemented_levers():
    """`PRD §12.6` 다섯 변수와 실제 지렛대가 **일대일로 대응**한다 (#756).

    정본이 든 변수와 구현이 도는 지렛대가 갈리면 **표의 한 행이 영영 비고**, 그
    사실이 화면에서는 「효과 없음」과 구분되지 않는다 — `#630`(속도)·`#756`(거리)이
    둘 다 그 모양이었다.

    ⚠️ 아직 **하나가 비어 있다**(`연료 CF`). 비었다는 사실을 :data:`_PRD_LEVERS`에
    사유와 함께 적고 목록과 대조한다 — 구현되는 날 이 검사가 깨져 목록을 지우게
    한다. **낡은 목록은 거짓말이다.**
    """
    from pathlib import Path

    prd = (Path(__file__).resolve().parents[1] / "PRD.md").read_text(encoding="utf-8")
    # 정본 표에 다섯 변수가 그대로 있는지부터 본다 — 표가 바뀌면 이 대응도 낡는다.
    for label in _PRD_LEVERS:
        assert f"| {label} |" in prd, label

    entries, _ = _sens()
    implemented = {e.variable for e in entries}
    expected = {name for name in _PRD_LEVERS.values() if name is not None}

    assert implemented == expected, (
        f"구현 {sorted(implemented)} ≠ 정본 대응 {sorted(expected)} — "
        "새 지렛대면 `_PRD_LEVERS`에 넣고, 미구현이 채워졌으면 `None`을 지울 것"
    )


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


# ─── parameters_used 스키마 버전 (#816) ──────────────────────────────────────
#
# **왜 동결이 필요한가.** `reproduce`는 저장된 해시를 두고 **지금 코드로**
# `parameters_used`를 다시 만들어 비교한다(`services/annual_simulation.py`).
# 빌더 출력이 한 글자만 바뀌어도 과거 실행 전부가 `ParameterError`(409)를 받는데,
# 실제로 바뀐 것은 규정이 아니라 우리 코드다. 사용자에게는 「규정 파라미터가
# 변경되어 재현할 수 없습니다」라는 **거짓 메시지**가 나간다.
#
# `calculation_run`은 `calc_run_guard()`(마이그레이션 024)가 UPDATE를 막아 저장된
# 해시를 소급해 고칠 수도 없다. 그래서 v1 형식을 동결하고 여기서 지킨다.


def _v1_kwargs() -> dict:
    """v1 빌더 재료. ORM 행 대신 같은 속성을 가진 객체를 쓴다."""
    return {
        "regulation": SimpleNamespace(year=2026, z_factor_percent=Decimal("11.0000")),
        "reference_line": SimpleNamespace(
            ship_type="BULK_CARRIER",
            capacity_rule="DWT",
            a_decimal=Decimal("4745.000000"),
            c=Decimal("0.622000"),
            source_ref="MEPC.353(78)",
        ),
        "rating_boundary": SimpleNamespace(
            ship_type="BULK_CARRIER",
            d1=Decimal("0.8600"),
            d2=Decimal("0.9400"),
            d3=Decimal("1.0600"),
            d4=Decimal("1.1800"),
        ),
        "profile_name": "DEFAULT",
        "profile_rows": [],
    }


def test_missing_version_field_is_v1():
    """버전 필드가 없는 저장 행은 v1로 판정한다 — `#816` 이전 행이 전부 그렇다."""
    assert parameters_schema_version(None) == PARAMETERS_SCHEMA_V1
    assert parameters_schema_version({}) == PARAMETERS_SCHEMA_V1
    assert parameters_schema_version({"regulation_year": {"year": "2026"}}) == PARAMETERS_SCHEMA_V1


def test_explicit_version_is_read():
    """버전 필드가 있으면 그대로 읽는다 — **정수만** 받는다 (#816).

    문자열 ``"2"``를 받아 주던 종전 안은 버렸다. JSONB는 정수를 정수로 돌려주므로
    문자열이 온다는 것은 **저장 경로가 잘못됐다는 신호**이고, 흡수하면 그 신호가
    사라진다.
    """
    assert parameters_schema_version({"parameter_schema_version": 1}) == 1
    assert parameters_schema_version({"parameter_schema_version": 2}) == 2


def test_unknown_version_raises():
    """모르는 버전은 조용히 v1로 떨어뜨리지 않는다.

    떨어뜨리면 해시 불일치의 원인이 「버전이 다르다」인지 「값이 다르다」인지
    가려지지 않는다 — 가장 찾기 어려운 종류의 오보다.
    """
    with pytest.raises(ValueError, match="알 수 없는"):
        build_parameters_used(99, **_v1_kwargs())


def test_v1_block_set_is_frozen():
    """**v1의 최상위 블록 집합을 고정한다.**

    이 단언이 깨지면 과거 실행의 `parameter_hash`가 재현되지 않는다. 새 필드는
    v1이 아니라 **v2 빌더**에 넣어야 한다.

    지금 v1에 없는 것 — `fuel_types`(`#832` CF 적용 시점 판정 대기) ·
    `parameter_source_version`(기준선 하나의 출처만 담아 이름이 실제보다 넓다.
    `parameter_sources` 객체로 바꾸는 안과 함께 v2에서 정한다).
    """
    built = build_parameters_used(PARAMETERS_SCHEMA_V1, **_v1_kwargs())

    assert set(built) == {
        "regulation_year",
        "reference_line",
        "rating_boundary",
        "simulation_profile",
    }, "v1 블록 집합이 바뀌었다 — 과거 실행의 parameter_hash가 깨진다 (#816)"

    # `rating_boundary.ship_type`은 `TECH_SPEC §5.2.1`에 없으나 **선택된 경계 행의
    # 식별 근거**이고, 빼면 과거 해시가 깨진다. 정본 등재 대상이다 (#816).
    assert built["rating_boundary"]["ship_type"] == "BULK_CARRIER"


def test_v1_hash_is_stable_across_calls():
    """같은 재료로 두 번 만들면 해시가 같다 — 키 순서·직렬화가 흔들리지 않는다."""
    first = compute_parameter_hash(build_parameters_used(PARAMETERS_SCHEMA_V1, **_v1_kwargs()))
    second = compute_parameter_hash(build_parameters_used(PARAMETERS_SCHEMA_V1, **_v1_kwargs()))
    assert first == second


#: **운영 DB에 실제로 저장돼 있던 v1 행**이다 (2026-09-08 채취).
#:
#: 골든 표본을 쓰는 이유 — :func:`test_v1_hash_is_stable_across_calls`는 같은 새
#: 코드를 두 번 부르므로 **v1 출력이 실수로 바뀌어도 잡지 못한다.** 고정된 옛 해시와
#: 대조해야 동결이 실제로 지켜지는지 알 수 있다.
_V1_GOLDEN_STORED: dict = {
    "reference_line": {
        "c": "0.460000",
        "a_decimal": "2023.000000",
        "ship_type": "RO_RO_PASSENGER",
        "reference_capacity_rule": "GT",
    },
    "rating_boundary": {
        "d1": "0.7600",
        "d2": "0.9200",
        "d3": "1.1400",
        "d4": "1.3000",
        "ship_type": "RO_RO_PASSENGER",
    },
    "regulation_year": {"year": "2026", "z_factor_percent": "11.0000"},
    "simulation_profile": {
        "profile": "DEFAULT",
        "version": "2026.08",
        "parameters": [
            {
                "max": "1.0500",
                "min": "0.9700",
                "mode": "1.0000",
                "variable": "DISTANCE",
                "bound_type": "FACTOR",
            },
            {
                "max": "1.1500",
                "min": "0.9000",
                "mode": "1.0000",
                "variable": "FUEL",
                "bound_type": "FACTOR",
            },
            {
                "max": "1.0000",
                "min": "-1.0000",
                "mode": "0.0000",
                "variable": "SPEED",
                "bound_type": "DELTA",
            },
        ],
    },
}

#: 위 행에 저장돼 있던 ``parameter_hash``. **이 값이 바뀌면 과거 실행이 재현되지 않는다.**
_V1_GOLDEN_HASH = "sha256:315842dd0a4aaa1a20050e7bff5bca188306a851990238e8ba28d928afde8a3f"


def test_v1_reproduces_the_stored_golden_hash():
    """**운영에 저장된 v1 행의 해시를 지금 빌더가 그대로 낸다.**

    이 단언이 이 파일에서 가장 중요하다. 깨지면 과거 실행 전부가 재실행에서
    ``ParameterError``(409)를 받는다 — 규정이 아니라 우리 코드가 바뀐 것인데
    사용자에게는 「규정 파라미터가 변경되었다」가 나간다 (`#816`).

    새 필드는 v1이 아니라 **v2 빌더**에 넣어야 한다.
    """
    built = build_parameters_used(
        PARAMETERS_SCHEMA_V1,
        regulation=SimpleNamespace(year=2026, z_factor_percent=Decimal("11.0000")),
        reference_line=SimpleNamespace(
            ship_type="RO_RO_PASSENGER",
            capacity_rule="GT",
            a_decimal=Decimal("2023.000000"),
            c=Decimal("0.460000"),
            source_ref="MEPC.353(78)",
        ),
        rating_boundary=SimpleNamespace(
            ship_type="RO_RO_PASSENGER",
            d1=Decimal("0.7600"),
            d2=Decimal("0.9200"),
            d3=Decimal("1.1400"),
            d4=Decimal("1.3000"),
        ),
        profile_name="DEFAULT",
        profile_rows=[
            SimpleNamespace(
                version="2026.08",
                variable="DISTANCE",
                bound_type="FACTOR",
                min_value=Decimal("0.9700"),
                mode_value=Decimal("1.0000"),
                max_value=Decimal("1.0500"),
            ),
            SimpleNamespace(
                version="2026.08",
                variable="FUEL",
                bound_type="FACTOR",
                min_value=Decimal("0.9000"),
                mode_value=Decimal("1.0000"),
                max_value=Decimal("1.1500"),
            ),
            SimpleNamespace(
                version="2026.08",
                variable="SPEED",
                bound_type="DELTA",
                min_value=Decimal("-1.0000"),
                mode_value=Decimal("0.0000"),
                max_value=Decimal("1.0000"),
            ),
        ],
    )

    assert built == _V1_GOLDEN_STORED, "v1 빌더 출력이 저장된 형식과 다르다 (#816)"
    assert compute_parameter_hash(built) == _V1_GOLDEN_HASH, (
        "v1 해시가 바뀌었다 — 과거 실행 전부가 재실행에서 409를 받는다 (#816)"
    )


def test_stored_golden_row_is_judged_v1():
    """실제 저장 행에는 버전 필드가 없다 — v1으로 판정돼야 한다."""
    assert "parameter_schema_version" not in _V1_GOLDEN_STORED
    assert parameters_schema_version(_V1_GOLDEN_STORED) == PARAMETERS_SCHEMA_V1


@pytest.mark.parametrize("bad", [None, "abc", 1.5, True, [], {}])
def test_corrupted_version_field_is_rejected(bad):
    """버전 필드가 **있는데** 정수가 아니면 거부한다 (#816).

    v1으로 흡수하면 손상된 행이 「옛 형식」으로 오인되어, 해시가 맞지 않는 이유가
    「버전이 다르다」인지 「값이 손상됐다」인지 가려진다.

    ``True``를 함께 보는 이유 — 파이썬에서 ``isinstance(True, int)``는 참이라
    가드가 없으면 ``True``가 **버전 1로 읽힌다.**
    """
    with pytest.raises(ValueError, match="정수가 아닙니다"):
        parameters_schema_version({"parameter_schema_version": bad})
