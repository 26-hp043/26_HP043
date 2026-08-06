"""Layer 1 작업 정밀도와 공표 확정 계약 (#179).

TECH_SPEC §1.2.1이 요구하는 세 가지를 잠근다.

- 회귀 ⓐ — 공표값이 §1.2.3의 정본 30자리와 정확히 일치한다
- 회귀 ⓑ — 공표값이 전정밀도 단일 체인과 일치한다 (단계별 확정이 남아 있지 않다)
- 회귀 ⓒ — 작업 정밀도를 올려도 출력이 바뀌지 않는다

**공표 확정은 값의 역할로 가른다** (#179 본문). 체인 중간값(``cii_ref`` ·
``required_cii``)과 판정 입력값(``attained_cii``)은 확정하지 않고 원값으로 넘긴다.
확정은 :func:`publish_layer1_canonical`을 통해 **최종 공표 시점에만** 한다.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest

from cii_platform.calc.cii_engine import calculate_required_cii
from cii_platform.calc.precision import (
    LAYER1_CANONICAL_SIGNIFICANT_DIGITS,
    LAYER1_WORKING_PRECISION,
    publish_layer1_canonical,
)
from cii_platform.calc.rating_engine import DVector, determine_rating

# Fixture 1 — BULK_CARRIER · DWT 50,000 · 2026년 (TECH_SPEC §1.2.3)
FIXTURE1 = {
    "a": Decimal("4745"),
    "c": Decimal("0.622"),
    "reference_capacity": Decimal("50000"),
    "z_factor_percent": Decimal("11"),
}
D_VECTOR = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))

#: TECH_SPEC §1.2.3 정본 30자리. 값 산출·대조는 데이터·문서 담당(sky01170851, 확인 9).
CANONICAL = {
    "cii_ref": Decimal("5.66861385673728321407947925818"),
    "required_cii": Decimal("5.04506633249618206053073653978"),
    "superior_boundary": Decimal("4.33875704594671657205643342421"),
    "lower_boundary": Decimal("4.74236235254641113689889234739"),
    "upper_boundary": Decimal("5.34777031244595298416258073217"),
    "inferior_boundary": Decimal("5.95317827234549483142626911694"),
}


def _publish30(value: Decimal) -> Decimal:
    """비교 기준용 유효숫자 30자리 확정. 구현과 독립된 경로로 계산한다."""
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 200, ROUND_HALF_UP
        return value.quantize(Decimal(1).scaleb(value.adjusted() - 29))


def _chain(prec: int) -> dict[str, Decimal]:
    """서비스 구조 그대로의 체인을 임의 정밀도로 계산한다 (중간 확정 없음)."""
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = prec, ROUND_HALF_UP
        ref = FIXTURE1["a"] * (FIXTURE1["reference_capacity"].ln() * -FIXTURE1["c"]).exp()
        req = ref * (Decimal("1") - FIXTURE1["z_factor_percent"] / Decimal("100"))
        return {
            "cii_ref": ref,
            "required_cii": req,
            "superior_boundary": req * D_VECTOR.d1,
            "lower_boundary": req * D_VECTOR.d2,
            "upper_boundary": req * D_VECTOR.d3,
            "inferior_boundary": req * D_VECTOR.d4,
        }


# ── 공표 헬퍼 단위 검증 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 정수부 1자리 → 소수 29자리
        ("5.668613856737283214079479258178", "5.66861385673728321407947925818"),
        # 정수부 2자리 → 소수 28자리. 고정 exponent quantize였다면 여기서 어긋난다
        ("10.09311054768270080670948883677", "10.0931105476827008067094888368"),
        # 음수도 부호를 보존한다 (margin_ratio는 음수가 될 수 있다)
        ("-0.3653700000000000000000000000004", "-0.365370000000000000000000000000"),
    ],
)
def test_publish_keeps_significant_digits(raw: str, expected: str) -> None:
    """「30자리」는 유효숫자다 — 정수부 자릿수가 달라도 유효숫자는 30을 유지한다."""
    published = publish_layer1_canonical(Decimal(raw))

    assert published == Decimal(expected)
    digits = len(published.as_tuple().digits)
    assert digits <= LAYER1_CANONICAL_SIGNIFICANT_DIGITS


def test_publish_works_outside_layer1_context() -> None:
    """호출 컨텍스트가 기본값(prec=28)이어도 InvalidOperation이 나지 않는다.

    전역 prec을 넓히지 않기로 했으므로(#179), 헬퍼가 스스로 컨텍스트를 고정해야 한다.
    """
    with localcontext() as ctx:
        ctx.prec = 28
        published = publish_layer1_canonical(Decimal("5.668613856737283214079479258178"))

    assert published == CANONICAL["cii_ref"]


def test_publish_rejects_non_finite() -> None:
    """비유한값은 공표 지점에서도 막는다 (§1.2.5와 같은 취지)."""
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError, match="non-finite"):
            publish_layer1_canonical(Decimal(bad))


def test_publish_zero_has_no_sign() -> None:
    """0은 부호 있는 0을 만들지 않는다."""
    assert publish_layer1_canonical(Decimal("-0")) == Decimal(0)
    assert publish_layer1_canonical(Decimal("0")).is_signed() is False


# ── 회귀 ⓐ · 정본 30자리 일치 ──────────────────────────────────────────


def test_regression_a_canonical_match() -> None:
    """공표 헬퍼를 경유한 6개 값이 TECH_SPEC §1.2.3 정본과 정확히 일치한다.

    **raw 반환값을 직접 비교하지 않는다.** 체인 중간값은 작업 정밀도로 유지되므로,
    정본 대조는 공표 확정을 통과시킨 뒤에 한다 (#179 완료 기준 ⓐ).
    """
    required = calculate_required_cii(**FIXTURE1)
    rating = determine_rating(
        attained_cii=Decimal("4.9824"),
        required_cii=required.required_cii,
        d_vector=D_VECTOR,
    )

    produced = {
        "cii_ref": required.cii_ref,
        "required_cii": required.required_cii,
        **rating.boundaries,
    }

    for name, canonical in CANONICAL.items():
        assert publish_layer1_canonical(produced[name]) == canonical, name


# ── 회귀 ⓑ · 전정밀도 단일 체인과 일치 ────────────────────────────────


def test_regression_b_matches_full_precision_chain() -> None:
    """공표값이 전정밀도 단일 체인과 일치한다 — 단계별 확정이 남아 있지 않다.

    Fixture 1로는 이 회귀가 검사되지 않는다. 발현 ⑵는 파라미터에 따라 나타나며
    Fixture 1의 경계 4개는 발현 ⑴만 제거해도 전부 일치한다(#179 본문).
    아래는 실제로 갈리는 체인 분기 케이스다.
    """
    a, c = Decimal("4745"), Decimal("0.622")
    capacity, z, d = Decimal("20000"), Decimal("5"), Decimal("0.86")

    required = calculate_required_cii(a=a, c=c, reference_capacity=capacity, z_factor_percent=z)
    rating = determine_rating(
        attained_cii=Decimal("1"),
        required_cii=required.required_cii,
        d_vector=DVector(d1=d, d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18")),
    )

    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 150, ROUND_HALF_UP
        ref = a * (capacity.ln() * -c).exp()
        req = ref * (Decimal("1") - z / Decimal("100"))
        expected = _publish30(req * d)

    assert publish_layer1_canonical(rating.boundaries["superior_boundary"]) == expected


# ── 회귀 ⓒ · 불변성 ───────────────────────────────────────────────────


def test_regression_c_invariance_under_higher_precision() -> None:
    """작업 정밀도 P · P+10 · P+20에서 공표값이 동일하다 (§1.2.1 불변성 검사).

    자릿수를 조금 올리는 것으로는 부족하다 — 31자리는 반대 방향으로 틀린다.
    판정 기준은 정밀도 값이 아니라 결과의 안정성이다.
    """
    p = LAYER1_WORKING_PRECISION
    baseline = {k: _publish30(v) for k, v in _chain(p).items()}

    for offset in (10, 20):
        higher = {k: _publish30(v) for k, v in _chain(p + offset).items()}
        assert higher == baseline, f"prec={p + offset}"

    # 기준이 정본과도 맞는지 함께 확인한다 — 안정적이지만 틀린 값을 잡기 위함.
    assert baseline == CANONICAL
