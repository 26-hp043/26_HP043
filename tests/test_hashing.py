"""Content hash 단위 테스트 (#42).

TEST_PLAN §2.5 UT-HASH-001~005 + 지수 표기 회귀 · golden hash · DB 제약 형식.
"""

import re
from decimal import Decimal

import pytest

from cii_platform.calc.hash import (
    DEFAULT_WEATHER_FACTOR,
    INPUT_FIELDS,
    _decimal_to_canonical_str,
    canonical_json,
    compute_input_hash,
    compute_parameter_hash,
)
from cii_platform.db.seed import SEED_REFERENCE_LINES

# --- 픽스처 (TECH_SPEC §5.2.1 스키마 형태) --------------------------------------
# 문서 예시를 그대로 쓰지 않고 자체 정의한다. 이 테스트의 목적은 "직렬화 경로가
# 바뀌지 않았다"이지 "문서 예시가 바뀌지 않았다"가 아니라서, 문서 쪽 변경으로 깨지면
# 신호가 흐려진다.

# parameter_source_version은 값 규격이 미확정이다(seed.PARAMETER_SET_VERSION "1.0"
# vs TECH_SPEC §5.2.1 예시 "imo-mepc-2024-q1"). golden은 이 문자열을 포함하므로
# 규격 확정 시 재산출이 필요하다 — 직렬화 회귀와 구분할 것.
PARAMETERS_USED = {
    "regulation_year": {"year": "2026", "z_factor_percent": Decimal("11.0000")},
    "fuel_types": [{"code": "HFO", "cf": Decimal("3.114000")}],
    # reference_line은 발산 값(14405E7 → a_decimal 144050000000)을 쓴다. 비발산 값만
    # 담으면 str(normalize()) 방식으로 되돌려도 golden hash가 그대로 통과해, 이 픽스처가
    # 지수 표기 경로를 잠그지 못한다.
    "reference_line": {
        "ship_type": "GAS_CARRIER",
        "reference_capacity_rule": "DWT",
        "a_decimal": Decimal("144050000000"),
        "c": Decimal("2.071000"),
    },
    "rating_boundary": {
        "d1": Decimal("0.8600"),
        "d2": Decimal("0.9400"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.1800"),
    },
    "parameter_source_version": "1.0",
}

# transport_capacity·reference_capacity·distance_nm은 trailing zero가 있는 값이라
# str(normalize()) 방식으로 되돌리면 GOLDEN_INPUT_HASH가 깨진다. 값 변경 시 이 성질을
# 유지할 것 — PARAMETERS_USED.reference_line과 같은 이유다.
CALCULATION_INPUT = {
    "vessel_id": "test-vessel-uuid",
    "regulation_year": "2026",
    "ship_type": "BULK_CARRIER",
    "transport_capacity": Decimal("50000"),
    "reference_capacity": Decimal("50000"),
    "distance_nm": Decimal("1000"),
    "speed_kn": Decimal("12.0"),
    "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": Decimal("80.0"), "cf": Decimal("3.114")}],
    "weather_model": "NONE",
    "weather_factor": None,
}

# 위 픽스처의 고정 해시. 키 정렬 · separators · Decimal 포맷(지수 표기 포함) ·
# UTF-8 인코딩까지 전 경로가 이 값 하나로 잠긴다.
GOLDEN_PARAMETER_HASH = "sha256:7519b4c70df21767054f7e1620523c532397212bba455487bd194e2f9324d33e"
GOLDEN_INPUT_HASH = "sha256:90f1c6c813d62231a6753eabc8cc6fb9db84dec9702c39185ee512eb9c7ae44f"

HASH_FORMAT = re.compile(r"^sha256:[0-9a-f]{64}$")


# --- TEST_PLAN §2.5 -------------------------------------------------------------


def test_ut_hash_001_deterministic():
    """UT-HASH-001 — 동일 파라미터는 항상 동일 hash."""
    assert compute_parameter_hash(PARAMETERS_USED) == compute_parameter_hash(PARAMETERS_USED)
    assert compute_parameter_hash(PARAMETERS_USED) == GOLDEN_PARAMETER_HASH


def test_ut_hash_001b_changed_parameter_changes_hash():
    """파라미터 1개만 바꿔도 hash가 달라진다 (이슈 완료 기준)."""
    changed = {**PARAMETERS_USED, "parameter_source_version": "1.1"}
    assert compute_parameter_hash(changed) != GOLDEN_PARAMETER_HASH


def test_ut_hash_002_trailing_zeros_normalized():
    """UT-HASH-002 — Decimal trailing zero는 정규화되어 같은 hash."""
    assert canonical_json({"cf": Decimal("3.114")}) == canonical_json({"cf": Decimal("3.114000")})
    assert canonical_json({"x": Decimal("1.0")}) == canonical_json({"x": Decimal("1")})


def test_ut_hash_003_key_order_irrelevant():
    """UT-HASH-003 — 키 순서가 달라도 동일 hash."""
    reversed_order = dict(reversed(list(PARAMETERS_USED.items())))
    assert compute_parameter_hash(reversed_order) == GOLDEN_PARAMETER_HASH


@pytest.mark.parametrize(
    "payload",
    [
        {"x": 1.0},
        {"a": {"b": 1.0}},
        {"a": [{"b": 1.0}]},
        {"a": (1.0,)},
    ],
)
def test_ut_hash_004_float_rejected(payload):
    """UT-HASH-004 [ORACLE-M-4] — float는 중첩 위치에서도 TypeError."""
    with pytest.raises(TypeError, match="float not allowed"):
        canonical_json(payload)


def test_ut_hash_005_weather_factor_none_uses_default():
    """UT-HASH-005 [ORACLE-S-5] — weather_factor가 None이면 1.0으로 간주."""
    explicit = {**CALCULATION_INPUT, "weather_factor": DEFAULT_WEATHER_FACTOR}

    assert compute_input_hash(CALCULATION_INPUT) == compute_input_hash(explicit)
    assert compute_input_hash(CALCULATION_INPUT) == GOLDEN_INPUT_HASH


# --- 지수 표기 회귀 (#42 코멘트 1항) ----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # seed a_decimal 중 str(normalize())와 결과가 갈리는 6행. 기대값은 리터럴로
        # 박는다 — 계산해서 비교하면 구현이 틀려도 통과한다.
        ("144050000000", "144050000000"),  # 14405E7
        ("4600", "4600"),
        ("144790000000000", "144790000000000"),  # 14479E10
        ("147790000000000", "147790000000000"),  # 14779E10
        ("330", "330"),
        ("930", "930"),
        # 발산하지 않는 대조군
        ("3627", "3627"),
        ("3.114000", "3.114"),
        # 음수 지수 — normalize()가 1E-7을 만드는 구간
        ("0.0000001", "0.0000001"),
        ("1E-7", "0.0000001"),
    ],
)
def test_decimal_canonical_str_avoids_scientific_notation(raw, expected):
    """[ORACLE-C-2] normalize() 후 고정 소수점 변환이 유지되는지 잠근다."""
    assert _decimal_to_canonical_str(Decimal(raw)) == expected


def test_seed_a_decimal_never_serializes_as_scientific():
    """seed의 a_decimal 20행 전건이 지수 표기로 새지 않는지 확인한다.

    헬퍼가 아니라 :func:`canonical_json`을 통과시킨다. 헬퍼만 직접 호출하면 인코더
    배선이 끊어져도(= canonical_json이 헬퍼를 더 이상 부르지 않게 되어도) 통과한다.
    """
    for line in SEED_REFERENCE_LINES:
        serialized = canonical_json({"a_decimal": line.a_decimal})
        assert "E+" not in serialized, f"{line.ship_type}: {serialized}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("144050000000", '{"a":"144050000000"}'),  # 14405E7
        ("4600", '{"a":"4600"}'),
        ("144790000000000", '{"a":"144790000000000"}'),  # 14479E10
        ("147790000000000", '{"a":"147790000000000"}'),  # 14779E10
        ("330", '{"a":"330"}'),
        ("930", '{"a":"930"}'),
    ],
)
def test_divergent_values_through_canonical_json(raw, expected):
    """발산 6값이 직렬화 경로 전체를 통과해도 고정 소수점으로 남는지 잠근다.

    위 문자열 단위 테스트와 중복되지만 층이 다르다 — 이쪽은 파이프라인 단위다.
    """
    assert canonical_json({"a": Decimal(raw)}) == expected


# --- 직렬화 세부 규칙 (TECH_SPEC §5.1.1) ------------------------------------------


def test_none_serialized_as_null_not_omitted():
    """[ORACLE-M-3] None은 JSON null이며 필드를 생략하지 않는다."""
    assert canonical_json({"a": None, "b": "x"}) == '{"a":null,"b":"x"}'


def test_minified_and_utf8_preserved():
    """공백 없음(minified) · ensure_ascii=False로 한글이 이스케이프되지 않는다."""
    assert canonical_json({"name": "벌크선", "n": Decimal("1")}) == '{"n":"1","name":"벌크선"}'


def test_numeric_array_order_preserved():
    """§5.1.1 — 수치 배열은 원래 순서를 유지한다(정렬하지 않음)."""
    unsorted = {"d": [Decimal("3"), Decimal("1"), Decimal("2")]}
    assert canonical_json(unsorted) == '{"d":["3","1","2"]}'


def test_int_and_bool_pass_through():
    """정본 §5.1.2 동작 고정 — int·bool은 JSON 숫자/불리언으로 통과한다.

    ``{"year": 2026}``과 ``{"year": "2026"}``이 다른 해시를 내는 것은 의도된 동작이다.
    float와 달리 int는 표현이 결정적이라 재현성 문제가 없으며, 값을 문자열로 넘기는
    것은 §5.2.1 스키마가 정한 호출부 규약이다.
    """
    assert canonical_json({"year": 2026}) == '{"year":2026}'
    assert canonical_json({"year": "2026"}) == '{"year":"2026"}'
    assert canonical_json({"flag": True}) == '{"flag":true}'


def test_special_decimal_values_are_unspecified_behavior():
    """정본 미규정 구간의 현재 동작을 기록한다.

    TECH_SPEC §5.1은 NaN·Infinity·음수 0을 규정하지 않는다. 코드에 별도 처리를 넣지
    않았으므로 아래는 "현재 이렇게 동작한다"는 기록이며, 정본이 규정을 추가하면 이
    테스트도 함께 갱신한다.
    """
    assert canonical_json({"x": Decimal("NaN")}) == '{"x":"NaN"}'
    assert canonical_json({"x": Decimal("Infinity")}) == '{"x":"Infinity"}'
    assert canonical_json({"x": Decimal("-0.0")}) == '{"x":"-0"}'


# --- INPUT_FIELDS 계약 ------------------------------------------------------------


def test_input_fields_locked():
    """§5.3 필드 목록과 순서를 잠근다.

    이 목록이 바뀌면 이미 저장된 모든 input_hash가 무효가 되고, §5.4 재현성 계약
    2항이 이 목록을 전제로 서 있다. 변경 시 마이그레이션 판단이 필요하다.
    """
    assert INPUT_FIELDS == (
        "vessel_id",
        "regulation_year",
        "ship_type",
        "transport_capacity",
        "reference_capacity",
        "distance_nm",
        "speed_kn",
        "fuel_uses",
        "weather_model",
        "weather_factor",
    )


def test_input_hash_ignores_fields_outside_the_list():
    """목록 밖 필드는 hash에 영향을 주지 않는다."""
    noisy = {**CALCULATION_INPUT, "requested_by": "tester", "trace_id": "abc-123"}
    assert compute_input_hash(noisy) == GOLDEN_INPUT_HASH


def test_input_hash_changes_when_listed_field_changes():
    changed = {**CALCULATION_INPUT, "distance_nm": Decimal("1001")}
    assert compute_input_hash(changed) != GOLDEN_INPUT_HASH


def test_missing_optional_field_is_omitted_not_defaulted():
    """§5.3 — 목록에 있으나 입력에 없는 키는 넣지 않는다(weather_factor 제외)."""
    without_speed = {k: v for k, v in CALCULATION_INPUT.items() if k != "speed_kn"}
    assert "speed_kn" not in canonical_json(without_speed)
    assert compute_input_hash(without_speed) != GOLDEN_INPUT_HASH


# --- DB 제약 형식 (DB_SCHEMA §2.5) -------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        compute_parameter_hash(PARAMETERS_USED),
        compute_input_hash(CALCULATION_INPUT),
    ],
)
def test_hash_matches_db_constraint(value):
    """DB_SCHEMA §2.5 — VARCHAR(71) · chk_*_hash_format 정규식을 만족해야 한다.

    계산 모듈과 DB 제약의 유일한 접점이다. 여기서 어긋나면 #55의 INSERT가 실패하는
    형태로만 드러나므로 미리 잠근다.
    """
    assert len(value) == 71
    assert HASH_FORMAT.match(value)
