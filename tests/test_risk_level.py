"""위험도 산정 단위 테스트 (#40).

TEST_PLAN §2.9 UT-RISK-001~008 전건(경계값 변형 포함) + `next_worse_boundary` 선택 +
`margin_ratio` 산식 검증.

TEST_PLAN §2.9의 입력은 `rating`과 `margin`뿐이라 두 함수의 **결합**은 검증하지 않는다.
그래서 API_SPEC §4.1 응답 예시(`attained` · `required` · d-vector가 모두 명시된 유일한
정본 사례)를 써서 `determine_rating → select_next_worse_boundary →
calculate_margin_ratio → calculate_deterministic_risk` 전 구간을 한 번 통과시킨다.
그 예시의 `next_worse_boundary_margin` · `_margin_ratio` · `risk_level` 세 값이 기대값이다.

`margin` 입력은 TEST_PLAN 표가 퍼센트로 적었지만 함수 인자는 비율이다(PRD §9.4.1 산식이
비율을 낸다). 8% → `Decimal("0.08")`로 옮긴다.

TC ID는 TEST_PLAN §2.9를 따른다. P=0.50 행만 PR #173에서 정정된 ID(`UT-RISK-006B`)를
쓴다 — 사유는 해당 테스트 docstring 참조.
"""

import threading
from decimal import ROUND_HALF_EVEN, Context, Decimal, setcontext

import pytest

from cii_platform.calc.rating_engine import (
    DVector,
    calculate_deterministic_risk,
    calculate_margin_ratio,
    calculate_probability_risk,
    determine_rating,
    select_next_worse_boundary,
)

# PRD §3.4.4 BULK_CARRIER 행. API_SPEC §4.1 예시가 쓰는 d-vector와 같다.
BULK_DV = DVector(Decimal("0.86"), Decimal("0.94"), Decimal("1.06"), Decimal("1.18"))


# --- TEST_PLAN §2.9 결정론 위험도 (PRD §9.4.1) ---------------------------------------


@pytest.mark.parametrize(
    ("tc", "rating", "margin", "expected"),
    [
        ("UT-RISK-001", "B", "0.08", "LOW"),
        ("UT-RISK-002", "B", "0.03", "MEDIUM"),
        ("UT-RISK-003", "C", "0.01", "HIGH"),
        ("UT-RISK-001B", "B", "0.05", "LOW"),
        ("UT-RISK-003A", "C", "0.05", "MEDIUM"),
        ("UT-RISK-003B", "C", "0.03", "MEDIUM"),
        ("UT-RISK-003C", "D", "0.08", "HIGH"),
    ],
)
def test_ut_risk_deterministic_table(tc, rating, margin, expected):
    """UT-RISK-001~003C — PRD §9.4.1 표 전건.

    001B·003B는 임계값 정확 일치다. 부등호를 `>`로 구현하면 두 건이 한 단계 나쁘게 나온다.
    """
    assert calculate_deterministic_risk(rating, Decimal(margin)) == expected


def test_ut_risk_004_rating_e_is_critical():
    """UT-RISK-004 — 등급 E는 여유율과 무관하게 CRITICAL.

    E는 다음 악화 경계가 없어 margin_ratio를 넘길 수단이 없다. 인자 없이 호출된다.
    """
    assert calculate_deterministic_risk("E") == "CRITICAL"


def test_rating_a_uses_same_threshold_as_b():
    """PRD §9.4.1 표 1·2행은 "A 또는 B"다 — A를 B와 다르게 다루면 안 된다.

    TEST_PLAN §2.9는 A 단독 입력이 없어 이 테스트가 없으면 A 행이 비어도 통과한다.
    """
    assert calculate_deterministic_risk("A", Decimal("0.05")) == "LOW"
    assert calculate_deterministic_risk("A", Decimal("0.049999")) == "MEDIUM"


def test_rating_d_ignores_margin_ratio():
    """D는 여유율 조건이 표에 없다 — 여유가 커도 HIGH다.

    C의 3% 규칙을 D에 잘못 확장하면 margin=8%에서 MEDIUM이 나온다.
    """
    assert calculate_deterministic_risk("D", Decimal("0.50")) == "HIGH"
    assert calculate_deterministic_risk("D") == "HIGH"
    # float도 통과해야 한다 — D는 타입 가드 앞에서 반환되므로. 가드가 함수 앞으로
    # 이동하면 이 줄이 TypeError로 깨진다.
    assert calculate_deterministic_risk("D", 0.5) == "HIGH"


def test_negative_margin_is_worst_bucket():
    """음수 여유율은 **정상 경로에서는 나오지 않는다** — 잘못 짝지은 입력에 대한 방어다.

    `determine_rating → select_next_worse_boundary → calculate_margin_ratio` 를 거치면
    A~D 등급의 next worse boundary는 attained 이상이므로 여유율이 0 이상이다. 음수는
    호출자가 다른 선박·다른 연도의 경계를 넘겼거나, 이 함수를 직접 호출한 경우에 생긴다.
    그런 경우에도 임계 미만 쪽으로 판정되어야 하며 `abs()` 같은 보정이 들어가면 안 된다.
    """
    assert calculate_deterministic_risk("B", Decimal("-0.10")) == "MEDIUM"
    assert calculate_deterministic_risk("C", Decimal("-0.10")) == "HIGH"


def test_deterministic_risk_rejects_float_margin_ratio():
    """float 여유율은 TypeError — 임계값에서 판정이 뒤집힌다.

    `float` 0.03은 실제로 `0.0299999999999999988897…`이라 `Decimal("0.03")`보다 작다.
    그래서 이 가드가 없으면 TEST_PLAN §2.9 UT-RISK-003B(C 등급 + 여유율 정확히 3%)가
    MEDIUM이어야 하는데 HIGH가 된다. `float` 0.05는 오차가 반대 방향이라 우연히 맞으므로
    일관되게 틀리지도 않는다 — 그래서 가드로 막지 않으면 늦게 발견된다.

    이 함수는 비교 연산만 하므로 `calculate_margin_ratio`처럼 산술 단계에서 TypeError가
    나는 자동 방어가 없다.
    """
    with pytest.raises(TypeError, match="margin_ratio must be Decimal"):
        calculate_deterministic_risk("C", 0.03)


def test_deterministic_risk_rejects_int_margin_ratio():
    """int도 받지 않는다 — "Decimal만"이 예외 있는 규칙보다 지키기 쉽다.

    int는 오차가 없어 기술적으로는 안전하지만, 예외를 하나 열면 다음 사람이 float도
    되는 줄 안다.
    """
    with pytest.raises(TypeError, match="margin_ratio must be Decimal"):
        calculate_deterministic_risk("C", 0)


def test_deterministic_type_guard_does_not_block_d_and_e():
    """타입 가드는 A·B·C 경로 안에만 있다 — D·E는 여유율을 보지 않는다.

    가드를 함수 맨 앞에 두면 `margin_ratio=None`인 D·E 호출이 TypeError로 깨진다.
    """
    assert calculate_deterministic_risk("E") == "CRITICAL"
    assert calculate_deterministic_risk("D") == "HIGH"


def test_margin_ratio_required_for_a_b_c():
    """A·B·C에서 여유율을 빠뜨리면 예외 — 임의 기본값으로 판정하지 않는다."""
    for rating in ("A", "B", "C"):
        with pytest.raises(ValueError, match="margin_ratio is required"):
            calculate_deterministic_risk(rating)


def test_unknown_rating_rejected():
    """표에 없는 등급은 예외다 — 최빈 등급으로 흡수하면 상류 회귀가 위장된다 (#126 정책)."""
    for bad in ("F", "a", "", "CRITICAL"):
        with pytest.raises(ValueError, match="Unknown rating"):
            calculate_deterministic_risk(bad, Decimal("0.10"))


# --- TEST_PLAN §2.9 확률 위험도 (PRD §9.4.2) -----------------------------------------


@pytest.mark.parametrize(
    ("tc", "prob", "expected"),
    [
        ("UT-RISK-005", "0.85", "LOW"),
        ("UT-RISK-006", "0.60", "MEDIUM"),
        ("UT-RISK-007", "0.35", "HIGH"),
        ("UT-RISK-008", "0.10", "CRITICAL"),
        ("UT-RISK-005B", "0.80", "LOW"),
        ("UT-RISK-006B", "0.50", "MEDIUM"),
        ("UT-RISK-007B", "0.20", "HIGH"),
    ],
)
def test_ut_risk_probability_table(tc, prob, expected):
    """UT-RISK-005~008B — PRD §9.4.2 표 전건.

    P=0.50 행은 TEST_PLAN §2.9에 `UT-RISK-005B`로 중복 기재돼 있었다(P=0.80 행과 같은
    ID). 구간이 각각 80%·50% 경계로 다르므로 #172로 등록해 PR #173에서 `UT-RISK-006B`로
    정정했고, 이 테스트는 정정 후 ID를 쓴다. 기대값은 정정 전후 동일하다.
    """
    assert calculate_probability_risk(Decimal(prob)) == expected


def test_probability_boundaries_are_inclusive_below():
    """임계 바로 아래는 한 단계 나쁜 쪽이다 — `>=`를 `>`로 쓰면 세 경계가 전부 틀어진다."""
    assert calculate_probability_risk(Decimal("0.7999")) == "MEDIUM"
    assert calculate_probability_risk(Decimal("0.4999")) == "HIGH"
    assert calculate_probability_risk(Decimal("0.1999")) == "CRITICAL"


def test_probability_extremes():
    assert calculate_probability_risk(Decimal("1")) == "LOW"
    assert calculate_probability_risk(Decimal("0")) == "CRITICAL"


def test_probability_risk_rejects_float_probability():
    """float 확률은 TypeError — 표시 확률과 위험도가 어긋난다.

    0.79996은 TECH_SPEC §2.4의 `round_probability()`를 거치면 `Decimal("0.8000")`이 되어
    화면에 80.0%로 뜨고 위험도는 LOW다. 변환 없이 넘기면 MEDIUM이 나온다.
    """
    with pytest.raises(TypeError, match="target_success_probability must be Decimal"):
        calculate_probability_risk(0.79996)


def test_probability_type_guard_precedes_range_guard():
    """타입 검사가 범위 검사보다 앞이다 — **범위 밖 float**으로 확인한다.

    순서가 반대면 `85.0`이 범위 검사에 먼저 걸려 ValueError가 되고, 진짜 원인인
    "미변환 float"이 범위 오류로 위장된다. 85.0은 퍼센트를 float으로 그대로 넘긴 실제
    실수 형태다.

    범위 **안**의 float(0.5 등)으로는 이 회귀를 못 잡는다. 순서를 뒤집어도 범위를
    통과한 뒤 타입 검사에 걸려 양쪽 다 TypeError가 나기 때문이다. 추적 결과:

    ==========  ====================  ====================
    입력        타입→범위 (현재)      범위→타입 (회귀)
    ==========  ====================  ====================
    0.5         TypeError             TypeError   ← 구분 못 함
    85.0        TypeError             ValueError  ← 구분됨
    ==========  ====================  ====================
    """
    with pytest.raises(TypeError, match="must be Decimal"):
        calculate_probability_risk(85.0)


def test_probability_out_of_range_rejected():
    """퍼센트를 그대로 넘기는 실수를 막는다.

    `85`가 통과하면 LOW로 맞아떨어져 드러나지 않지만, 같은 실수의 `10`은 CRITICAL이어야
    할 것이 LOW가 된다 — 위험도가 정반대로 뒤집힌다.
    """
    for bad in ("85", "10", "-0.01", "1.01"):
        with pytest.raises(ValueError, match=r"must be within \[0, 1\]"):
            calculate_probability_risk(Decimal(bad))


# --- next_worse_boundary 선택 (PRD §9.4.1) -------------------------------------------


@pytest.mark.parametrize(
    ("rating", "key"),
    [
        ("A", "superior_boundary"),
        ("B", "lower_boundary"),
        ("C", "upper_boundary"),
        ("D", "inferior_boundary"),
    ],
)
def test_next_worse_boundary_matches_rating_interval(rating, key):
    """등급별로 그 등급을 벗어나는 경계를 고른다.

    한 칸 밀려 고르면(예: C에 `inferior`) 여유율이 한 등급만큼 과대 산정돼 위험도가
    실제보다 낮게 나온다.
    """
    boundaries = determine_rating(Decimal("1"), Decimal("100"), BULK_DV).boundaries
    assert select_next_worse_boundary(rating, boundaries) == boundaries[key]


def test_next_worse_boundary_is_none_for_e():
    """E는 더 나쁜 등급이 없어 경계가 정의되지 않는다 — 0이나 inferior를 대신 주지 않는다.

    `inferior`를 돌려주면 여유율이 음수가 되어 "이미 지나온 경계"가 "여유 부족"으로
    읽히고, 0을 돌려주면 실제로 여유가 0인 상태와 구분되지 않는다.
    """
    boundaries = determine_rating(Decimal("1000"), Decimal("100"), BULK_DV).boundaries
    assert select_next_worse_boundary("E", boundaries) is None


def test_next_worse_boundary_rejects_unknown_rating():
    boundaries = determine_rating(Decimal("1"), Decimal("100"), BULK_DV).boundaries
    with pytest.raises(ValueError, match="Unknown rating"):
        select_next_worse_boundary("F", boundaries)


def test_next_worse_boundary_rejects_incomplete_mapping():
    """경계 dict가 불완전하면 예외 — KeyError로 새어나가지 않는다."""
    with pytest.raises(ValueError, match="missing 'upper_boundary'"):
        select_next_worse_boundary("C", {"superior_boundary": Decimal("1")})


# --- margin_ratio 산식 (PRD §9.4.1) --------------------------------------------------


def test_margin_ratio_formula():
    """margin_ratio = (next_worse_boundary - attained) / required.

    분모를 `next_worse_boundary`로 잘못 쓰면 이 입력에서 0.05가 아니라 0.047…이 된다.
    """
    ratio = calculate_margin_ratio(Decimal("95"), Decimal("100"), Decimal("100"))
    assert ratio == Decimal("0.05")


def test_margin_ratio_zero_at_next_worse_boundary_is_valid():
    """attained가 경계와 정확히 일치하면 여유율 0 — 예외가 아니라 정상값이다.

    PRD §3.3.6이 "경계 정확 일치 시 더 우수한 등급"으로 규정한 **도달 가능한 상태**다.
    `attained == upper` 면 C 등급이고 그 C의 next worse boundary가 곧 attained이므로
    여유율이 정확히 0이 된다.

    `calculate_margin_ratio`는 `validate_layer1_result`를 호출하는데, 이 함수는 지금
    `is_finite()`만 검사해 0을 통과시킨다. 누군가 거기에 `> 0` 가드를 넣으면 경계에 딱
    걸린 선박에서 예외가 터지는데, 이 테스트가 없으면 그때 아무것도 깨지지 않는다.
    부등호를 `>`로 바꾸는 회귀도 같이 잡는다(0 ≥ 0.03 거짓 → HIGH가 정답).
    """
    required = Decimal("100")
    attained = required * BULK_DV.d3  # C/D 경계 = 106

    result = determine_rating(attained, required, BULK_DV)
    assert result.rating == "C"

    boundary = select_next_worse_boundary(result.rating, result.boundaries)
    assert boundary == attained

    ratio = calculate_margin_ratio(attained, required, boundary)
    assert ratio == Decimal("0")
    assert calculate_deterministic_risk(result.rating, ratio) == "HIGH"


def test_margin_ratio_is_unrounded():
    """표시 자릿수로 미리 반올림하지 않는다 (PRD §9.3).

    나눗셈이 딱 떨어지지 않는 입력이라 quantize가 섞이면 자릿수가 줄어 바로 걸린다.
    """
    ratio = calculate_margin_ratio(Decimal("1"), Decimal("3"), Decimal("2"))
    assert -ratio.as_tuple().exponent > 20


def test_margin_ratio_required_cii_guard():
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError, match="required_cii must be > 0"):
            calculate_margin_ratio(Decimal("1"), bad, Decimal("2"))


def test_margin_ratio_is_stable_across_threads():
    """워커 스레드가 컨텍스트를 낮춰도 같은 값이다 (@layer1_context).

    나눗셈 결과는 precision에서 잘리므로 데코레이터가 빠지면 prec=9에서 값이 달라진다.
    """
    args = (Decimal("1"), Decimal("3"), Decimal("2"))
    baseline = calculate_margin_ratio(*args)
    captured: list[Decimal] = []

    def target():
        setcontext(Context(prec=9, rounding=ROUND_HALF_EVEN))
        captured.append(calculate_margin_ratio(*args))

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    assert captured == [baseline]


# --- 정본 사례 전 구간 통과 (API_SPEC §4.1) -------------------------------------------


def test_api_spec_example_end_to_end():
    """API_SPEC §4.1 응답 예시의 세 값을 판정→경계→여유율→위험도로 재현한다.

    예시는 `attained=4.982400` · `required=5.045066` · BULK_CARRIER d-vector에서
    `estimated_rating=C` · `next_worse_boundary_margin=0.365370` ·
    `next_worse_boundary_margin_ratio=0.0724` · `risk_level=MEDIUM`이다.
    표시 자릿수(6자리 · 4자리)는 API_SPEC 예시가 쓴 형식이며, 비교 직전에만 적용한다.
    """
    attained = Decimal("4.982400")
    required = Decimal("5.045066")

    result = determine_rating(attained, required, BULK_DV)
    assert result.rating == "C"

    boundary = select_next_worse_boundary(result.rating, result.boundaries)
    assert boundary is not None
    assert (boundary - attained).quantize(Decimal("0.000001")) == Decimal("0.365370")

    ratio = calculate_margin_ratio(attained, required, boundary)
    assert ratio.quantize(Decimal("0.0001")) == Decimal("0.0724")

    # 0.0724 ≥ 3% 이므로 C에서 MEDIUM.
    assert calculate_deterministic_risk(result.rating, ratio) == "MEDIUM"
