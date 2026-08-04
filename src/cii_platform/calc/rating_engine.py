"""Layer 1 등급 판정 (#39)과 위험도 산정 (#40).

``attained_CII``를 A~E 등급으로 판정하고, 그 등급에서 화면 위험도를 산정한다.
등급 규칙은 PRD §3.3.6, d-vector 값은 PRD §3.4.4(= DB ``cii_rating_boundary``),
위험도 규칙은 PRD §9.4.1(결정론)·§9.4.2(확률)다.

.. code-block:: text

    superior = required_CII × d1        A/B 경계
    lower    = required_CII × d2        B/C 경계
    upper    = required_CII × d3        C/D 경계
    inferior = required_CII × d4        D/E 경계

    attained <= superior → A
    attained <= lower    → B
    attained <= upper    → C
    attained <= inferior → D
    그 외                 → E

경계값과 정확히 같으면 **더 우수한 등급**이다(PRD §3.3.6 마지막 문단). 그래서 비교가
``<``가 아니라 ``<=``다. 이슈 본문이 이 규칙의 출처로 든 ``PRD §9.4.1``은 결정론 화면
위험도 절이며, 규칙은 §3.3.6에 있다(#39 코멘트).

비교는 표시 반올림을 거치지 않은 값으로 한다. 이 함수가 :class:`~decimal.Decimal`을
받고 반환하므로 자연히 성립하며, 표시 자릿수 처리는 호출부 책임이다.
(확인 8 회신에서 확정된 규칙이고 #166 커밋 2에서 PRD §13.1 [EXT-P0-3]에 정본화된다.)

d-vector 필드는 정본 이름 ``d1``~``d4``를 쓴다. DB_SCHEMA §2.11의 CHECK 제약이
``d1 < d2 AND d2 < d3 AND d3 < d4``로 같은 이름을 쓰고 있어, 여기서 경계 이름으로
바꾸면 제약과 코드가 다른 이름으로 같은 값을 가리키게 된다.

Fixture 2 JSON 생성(#46), 규칙 조항 정본화(#166)는 범위 밖이다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from cii_platform.calc.capacity import evaluate_condition
from cii_platform.calc.precision import layer1_context, validate_layer1_result

#: d-vector 행이 없는 선종 → 상속받을 선종.
#:
#: ``RO_RO_PASSENGER_HSC``는 ``cii_reference_line``에는 있으나 ``cii_rating_boundary``
#: 에는 없다. MEPC.354(78) Table 1에 행이 없는 것이 원문대로이며 전사 누락이 아니다
#: (#126 · PRD §3.4.4 각주). **reference line은 상속하지 않는다** — G2에 HSC 전용
#: ``a=4196``이 따로 있으므로 그대로 조회한다. d-vector만 상속이다.
#:
#: seed 교차검증 테스트가 이 상수를 그대로 쓴다. 허용 목록을 따로 두면 seed가 바뀔 때
#: 둘이 어긋날 수 있다.
RATING_BOUNDARY_FALLBACK: dict[str, str] = {
    "RO_RO_PASSENGER_HSC": "RO_RO_PASSENGER",
}


class _Vessel(Protocol):
    """이 모듈이 선박에서 읽는 값.

    ``capacity._Vessel``과 같은 3속성이지만 private 심볼을 import하지 않기 위해
    로컬로 선언한다. Protocol은 구조적 타입이라 양쪽이 호환된다.
    """

    ship_type: str
    deadweight: object
    gross_tonnage: object


class _RatingBoundary(Protocol):
    """이 모듈이 등급 경계 행에서 읽는 값 (DB_SCHEMA §2.11)."""

    ship_type: str
    condition_expr: str
    d1: Decimal
    d2: Decimal
    d3: Decimal
    d4: Decimal


@dataclass(frozen=True)
class DVector:
    """등급 경계 계수 (PRD §3.4.4).

    :param d1: A/B 경계 계수 (superior).
    :param d2: B/C 경계 계수 (lower).
    :param d3: C/D 경계 계수 (upper).
    :param d4: D/E 경계 계수 (inferior).
    """

    d1: Decimal
    d2: Decimal
    d3: Decimal
    d4: Decimal


@dataclass(frozen=True)
class RatingResult:
    """등급 판정 결과.

    ``boundaries``를 함께 반환하는 이유는 위험도 산정(#40)이 ``next_worse_boundary``를
    쓰고 API 응답(#55)이 경계 4개를 그대로 싣기 때문이다. 호출부가 다시 계산하면 같은
    식이 여러 곳에 생긴다.
    """

    rating: str
    boundaries: dict[str, Decimal]


def select_rating_boundary(
    vessel: _Vessel,
    boundaries: Sequence[_RatingBoundary],
) -> _RatingBoundary:
    """선박에 해당하는 등급 경계 행 1건을 고른다 (DB_SCHEMA §2.11).

    ``boundaries``는 걸러지지 않은 전체 목록이어도 된다 — 선종 필터링을 이 함수 안에서
    수행한다. 조회는 호출자 몫이다(TECH_SPEC §16.3 — calc는 DB에 접근하지 않는다).

    조건식 평가는 :func:`~cii_platform.calc.capacity.evaluate_condition`을 재사용한다.
    같은 문법(DB_SCHEMA §3.3·§3.4)을 두 번 구현하면 두 표의 해석이 갈릴 수 있다.

    **HSC 폴백은 선종 필터 단계에서 적용한다.** 조건식 평가 뒤에 두면 상속 대상 선종의
    조건식을 평가할 기회가 없어진다. 폴백 후에도 매칭이 없으면 예외다 — 등급이 조용히
    비면 통합 시점까지 드러나지 않는다(#126).

    매칭이 0건이거나 2건 이상이면 :class:`ValueError`를 낸다. 후자는 seed 구간이
    겹쳤다는 뜻이므로 임의로 하나를 고르지 않는다(#41 `select_reference_line`과 동일).
    """
    ship_type = vessel.ship_type
    candidates = [row for row in boundaries if row.ship_type == ship_type]

    if not candidates:
        inherited = RATING_BOUNDARY_FALLBACK.get(ship_type)
        if inherited is not None:
            candidates = [row for row in boundaries if row.ship_type == inherited]
        if not candidates:
            raise ValueError(f"No rating boundary for ship_type {ship_type!r}")

    matched = [row for row in candidates if evaluate_condition(row.condition_expr, vessel)]
    if not matched:
        exprs = ", ".join(repr(row.condition_expr) for row in candidates)
        raise ValueError(
            f"No rating boundary condition matched for ship_type {ship_type!r} "
            f"(DWT={vessel.deadweight}, GT={vessel.gross_tonnage}; 후보 조건 {exprs}). "
            f"seed 구간에 빈틈이 있을 수 있다."
        )
    if len(matched) > 1:
        exprs = ", ".join(repr(row.condition_expr) for row in matched)
        raise ValueError(f"Ambiguous rating boundary for ship_type {ship_type!r}: {exprs}")
    return matched[0]


@layer1_context
def determine_rating(
    attained_cii: Decimal,
    required_cii: Decimal,
    d_vector: DVector,
) -> RatingResult:
    """A~E 등급을 판정한다 (PRD §3.3.6).

    ``@layer1_context``를 붙이는 이유는 이 함수가 경계값 4개를 **산출**하기 때문이다.
    ``required × d``는 자릿수가 늘어 컨텍스트 precision에서 반올림되므로, 호출 스레드의
    컨텍스트를 상속하면 워커 스레드에서 다른 경계값이 나온다(TECH_SPEC §1.2.1 · §5.4 7항).
    :func:`select_rating_boundary`는 산출이 없어 붙이지 않는다.

    :param attained_cii: 항차 attained CII (#37).
    :param required_cii: required CII (#38). 표시 반올림을 거치지 않은 값을 넘긴다.
    :param d_vector: 선종별 경계 계수. 선택은 :func:`select_rating_boundary` 소관이다.
    """
    if required_cii <= 0:
        raise ValueError(f"required_cii must be > 0: got {required_cii}")

    superior = required_cii * d_vector.d1
    lower = required_cii * d_vector.d2
    upper = required_cii * d_vector.d3
    inferior = required_cii * d_vector.d4

    for name, value in (
        ("superior_boundary", superior),
        ("lower_boundary", lower),
        ("upper_boundary", upper),
        ("inferior_boundary", inferior),
    ):
        validate_layer1_result(value, name)

    # 경계값과 정확히 같으면 더 우수한 등급 (PRD §3.3.6).
    if attained_cii <= superior:
        rating = "A"
    elif attained_cii <= lower:
        rating = "B"
    elif attained_cii <= upper:
        rating = "C"
    elif attained_cii <= inferior:
        rating = "D"
    else:
        rating = "E"

    return RatingResult(
        rating=rating,
        boundaries={
            "superior_boundary": superior,
            "lower_boundary": lower,
            "upper_boundary": upper,
            "inferior_boundary": inferior,
        },
    )


# --- 위험도 산정 (#40 · PRD §9.4) ----------------------------------------------------

#: 등급 → 그 등급에서 **다음 악화 등급으로 넘어가는** 경계의
#: :attr:`RatingResult.boundaries` 키 (PRD §9.4.1).
#:
#: 판정에 쓴 부등식과 짝이다 — ``attained <= upper``로 C가 됐다면 C를 벗어나는 지점도
#: ``upper``다. **E는 키가 없다**: 더 나쁜 등급이 없어 경계가 정의되지 않는다.
NEXT_WORSE_BOUNDARY_KEY: dict[str, str] = {
    "A": "superior_boundary",
    "B": "lower_boundary",
    "C": "upper_boundary",
    "D": "inferior_boundary",
}

#: attained 등급의 정의역 (PRD §3.3.6). 목표 등급(``target_rating``)은 E를 제외한
#: A~D이므로(PRD §12.8 · DB ``annual_simulation_run`` CHECK) 이 상수를 그쪽 검증에
#: 재사용하지 않는다.
RATINGS: tuple[str, ...] = ("A", "B", "C", "D", "E")

#: 결정론 위험도 판정 표 (PRD §9.4.1): 등급 → (임계 margin_ratio, 이상일 때, 미만일 때).
#:
#: D·E는 ``margin_ratio``와 무관하게 결정되므로 이 표에 없다
#: (:func:`calculate_deterministic_risk` 참조).
DETERMINISTIC_RISK_TABLE: dict[str, tuple[Decimal, str, str]] = {
    "A": (Decimal("0.05"), "LOW", "MEDIUM"),
    "B": (Decimal("0.05"), "LOW", "MEDIUM"),
    "C": (Decimal("0.03"), "MEDIUM", "HIGH"),
}

#: 확률 위험도 판정 표 (PRD §9.4.2): (임계 확률, 그 이상일 때의 위험도).
#: 내림차순이며, 어느 임계도 넘지 못하면 ``CRITICAL``이다.
PROBABILITY_RISK_TABLE: tuple[tuple[Decimal, str], ...] = (
    (Decimal("0.80"), "LOW"),
    (Decimal("0.50"), "MEDIUM"),
    (Decimal("0.20"), "HIGH"),
)


def select_next_worse_boundary(
    rating: str,
    boundaries: Mapping[str, Decimal],
) -> Decimal | None:
    """현재 등급에서 다음 악화 등급으로 넘어가는 경계값을 고른다 (PRD §9.4.1).

    ``boundaries``는 :func:`determine_rating`이 반환한 :attr:`RatingResult.boundaries`를
    그대로 넘긴다. 호출부가 ``required × d3`` 같은 식을 다시 쓰면 판정에 쓴 경계와 표시에
    쓰는 경계가 갈릴 수 있다.

    :return: 경계값. **등급 E면 ``None``** — E보다 나쁜 등급이 없어 경계가 존재하지 않는다.
        ``0``이나 판정 경계(``inferior``)를 대신 돌려주지 않는다. 전자는 여유가 없다는
        뜻으로 읽히고 후자는 이미 지나온 경계라 여유율이 음수가 되어, 둘 다 "정의되지
        않음"과 다른 값이다. 호출부(#55 응답 직렬화)가 표시 방법을 정한다.
    """
    if rating not in RATINGS:
        raise ValueError(f"Unknown rating {rating!r}: expected one of {', '.join(RATINGS)}")
    if rating == "E":
        return None

    key = NEXT_WORSE_BOUNDARY_KEY[rating]
    if key not in boundaries:
        raise ValueError(
            f"boundaries is missing {key!r} for rating {rating!r}. "
            f"determine_rating()이 반환한 RatingResult.boundaries를 그대로 넘긴다."
        )
    return boundaries[key]


@layer1_context
def calculate_margin_ratio(
    attained_cii: Decimal,
    required_cii: Decimal,
    next_worse_boundary: Decimal,
) -> Decimal:
    """다음 악화 경계까지의 여유율을 계산한다 (PRD §9.4.1).

    .. code-block:: text

        margin_ratio = (next_worse_boundary - attained_cii) / required_cii

    ``@layer1_context``를 붙이는 이유는 뺄셈·나눗셈으로 **새 값을 산출**하기 때문이다.
    나눗셈은 컨텍스트 precision에서 잘리므로, 워커 스레드가 기본 컨텍스트(``prec=28``)를
    상속하면 같은 입력에서 다른 값이 나온다(TECH_SPEC §1.2.1 · §5.4 7항).
    :func:`select_next_worse_boundary`는 값을 고르기만 하므로 붙이지 않는다.

    반환값은 **비율**이다(0.05 = 5%). 퍼센트로 환산하거나 표시 자릿수로 반올림하는 것은
    호출부 책임이다 — PRD §9.3 "내부 계산값은 화면 표시 반올림값을 다시 사용하지 않는다".

    :param next_worse_boundary: :func:`select_next_worse_boundary` 결과. 등급 E는 이
        경계가 없으므로 이 함수를 호출하지 않는다 — 위험도는 등급만으로 CRITICAL이다.
    """
    if required_cii <= 0:
        raise ValueError(f"required_cii must be > 0: got {required_cii}")

    ratio = (next_worse_boundary - attained_cii) / required_cii
    return validate_layer1_result(ratio, "margin_ratio")


def calculate_deterministic_risk(rating: str, margin_ratio: Decimal | None = None) -> str:
    """기능①·② 결정론 화면 위험도를 산정한다 (PRD §9.4.1).

    ==========  ======================  ==========
    예상 등급   margin_ratio            위험도
    ==========  ======================  ==========
    A 또는 B    ≥ 5%                    LOW
    A 또는 B    < 5%                    MEDIUM
    C           ≥ 3%                    MEDIUM
    C           < 3%                    HIGH
    D           (무관)                  HIGH
    E           (무관)                  CRITICAL
    ==========  ======================  ==========

    **D·E는 ``margin_ratio``를 보지 않는다.** 표에 여유율 조건이 없어서다. E는 다음 악화
    경계 자체가 없으므로(:func:`select_next_worse_boundary`) 여유율을 넘길 수단도 없다.
    그래서 ``margin_ratio``가 선택 인자다.

    **미등록 등급은 예외로 낸다.** 표에 없는 값을 최빈 등급(HIGH 등)으로 흡수하면 오타나
    상류 회귀가 "조금 나쁜 위험도"로 위장돼 통합 시점까지 드러나지 않는다
    (:func:`select_rating_boundary`의 0행 처리와 같은 정책, #126).

    **``margin_ratio``는 ``Decimal``만 받는다.** 이 함수는 비교 연산만 하고, 파이썬은
    ``Decimal``과 ``float``의 비교를 허용한다. 그래서 :func:`calculate_margin_ratio`처럼
    산술 단계에서 ``TypeError``가 나는 자동 방어가 여기에는 없다. 임계값에서 결과가
    뒤집힌다 — ``float`` ``0.03``은 실제로 ``0.0299999999999999988…``이라
    ``Decimal("0.03")``보다 작아, TEST_PLAN §2.9 UT-RISK-003B(C 등급 + 여유율 정확히 3%)가
    ``MEDIUM``이어야 하는데 ``HIGH``가 된다. ``float`` ``0.05``는 오차가 반대 방향이라
    우연히 맞으므로 **일관되게 틀리지도 않아** 더 늦게 발견된다.

    ``int``도 받지 않는다. ``int``는 오차가 없어 기술적으로는 안전하지만, "Decimal만"이
    "Decimal과 int는 되고 float은 안 됨"보다 지키기 쉽다.

    :param rating: :func:`determine_rating` 결과 등급.
    :param margin_ratio: :func:`calculate_margin_ratio` 결과. 비율이며 퍼센트가 아니다
        (0.05 = 5%). 등급 A·B·C에서는 필수다.
    """
    if rating not in RATINGS:
        raise ValueError(f"Unknown rating {rating!r}: expected one of {', '.join(RATINGS)}")
    if rating == "E":
        return "CRITICAL"
    if rating == "D":
        return "HIGH"

    # 타입 검사를 D·E 뒤에 두는 이유 — 두 등급은 ``margin_ratio``를 쓰지 않으므로
    # 앞에서 막으면 "D·E는 여유율을 보지 않는다"는 계약이 깨진다. 값을 실제로 쓰는
    # A·B·C 경로에서만 검사한다.
    if margin_ratio is None:
        raise ValueError(f"margin_ratio is required for rating {rating!r}")
    if not isinstance(margin_ratio, Decimal):
        raise TypeError(
            f"margin_ratio must be Decimal, got {type(margin_ratio).__name__}. "
            f"float은 임계값에서 판정을 뒤집는다(0.03 → 0.0299999…)."
        )

    threshold, at_or_above, below = DETERMINISTIC_RISK_TABLE[rating]
    return at_or_above if margin_ratio >= threshold else below


def calculate_probability_risk(target_success_probability: Decimal) -> str:
    """기능③ 확률 화면 위험도를 산정한다 (PRD §9.4.2).

    ============================  ==========
    목표 등급 달성 확률           위험도
    ============================  ==========
    ≥ 80%                         LOW
    50% 이상 80% 미만             MEDIUM
    20% 이상 50% 미만             HIGH
    < 20%                         CRITICAL
    ============================  ==========

    입력은 **Monte Carlo 집계를 마친 Decimal**이다. TECH_SPEC §2.4가 rating probability를
    ``float64 → Decimal`` 소수점 4자리 ROUND_HALF_UP으로 규정하므로, 그 변환
    (``round_probability``) 뒤의 값을 넘긴다.

    **``float``은 ``TypeError``로 막는다.** 이 함수도 비교 연산만 하므로
    :func:`calculate_deterministic_risk`와 같은 이유로 자동 방어가 없다. 미변환 float을
    받으면 화면에 표시되는 확률과 위험도가 경계 근처에서 어긋난다 — 0.79996은 표시상
    80.0%(LOW)인데 미변환 비교로는 MEDIUM이다. 이 함수는 프로젝트에서 Layer 2 float64
    파이프라인의 값을 직접 받는 유일한 계산 함수라 유입 경로가 실재한다.

    타입 검사가 범위 검사보다 **앞**이다. 순서가 반대면 범위를 벗어난 float(퍼센트를 그대로
    넘긴 ``85.0`` 등)이 범위 검사에 먼저 걸려 ``ValueError``가 되고, 진짜 원인인 "미변환
    float"이 범위 오류로 위장된다. 범위 **안**의 float은 어느 순서로도 ``TypeError``라
    차이가 없다.

    :param target_success_probability: 목표 등급 달성 확률. 0~1 비율이며 퍼센트가 아니다.
    """
    if not isinstance(target_success_probability, Decimal):
        raise TypeError(
            f"target_success_probability must be Decimal, "
            f"got {type(target_success_probability).__name__}. "
            f"TECH_SPEC §2.4의 round_probability() 변환을 거친 값을 넘긴다."
        )
    if not Decimal("0") <= target_success_probability <= Decimal("1"):
        raise ValueError(
            f"target_success_probability must be within [0, 1]: "
            f"got {target_success_probability}. 퍼센트가 아니라 비율이다."
        )

    for threshold, risk in PROBABILITY_RISK_TABLE:
        if target_success_probability >= threshold:
            return risk
    return "CRITICAL"
