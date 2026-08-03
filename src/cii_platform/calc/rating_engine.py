"""Layer 1 등급 판정 (#39).

``attained_CII``를 A~E 등급으로 판정한다. 규칙은 PRD §3.3.6, d-vector 값은
PRD §3.4.4(= DB ``cii_rating_boundary``)다.

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

위험도 산정(#40), Fixture 2 JSON 생성(#46), 규칙 조항 정본화(#166)는 범위 밖이다.
"""

from collections.abc import Sequence
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
