"""Layer 1 CII 계산 엔진 단위 테스트 (#37).

TEST_PLAN §2.1 중 본 이슈 범위: UT-CII-002 · 003 · 004 · 006 · 007.
(001은 required_cii(#38)·등급(#39)까지 필요, 005는 #38, 008은 Layer 2(#63) 소관)
"""

from decimal import Decimal

import pytest

from cii_platform.calc.cii_engine import (
    CiiResult,
    FuelUse,
    calculate_attained_cii,
    calculate_required_cii,
    calculate_voyage_co2,
)
from cii_platform.calc.precision import publish_layer1_canonical

# --- Fixture 1 기대값 (출처: TEST_PLAN §1.2 · PRD §13.1) ------------------------
# tests/fixtures/cii/bulk_50000_hfo_2026.json 이 아직 없어 인라인한다.
# #45에서 fixture 로더로 이관한다 (#45 코멘트 참조).
# #37 산출값 3개로 한정한다. cii_ref · required_cii · boundary 는 #38 · #39 소관.

FIXTURE1_FUEL_USES = [FuelUse("HFO", Decimal("80"), Decimal("3.114"))]
FIXTURE1_TRANSPORT_CAPACITY = Decimal("50000")  # BULK_CARRIER 50,000 DWT
FIXTURE1_DISTANCE_NM = Decimal("1000")

FIXTURE1_ATTAINED_CII = Decimal("4.982400")
FIXTURE1_TOTAL_CO2_G = Decimal("249120000")
FIXTURE1_TOTAL_CO2_T = Decimal("249.12")

# --------------------------------------------------------------------------------


def _fixture1() -> CiiResult:
    return calculate_attained_cii(
        FIXTURE1_FUEL_USES, FIXTURE1_TRANSPORT_CAPACITY, FIXTURE1_DISTANCE_NM
    )


# --- TEST_PLAN §2.1 ---


def test_ut_cii_002_single_fuel_co2():
    """UT-CII-002 — HFO 80ton, CF=3.114 → 249,120,000 gCO₂ (bit-exact)."""
    total_co2_g, breakdown = calculate_voyage_co2(FIXTURE1_FUEL_USES)
    assert total_co2_g == FIXTURE1_TOTAL_CO2_G
    assert breakdown == {"HFO": FIXTURE1_TOTAL_CO2_G}


def test_ut_cii_003_multi_fuel_co2():
    """UT-CII-003 — HFO 60ton + LNG 20ton → 연료별 CO₂ 합산 (bit-exact)."""
    fuel_uses = [
        FuelUse("HFO", Decimal("60"), Decimal("3.114")),
        FuelUse("LNG", Decimal("20"), Decimal("2.750")),
    ]
    total_co2_g, breakdown = calculate_voyage_co2(fuel_uses)

    assert breakdown["HFO"] == Decimal("186840000")
    assert breakdown["LNG"] == Decimal("55000000")
    assert total_co2_g == Decimal("241840000")
    assert total_co2_g == breakdown["HFO"] + breakdown["LNG"]


def test_ut_cii_004_transport_work():
    """UT-CII-004 — DWT=50,000 · dist=1,000 → W=50,000,000 (bit-exact).

    W는 반환값이 아니므로 attained = M / W 관계로 검증한다.
    """
    result = _fixture1()
    transport_work = FIXTURE1_TRANSPORT_CAPACITY * FIXTURE1_DISTANCE_NM
    assert transport_work == Decimal("50000000")
    assert result.attained_cii * transport_work == result.total_co2_g


def test_ut_cii_006_repeated_calls_identical():
    """UT-CII-006 — 동일 입력 3회 반복 시 결과 동일 (허용 오차 0)."""
    results = [_fixture1() for _ in range(3)]
    assert results[0] == results[1] == results[2]


def test_ut_cii_007_zero_fuel_guard():
    """UT-CII-007 — fuel_ton=0 → ValueError (총합 기준 판정)."""
    with pytest.raises(ValueError, match="Invalid CO₂ result"):
        calculate_voyage_co2([FuelUse("HFO", Decimal("0"), Decimal("3.114"))])


# --- Fixture 1 기대값 ---


def test_fixture1_expected_values():
    result = _fixture1()
    assert result.attained_cii == FIXTURE1_ATTAINED_CII
    assert result.total_co2_g == FIXTURE1_TOTAL_CO2_G
    assert result.total_co2_t == FIXTURE1_TOTAL_CO2_T


def test_layer1_returns_decimal():
    """TECH_SPEC §1.1 — Layer 1 산출값은 전부 Decimal."""
    result = _fixture1()
    assert isinstance(result.attained_cii, Decimal)
    assert isinstance(result.total_co2_g, Decimal)
    assert isinstance(result.total_co2_t, Decimal)
    assert all(isinstance(v, Decimal) for v in result.fuel_breakdown.values())


def test_fuel_breakdown_returned():
    """TECH_SPEC §4.3 [ORACLE-M-6] — 연료별 내역을 함께 반환한다."""
    result = _fixture1()
    assert result.fuel_breakdown == {"HFO": FIXTURE1_TOTAL_CO2_G}


def test_duplicate_fuel_code_is_summed():
    """같은 fuel_code가 여러 건이면 내역에서 합산한다."""
    fuel_uses = [
        FuelUse("HFO", Decimal("50"), Decimal("3.114")),
        FuelUse("HFO", Decimal("30"), Decimal("3.114")),
    ]
    total_co2_g, breakdown = calculate_voyage_co2(fuel_uses)
    assert breakdown == {"HFO": FIXTURE1_TOTAL_CO2_G}
    assert total_co2_g == FIXTURE1_TOTAL_CO2_G


def test_zero_ton_entry_allowed_when_total_positive():
    """다중 연료 중 한 유종이 0톤인 것은 정상 입력이다 (총합 기준 가드)."""
    fuel_uses = [
        FuelUse("HFO", Decimal("80"), Decimal("3.114")),
        FuelUse("LNG", Decimal("0"), Decimal("2.750")),
    ]
    total_co2_g, breakdown = calculate_voyage_co2(fuel_uses)
    assert total_co2_g == FIXTURE1_TOTAL_CO2_G
    assert breakdown["LNG"] == Decimal("0")


# --- 입력 가드 ---


def test_empty_fuel_uses_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        calculate_voyage_co2([])


def test_negative_fuel_ton_rejected():
    with pytest.raises(ValueError, match="fuel_ton must be >= 0"):
        calculate_voyage_co2([FuelUse("HFO", Decimal("-1"), Decimal("3.114"))])


def test_non_positive_cf_rejected():
    with pytest.raises(ValueError, match="cf_value must be > 0"):
        calculate_voyage_co2([FuelUse("HFO", Decimal("80"), Decimal("0"))])


@pytest.mark.parametrize(
    ("capacity", "distance", "expected"),
    [
        (Decimal("0"), Decimal("1000"), "transport_capacity must be > 0"),
        (Decimal("-1"), Decimal("1000"), "transport_capacity must be > 0"),
        (Decimal("50000"), Decimal("0"), "distance_nm must be > 0"),
        (Decimal("50000"), Decimal("-1"), "distance_nm must be > 0"),
    ],
)
def test_zero_denominator_guards_name_the_offending_input(capacity, distance, expected):
    """capacity=0과 distance=0이 같은 메시지로 나오면 안 된다."""
    with pytest.raises(ValueError, match=expected):
        calculate_attained_cii(FIXTURE1_FUEL_USES, capacity, distance)


# --- required CII (#38) — TEST_PLAN §2.1 중 본 이슈 범위: UT-CII-005 ------------
# Fixture 1의 9 소수자리 기대값은 쓰지 않는다. 그 값의 확정은 별도 이슈 소관이며,
# 아래 케이스는 어느 쪽으로 확정되든 영향받지 않는다 (#38 정정 코멘트 참조).

# PRD §3.4.3 LNG_CARRIER DWT >= 100,000 — c=0이라 CII_ref가 capacity와 무관해진다.
LNG_FIXED_A = Decimal("9.827")

# TECH_SPEC §1.2.2(ln/exp)와 float math.pow가 9 소수자리에서 갈리는 유일한 seed 조합.
# 기대값은 표시용 9자리가 아니라 prec=30 원값이라 자릿수 표기 규칙과 무관하다.
LNEXP_DIVERGENT_A = Decimal("14779E10")
LNEXP_DIVERGENT_C = Decimal("2.673")
LNEXP_DIVERGENT_CAPACITY = Decimal("1000")
#: 공표 확정(유효숫자 30자리)을 거친 기대값. 작업 정밀도가 50이라 raw 반환값은
#: 50자리이며, 정본과 대조할 수 있는 형태는 공표값이다 (#179).
#:
#: 종전 값은 ``…642109``였다. 그것은 작업 정밀도가 30이던 시절의 산출값이며 #179가
#: 고친 결함을 그대로 담고 있었다. 작업 정밀도 50 · 60 · 80 · 150 · 300 전부
#: ``…642107``로 수렴한다.
LNEXP_DIVERGENT_CII_REF = Decimal("1414637.11796665060056953642107")


def test_required_cii_applies_negative_exponent():
    """`^(-c)`가 적용되는지 — 부호가 뒤집히면 100 × 20 = 2000 계열이 나온다.

    ln/exp 경유라 정확 연산이 아니므로(실측 5.00000000000000000000000000001)
    허용오차로 비교한다. 이 테스트의 목적은 exact 산술이 아니라 부호 검출이다.
    """
    result = calculate_required_cii(
        a=Decimal("100"),
        c=Decimal("1"),
        reference_capacity=Decimal("20"),
        z_factor_percent=Decimal("0"),
    )
    assert abs(result.cii_ref - Decimal("5")) < Decimal("1e-25")
    assert result.required_cii == result.cii_ref


def test_required_cii_decreases_as_capacity_grows():
    """capacity가 커지면 CII_ref는 작아진다. `+c`면 즉시 뒤집힌다."""
    args = {"a": Decimal("100"), "c": Decimal("1"), "z_factor_percent": Decimal("0")}
    refs = [
        calculate_required_cii(reference_capacity=Decimal(cap), **args).cii_ref
        for cap in (10, 20, 40, 80)
    ]
    assert refs == sorted(refs, reverse=True)


def test_ut_cii_005_required_cii_decreases_as_z_factor_grows():
    """UT-CII-005 — Z-factor가 커지면 required CII가 낮아진다.

    대상 함수가 z_factor_percent를 이미 받은 순수 함수라 연도 seed를 조회하지 않고
    입력 퍼센트를 직접 올려 검증한다. 연도별 검증은 성격상 통합 테스트다.
    """
    args = {
        "a": Decimal("4745"),
        "c": Decimal("0.622"),
        "reference_capacity": Decimal("50000"),
    }
    low = calculate_required_cii(z_factor_percent=Decimal("10"), **args)
    high = calculate_required_cii(z_factor_percent=Decimal("20"), **args)

    assert high.required_cii < low.required_cii
    # CII_ref는 Z와 무관하다 — 감소가 Z 경로에서만 왔는지 확인한다.
    assert low.cii_ref == high.cii_ref


def test_required_cii_with_zero_c_ignores_capacity():
    """c=0이면 CII_ref = a. PRD §3.4.3 LNG_CARRIER DWT >= 100,000."""
    result = calculate_required_cii(
        a=LNG_FIXED_A,
        c=Decimal("0"),
        reference_capacity=Decimal("120000"),
        z_factor_percent=Decimal("0"),
    )
    assert result.cii_ref == LNG_FIXED_A

    far = calculate_required_cii(
        a=LNG_FIXED_A,
        c=Decimal("0"),
        reference_capacity=Decimal("999999"),
        z_factor_percent=Decimal("0"),
    )
    assert far.cii_ref == result.cii_ref


def test_decimal_power_does_not_regress_to_float_pow():
    """TECH_SPEC §1.2.2 위반(float 경유) 회귀 방지 — 공표값 기준.

    Fixture 1(a=4745)에서는 두 방식이 12자리까지 같아 이 위반이 검출되지 않는다.
    seed 133개 조합 중 갈리는 것은 이 하나뿐이다.
      Decimal ln/exp : ...117966651   float math.pow : ...117966650 (9자리 기준)

    ``cii_ref``는 체인 중간값이라 raw 반환값이 작업 정밀도(50자리)로 나온다 (#179).
    정본과 대조하려면 :func:`publish_layer1_canonical`을 거친다.
    """
    result = calculate_required_cii(
        a=LNEXP_DIVERGENT_A,
        c=LNEXP_DIVERGENT_C,
        reference_capacity=LNEXP_DIVERGENT_CAPACITY,
        z_factor_percent=Decimal("0"),
    )
    assert publish_layer1_canonical(result.cii_ref) == LNEXP_DIVERGENT_CII_REF


def test_required_cii_does_not_round_intermediate_values():
    """중간에 자르거나 반올림하지 않는다.

    입력은 Fixture 1 조합이라 prec=30에서 소수 29자리가 나온다. 9자리로 잘렸다면
    소수 자릿수가 9를 넘지 못한다.

    한계 — 이 단언은 **9자리 quantize만** 잡는다. 12자리나 16자리로 자르면 통과한다.
    자릿수까지 잠그는 것은 test_decimal_power_does_not_regress_to_float_pow의
    prec=30 원값 리터럴 대조이며, 이쪽이 주 잠금이다.
    """
    result = calculate_required_cii(
        a=Decimal("4745"),
        c=Decimal("0.622"),
        reference_capacity=Decimal("50000"),
        z_factor_percent=Decimal("11"),
    )
    assert -result.cii_ref.as_tuple().exponent > 9
    assert -result.required_cii.as_tuple().exponent > 9


@pytest.mark.parametrize("capacity", [Decimal("0"), Decimal("-1")])
def test_required_cii_rejects_non_positive_reference_capacity(capacity):
    with pytest.raises(ValueError, match="reference_capacity must be > 0"):
        calculate_required_cii(
            a=Decimal("4745"),
            c=Decimal("0.622"),
            reference_capacity=capacity,
            z_factor_percent=Decimal("11"),
        )
