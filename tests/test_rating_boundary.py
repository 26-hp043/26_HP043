"""등급 판정 단위 테스트 (#39).

TEST_PLAN §2.2 UT-RATING-001~007 전건 + HSC 상속 회귀 + seed 교차검증.

**Fixture 2(`boundary_cases.json`)의 절대 경계값을 쓰지 않는다.** 그 6개 값은 #166에서
바뀔 예정이고, 이슈 본문에 적힌 값(`required = 5.045066331`로 재계산한 것)은 4개 중
3개가 마지막 자리에서 이미 틀리다. TEST_PLAN §2.2가 입력을 전부 `required`·경계에 대한
**상대값**으로 정의하고 있어 절대 리터럴 없이 7건 전부 성립한다.

기대값을 `required * d`로 다시 계산해 구현 결과와 비교하면 곱셈은 검증되지 않는다.
그래서 계산한 경계값을 **attained으로 입력**하고 더 우수한 등급이 나오는지 본다 —
이쪽은 `<=` 방향과 구간 귀속을 실제로 검증한다.
"""

import threading
from decimal import ROUND_HALF_EVEN, Context, Decimal, setcontext

import pytest

from cii_platform.calc.rating_engine import (
    RATING_BOUNDARY_FALLBACK,
    DVector,
    determine_rating,
    select_rating_boundary,
)
from cii_platform.db.seed import SEED_RATING_BOUNDARIES, SEED_REFERENCE_LINES

# --- 테스트 더블 ------------------------------------------------------------------
# ORM 모델 대신 Protocol이 읽는 속성만 가진 더블을 쓴다 (#41 test와 같은 방식).


class _V:
    def __init__(self, ship_type, deadweight=None, gross_tonnage=None):
        self.ship_type = ship_type
        self.deadweight = deadweight
        self.gross_tonnage = gross_tonnage


class _B:
    def __init__(self, ship_type, condition_expr, d1, d2, d3, d4):
        self.ship_type = ship_type
        self.condition_expr = condition_expr
        self.d1, self.d2, self.d3, self.d4 = (Decimal(x) for x in (d1, d2, d3, d4))


# PRD §3.4.4 BULK_CARRIER 행. 판정 규칙 검증용이며 선종 자체가 쟁점은 아니다.
BULK_DV = DVector(Decimal("0.86"), Decimal("0.94"), Decimal("1.06"), Decimal("1.18"))

# 정본과 무관한 임의값. 자릿수가 짧으면 함수 안에 quantize나 float이 섞여도 통과하므로
# 30자리를 쓴다. Fixture 1의 참 required를 쓰지 않는 이유는 #166이 정본화할 값에
# 테스트를 묶지 않기 위함이다.
LONG_REQUIRED = Decimal("7.123456789012345678901234567890")


def _boundaries(required, dv=BULK_DV):
    return {
        "superior": required * dv.d1,
        "lower": required * dv.d2,
        "upper": required * dv.d3,
        "inferior": required * dv.d4,
    }


# --- TEST_PLAN §2.2 UT-RATING-001~007 --------------------------------------------


@pytest.mark.parametrize(
    ("tc", "key", "expected"),
    [
        ("UT-RATING-001", "superior", "A"),
        ("UT-RATING-002", "lower", "B"),
        ("UT-RATING-003", "upper", "C"),
        ("UT-RATING-004", "inferior", "D"),
    ],
)
def test_ut_rating_001_004_boundary_exact_takes_better_grade(tc, key, expected):
    """UT-RATING-001~004 — attained == 경계값이면 더 우수한 등급 (PRD §3.3.6).

    `<`로 구현하면 네 건 전부 한 등급씩 나쁘게 나온다.
    """
    required = Decimal("100")
    attained = _boundaries(required)[key]
    assert determine_rating(attained, required, BULK_DV).rating == expected


def test_ut_rating_005_inferior_plus_epsilon_is_e():
    """UT-RATING-005 — inferior + 0.000001 → E."""
    required = Decimal("100")
    attained = _boundaries(required)["inferior"] + Decimal("0.000001")
    assert determine_rating(attained, required, BULK_DV).rating == "E"


def test_ut_rating_006_very_good_is_a():
    """UT-RATING-006 — attained = 0.1 × required → A.

    이 dv(BULK_CARRIER)에 대한 주장이다. 모든 선종에서 성립하는지는 확인하지 않았다.
    """
    required = Decimal("100")
    assert determine_rating(required * Decimal("0.1"), required, BULK_DV).rating == "A"


def test_ut_rating_007_very_bad_is_e():
    """UT-RATING-007 — attained = 2.0 × required → E. 위와 같은 dv 한정 주장이다."""
    required = Decimal("100")
    assert determine_rating(required * Decimal("2.0"), required, BULK_DV).rating == "E"


# --- 완료 기준: Fixture 1 ----------------------------------------------------------


def test_fixture1_attained_is_grade_c():
    """Fixture 1 — attained 4.9824 → C (#39 완료 기준).

    required는 표시 반올림값이다. 판정 여유가 upper 경계까지 약 0.24로 #166 델타(1e-9)
    보다 8자리 크므로 그 값 확정에 영향받지 않는다.
    """
    required = Decimal("5.045066331")
    assert determine_rating(Decimal("4.9824"), required, BULK_DV).rating == "C"


# --- 산출값 정합 -------------------------------------------------------------------


def test_boundaries_are_returned_unrounded():
    """경계값은 `required × d` 원값 그대로 반환한다.

    30자리 required를 쓰는 이유 — 짧은 값에서는 함수 안에 quantize가 들어와도 결과가
    같아 검출되지 않는다. `#166` 결론에 따라 중간 자릿수 처리가 도입되면 이 테스트가
    먼저 깨지며, 그때가 함수 동작을 바꿀 시점이다.
    """
    result = determine_rating(Decimal("0"), LONG_REQUIRED, BULK_DV)
    assert result.boundaries["superior_boundary"] == LONG_REQUIRED * BULK_DV.d1
    assert result.boundaries["inferior_boundary"] == LONG_REQUIRED * BULK_DV.d4
    # 9자리로 잘렸다면 소수 자릿수가 9를 넘지 못한다.
    assert -result.boundaries["superior_boundary"].as_tuple().exponent > 9


def test_long_required_boundary_exact_still_takes_better_grade():
    """30자리 required에서도 경계 정확 일치가 성립한다.

    컨텍스트 precision이 다르거나 중간 반올림이 섞이면 계산한 경계와 함수 내부 경계가
    어긋나 `<=`가 깨진다.
    """
    result = determine_rating(LONG_REQUIRED * BULK_DV.d2, LONG_REQUIRED, BULK_DV)
    assert result.rating == "B"


def test_rating_is_stable_across_threads():
    """워커 스레드에서 컨텍스트를 낮춰도 경계값이 같다 (@layer1_context).

    데코레이터가 빠지면 prec=9 컨텍스트를 상속해 경계값이 달라진다.
    """
    baseline = determine_rating(Decimal("0"), LONG_REQUIRED, BULK_DV).boundaries
    captured: dict[str, Decimal] = {}

    def target():
        setcontext(Context(prec=9, rounding=ROUND_HALF_EVEN))
        captured.update(determine_rating(Decimal("0"), LONG_REQUIRED, BULK_DV).boundaries)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    assert captured == baseline


def test_required_cii_guard():
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError, match="required_cii must be > 0"):
            determine_rating(Decimal("1"), bad, BULK_DV)


# --- select_rating_boundary --------------------------------------------------------


def test_hsc_rating_uses_ro_ro_passenger_boundary():
    """RO_RO_PASSENGER_HSC는 RO_RO_PASSENGER의 d-vector를 상속한다 (#126).

    `cii_rating_boundary` 조회가 0행인 것은 에러가 아니다. 폴백이 없으면 등급이 조용히
    비어 통합 시점까지 드러나지 않는다.
    """
    hsc = _V("RO_RO_PASSENGER_HSC", gross_tonnage=Decimal("20000"))
    row = select_rating_boundary(hsc, SEED_RATING_BOUNDARIES)

    assert row.ship_type == "RO_RO_PASSENGER"
    assert (row.d1, row.d2, row.d3, row.d4) == (
        Decimal("0.7600"),
        Decimal("0.9200"),
        Decimal("1.1400"),
        Decimal("1.3000"),
    )


def test_condition_expr_is_evaluated_for_multi_row_ship_types():
    """선종당 행이 여러 개인 경우 condition_expr로 갈린다 (LNG_CARRIER 2행).

    선종만으로 행을 특정할 수 있다고 보면 이 선종에서 틀린 행을 집는다.
    """
    small = select_rating_boundary(
        _V("LNG_CARRIER", deadweight=Decimal("50000")), SEED_RATING_BOUNDARIES
    )
    large = select_rating_boundary(
        _V("LNG_CARRIER", deadweight=Decimal("150000")), SEED_RATING_BOUNDARIES
    )
    assert small.condition_expr != large.condition_expr
    assert (small.d1, large.d1) == (Decimal("0.7800"), Decimal("0.8900"))


def test_unknown_ship_type_rejected():
    """폴백 목록에 없는 미등록 선종은 예외다 — 조용히 넘어가지 않는다."""
    with pytest.raises(ValueError, match="No rating boundary for ship_type"):
        select_rating_boundary(_V("NOT_A_SHIP", deadweight=Decimal("1")), SEED_RATING_BOUNDARIES)


def test_ambiguous_rows_rejected():
    """조건식이 겹쳐 2행 이상 매칭되면 임의로 고르지 않는다 (#41과 동일 정책)."""
    rows = [
        _B("BULK_CARRIER", "all", "0.86", "0.94", "1.06", "1.18"),
        _B("BULK_CARRIER", "DWT >= 1000", "0.80", "0.90", "1.00", "1.10"),
    ]
    with pytest.raises(ValueError, match="Ambiguous rating boundary"):
        select_rating_boundary(_V("BULK_CARRIER", deadweight=Decimal("50000")), rows)


def test_no_matching_condition_rejected():
    """선종은 있는데 어느 구간에도 안 걸리면 예외 — seed 빈틈을 알린다."""
    rows = [_B("BULK_CARRIER", "DWT >= 999999", "0.86", "0.94", "1.06", "1.18")]
    with pytest.raises(ValueError, match="No rating boundary condition matched"):
        select_rating_boundary(_V("BULK_CARRIER", deadweight=Decimal("50000")), rows)


# --- seed 교차검증 -----------------------------------------------------------------


def test_seed_ship_types_match_except_allowed_fallback():
    """기준선에는 있고 d-vector에는 없는 선종은 폴백 목록과 **정확히 일치**해야 한다.

    부분집합으로 단언하면 ⑴ 새 선종이 d-vector에서 누락돼도 ⑵ HSC가 나중에 seed에
    추가돼 폴백이 불필요해져도 걸리지 않는다. 폴백 상수를 그대로 쓰므로 둘이 어긋날
    수 없다.
    """
    reference = {row.ship_type for row in SEED_REFERENCE_LINES}
    boundary = {row.ship_type for row in SEED_RATING_BOUNDARIES}

    assert reference - boundary == set(RATING_BOUNDARY_FALLBACK)
    assert boundary - reference == set()


def test_fallback_targets_exist_in_seed():
    """폴백 대상 선종이 실제로 d-vector seed에 있어야 한다."""
    boundary = {row.ship_type for row in SEED_RATING_BOUNDARIES}
    assert set(RATING_BOUNDARY_FALLBACK.values()) <= boundary
