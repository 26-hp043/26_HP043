"""YTD 누적 CII 엔진 검증 (#353) — **DB 없이 돈다.**

완료 기준(이슈 #353)에 대응한다.

* 동일 입력에 동일 결과 (재현성)
* **not under way 연료를 추가하면 CII가 악화되는 것이 테스트로 고정됨**
* Layer 1 정밀도 규약 위반 없음
* 기존 Fixture 1~4 회귀 없음 → :class:`TestNoRegressionAgainstVoyageEngine`

가장 중요한 것은 :class:`TestNotUnderwayWorsensCii`다. 「정박이 지속되면 등급이
떨어진다」가 서비스 방향 전환의 핵심 주장인데, 그것이 성립하는 이유는 **분자에만
더해지고 분모에는 더해지지 않기 때문**이다. 분모에 not under way 거리를 실수로
넣으면 값이 거의 변하지 않으면서 테스트는 통과할 수 있으므로, 분자·분모를 각각
따로 단언한다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fixture_loader import assert_layer1_equal

from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii
from cii_platform.calc.ytd_engine import calculate_ytd_cii

# Fixture 1 조건 — PRD §13.1 Bulk carrier 50,000 DWT, 2026, HFO.
CAPACITY = Decimal("50000")
DISTANCE = Decimal("1000")
HFO_CF = Decimal("3.114")


def _hfo(ton: str) -> FuelUse:
    return FuelUse(fuel_code="HFO", fuel_ton=Decimal(ton), cf_value=HFO_CF)


def _mdo(ton: str) -> FuelUse:
    # DIESEL_GAS_OIL CF — DB_SCHEMA §3.2 seed 값.
    return FuelUse(fuel_code="DIESEL_GAS_OIL", fuel_ton=Decimal(ton), cf_value=Decimal("3.206"))


@pytest.fixture
def baseline():
    """not under way 기록이 없는 상태 — Fixture 1과 같은 조건."""
    return calculate_ytd_cii(
        underway_fuel_uses=[_hfo("80")],
        not_underway_fuel_uses=[],
        transport_capacity=CAPACITY,
        underway_distance_nm=DISTANCE,
    )


# --- 1. 기존 엔진과의 일치 -----------------------------------------------------------


class TestNoRegressionAgainstVoyageEngine:
    """not under way가 0건이면 기존 항차 엔진과 **완전히 같은 값**이어야 한다.

    같지 않다면 YTD 엔진이 규제 계산식을 다시 쓴 것이고, 그 순간
    ``TECH_SPEC §1``의 Layer 1 bit-exact 계약(``RK-9`` 불가침)이 깨진다.
    """

    def test_attained_cii_matches_fixture_1(self, baseline, load_fixture):
        expected = load_fixture("cii/bulk_50000_hfo_2026.json")["expected"]
        assert_layer1_equal(str(baseline.attained_cii), expected["attained_cii"])

    def test_attained_cii_matches_voyage_engine_bitwise(self, baseline):
        voyage = calculate_attained_cii(
            fuel_uses=[_hfo("80")],
            transport_capacity=CAPACITY,
            distance_nm=DISTANCE,
        )
        assert baseline.attained_cii == voyage.attained_cii
        assert baseline.total_co2_g == voyage.total_co2_g
        assert baseline.total_co2_t == voyage.total_co2_t

    def test_co2_total_matches_fixture_1(self, baseline, load_fixture):
        expected = load_fixture("cii/bulk_50000_hfo_2026.json")["expected"]
        assert_layer1_equal(str(baseline.total_co2_g), expected["co2_emission_g"])


# --- 2. 방향 전환의 핵심 주장 --------------------------------------------------------


class TestNotUnderwayWorsensCii:
    """★ **정박 연료를 더하면 CII가 나빠진다** (완료 기준).

    CII는 낮을수록 좋은 지표이므로 「악화」는 **값의 증가**다.
    """

    def test_adding_not_underway_fuel_increases_cii(self, baseline):
        with_stay = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("80")],
            not_underway_fuel_uses=[_hfo("10")],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert with_stay.attained_cii > baseline.attained_cii

    def test_longer_stay_is_monotonically_worse(self, baseline):
        """정박이 길어질수록(연료가 쌓일수록) 단조 증가한다."""
        values = [
            calculate_ytd_cii(
                underway_fuel_uses=[_hfo("80")],
                not_underway_fuel_uses=[_hfo(str(ton))] if ton else [],
                transport_capacity=CAPACITY,
                underway_distance_nm=DISTANCE,
            ).attained_cii
            for ton in (0, 5, 10, 20, 40)
        ]
        assert values == sorted(values)
        assert values[0] < values[-1]

    def test_denominator_does_not_change(self, baseline):
        """⚠️ **분모는 그대로여야 한다.**

        not under way 구간의 거리를 분모에 넣으면 등급 악화가 상쇄되어 방향 전환의
        전제가 무너진다. 값이 「조금 나빠지는」 것만 보는 테스트로는 이 결함이 잡히지
        않으므로 ``transport_work``를 직접 단언한다.
        """
        with_stay = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("80")],
            not_underway_fuel_uses=[_hfo("10")],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert with_stay.transport_work == baseline.transport_work
        assert with_stay.transport_work == CAPACITY * DISTANCE

    def test_numerator_grows_by_exactly_the_stay_co2(self, baseline):
        """분자 증가분이 **정박 연료의 CO₂와 정확히 같다** — 10 t × 1e6 × 3.114."""
        with_stay = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("80")],
            not_underway_fuel_uses=[_hfo("10")],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert with_stay.total_co2_g - baseline.total_co2_g == Decimal("31140000")
        assert with_stay.not_underway_co2_g == Decimal("31140000")


# --- 3. 분해와 합산 ----------------------------------------------------------------


class TestBreakdown:
    def test_split_sums_to_total(self):
        result = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("80")],
            not_underway_fuel_uses=[_mdo("10")],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert result.underway_co2_g + result.not_underway_co2_g == result.total_co2_g

    def test_same_fuel_code_merges_across_streams(self):
        """같은 유종을 항해 중에도 정박 중에도 쓰면 ``fuel_breakdown_g``에서 합쳐진다."""
        result = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("80")],
            not_underway_fuel_uses=[_hfo("10")],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert list(result.fuel_breakdown_g) == ["HFO"]
        assert result.fuel_breakdown_g["HFO"] == result.total_co2_g

    def test_different_fuel_codes_stay_separate(self):
        result = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("80")],
            not_underway_fuel_uses=[_mdo("10")],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert set(result.fuel_breakdown_g) == {"HFO", "DIESEL_GAS_OIL"}
        assert result.fuel_breakdown_g["DIESEL_GAS_OIL"] == Decimal("32060000")


# --- 4. 빈 목록 -------------------------------------------------------------------


class TestEmptyStreams:
    """한쪽 갈래가 비는 것은 **정상 입력**이다 — ``cii_engine``과 다른 점."""

    def test_no_not_underway_records_is_valid(self, baseline):
        assert baseline.not_underway_co2_g == Decimal(0)
        assert baseline.attained_cii > 0

    def test_no_underway_fuel_is_valid(self):
        """항해 연료가 아직 없고 정박 기록만 있는 상태도 계산된다.

        거리가 0이면 애초에 여기까지 오지 않는다 — 그 판정은 서비스 계층이 한다.
        """
        result = calculate_ytd_cii(
            underway_fuel_uses=[],
            not_underway_fuel_uses=[_hfo("10")],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert result.underway_co2_g == Decimal(0)
        assert result.total_co2_g == Decimal("31140000")


# --- 5. 입력 가드 (M/0 방어 포함) ----------------------------------------------------


class TestInputGuards:
    def test_zero_distance_raises(self):
        """``M/0`` 방어 — 거리 0이면 나눗셈 전에 막는다."""
        with pytest.raises(ValueError, match="underway_distance_nm"):
            calculate_ytd_cii(
                underway_fuel_uses=[_hfo("80")],
                not_underway_fuel_uses=[],
                transport_capacity=CAPACITY,
                underway_distance_nm=Decimal("0"),
            )

    def test_zero_capacity_raises(self):
        with pytest.raises(ValueError, match="transport_capacity"):
            calculate_ytd_cii(
                underway_fuel_uses=[_hfo("80")],
                not_underway_fuel_uses=[],
                transport_capacity=Decimal("0"),
                underway_distance_nm=DISTANCE,
            )

    def test_both_streams_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid YTD CO₂ result"):
            calculate_ytd_cii(
                underway_fuel_uses=[],
                not_underway_fuel_uses=[],
                transport_capacity=CAPACITY,
                underway_distance_nm=DISTANCE,
            )

    def test_all_zero_fuel_raises(self):
        with pytest.raises(ValueError, match="Invalid YTD CO₂ result"):
            calculate_ytd_cii(
                underway_fuel_uses=[_hfo("0")],
                not_underway_fuel_uses=[_hfo("0")],
                transport_capacity=CAPACITY,
                underway_distance_nm=DISTANCE,
            )

    def test_negative_fuel_ton_names_the_stream(self):
        """오류 메시지가 **어느 갈래인지** 밝힌다 — 두 목록을 받으므로 필요하다."""
        with pytest.raises(ValueError, match="not_underway"):
            calculate_ytd_cii(
                underway_fuel_uses=[_hfo("80")],
                not_underway_fuel_uses=[_hfo("-1")],
                transport_capacity=CAPACITY,
                underway_distance_nm=DISTANCE,
            )

    def test_non_positive_cf_raises(self):
        with pytest.raises(ValueError, match="cf_value"):
            calculate_ytd_cii(
                underway_fuel_uses=[FuelUse("HFO", Decimal("80"), Decimal("0"))],
                not_underway_fuel_uses=[],
                transport_capacity=CAPACITY,
                underway_distance_nm=DISTANCE,
            )


# --- 6. 재현성 --------------------------------------------------------------------


class TestReproducibility:
    def test_same_input_same_result(self):
        """TECH_SPEC §5.4 1항 — 동일 입력 → 동일 결과."""
        kwargs = {
            "underway_fuel_uses": [_hfo("80"), _mdo("3")],
            "not_underway_fuel_uses": [_hfo("10")],
            "transport_capacity": CAPACITY,
            "underway_distance_nm": DISTANCE,
        }
        first = calculate_ytd_cii(**kwargs)
        second = calculate_ytd_cii(**kwargs)
        assert first == second

    def test_stream_order_does_not_change_the_total(self):
        """같은 유종을 여러 행으로 나눠 넣어도 총합이 같다 (합산 결합법칙)."""
        merged = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("80")],
            not_underway_fuel_uses=[],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        split = calculate_ytd_cii(
            underway_fuel_uses=[_hfo("50"), _hfo("30")],
            not_underway_fuel_uses=[],
            transport_capacity=CAPACITY,
            underway_distance_nm=DISTANCE,
        )
        assert merged.total_co2_g == split.total_co2_g
        assert merged.attained_cii == split.attained_cii
