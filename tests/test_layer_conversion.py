"""Layer 1→2 변환 테스트 (#44).

TEST_PLAN §2.8 [ORACLE-S-6] — Layer 1 (Decimal) ↔ Layer 2 (float64) 경계의 단일
명시적 변환 지점을 검증한다.

- UT-CONVERT-001: Layer 1 진입점(``calculate_attained_cii``) 반환값이 ``Decimal``.
- UT-CONVERT-002: 정본값 30자리(#166)의 명시적 ``float()`` 변환이 IEEE 754 float64
  비트 패턴과 일치.
- UT-CONVERT-003: Layer 1 계산 중 내장 ``float()`` 호출 0회 (monkey-patch 탐지).
"""

import struct
from decimal import Decimal

from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii

#: UT-CONVERT-002 — TEST_PLAN §2.8가 명시한 정본값 30자리 (#166).
#:
#: Layer 1→2 경계에서 실제로 변환되는 것이 이 값이다. 소수 9자리 표시값을 쓰면
#: ``1e-12`` 단위 아래의 정밀도 손실이 검증에서 사라진다 (TEST_PLAN §2.8 [ORACLE-S-6]).
CANONICAL_30_DIGIT_VALUE = Decimal("5.66861385673728321407947925818")

#: UT-CONVERT-001/003용 최소 Layer 1 입력. 값의 정확성이 아니라 타입/float 미사용이
#: 관심사이므로 임의의 양수를 쓴다. ``cii_engine`` 진입점의 실제 회귀는 ``test_cii_engine.py``가
#: 별도로 다룬다.
_FUEL_USES = [
    FuelUse(fuel_code="HFO", fuel_ton=Decimal("100"), cf_value=Decimal("3.114")),
]
_TRANSPORT_CAPACITY = Decimal("50000")
_DISTANCE_NM = Decimal("2000")


def test_ut_convert_001_layer1_returns_decimal() -> None:
    """UT-CONVERT-001 — calculate_attained_cii 반환값이 Decimal (#44).

    Layer 1 결과가 Decimal이어야만 Layer 1→2 변환의 입력이 된다. float로 나오면
    변환 지점이 사라지고 정밀도 손실을 추적할 수 없다 (TECH_SPEC §1.1 [ORACLE-S-2]).
    """
    result = calculate_attained_cii(
        fuel_uses=_FUEL_USES,
        transport_capacity=_TRANSPORT_CAPACITY,
        distance_nm=_DISTANCE_NM,
    )
    assert isinstance(result.attained_cii, Decimal)
    assert isinstance(result.total_co2_g, Decimal)
    assert isinstance(result.total_co2_t, Decimal)
    for value in result.fuel_breakdown.values():
        assert isinstance(value, Decimal)


def test_ut_convert_002_decimal_to_float64_matches_expected_bit_pattern() -> None:
    """UT-CONVERT-002 — 정본값 30자리 → IEEE 754 float64 변환 비트 패턴 (#44, #166).

    기대 비트는 30자리 Decimal을 정수 분수로 놓고 binary64의 53비트 유효숫자에
    nearest-even 반올림해 독립 계산했다. 같은 float() 호출을 기대값에 쓰지 않는다.
    """
    actual = float(CANONICAL_30_DIGIT_VALUE)
    # 정수 분수 N/10**29, 지수 2, 53비트 유효숫자의 nearest-even 독립 검산 (#2102).
    assert struct.unpack("<Q", struct.pack("<d", actual))[0] == 0x4016ACA91C615B33
    # 변환 후 유효숫자는 15~17자리로 줄어든다 (정밀도 손실 관측).
    assert abs(actual - 5.668613856737283) < 1e-15


def test_ut_convert_003_layer1_does_not_invoke_builtin_float(monkeypatch) -> None:
    """UT-CONVERT-003 — Layer 1 계산 중 내장 float() 호출 0회 (#44).

    ``builtins.float``을 호출 추적용 trap으로 교체한 뒤 ``calculate_attained_cii``를
    실행한다. Layer 1은 Decimal로만 계산해야 하므로 (TECH_SPEC §1.1), float()가
    불리면 버그다. 명시적인 Decimal→float 변환은 Layer 1 밖에서만 한다.
    """

    seen: list[tuple[object, ...]] = []

    def trap_float(*args: object, **kwargs: object) -> float:
        seen.append(args)
        return 0.0  # trap이지만 정상 경로를 방해하지 않는 더미 값을 반환

    import builtins

    monkeypatch.setattr(builtins, "float", trap_float)

    result = calculate_attained_cii(
        fuel_uses=_FUEL_USES,
        transport_capacity=_TRANSPORT_CAPACITY,
        distance_nm=_DISTANCE_NM,
    )
    assert seen == [], f"Layer 1 must not call float(): got {seen}"
    assert isinstance(result.attained_cii, Decimal)
