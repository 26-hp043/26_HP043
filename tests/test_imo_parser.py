"""parse_imo_scientific / validate_a_value 단위 테스트 (#36).

이슈 명세 6개 + ORACLE-S-3 reject 3개 + §9.2 산술 경로 표현형 잠금 1개.

케이스: UT-IMO-001 · UT-IMO-002 · UT-IMO-004 · UT-IMO-005 (`TEST_PLAN §14.5`)
"""

from decimal import Decimal

import pytest

from cii_platform.calc.imo_parser import parse_imo_scientific, validate_a_value

# --- 이슈 명세 (TECH_SPEC §9.2) ---


def test_parse_integer():
    assert parse_imo_scientific("4745") == Decimal("4745")


def test_parse_decimal():
    assert parse_imo_scientific("9.827") == Decimal("9.827")


def test_parse_large_scientific():
    # 14479E10 = 144,790,000,000,000 (LNG 65k ≤ DWT < 100k)
    assert parse_imo_scientific("14479E10") == Decimal("144790000000000")


def test_parse_lng_small_bin():
    # 14779E10 = 147,790,000,000,000 (LNG DWT < 65k)
    assert parse_imo_scientific("14779E10") == Decimal("147790000000000")


def test_14479_vs_14779_not_equal():
    # AGENTS.md §2.3: 서로 다른 DWT 구간의 서로 다른 값. 임의 정정 금지.
    assert parse_imo_scientific("14479E10") != parse_imo_scientific("14779E10")


def test_validate_consistency():
    assert validate_a_value("14479E10", Decimal("144790000000000")) is True


# --- ORACLE-S-3 reject 가드 잠금 ---


def test_reject_nan():
    with pytest.raises(ValueError):
        parse_imo_scientific("nan")


def test_reject_infinity():
    with pytest.raises(ValueError):
        parse_imo_scientific("inf")


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_reject_non_positive(bad):
    with pytest.raises(ValueError):
        parse_imo_scientific(bad)


# --- §9.2 산술 경로 표현형 잠금 (E-정수 입력 한정) ---


@pytest.mark.parametrize("raw", ["14479E10", "14779E10"])
def test_scientific_normalized_exponent(raw):
    """§9.2 산술 경로 충실성 잠금.

    parse가 ``Decimal(raw)``로 회귀하면 E-입력 exp가 0→10으로 바뀐다. 이를 잡는다.
    정본 표현형 계약은 #102 소유이며, §9.2 표현이 바뀌면 이 테스트도 갱신한다.
    (``"9.827"`` 처럼 소수 mantissa는 exp≠0이므로 E-정수 입력에만 적용)
    """
    assert parse_imo_scientific(raw).as_tuple().exponent == 0
