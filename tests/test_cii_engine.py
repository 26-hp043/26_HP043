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
    calculate_voyage_co2,
)

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
