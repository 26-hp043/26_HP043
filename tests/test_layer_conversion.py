"""Layer 1→2 변환 테스트 (#44).

TEST_PLAN §2.8 [ORACLE-S-6] — Layer 1 (Decimal) ↔ Layer 2 (float64) 경계의 단일
명시적 변환 지점을 검증한다.

- UT-CONVERT-001: Layer 1 진입점(``calculate_attained_cii``) 반환값이 ``Decimal``.
- UT-CONVERT-002: 정본값 30자리(#166)의 ``to_float64`` 변환이 IEEE 754 float64
  비트 패턴과 일치.
- UT-CONVERT-003: Layer 1 계산 중 내장 ``float()`` 호출 0회 (monkey-patch 탐지).
"""

import struct
from decimal import Decimal

from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii
from cii_platform.calc.converter import (
    convert_simulation_params,
    estimate_precision_loss,
    to_float64,
)

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

    float64는 약 15~17자리 유효숫자. ``to_float64``가 Python ``float(Decimal)``
    동작을 그대로 따르는지 비트 단위로 잠근다. ``==``가 NaN/부호있는 0을 넘길 수
    있어 ``struct.pack``으로 비교한다.
    """
    actual = to_float64(CANONICAL_30_DIGIT_VALUE)
    expected = float(CANONICAL_30_DIGIT_VALUE)
    assert struct.pack("<d", actual) == struct.pack("<d", expected)
    # 변환 후 유효숫자는 15~17자리로 줄어든다 (정밀도 손실 관측).
    assert abs(actual - 5.668613856737283) < 1e-15


def test_ut_convert_003_layer1_does_not_invoke_builtin_float(monkeypatch) -> None:
    """UT-CONVERT-003 — Layer 1 계산 중 내장 float() 호출 0회 (#44).

    ``builtins.float``을 호출 추적용 trap으로 교체한 뒤 ``calculate_attained_cii``를
    실행한다. Layer 1은 Decimal로만 계산해야 하므로 (TECH_SPEC §1.1), float()가
    불리면 버그다. ``convert_simulation_params``/``to_float64``는 Layer 1 **밖**에서만
    불려야 한다.
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


# --- converter.py 단위 (#44 본문 체크리스트) -----------------------------------------


def test_to_float64_rejects_non_decimal() -> None:
    """to_float64는 Decimal만 받는다 (TECH_SPEC §1.1 단일 변환 지점 계약)."""
    import pytest

    with pytest.raises(TypeError):
        to_float64("5.0")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_float64(5.0)  # type: ignore[arg-type]


def test_convert_simulation_params_preserves_structure() -> None:
    """convert_simulation_params는 Decimal leaf만 float로 바꾸고 구조는 보존한다."""
    params = {
        "attained_cii": Decimal("4.9824"),
        "year": 2026,
        "fuel_breakdown": {"HFO": Decimal("100"), "LNG": Decimal("50")},
        "list_field": [Decimal("1"), Decimal("2"), "keep"],
        "name": "voyage-1",
        "nested": {"inner": Decimal("9.9")},
    }
    converted = convert_simulation_params(params)
    assert converted["attained_cii"] == 4.9824
    assert isinstance(converted["attained_cii"], float)
    assert converted["year"] == 2026  # int 그대로
    assert isinstance(converted["year"], int)
    assert converted["fuel_breakdown"] == {"HFO": 100.0, "LNG": 50.0}
    assert converted["list_field"] == [1.0, 2.0, "keep"]
    assert converted["name"] == "voyage-1"
    assert converted["nested"] == {"inner": 9.9}


def test_estimate_precision_loss_reports_difference() -> None:
    """estimate_precision_loss는 변환 전후 차이를 문자열로 돌려준다 (TECH_SPEC §5.4 4항)."""
    original = CANONICAL_30_DIGIT_VALUE
    converted = to_float64(original)
    loss = estimate_precision_loss(original, converted)
    assert loss.startswith("loss=")
    # 30자리 정본값을 float64로 변환하면 1e-15 근처의 손실이 발생한다.
    diff = Decimal(loss.removeprefix("loss="))
    assert Decimal("1e-30") < diff < Decimal("1e-13")
