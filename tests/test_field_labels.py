"""field_label 매핑 계약 테스트 (#49).

핵심 계약: 미등록 필드는 KeyError가 아니라 원문을 그대로 반환한다(D4).
"""

from cii_platform.api.field_labels import field_label


def test_registered_field_returns_korean_label() -> None:
    # API_SPEC §1.3.2 예시 / §11 VAL-002.
    assert field_label("distance_nm") == "운항 거리"


def test_unregistered_field_returns_verbatim_without_error() -> None:
    # D4: 미등록 필드는 예외 없이 필드명 원문을 반환한다.
    assert field_label("unregistered_field_xyz") == "unregistered_field_xyz"
