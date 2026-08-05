"""수치 직렬화 유틸 계약 테스트 (#49).

API_SPEC §1.7: Layer 1(Decimal) 값은 JSON 문자열로 직렬화하며, 저장된 표현을
반올림·재포맷 없이 보존한다.
"""

from decimal import Decimal

from cii_platform.api.serialization import serialize_decimal


def test_layer1_decimal_serialized_as_string() -> None:
    assert serialize_decimal(Decimal("4.982400")) == "4.982400"


def test_trailing_zeros_preserved() -> None:
    # 정밀도 표현을 임의로 깎지 않는다.
    assert serialize_decimal(Decimal("0.890")) == "0.890"


def test_return_type_is_str() -> None:
    assert isinstance(serialize_decimal(Decimal("1")), str)
