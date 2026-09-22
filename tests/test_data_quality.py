"""데이터 점검 판정 단위 검증 (`PRD §17.4` · #513).

``calc/data_quality.py``의 판정만 본다. **무엇이 이상치인가**를 숫자로 정한 곳이라,
경계가 한쪽으로 밀리면 화면이 조용히 다른 선박을 지목한다.

기대값은 **cubic speed model을 손으로 풀어** 만든다(`PRD §11.4.1`):

    기준 속력 12kn · 기준 일일 연료 24t · 거리 2,880nm · 속력 12kn
    → 항해 10일 · 속력 계수 1 → 기대 연료 240t
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cii_platform.calc.data_quality import (
    ANOMALY_FUEL_VS_MODEL,
    ANOMALY_SPEED_ABOVE_REFERENCE,
    ANOMALY_SPEED_MISMATCH,
    FUEL_MODEL_LOWER,
    FUEL_MODEL_UPPER,
    VoyageObservation,
    co2_grams,
    completeness_ratio,
    judge_anomaly,
)

#: 기대 연료가 240t이 되는 항차 (모듈 docstring).
BASE = VoyageObservation(
    distance_nm=Decimal("2880"),
    fuel_ton=Decimal("240"),
    recorded_speed_kn=Decimal("12"),
    sailing_hours=Decimal("240"),
    reference_speed_kn=Decimal("12"),
    reference_daily_foc_ton=Decimal("24"),
)


def _with(**changes) -> VoyageObservation:
    return VoyageObservation(**{**BASE.__dict__, **changes})


def test_a_voyage_that_matches_the_model_is_clean():
    result = judge_anomaly(BASE)

    assert result.codes == ()
    assert result.judged is True
    assert result.fuel_ratio == Decimal(1)
    assert result.implied_speed_kn == Decimal(12)


@pytest.mark.parametrize(
    ("fuel", "anomalous"),
    [
        # ⚠️ 경계는 **포함하지 않는다** — 0.6배·1.4배 정확히는 정상이다.
        ("144", False),  # 240 × 0.6
        ("143.9", True),
        ("336", False),  # 240 × 1.4
        ("336.1", True),
    ],
)
def test_fuel_ratio_bounds_are_exclusive(fuel, anomalous):
    """경계에서 판정이 뒤집히면 **같은 항차가 날마다 다른 결과**를 낼 수 있다(반올림 경계)."""
    result = judge_anomaly(_with(fuel_ton=Decimal(fuel)))

    assert (ANOMALY_FUEL_VS_MODEL in result.codes) is anomalous
    assert Decimal("0.6") == FUEL_MODEL_LOWER
    assert Decimal("1.4") == FUEL_MODEL_UPPER


def test_tons_entered_as_kilograms_are_caught():
    """가장 흔한 입력 실수 — 1,000배. 이 검사가 존재하는 이유다."""
    result = judge_anomaly(_with(fuel_ton=Decimal("240000")))

    assert ANOMALY_FUEL_VS_MODEL in result.codes


def test_the_model_uses_the_same_cubic_law_as_route_comparison():
    """⚠️ 속력이 떨어지면 기대 연료가 **세제곱으로** 준다 — 선형으로 두면 감속 항차가 이상치가 된다.

    10kn · 2,880nm → 12일 · (10/12)³ = 0.5787 → 24 × 0.5787 × 12 = 166.67t.
    실적 166.67t이면 비는 1이다.
    """
    result = judge_anomaly(
        _with(
            recorded_speed_kn=Decimal("10"),
            sailing_hours=Decimal("288"),
            fuel_ton=Decimal("166.6666666666666666666666667"),
        )
    )

    assert result.fuel_ratio == pytest.approx(Decimal(1), abs=Decimal("1e-20"))
    assert result.codes == ()


def test_implied_speed_far_above_reference_is_caught():
    """2,880nm를 120시간에 갔다 = 24kn = 기준 속력의 2배 — 시각 입력이 틀렸다."""
    result = judge_anomaly(_with(sailing_hours=Decimal("120"), recorded_speed_kn=None))

    assert ANOMALY_SPEED_ABOVE_REFERENCE in result.codes


def test_implied_speed_at_one_and_a_half_times_reference_is_not_an_anomaly():
    """18kn = 12 × 1.5 정확히 — 초과만 이상치다."""
    result = judge_anomaly(_with(sailing_hours=Decimal("160"), recorded_speed_kn=None))

    assert ANOMALY_SPEED_ABOVE_REFERENCE not in result.codes


@pytest.mark.parametrize(
    ("hours", "anomalous"),
    [
        ("240", False),  # 12kn — 기록과 같음
        # 기록 12kn의 30% = 3.6kn. 차이가 그 이상이면 이상치.
        ("360", True),  # 8.0kn — 차이 4.0kn
        ("300", False),  # 9.6kn
    ],
)
def test_recorded_and_implied_speed_must_agree(hours, anomalous):
    result = judge_anomaly(_with(sailing_hours=Decimal(hours)))

    assert (ANOMALY_SPEED_MISMATCH in result.codes) is anomalous


def test_without_specs_or_times_nothing_is_judged():
    """⚠️ **판정하지 못한 것은 0건이 아니다.** 제원도 시각도 없는 항차가 「깨끗」으로 나가면
    데이터가 가장 부실한 선박이 가장 믿을 만해 보인다."""
    result = judge_anomaly(
        _with(
            sailing_hours=None,
            reference_speed_kn=None,
            reference_daily_foc_ton=None,
        )
    )

    assert result.judged is False
    assert result.codes == ()


def test_a_substituted_fuel_is_not_judged_against_the_model():
    """대체된 연료는 ``None``으로 온다 — **계획이 이상한 것**을 실적 탓으로 돌리지 않는다."""
    result = judge_anomaly(_with(fuel_ton=None))

    assert result.fuel_ratio is None
    assert ANOMALY_FUEL_VS_MODEL not in result.codes
    # 속력 검사는 여전히 돈다.
    assert result.judged is True


def test_co2_is_fuel_times_cf_times_a_million():
    """`PRD §3.3.2` — 100t HFO(3.114) = 311,400,000 g."""
    assert co2_grams([(Decimal("100"), Decimal("3.114"))]) == Decimal("311400000")


def test_completeness_is_a_share_of_emissions_not_of_voyages():
    """큰 항차 1건(900g)이 실측이고 작은 항차 9건(100g)이 추정이면 90%다 — 건수로 세면 10%다."""
    assert completeness_ratio(Decimal("900"), Decimal("1000")) == Decimal("0.9")


def test_no_emissions_is_not_full_completeness():
    """배출이 없는 선박을 100%로 적으면 **데이터가 없는 선박이 가장 완결돼 보인다.**"""
    assert completeness_ratio(Decimal(0), Decimal(0)) is None


def test_publish_cii_and_ratio_truncate_toward_zero():
    """CII 영향값도 완전성 비율도 절사 (`#1349` → `#1600` · `TECH_SPEC §1.2.1`).

    ``delta``는 음수일 수 있다 — ``ROUND_DOWN``은 0 방향 절사라 부호에 대칭이고, 절사 뒤
    화면의 3자리 반올림은 원값 직접 반올림과 같다. 기대값은 수치 계약이며 표시 문구가 아니다.
    """
    from cii_platform.services.data_quality import _RATIO_DIGITS, _publish, _publish_cii

    assert _publish_cii(Decimal("4.9824996")) == "4.9824"
    assert _publish_cii(Decimal("-0.0004996")) == "-0.0004"
    assert _publish_cii(None) is None
    assert _publish(Decimal("0.98765"), _RATIO_DIGITS) == "0.9876"


def test_co2_ton_truncates():
    """`#1600` — 완결성의 CO₂ 톤(소수 2)은 표시(소수 1)보다 길어 **절사**한다."""
    from decimal import Decimal

    from cii_platform.services.data_quality import _publish_co2_ton

    assert _publish_co2_ton(Decimal("249125000")) == "249.12"
