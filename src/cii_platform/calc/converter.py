"""Layer 1 (Decimal) → Layer 2 (float64) 변환 (#44).

TECH_SPEC §2.1 이중 정밀도 엔진의 다리. Layer 1 결정론 계산은 ``Decimal(prec=50)``
으로 bit-exact 재현성을 보증하고, Monte Carlo 시뮬레이션은 성능을 위해 ``float64``로
실행한다. Monte Carlo 5,000회를 Decimal으로 돌리면 p95 < 3초 목표(TECH_SPEC §9.4)를
만족할 수 없어, **단일 명시적 변환 지점**(TECH_SPEC §1.1 [ORACLE-S-2])을 거쳐
float64로 넘긴다.

변환 시 정밀도 손실(유효숫자 30 → 15~17)은 피할 수 없다. 이 모듈은 **손실을 숨기지
않고** ``estimate_precision_loss``로 관측 가능하게 만들어, 결과 메타데이터
(``rng_metadata.precision_loss``)에 기록되도록 한다 (TEST_PLAN §2.8 [ORACLE-S-6]).

``float`` 직접 호출을 이 파일 안에만 묶어두면, 정적 분석과 UT-CONVERT-003이 Layer 1
엔진의 암시적 float 변환을 잡아낼 수 있다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_float64(value: Decimal) -> float:
    """``Decimal``을 IEEE 754 float64로 변환한다 (#44).

    Python 내장 ``float(Decimal)``과 결과는 동일하다 — 이 함수를 거치는 이유는
    **변환 지점을 단일화**하기 위해서다 (TECH_SPEC §1.1 [ORACLE-S-2]). 호출부가
    흩어진 ``float()``를 쓰면 정밀도 손실이 어디서 일어났는지 추적할 수 없다.

    :raises TypeError: ``value``가 ``Decimal``이 아닌 경우 — 다른 타입의 float 변환은
        이 함수의 계약 밖이며, ``float(x)``를 직접 쓰는 것이 의도를 더 명확히 드러낸다.
    """
    if not isinstance(value, Decimal):
        raise TypeError(
            f"to_float64 accepts Decimal only (TECH_SPEC §1.1): got {type(value).__name__}"
        )
    return float(value)


def convert_simulation_params(params: dict[str, Any]) -> dict[str, Any]:
    """``params`` dict 내의 모든 ``Decimal`` 값을 ``float``로 변환한다 (#44).

    Monte Carlo 엔진에 넘기기 전 한 번에 변환한다. dict 구조(중첩 dict · list 포함)는
    그대로 보존하며, ``Decimal``인 leaf만 ``float``로 바꾼다. 그 외 타입(``int`` ·
    ``str`` · ``bool`` · ``None``)은 손대지 않는다.
    """
    return {key: _convert_value(value) for key, value in params.items()}


def _convert_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return to_float64(value)
    if isinstance(value, dict):
        return {k: _convert_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        converted = [_convert_value(item) for item in value]
        return type(value)(converted) if isinstance(value, tuple) else converted
    return value


def estimate_precision_loss(original: Decimal, converted: float) -> str:
    """변환 전후 ``Decimal``과 ``float``의 차이를 문자열로 돌려준다 (#44).

    결과는 ``rng_metadata.precision_loss``에 기록되어, "이 Monte Carlo 결과는
    Layer 1→2 변환에서 ``X``만큼의 오차를 안고 있다"를 사후 감사할 수 있게 한다
    (TECH_SPEC §5.4 재현성 계약 4항).

    문자열 포맷을 쓰는 이유는 차원이 매우 다른 두 값(정수부 자릿수가 1~5인 CII,
    ``1e10`` 단위의 CO₂ g)을 같은 포맷으로 메타데이터에 담기 위해서다.
    """
    if not isinstance(original, Decimal):
        raise TypeError(f"original must be Decimal: got {type(original).__name__}")
    diff = abs(original - Decimal(str(converted)))
    return f"loss={diff}"
