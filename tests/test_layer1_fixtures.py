"""픽스처 기반 Layer 1 대조 — `TEST_PLAN §1.2` · `§1.3` · `§9.1` (#45 · #46).

**이 파일이 픽스처의 존재 이유다.** 픽스처는 값을 적어 두는 곳이 아니라,
서비스 산출값이 정본과 일치하는지 검사하는 기준이다. 검사하는 코드가 없으면
값이 틀려도 아무도 모른다 — `#179`가 그 상태였다.

기대값을 코드에 직접 적지 않는다. `TEST_PLAN §1.2`가 정본이고 픽스처가 그
사본이므로, 코드에 다시 적으면 세 번째 사본이 생긴다.
"""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fixture_loader import assert_layer1_equal, load_fixture

from cii_platform.calc.cii_engine import (
    FuelUse,
    calculate_attained_cii,
    calculate_required_cii,
)
from cii_platform.calc.precision import layer1_context, publish_layer1_canonical
from cii_platform.calc.rating_engine import DVector, determine_rating

FIXTURE_1 = "cii/bulk_50000_hfo_2026.json"
FIXTURE_2 = "cii/rating_boundaries_bulk_2026.json"

_ROOT = Path(__file__).resolve().parent.parent

# ────────────────────────────────────────────────────────────────────────────
# 픽스처 `input` → 규제 파라미터
#
# **키가 없으면 `KeyError`로 실패한다.** 픽스처의 `input`이 바뀌었는데 테스트가
# 옛 조건으로 계속 통과하는 상태를 막기 위해서다 — 그러면 `input` 블록이
# 「쓰이지 않는 장식 데이터」가 되고, 픽스처가 자립한다는 주장이 성립하지 않는다.
#
# 값은 프로젝트 정본에서 옮긴다. 생성기(`scripts/gen_fixtures.py`)는 규정 원문에서
# 독립 전사하지만, **테스트는 서비스와 정본을 대조하는 쪽**이라 정본을 인용한다.
# ────────────────────────────────────────────────────────────────────────────

#: 선종 → reference line 계수 `(a, c)`. `PRD §3.4.1` · `MEPC.353(78) Table 1`.
_REFERENCE_LINE = {
    "BULK_CARRIER": (Decimal("4745"), Decimal("0.622")),  # DWT < 279,000
}

#: 규제 연도 → 감축률 Z (%). `PRD §3.4.4` · `MEPC.400(83)`.
_Z_FACTOR_PERCENT = {
    2026: Decimal("11"),
}

#: 선종 → d-vector. `PRD §3.3.6` · `MEPC.354(78) Table 1`.
_D_VECTORS = {
    "BULK_CARRIER": DVector(Decimal("0.86"), Decimal("0.94"), Decimal("1.06"), Decimal("1.18")),
}


def _required_and_dvector(spec: dict):
    """픽스처 `input`의 **세 필드를 전부 소비해** `required_cii`와 d-vector를 만든다.

    ``ship_type``이 계수와 d-vector를, ``regulation_year``가 감축률을,
    ``deadweight``가 capacity를 정한다. 하나라도 하드코딩하면 그 필드는
    픽스처에 적혀 있어도 **아무 영향을 주지 않는 장식**이 된다.
    """
    a, c = _REFERENCE_LINE[spec["ship_type"]]
    z = _Z_FACTOR_PERCENT[spec["regulation_year"]]
    required = calculate_required_cii(a, c, Decimal(str(spec["deadweight"])), z)
    return required, _D_VECTORS[spec["ship_type"]]


def _compute(fixture: dict):
    """`§1.2`의 `input`으로 서비스 계산을 돌린다.

    입력을 픽스처에서 읽는 이유는, 코드에 입력을 적으면 픽스처의 `input`이
    바뀌어도 테스트가 옛 입력을 계속 쓰기 때문이다.
    """
    spec = fixture["input"]
    fuel_uses = [
        FuelUse(u["fuel_type"], Decimal(str(u["fuel_ton"])), Decimal(str(u["cf"])))
        for u in spec["fuel_uses"]
    ]
    attained = calculate_attained_cii(
        fuel_uses,
        Decimal(str(spec["deadweight"])),
        Decimal(str(spec["distance_nm"])),
    )
    required, d_vector = _required_and_dvector(spec)
    return attained, required, d_vector


# ────────────────────────────────────────────────────────────────────────────
# Fixture 1 — TEST_PLAN §1.2
# ────────────────────────────────────────────────────────────────────────────


def test_fixture_1_integer_values_are_bit_exact():
    """정수값은 bit-exact 비교다 (`§9.1`). 표기 자릿수는 결과를 바꾸지 않는다."""
    fixture = load_fixture(FIXTURE_1)
    attained, _, _ = _compute(fixture)
    assert_layer1_equal(str(attained.total_co2_g), fixture["expected"]["co2_emission_g"])


@pytest.mark.parametrize(
    "field",
    ["co2_emission_ton", "attained_cii"],
)
def test_fixture_1_terminating_values(field: str):
    """나누어떨어지는 값은 **수학적 최소 표기**로 적힌다 (`§1.2.1` 표기 조항 1).

    `4.982400`이 아니라 `4.9824`, `249.120`이 아니라 `249.12`다.
    후행 0은 정밀도 정보가 아니라 `CF` 표기의 부산물이었다.
    """
    fixture = load_fixture(FIXTURE_1)
    attained, _, _ = _compute(fixture)
    actual = {"co2_emission_ton": attained.total_co2_t, "attained_cii": attained.attained_cii}[
        field
    ]
    assert_layer1_equal(str(actual), fixture["expected"][field])
    assert "." not in fixture["expected"][field] or not fixture["expected"][field].endswith("0"), (
        f"{field}에 후행 0이 남아 있다: {fixture['expected'][field]}"
    )


@pytest.mark.parametrize("field", ["cii_ref", "required_cii"])
def test_fixture_1_canonical_chain_values(field: str):
    """`cii_ref` · `required_cii`는 **정본값 30자리**로 확정 비교한다.

    서비스는 작업 정밀도 원값(50자리)을 반환하므로, `§9.1`이 규정한 대로
    `publish_layer1_canonical`을 거쳐야 픽스처와 맞는다.
    """
    fixture = load_fixture(FIXTURE_1)
    _, required, _ = _compute(fixture)
    assert_layer1_equal(str(getattr(required, field)), fixture["expected"][field])


@pytest.mark.parametrize(
    "field",
    ["superior_boundary", "lower_boundary", "upper_boundary", "inferior_boundary"],
)
def test_fixture_1_boundaries(field: str):
    """등급 경계 4개도 정본값 30자리로 일치한다."""
    fixture = load_fixture(FIXTURE_1)
    attained, required, d_vector = _compute(fixture)
    result = determine_rating(attained.attained_cii, required.required_cii, d_vector)
    assert_layer1_equal(str(result.boundaries[field]), fixture["expected"][field])


def test_fixture_1_rating():
    """등급은 **확정 전 원값**으로 판정한다 (`§1.2.1` · `PRD §13.1 [EXT-P0-3]`)."""
    fixture = load_fixture(FIXTURE_1)
    attained, required, d_vector = _compute(fixture)
    result = determine_rating(attained.attained_cii, required.required_cii, d_vector)
    assert result.rating == fixture["expected"]["estimated_rating"]


def test_fixture_1_ratio_must_use_unpublished_denominator():
    """`ratio_to_required`의 분모는 **확정 전 원값**이다 (`§1.2.1` 「중간 단계 처리」).

    확정된 30자리 `required_cii`로 나누면 끝자리가 갈린다. 두 값 모두 30자리로
    확정되지만 27번째 자리부터 다르므로, **자릿수가 맞다고 정밀도가 맞는 것이
    아니다.** 이 테스트가 없으면 회귀가 조용히 통과한다.
    """
    fixture = load_fixture(FIXTURE_1)
    attained, required, d_vector = _compute(fixture)
    expected = Decimal(fixture["expected"]["ratio_to_required"])

    @layer1_context
    def ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
        return numerator / denominator

    from_raw = publish_layer1_canonical(ratio(attained.attained_cii, required.required_cii))
    assert from_raw == expected

    from_published = publish_layer1_canonical(
        ratio(attained.attained_cii, publish_layer1_canonical(required.required_cii))
    )
    assert from_published != expected, (
        "확정값을 분모로 써도 같은 값이 나온다면 이 회귀는 더 이상 검사되지 않는다"
    )


def test_fixture_1_derived_value_needs_working_precision():
    """파생값을 **적용 지점 밖에서** 계산하면 기본 정밀도(28)로 계산된다.

    전역 `prec`을 넓히지 않기로 한 결과다(`§1.2.1` 「작업 정밀도의 적용 지점」).
    `#55`가 `ratio_to_required`를 계산할 때 정확히 이 지점에 걸린다.
    """
    fixture = load_fixture(FIXTURE_1)
    attained, required, d_vector = _compute(fixture)
    expected = Decimal(fixture["expected"]["ratio_to_required"])

    outside = publish_layer1_canonical(attained.attained_cii / required.required_cii)
    assert outside != expected, "전역 정밀도가 넓어졌다면 §1.2.1의 적용 지점 규칙이 깨진 것이다"


def test_fixture_1_canonical_digits_block_matches_values():
    """`canonical_digits`가 가리키는 필드가 실제로 그 자릿수로 적혀 있어야 한다.

    표기 조항 1이 「확정 자릿수와 대상 필드를 픽스처 안에 적는다」고 요구하는데,
    블록과 값이 어긋나면 그 기재가 거짓말이 된다.
    """
    fixture = load_fixture(FIXTURE_1)
    digits = fixture["canonical_digits"]["significant"]
    for field in fixture["canonical_digits"]["fields"]:
        value = Decimal(fixture["expected"][field])
        assert len(value.as_tuple().digits) == digits, (
            f"{field}의 유효숫자가 {len(value.as_tuple().digits)}자리다 (기대 {digits})"
        )


# ────────────────────────────────────────────────────────────────────────────
# Fixture 2 — TEST_PLAN §1.3
# ────────────────────────────────────────────────────────────────────────────


#: `§1.3` `boundaries` 키 → 엔진 `RatingResult.boundaries` 키.
_BOUNDARY_KEY = {
    "superior": "superior_boundary",
    "lower": "lower_boundary",
    "upper": "upper_boundary",
    "inferior": "inferior_boundary",
}


def _raw_boundaries():
    """`§1.3`의 `input` 조건으로 **확정 전 원경계**를 재계산한다.

    픽스처의 `boundaries`는 **공표 자릿수로 확정한 기록**이라 판정에 쓸 수 없다.
    `§1.2.1`이 「판정은 확정 전 원값으로」를 규정하므로 여기서 다시 만든다.

    `input`의 **세 필드를 전부 소비한다**(`_required_and_dvector`). 하나라도
    하드코딩하면 `input`이 장식 데이터가 되고, 조건이 바뀌어도 테스트가 옛
    값으로 계속 통과한다.
    """
    spec = load_fixture(FIXTURE_2)["input"]
    required, d_vector = _required_and_dvector(spec)
    # 판정 입력은 여기서 쓰지 않는다 — 경계만 얻는다. 어떤 값을 넣어도 경계는 같다.
    boundaries = determine_rating(Decimal("4.9824"), required.required_cii, d_vector).boundaries
    return required, boundaries, d_vector


def test_fixture_2_shares_canonical_values_with_fixture_1():
    """두 픽스처의 정본값이 **글자까지 같아야** 한다.

    같은 값을 다른 자릿수로 적으면 어느 쪽이 정본인지 알 수 없다.
    """
    f1 = load_fixture(FIXTURE_1)["expected"]
    f2 = load_fixture(FIXTURE_2)
    assert f2["base_required_cii"] == f1["required_cii"]
    for short, long in _BOUNDARY_KEY.items():
        assert f2["boundaries"][short] == f1[long], f"{short} 경계가 §1.2와 다르다"


def test_fixture_2_cases_are_symbolic():
    """케이스는 **구체적인 `attained_cii`를 담지 않는다** (`§1.3` · `#46`).

    구체값을 적으면 그 값이 곧 틀린 입력이 된다 — `boundaries`는 확정값이고
    판정은 확정 전 원값과 비교하므로, 올림된 경계에서 등급이 뒤집힌다.
    """
    f2 = load_fixture(FIXTURE_2)
    for case in f2["cases"]:
        assert "attained_cii" not in case, "케이스에 구체값이 다시 들어왔다"
        assert case["boundary"] in _BOUNDARY_KEY, f"알 수 없는 경계: {case['boundary']}"
        Decimal(case["offset"])  # 파싱 가능한 십진 문자열이어야 한다
    assert "cases[].attained_cii" not in f2["canonical_digits"]["fields"]


def test_fixture_2_case_boundary_coverage():
    """경계 4개가 각각 `offset = 0` 케이스로 한 번씩 덮여야 한다.

    하나가 빠지면 그 경계의 「경계값 = 더 우수한 등급」이 검증되지 않는다.
    """
    f2 = load_fixture(FIXTURE_2)
    zero_offset = [c["boundary"] for c in f2["cases"] if Decimal(c["offset"]) == 0]
    assert sorted(zero_offset) == sorted(_BOUNDARY_KEY), zero_offset
    assert [c["expected_rating"] for c in f2["cases"] if Decimal(c["offset"]) == 0] == [
        "A",
        "B",
        "C",
        "D",
    ]


def test_fixture_2_e_case_offset():
    """E 케이스는 `inferior`에 `0.000001`을 더한 것이다."""
    case = load_fixture(FIXTURE_2)["cases"][4]
    assert case["boundary"] == "inferior"
    assert Decimal(case["offset"]) == Decimal("0.000001")
    assert case["expected_rating"] == "E"


@pytest.mark.parametrize("index", range(5))
def test_fixture_2_rating_cases(index: int):
    """판정 5건 — 입력을 **확정 전 원경계 + `offset`** 으로 만들어 검증한다.

    `PRD §3.3.6` — `attained == 경계`면 더 우수한 등급.
    """
    f2 = load_fixture(FIXTURE_2)
    case = f2["cases"][index]
    required, boundaries, d_vector = _raw_boundaries()

    @layer1_context
    def shift(base: Decimal, offset: Decimal) -> Decimal:
        return base + offset

    attained = shift(boundaries[_BOUNDARY_KEY[case["boundary"]]], Decimal(case["offset"]))
    result = determine_rating(attained, required.required_cii, d_vector)
    assert result.rating == case["expected_rating"], case["note"]


def test_fixture_2_boundaries_are_published_form_of_raw():
    """`boundaries`에 적힌 30자리가 **원경계의 공표 형태**인지 확인한다.

    이것이 성립해야 `boundary` 키가 가리키는 대상이 하나로 정해진다.
    """
    f2 = load_fixture(FIXTURE_2)
    _, boundaries, _ = _raw_boundaries()
    for short, long in _BOUNDARY_KEY.items():
        assert_layer1_equal(str(boundaries[long]), f2["boundaries"][short])


def test_fixture_2_published_boundary_flips_rating():
    """**확정한 경계값을 판정 입력으로 쓰면 규칙이 뒤집힌다.**

    공표 확정이 **올림**되면 확정값이 원래 경계보다 커져 `PRD §3.3.6`의 `<=`가
    깨진다. `upper`·`inferior`가 그 경우다. `#179` 조사에서 경계 정착 1,820건 중
    **919건(50.49%)** 에서 등급이 뒤집힌 것과 같은 현상이다.

    이 테스트가 실패하면 둘 중 하나다 — 확정 방향이 바뀌었거나, 판정이 확정
    전 원값을 쓰지 않게 됐거나. **둘 다 `§1.2.1` 위반이므로 조사 대상이다.**

    `§1.3`이 케이스를 기호 표기로 바꾼 근거가 이 테스트다. 구체값을 적으면
    그 값이 곧 여기서 뒤집히는 입력이 된다.
    """
    required, boundaries, d_vector = _raw_boundaries()

    flipped = []
    for short, expected in zip(["superior", "lower", "upper", "inferior"], "ABCD", strict=True):
        raw = boundaries[_BOUNDARY_KEY[short]]
        published = publish_layer1_canonical(raw)
        if determine_rating(published, required.required_cii, d_vector).rating != expected:
            flipped.append(short)
            assert published > raw, f"{short}: 뒤집혔는데 확정이 올림이 아니다"

    assert flipped == ["upper", "inferior"], (
        f"뒤집히는 경계가 바뀌었다: {flipped} (기대 ['upper', 'inferior']). "
        "확정 방향이 바뀌었거나 판정이 확정값을 쓰게 된 신호다"
    )


# ────────────────────────────────────────────────────────────────────────────
# 생성기 계약 — TEST_PLAN §1.7
# ────────────────────────────────────────────────────────────────────────────


def test_generator_does_not_import_service_code():
    """생성기가 서비스 코드를 import하면 독립성이 깨진다 (`§1.7` 조건 1).

    서비스로 기준값을 만들면 서비스의 오류가 그대로 정답이 되어, 테스트는
    통과하는데 값은 틀린 상태가 된다. `#179`가 그 상태였다.
    """
    source = (_ROOT / "scripts" / "gen_fixtures.py").read_text(encoding="utf-8")
    offending = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "cii_platform" in line
    ]
    assert offending == [], f"생성기가 서비스 코드를 import한다: {offending}"


def test_generator_reproduces_fixture_files():
    """생성기를 다시 돌리면 저장된 픽스처와 같은 내용이 나온다.

    값을 손으로 고치고 생성기를 갱신하지 않으면 여기서 걸린다.
    """
    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "gen_fixtures.py")],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "불변성 검사 통과" in result.stdout
    assert "정본값 6개 재현 확인" in result.stdout

    for name in ("bulk_50000_hfo_2026.json", "rating_boundaries_bulk_2026.json"):
        stored = (_ROOT / "tests" / "fixtures" / "cii" / name).read_text(encoding="utf-8")
        # 생성기 출력은 파일별 구획 뒤에 붙는다. 값 몇 개로 동등성을 확인한다.
        for line in stored.splitlines():
            if '": "' in line and any(
                k in line for k in ("cii_ref", "required_cii", "attained_cii")
            ):
                assert line.strip() in result.stdout.replace("\n", "\n"), f"{name}: {line.strip()}"


def test_fixture_files_match_test_plan():
    """픽스처 파일이 `TEST_PLAN §1.2`·`§1.3`의 `json` 블록과 **완전히 같아야** 한다.

    정본과 파일이 갈리면 어느 쪽이 기준인지 알 수 없다. 문서만 고치고 파일을
    두거나 그 반대로 두는 드리프트를 여기서 막는다 — `#166`이 그 상태를
    정리하는 데 커밋 4건을 썼다.
    """
    import json
    import re

    doc = (_ROOT / "TEST_PLAN.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", doc, re.S)
    pairs = [
        (json.loads(blocks[0]), load_fixture(FIXTURE_1), "§1.2"),
        (json.loads(blocks[1]), load_fixture(FIXTURE_2), "§1.3"),
    ]
    for spec, stored, section in pairs:
        assert spec == stored, f"TEST_PLAN {section}와 픽스처 파일이 다르다"


def test_fixture_2_input_is_actually_consumed():
    """`§1.3`의 `input` **세 필드가 전부 판정 경로에 쓰이는지** 확인한다.

    A안은 판정 입력을 `input`으로 재계산한 원경계에서 만든다. 그런데 재계산이
    조건 일부를 하드코딩하면 **`input`은 적혀만 있고 아무 영향을 주지 않는
    장식 데이터**가 된다. 그러면 조건이 바뀌어도 테스트가 옛 값으로 계속
    통과하므로, 「픽스처가 자립한다」는 주장이 성립하지 않는다.

    필드를 하나씩 다른 값으로 바꿔 **결과가 실제로 달라지는지**로 검사한다.
    지원하지 않는 값이면 `KeyError`가 나므로 그것도 소비의 증거로 본다.
    """
    spec = dict(load_fixture(FIXTURE_2)["input"])
    baseline, _ = _required_and_dvector(spec)

    # deadweight — capacity가 바뀌면 required_cii가 바뀐다
    changed = {**spec, "deadweight": spec["deadweight"] * 2}
    assert _required_and_dvector(changed)[0].required_cii != baseline.required_cii

    # regulation_year — 지원 목록에 없으면 KeyError. 조회에 실제로 쓰인다는 뜻이다
    with pytest.raises(KeyError):
        _required_and_dvector({**spec, "regulation_year": 2099})

    # ship_type — 계수·d-vector 조회에 쓰인다
    with pytest.raises(KeyError):
        _required_and_dvector({**spec, "ship_type": "TANKER"})


def test_fixture_1_and_2_inputs_describe_the_same_ship():
    """두 픽스처의 `input`이 **같은 선박·연도**를 가리켜야 한다.

    `§1.3`의 경계는 `§1.2`와 같은 정본값이다. 조건이 갈리면 `boundaries` 대조
    (`test_fixture_2_shares_canonical_values_with_fixture_1`)가 우연히 통과하는
    상태가 된다.
    """
    f1 = load_fixture(FIXTURE_1)["input"]
    f2 = load_fixture(FIXTURE_2)["input"]
    for key in ("ship_type", "deadweight", "regulation_year"):
        assert f1[key] == f2[key], f"{key}: §1.2={f1[key]} · §1.3={f2[key]}"
