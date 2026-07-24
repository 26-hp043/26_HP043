"""수치 직렬화 유틸 (API_SPEC §1.7).

TECH_SPEC의 이중 정밀도 엔진에 맞춰 레이어별로 JSON 표현을 구분한다. Layer 1
(결정론 Decimal) 값은 JSON float로 내리면 정밀도가 깨지므로 **JSON 문자열**로
직렬화한다(§1.7). Layer 2(float)·입력값은 JSON number 그대로이므로 별도 유틸이
필요 없다.
"""

from __future__ import annotations

from decimal import Decimal


def serialize_decimal(value: Decimal) -> str:
    """Layer 1 Decimal 값을 API_SPEC §1.7 규칙대로 JSON 문자열로 직렬화한다.

    저장된 Decimal의 표현을 그대로 보존한다(반올림·재포맷하지 않음). 예:
    ``Decimal("4.982400")`` → ``"4.982400"``. 클라이언트는 이 문자열을 임의 정밀도
    Decimal로 파싱하는 것을 권장한다(§1.7).
    """
    return str(value)
