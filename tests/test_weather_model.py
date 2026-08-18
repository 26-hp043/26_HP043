"""기상 보정 모델 — 순수 계산 (TECH_SPEC §3 · §8, #61).

DB도 네트워크도 쓰지 않는다. **경험식이 정본과 같은 값을 내는지**와
**적용 범위 밖에서 멈추는지**를 본다.

## 두 모델의 실패 규칙이 다르다

`TOWNSIN_KWON_ALPHA`는 적용 범위 밖에서 **중단**하고(`§3.5`), `SIMPLE_RULE`은
입력을 **clamp**한다(`§8.2`). 성격이 다르기 때문이다 — 앞은 경험식이고 뒤는
데모 안정성용 fallback이라, fallback이 예외를 던지면 fallback이 아니다.

**한쪽 규칙이 다른 쪽으로 새는 것**이 이 파일이 막으려는 것이다.

케이스 (`TEST_PLAN §14.5`):
    UT-WX-001 · UT-WX-002 · UT-WX-003 · UT-WX-005
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cii_platform.calc.weather import (
    CFORM,
    MAX_BEAUFORT_NUMBER,
    NEUTRAL_FACTOR,
    SIMPLE_RULE_MAX_FACTOR,
    beaufort_number,
    cform_applies,
    interpolate_cbeta,
    simple_rule_factor,
    townsin_kwon_weather_factor,
)

#: 마이그레이션 019가 넣은 벌크선 계수 — `CU = 0.5 × BN + 0.5` (`TECH_SPEC §3.3.2`).
BULK_CU_A = Decimal("0.5")
BULK_CU_B = Decimal("0.5")


def _bulk(hs_m: float, **kwargs) -> Decimal:
    return townsin_kwon_weather_factor(
        hs_m=hs_m,
        ship_type="BULK_CARRIER",
        cu_a=BULK_CU_A,
        cu_b=BULK_CU_B,
        **kwargs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Beaufort Number
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hs_m", "expected"),
    [(0.0, 0), (0.5, 2), (1.5, 4), (3.0, 6), (5.0, 8)],
)
def test_beaufort_number_follows_the_spec_formula(hs_m, expected):
    """`BN = round(3.5 × √Hs)` (`TECH_SPEC §3.3.2`).

    표(`§3.3.2`)가 준 Hs 구간과 대조한다 — 공식만 옮겨 적으면 계수가 뒤집혀도
    자기 자신과는 일치한다.
    """
    assert beaufort_number(hs_m) == expected


def test_beaufort_number_uses_bankers_rounding():
    """`[ORACLE-M-1]` — 파이썬 내장 `round`(짝수 반올림)를 쓴다.

    시스템 전역 정책(`ROUND_HALF_UP`)과 다르지만 **정본이 알고도 허용했다.**
    여기서 정책을 통일하면 정본이 확정한 값과 달라진다.
    """
    # 3.5 × √(1/49) ... 정확히 .5로 떨어지는 입력을 만든다: √Hs = 1/7 → 3.5/7 = 0.5
    assert beaufort_number((1 / 7) ** 2) == 0  # round(0.5) == 0
    # √Hs = 3/7 → 3.5 × 3/7 = 1.5 → round(1.5) == 2
    assert beaufort_number((3 / 7) ** 2) == 2


def test_negative_wave_height_is_refused():
    """경험식은 **중단한다** (`§3.5`). 조용히 0으로 바꾸면 데이터 이상이 묻힌다."""
    with pytest.raises(ValueError, match="Hs"):
        beaufort_number(-0.1)


# ─────────────────────────────────────────────────────────────────────────────
# Cβ 보간
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("degree", "expected"),
    [(0, "1.000"), (30, "0.810"), (90, "0.250"), (180, "0.500")],
)
def test_cbeta_table_values_match_the_spec(degree, expected):
    assert interpolate_cbeta(degree) == Decimal(expected)


def test_cbeta_interpolates_between_table_points():
    """45°는 30°와 60°의 **중간**이다 (`§3.3.1`).

    스냅하면 각도가 1° 달라질 때 계수가 계단처럼 뛴다.
    """
    middle = (Decimal("0.810") + Decimal("0.529")) / 2
    assert interpolate_cbeta(45) == middle


def test_cbeta_folds_symmetric_angles():
    """210°는 150°와 같은 상대 방향이다 — 표가 0~180만 정의한다."""
    assert interpolate_cbeta(210) == interpolate_cbeta(150)
    assert interpolate_cbeta(-30) == interpolate_cbeta(30)


# ─────────────────────────────────────────────────────────────────────────────
# TOWNSIN_KWON_ALPHA — UT-WX-002 · UT-WX-003
# ─────────────────────────────────────────────────────────────────────────────


def test_calm_sea_barely_changes_the_factor():
    """UT-WX-002 — 잔잔하면 보정이 거의 없다.

    Hs=0 → BN=0 → CU = 0.5. 계수가 남아 있어 정확히 1.0은 아니지만 1% 미만이다.
    """
    factor = _bulk(0.0)
    assert NEUTRAL_FACTOR < factor < Decimal("1.01")


def test_rough_sea_raises_the_factor():
    """UT-WX-003 — 거칠수록 커진다. **단조 증가**가 이 모델의 성질이다."""
    calm = _bulk(0.5)
    rough = _bulk(4.0)
    assert rough > calm > NEUTRAL_FACTOR


def test_factor_matches_the_hand_computed_value():
    """공식을 그대로 손으로 계산한 값과 맞춘다.

    Hs=4 → BN = round(3.5×2) = 7 · CU = 0.5×7+0.5 = 4.0 · Cβ(0°) = 1.0 ·
    Cform(BULK) = 0.90 → ΔV/V = 3.6% → factor = 1/(1−0.036).
    """
    expected = Decimal(1) / (Decimal(1) - Decimal("3.600") / Decimal(100))
    assert _bulk(4.0) == expected


def test_beam_sea_loses_less_speed_than_head_sea():
    """Cβ가 실제로 적용되는지 — 90°(beam)는 0°(head)의 4분의 1이다."""
    assert _bulk(4.0, wave_heading_deg=90) < _bulk(4.0, wave_heading_deg=0)


def test_above_the_beaufort_limit_the_model_stops():
    """BN > 8이면 계산하지 않는다 (`§3.3.2` 적용 한계).

    값을 내면 그 값이 **얼마나 못 믿을 값인지** 아무도 모른 채 쓰인다.
    """
    with pytest.raises(ValueError, match=str(MAX_BEAUFORT_NUMBER)):
        _bulk(9.0)


def test_unsupported_ship_type_is_refused():
    """계수가 정의된 것은 5종뿐이다. 없는 선종에 다른 값을 빌려 쓰지 않는다."""
    assert "CRUISE_PASSENGER" not in CFORM
    with pytest.raises(ValueError, match="CRUISE_PASSENGER"):
        townsin_kwon_weather_factor(
            hs_m=1.0, ship_type="CRUISE_PASSENGER", cu_a=BULK_CU_A, cu_b=BULK_CU_B
        )


def test_speed_loss_over_100_percent_is_refused():
    """`[ORACLE-S-3]` — 분모가 0 이하가 되면 factor가 음수·무한대가 된다.

    계수를 크게 넣어 그 상태를 직접 만든다. 실제 계수로는 도달하지 않지만,
    **가드가 없으면 계수 개정 한 번으로 도달한다.**
    """
    with pytest.raises(ValueError, match="100"):
        townsin_kwon_weather_factor(
            hs_m=4.0, ship_type="BULK_CARRIER", cu_a=Decimal("20"), cu_b=Decimal("0")
        )


def test_cb_range_is_reported_not_enforced():
    """CB가 표의 범위 밖이어도 계산은 된다 — 정본이 대체값을 정하지 않았다.

    대신 **범위 밖이라는 사실**은 물어볼 수 있어야 한다.
    """
    assert cform_applies("BULK_CARRIER", None) is True
    assert cform_applies("BULK_CARRIER", Decimal("0.60")) is False
    # 범위 밖이어도 예외가 아니다.
    assert _bulk(1.0, block_coefficient=Decimal("0.60")) > NEUTRAL_FACTOR


# ─────────────────────────────────────────────────────────────────────────────
# SIMPLE_RULE — UT-WX-005
# ─────────────────────────────────────────────────────────────────────────────


def test_simple_rule_follows_the_linear_formula():
    """`factor = 1.0 + Hs×0.02 + wind×0.005` (`§8.1`)."""
    assert simple_rule_factor(hs_m=2.0, wind_speed_ms=10.0) == Decimal("1.0900")


def test_simple_rule_clamps_negative_inputs():
    """UT-WX-005 — `[ORACLE-M-2]` 음수 clamping.

    **중단하지 않는다.** 이 모델은 fallback이라, 이상한 입력에 예외를 던지면
    fallback이 아니게 된다 — 경험식과 정반대 규칙이며 그것이 의도다.
    """
    assert simple_rule_factor(hs_m=-3.0, wind_speed_ms=-1.0) == NEUTRAL_FACTOR


def test_simple_rule_treats_missing_values_as_zero():
    """값이 없으면 그 항이 없는 것과 같다 — 예외가 아니다."""
    assert simple_rule_factor(hs_m=None, wind_speed_ms=None) == NEUTRAL_FACTOR
    assert simple_rule_factor(hs_m=1.0, wind_speed_ms=None) == Decimal("1.02")


def test_simple_rule_caps_at_two():
    """`§8.3` 상한 2.0 — 파고 25m·풍속 100m/s 이상은 데이터 오류에 가깝다."""
    assert simple_rule_factor(hs_m=999.0, wind_speed_ms=999.0) == SIMPLE_RULE_MAX_FACTOR
