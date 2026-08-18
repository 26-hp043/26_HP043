"""field_label 매핑 계약 테스트 (#49).

핵심 계약: 미등록 필드는 KeyError가 아니라 원문을 그대로 반환한다(D4).

케이스: AT-ERR-001 · AT-ERR-002 (`TEST_PLAN §14.5`)
"""

import pytest

from cii_platform.api.field_labels import field_label


def test_registered_field_returns_korean_label() -> None:
    # API_SPEC §1.3.2 예시 / §11 VAL-002.
    assert field_label("distance_nm") == "운항 거리"


def test_unregistered_field_returns_verbatim_without_error() -> None:
    # D4: 미등록 필드는 예외 없이 필드명 원문을 반환한다.
    assert field_label("unregistered_field_xyz") == "unregistered_field_xyz"


# --- #55 · #51 이 채운 라벨 -----------------------------------------------------------


class TestRequestFieldLabels:
    """기능① 요청 필드와 목록 쿼리 파라미터에 한글 라벨이 있다.

    `#55` 구현 시 빠뜨렸다가 **실 API 시연 준비 중에 드러났다** — 오류 응답의
    ``field_label``이 ``fuel_uses[0].fuel_ton``처럼 필드명 그대로 나가고 있었다.
    """

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("vessel_id", "선박"),
            ("regulation_year", "규제연도"),
            ("distance_nm", "운항 거리"),
            ("speed_kn", "속력"),
            ("fuel_uses", "연료 사용량"),
            ("weather_model", "기상 모델"),
            ("limit", "페이지 크기"),
            ("cursor", "커서"),
            ("ship_type", "선종"),
            ("search", "검색어"),
        ],
    )
    def test_label(self, field, expected):
        assert field_label(field) == expected


class TestArrayIndexPaths:
    """배열 인덱스가 붙은 경로도 라벨을 찾는다.

    ``fuel_uses[0].fuel_ton``과 ``fuel_uses[3].fuel_ton``은 **같은 필드**이고
    인덱스는 요청마다 달라지므로 정적 dict에 모두 적을 수 없다.
    """

    @pytest.mark.parametrize("index", [0, 1, 12, 999])
    def test_fuel_ton_at_any_index(self, index):
        assert field_label(f"fuel_uses[{index}].fuel_ton") == "연료 사용량"

    @pytest.mark.parametrize("index", [0, 7])
    def test_fuel_type_at_any_index(self, index):
        assert field_label(f"fuel_uses[{index}].fuel_type") == "연료 종류"

    def test_unknown_array_field_falls_back_to_path(self):
        """모르는 배열 필드는 **경로 원문**을 돌려준다 — 조회 실패 계약."""
        assert field_label("scenarios[0].unknown") == "scenarios[0].unknown"

    def test_registered_exact_path_wins(self):
        """인덱스 없는 정확한 경로가 먼저 조회된다."""
        assert field_label("fuel_uses") == "연료 사용량"
