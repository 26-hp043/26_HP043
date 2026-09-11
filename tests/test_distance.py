"""대권거리 단위 검사 — `calc/distance.py` (`TECH_SPEC §6`, #828).

종전 수치 단언은 `test_scenario_compare_api.py`의 **부산→로테르담 한 점**(4832.64 nm)뿐이었다.
그 한 점은 같은 반구·짧지 않은 경도 차라 **haversine이 쉽게 맞는 자리**다. 틀리기 쉬운
자리는 따로 있다.

- **날짜변경선** — 경도 차를 그대로 빼면 `179.5 − (−179.5) = 359°`가 된다. haversine은
  `sin²(Δλ/2)`라 360° 주기에서 자동으로 맞지만, 식을 「단순화」하는 순간 깨진다
- **극** — `cos φ = 0`이라 경도 항이 사라진다. 극에서의 경도는 의미가 없어야 한다
- **이종 반구** — 위도 부호가 갈리는 항로(남반구 ↔ 북반구)

기대값은 **haversine을 다시 쓰지 않고** 구한다 — 같은 식으로 기대값을 만들면 식의 오류가
양쪽에 똑같이 들어가 검사가 통과한다. 적도·자오선 위의 거리는 **호의 길이 `R × 각도`**로,
그 밖은 **구면 코사인 법칙**(다른 식)으로 대조한다.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from cii_platform.calc.distance import EARTH_RADIUS_NM, great_circle_distance_nm

D = Decimal


def _arc(degrees: float) -> Decimal:
    """중심각 ``degrees``의 호 길이(해리) — 대권 위 두 점의 거리 정의 그대로."""
    return D(str(EARTH_RADIUS_NM * math.radians(degrees))).quantize(D("0.01"))


def _law_of_cosines(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """구면 코사인 법칙 — haversine과 **다른 식**으로 같은 중심각을 낸다."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    cos_c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return EARTH_RADIUS_NM * math.acos(max(-1.0, min(1.0, cos_c)))


def test_same_point_is_zero():
    assert great_circle_distance_nm(D("35.1"), D("129.0"), D("35.1"), D("129.0")) == D("0.00")


def test_distance_is_symmetric():
    there = great_circle_distance_nm(D("35.1"), D("129.0"), D("51.9"), D("4.1"))
    back = great_circle_distance_nm(D("51.9"), D("4.1"), D("35.1"), D("129.0"))
    assert there == back


def test_crossing_the_date_line_takes_the_short_way():
    """적도에서 179.5°E → 179.5°W는 **1°**다 — 359°(약 21,500 nm)가 아니다."""
    got = great_circle_distance_nm(D("0"), D("179.5"), D("0"), D("-179.5"))
    assert got == _arc(1.0)
    assert got < D("100")


def test_minus_180_and_plus_180_are_the_same_meridian():
    assert great_circle_distance_nm(D("10"), D("-180"), D("10"), D("180")) == D("0.00")


def test_pole_to_pole_is_half_a_great_circle():
    """북극 → 남극은 `πR`이다. 극에서는 경도가 거리에 영향을 주지 않는다."""
    assert great_circle_distance_nm(D("90"), D("0"), D("-90"), D("0")) == _arc(180.0)
    assert great_circle_distance_nm(D("90"), D("37"), D("-90"), D("-120")) == _arc(180.0)


def test_longitude_does_not_matter_at_a_pole():
    """같은 극의 두 「점」은 경도가 달라도 같은 점이다."""
    assert great_circle_distance_nm(D("90"), D("0"), D("90"), D("135")) == D("0.00")


@pytest.mark.parametrize(
    ("lat1", "lon1", "lat2", "lon2", "degrees"),
    [
        ("0", "0", "0", "90", 90.0),  # 적도 위 사분원
        ("0", "0", "60", "0", 60.0),  # 자오선 위
        ("-30", "20", "30", "20", 60.0),  # 자오선 위 · 적도를 건넌다
    ],
)
def test_arcs_on_a_great_circle(lat1, lon1, lat2, lon2, degrees):
    """적도·자오선은 그 자체가 대권이라 거리가 **호의 길이**와 같다."""
    got = great_circle_distance_nm(D(lat1), D(lon1), D(lat2), D(lon2))
    assert got == _arc(degrees)


@pytest.mark.parametrize(
    ("lat1", "lon1", "lat2", "lon2"),
    [
        (-33.9, 18.4, 35.1, 129.0),  # 케이프타운 → 부산 (남 ↔ 북)
        (-37.8, 144.9, 34.0, -118.2),  # 멜버른 → 로스앤젤레스 (남 ↔ 북 · 날짜변경선)
        (1.3, 103.8, -23.0, -43.2),  # 싱가포르 → 리우데자네이루 (남 ↔ 북 · 동 ↔ 서)
    ],
)
def test_matches_an_independent_formula_across_hemispheres(lat1, lon1, lat2, lon2):
    """haversine과 구면 코사인 법칙이 **0.01 nm 안에서** 같은 값을 낸다.

    두 식은 수학적으로 같고 이 거리대에서는 수치 오차도 해리 단위의 백분의 일보다
    훨씬 작다. 갈리면 둘 중 하나의 구현이 틀린 것이다.
    """
    got = great_circle_distance_nm(D(str(lat1)), D(str(lon1)), D(str(lat2)), D(str(lon2)))
    assert abs(float(got) - _law_of_cosines(lat1, lon1, lat2, lon2)) <= 0.01


def test_result_is_a_decimal_fixed_to_two_places():
    """`voyage_scenario.distance_nm`이 NUMERIC(12,2)다 — 저장 전에 자릿수가 확정된다."""
    got = great_circle_distance_nm(D("35.1"), D("129.0"), D("51.9"), D("4.1"))
    assert isinstance(got, Decimal)
    assert got.as_tuple().exponent == -2


def test_radius_is_the_value_in_tech_spec():
    """`TECH_SPEC §6` — `R = 3440.065 nm`. 기하 상수라도 **문서와 같은 값**이어야 한다."""
    assert EARTH_RADIUS_NM == 3440.065
