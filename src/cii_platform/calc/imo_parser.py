"""IMO 과학표기법 파서 (#36).

MEPC.353(78) Table 1의 reference line 계수 ``a``는 과학표기(예: ``"14479E10"``)로
표기된다. 이를 오차 없는 :class:`~decimal.Decimal`로 변환한다. 구현은 TECH_SPEC
§9.2 원문을 그대로 따른다 (E→×10^ 산술 정규화 + ORACLE-S-3 NaN/Infinity/비양수 검증).

Decimal 컨텍스트(prec=30)는 ``calc`` 패키지 ``__init__``에서 설정된다
(TECH_SPEC §1.2.1).
"""

from decimal import Decimal


def parse_imo_scientific(raw: str) -> Decimal:
    """
    IMO 표 원문의 E 표기를 Decimal로 변환.
    예: "14405E7" → Decimal("144050000000")
         "14779E10" → Decimal("147790000000000")
    """
    # E 표기를 Decimal이 이해할 수 있는 형태로 변환
    normalized = raw.upper().replace("E", "×10^")
    if "×10^" in normalized:
        mantissa_str, exp_str = normalized.split("×10^")
        mantissa = Decimal(mantissa_str)
        exponent = int(exp_str)
        result = mantissa * (Decimal(10) ** exponent)
    else:
        result = Decimal(raw)

    # [ORACLE-S-3] NaN / Infinity 검증
    if result.is_nan() or result.is_infinite():
        raise ValueError(f"Invalid IMO coefficient: '{raw}' → {result} (NaN/Infinity)")

    # [ORACLE-S-3] 비양수 값 검증
    if result <= 0:
        raise ValueError(f"IMO coefficient must be > 0: '{raw}' → {result}")

    return result


def validate_a_value(a_raw: str, a_decimal: Decimal) -> bool:
    """``a_raw``를 파싱한 값이 ``a_decimal``과 일치하는지 검증 (값 동등).

    DB ``cii_reference_line``의 ``a_raw``(원문 문자열)와 ``a_decimal``(NUMERIC)
    이중 저장이 서로 맞는지 확인하는 순수 헬퍼. DB 전체 순회 검증
    (TECH_SPEC §9.3 ``validate_a_values(session)``)은 seed/앱 시작 단계 소관이며
    여기 두지 않는다.
    """
    return parse_imo_scientific(a_raw) == a_decimal
