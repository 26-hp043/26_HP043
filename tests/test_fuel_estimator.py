"""cubic speed model 연료 추정 테스트 (#75).

TECH_SPEC §4.1 기본 수식, §4.2 가드 조건, §4.4 NONE 기본값, 그리고 이슈 #75의
완료 기준(cubic 8배 · 결정론 · weather_factor 기본값)을 검증한다.

`Decimal` 연산은 Layer 1 컨텍스트 안에서 수행되므로 정밀도는 `prec=50`으로
고정된다 (TECH_SPEC §1.2.1). 테스트 함수에도 `@layer1_context`를 붙여 같은 정밀도로
`expected`를 계산한다 — 기본 `prec=28`에서 계산하면 50자리 정본값과 22자리가 어긋난다.
"""

from decimal import Decimal

import pytest

from cii_platform.calc.fuel_estimator import (
    DEFAULT_WEATHER_FACTOR,
    estimate_fuel_ton,
)
from cii_platform.calc.precision import layer1_context


@layer1_context
def test_basic_estimation_matches_formula() -> None:
    """TECH_SPEC §4.1 공식을 충실하게 계산한다 (#75)."""
    fuel = estimate_fuel_ton(
        distance_nm=Decimal("1000"),
        speed_kn=Decimal("14"),
        reference_speed_kn=Decimal("14"),
        base_daily_foc_ton=Decimal("40"),
    )
    # Decimal 나눗셈은 prec=50에서 잘리므로 **연산 순서가 다르면 미세하게 어긋난다**
    # (결합법칙 비보장). expected를 구현과 같은 순서·값·정밀도로 계산한다.
    # weather_factor=None → DEFAULT_WEATHER_FACTOR=Decimal("1.0") 을 쓴다.
    speed_factor = (Decimal("14") / Decimal("14")) ** 3
    duration_days = Decimal("1000") / Decimal("14") / Decimal("24")
    expected = Decimal("40") * speed_factor * DEFAULT_WEATHER_FACTOR * duration_days
    assert fuel == expected


def test_cubic_speed_doubling_octuples_fuel_rate() -> None:
    """완료 기준 — speed 2배 → speed_factor 8배, duration 1/2 → fuel_ton 약 4배 (#75).

    Decimal 결합법칙 비보장으로 비율 비교(tolerance ``1e-30``)를 쓴다. 8배 × 1/2 = 4는
    대수학으로 정확하지만, 각 단계의 rounding이 쌓여 Layer 1 정밀도 안에서 흔들린다.
    """
    fuel_at_14 = estimate_fuel_ton(
        distance_nm=Decimal("1000"),
        speed_kn=Decimal("14"),
        reference_speed_kn=Decimal("14"),
        base_daily_foc_ton=Decimal("40"),
    )
    fuel_at_28 = estimate_fuel_ton(
        distance_nm=Decimal("1000"),
        speed_kn=Decimal("28"),
        reference_speed_kn=Decimal("14"),
        base_daily_foc_ton=Decimal("40"),
    )
    ratio = fuel_at_28 / fuel_at_14
    assert abs(ratio - Decimal("4")) < Decimal("1e-30")


def test_default_weather_factor_is_one_when_none() -> None:
    """TECH_SPEC §4.4 — weather_factor=None → DEFAULT_WEATHER_FACTOR(1.0) 적용 (#75)."""
    common = dict(
        distance_nm=Decimal("1000"),
        speed_kn=Decimal("14"),
        reference_speed_kn=Decimal("14"),
        base_daily_foc_ton=Decimal("40"),
    )
    fuel_none = estimate_fuel_ton(weather_factor=None, **common)
    fuel_explicit_one = estimate_fuel_ton(weather_factor=DEFAULT_WEATHER_FACTOR, **common)
    assert fuel_none == fuel_explicit_one


def test_weather_factor_scales_output_linearly() -> None:
    """weather_factor 1.5 → fuel_ton 1.5배 (§4.1 선형 항, tolerance 비교)."""
    common = dict(
        distance_nm=Decimal("1000"),
        speed_kn=Decimal("14"),
        reference_speed_kn=Decimal("14"),
        base_daily_foc_ton=Decimal("40"),
    )
    fuel_w1 = estimate_fuel_ton(weather_factor=Decimal("1.0"), **common)
    fuel_w15 = estimate_fuel_ton(weather_factor=Decimal("1.5"), **common)
    # 결합법칙 비보장 — 비율 비교(tolerance)로 검증.
    ratio = fuel_w15 / fuel_w1
    assert abs(ratio - Decimal("1.5")) < Decimal("1e-30")


def test_deterministic_output_for_same_input() -> None:
    """완료 기준 — 동일 입력 → 결정론적 동일 출력 (재현성 계약 §5.4 1항, #75)."""
    kwargs = dict(
        distance_nm=Decimal("1234"),
        speed_kn=Decimal("13.5"),
        reference_speed_kn=Decimal("14.0"),
        base_daily_foc_ton=Decimal("42.7"),
        weather_factor=Decimal("1.1"),
    )
    assert estimate_fuel_ton(**kwargs) == estimate_fuel_ton(**kwargs)


# --- 가드 조건 (TECH_SPEC §4.2) ------------------------------------------------------


def test_guard_rejects_speed_below_minimum() -> None:
    """VAL-009 — speed_kn < 1.0이면 ValueError."""
    with pytest.raises(ValueError, match="speed_kn"):
        estimate_fuel_ton(
            distance_nm=Decimal("1000"),
            speed_kn=Decimal("0.5"),
            reference_speed_kn=Decimal("14"),
            base_daily_foc_ton=Decimal("40"),
        )


def test_guard_allows_speed_exactly_one() -> None:
    """VAL-009 경계 — speed_kn == 1.0은 허용."""
    fuel = estimate_fuel_ton(
        distance_nm=Decimal("100"),
        speed_kn=Decimal("1.0"),
        reference_speed_kn=Decimal("14"),
        base_daily_foc_ton=Decimal("40"),
    )
    assert fuel > 0


def test_guard_rejects_non_positive_reference_speed() -> None:
    with pytest.raises(ValueError, match="reference_speed_kn"):
        estimate_fuel_ton(
            distance_nm=Decimal("1000"),
            speed_kn=Decimal("14"),
            reference_speed_kn=Decimal("0"),
            base_daily_foc_ton=Decimal("40"),
        )


def test_guard_rejects_non_positive_distance() -> None:
    """VAL-002 — distance_nm <= 0이면 ValueError."""
    with pytest.raises(ValueError, match="distance_nm"):
        estimate_fuel_ton(
            distance_nm=Decimal("0"),
            speed_kn=Decimal("14"),
            reference_speed_kn=Decimal("14"),
            base_daily_foc_ton=Decimal("40"),
        )


def test_guard_rejects_non_positive_base_daily_foc() -> None:
    with pytest.raises(ValueError, match="base_daily_foc_ton"):
        estimate_fuel_ton(
            distance_nm=Decimal("1000"),
            speed_kn=Decimal("14"),
            reference_speed_kn=Decimal("14"),
            base_daily_foc_ton=Decimal("0"),
        )


def test_guard_rejects_non_positive_weather_factor() -> None:
    with pytest.raises(ValueError, match="weather_factor"):
        estimate_fuel_ton(
            distance_nm=Decimal("1000"),
            speed_kn=Decimal("14"),
            reference_speed_kn=Decimal("14"),
            base_daily_foc_ton=Decimal("40"),
            weather_factor=Decimal("0"),
        )
