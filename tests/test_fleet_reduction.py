"""함대 감축 계획 계산 단위 검증 (`PRD §12.3.2` · #513).

기대값은 **손으로 푼다.** 12kn → 10% 감속 = 10.8kn:

    연료 비   (10.8/12)² = 0.81             → 100t → 81t · 절감 19t
    항해일    2,880nm ÷ (10.8 × 24) − 2,880 ÷ (12 × 24) = 11.1111… − 10 = 1.1111…일
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cii_platform.calc.annual_simulation import RemainingVoyage
from cii_platform.calc.fleet_reduction import (
    MAX_REDUCTION_PERCENT,
    TARGET_ALL_C_OR_BETTER,
    TARGET_NO_AT_RISK,
    PlannedLeg,
    apply_slowdown,
    meets_target,
    summarize_costs,
    target_rating_for,
)

VOYAGE = RemainingVoyage(
    distance_nm=2880.0,
    fuel_ton=100.0,
    cf=3.114,
    speed_kn=12.0,
    reference_speed_kn=12.0,
    base_daily_foc_ton=24.0,
)
LEG = PlannedLeg(
    distance_nm=Decimal("2880"), speed_kn=Decimal("12"), fuel_ton_by_type={"HFO": Decimal("100")}
)


def test_zero_reduction_changes_nothing():
    """⚠️ **0%면 조정 후가 조정 전과 같다** — `#513` 완료 기준(감속률 0%면 등급 그대로)."""
    result = apply_slowdown([VOYAGE], [LEG], Decimal(0))

    assert result.remaining == [VOYAGE]
    assert result.extra_days == 0
    assert result.fuel_saved_ton_by_type == {}


def test_ten_percent_follows_the_cubic_model():
    """연료는 **속력의 제곱**으로 준다(거리 고정) — 선형이면 절감이 절반으로 잡힌다."""
    result = apply_slowdown([VOYAGE], [LEG], Decimal(10))

    assert result.remaining[0].fuel_ton == pytest.approx(81.0)
    assert result.remaining[0].speed_kn == pytest.approx(10.8)
    assert result.fuel_saved_ton_by_type["HFO"] == pytest.approx(Decimal(19), abs=Decimal("1e-20"))


def test_extra_days_are_the_difference_in_sailing_time():
    result = apply_slowdown([VOYAGE], [LEG], Decimal(10))

    assert result.extra_days == pytest.approx(Decimal("1.111111111"), abs=Decimal("1e-9"))


def test_the_slowdown_matches_the_annual_speed_lever():
    """연간 등급 관리의 속력 민감도(`_shift_speed`)와 **같은 연료**를 낸다.

    두 벌이면 같은 선박에서 갈린다.

    12kn − 1.2kn(=10%)를 그쪽에 넣은 결과와 비교한다.
    """
    from cii_platform.calc.annual_simulation import _shift_speed

    ours = apply_slowdown([VOYAGE], [LEG], Decimal(10)).remaining[0].fuel_ton
    theirs = _shift_speed([VOYAGE], -1.2)[0].fuel_ton

    assert ours == pytest.approx(theirs)


def test_voyages_without_a_speed_model_are_skipped_and_counted():
    """제원이 없으면 감속을 적용하지 못한다 — **조용히 0%로 두지 않고** 센다."""
    bare = RemainingVoyage(distance_nm=2880.0, fuel_ton=100.0, cf=3.114, speed_kn=12.0)

    result = apply_slowdown([bare], [LEG], Decimal(10))

    assert result.skipped_voyages == 1
    assert result.remaining == [bare]
    assert result.extra_days == 0


def test_reduction_beyond_the_cap_is_rejected():
    """50%를 넘으면 운항할 수 없는 답(속력 1kn · 연료 거의 0)이 나온다."""
    with pytest.raises(ValueError):
        apply_slowdown([VOYAGE], [LEG], MAX_REDUCTION_PERCENT + 1)


def test_lists_that_do_not_line_up_are_rejected():
    """두 목록이 어긋나면 유종별 절감이 다른 항차의 연료로 계산된다 — 조용히 넘기지 않는다."""
    with pytest.raises(ValueError):
        apply_slowdown([VOYAGE, VOYAGE], [LEG], Decimal(10))


def test_costs_multiply_days_and_tons_by_their_prices():
    """1.5일 × 20,000 = 30,000 손실 · 19t × 600 = 11,400 절감 → 순손익 −18,600."""
    costs = summarize_costs(
        extra_days_by_vessel={"v1": Decimal("1.5")},
        fuel_saved_by_type={"HFO": Decimal(19)},
        charter_usd_per_day={"v1": Decimal(20000)},
        fuel_usd_per_ton={"HFO": Decimal(600)},
    )

    assert costs.charter_loss_usd == Decimal("30000.0")
    assert costs.fuel_saving_usd == Decimal(11400)
    assert costs.net_usd == Decimal("-18600.0")


def test_a_missing_price_empties_its_cell_instead_of_counting_zero():
    """⚠️ **단가가 없으면 0이 아니라 빈칸이다** — 0이면 「손익 영향 없음」으로 읽힌다."""
    costs = summarize_costs(
        extra_days_by_vessel={"v1": Decimal("1.5"), "v2": Decimal("2")},
        fuel_saved_by_type={"HFO": Decimal(19)},
        charter_usd_per_day={"v1": Decimal(20000)},
        fuel_usd_per_ton={},
    )

    assert costs.charter_loss_usd is None
    assert costs.fuel_saving_usd is None
    assert costs.net_usd is None
    assert costs.missing_charter_rates == ("v2",)
    assert costs.missing_fuel_prices == ("HFO",)


def test_a_vessel_that_was_not_slowed_needs_no_price():
    """추가 항해일이 0인 선박은 곱할 것이 없다 — 단가가 없다고 칸을 비우지 않는다."""
    costs = summarize_costs(
        extra_days_by_vessel={"v1": Decimal(0)},
        fuel_saved_by_type={},
        charter_usd_per_day={},
        fuel_usd_per_ton={},
    )

    assert costs.charter_loss_usd == 0
    assert costs.net_usd == 0


@pytest.mark.parametrize(
    ("target", "prior", "expected"),
    [
        (TARGET_ALL_C_OR_BETTER, [], "C"),
        (TARGET_NO_AT_RISK, [], "D"),
        (TARGET_NO_AT_RISK, ["C", "D"], "D"),
        # ⚠️ 직전 2년이 확정 D면 올해 D는 3년 연속(`PRD §3.3.7`) — 위험 선박이다.
        (TARGET_NO_AT_RISK, ["D", "D"], "C"),
    ],
)
def test_target_rating_follows_the_warning_banner_rule(target, prior, expected):
    assert target_rating_for(target, prior_ratings=prior) == expected


def test_meeting_a_target_means_that_grade_or_better():
    assert meets_target("B", "C") is True
    assert meets_target("C", "C") is True
    assert meets_target("D", "C") is False


def test_slowed_fuel_equals_route_comparison_at_the_new_speed():
    """⚠️ `#513` 완료 기준 — **`2-10`의 연료가 `2-2 항로 비교`와 같은 값을 낸다.**

    항로 비교는 `estimate_fuel_ton`(cubic model)으로 속력마다 연료를 낸다. 계획 연료가 그 모델로
    원래 속력에서 나온 값이면, 감속 후 연료는 **같은 모델을 새 속력에 넣은 값**과 같아야 한다.
    """
    from cii_platform.calc.fuel_estimator import estimate_fuel_ton

    planned = estimate_fuel_ton(
        distance_nm=Decimal("2880"),
        speed_kn=Decimal("12"),
        reference_speed_kn=Decimal("12"),
        base_daily_foc_ton=Decimal("24"),
    )
    voyage = RemainingVoyage(
        distance_nm=2880.0,
        fuel_ton=float(planned),
        cf=3.114,
        speed_kn=12.0,
        reference_speed_kn=12.0,
        base_daily_foc_ton=24.0,
    )
    leg = PlannedLeg(
        distance_nm=Decimal("2880"), speed_kn=Decimal("12"), fuel_ton_by_type={"HFO": planned}
    )

    slowed = apply_slowdown([voyage], [leg], Decimal(15)).remaining[0].fuel_ton
    route_comparison = estimate_fuel_ton(
        distance_nm=Decimal("2880"),
        speed_kn=Decimal("10.2"),
        reference_speed_kn=Decimal("12"),
        base_daily_foc_ton=Decimal("24"),
    )

    assert slowed == pytest.approx(float(route_comparison))


def test_publish_cii_truncates_and_quantities_round():
    """감속 전후 CII는 4자리 **절사**, 연료·일수·감속률은 반올림 (`#1349` · `TECH_SPEC §1.2.1`).

    기대값은 수치 계약이며 표시 문구가 아니다.
    """
    from cii_platform.services.fleet_reduction import _TON_DIGITS, _publish, _publish_cii

    assert _publish_cii(Decimal("4.9824996")) == "4.9824"
    assert _publish_cii(None) is None
    assert _publish(Decimal("80.005"), _TON_DIGITS) == "80.01"
    assert _publish(Decimal("12.35"), 1) == "12.4"


def test_measures_truncate_but_money_rounds():
    """`#1600` — 연료 톤·일수는 표시(소수 1 · 정수)보다 길게 보내므로 **절사**, 금액은 반올림.

    금액은 `DESIGN_SYSTEM §4.2`에 표시 자릿수 행이 없어 넓히지 않았다. 기대값은 수치 계약이다.
    """
    from decimal import Decimal

    from cii_platform.services.fleet_reduction import _publish, _publish_measure

    assert _publish_measure(Decimal("80.005"), 2) == "80.00"
    assert _publish_measure(Decimal("12.345"), 2) == "12.34"
    assert _publish_measure(None, 2) is None
    assert _publish(Decimal("80.005"), 2) == "80.01"
