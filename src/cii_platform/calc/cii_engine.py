"""Layer 1 결정론 CII 계산 엔진 (#37).

계산식은 PRD §3.3이다 (이슈 본문의 "§3.4" 표기는 규정 파라미터 표를 가리킨다).

.. code-block:: text

    M(gCO₂)      = Σ(fuel_ton_j × 1,000,000 × CF_j)        PRD §3.3.2
    W(dwt·nm)    = transport_capacity × distance_nm         PRD §3.3.3
    attained_CII = M / W                                    PRD §3.3.1

반환 타입과 ``fuel_breakdown``은 TECH_SPEC §4.3([ORACLE-S-2]/[ORACLE-M-6])을 따른다.
§4.3 원문에서 세 가지가 다르며 근거는 #37 코멘트에 남겼다.

* ``vessel`` 인자 제거 — §4.3 본문에서 참조되지 않아 순수함수로 유지한다.
* 입력을 ``list[dict]`` 대신 :class:`FuelUse` — dict 키 오타를 런타임까지 끌고 가지 않는다.
* :class:`FuelUse`에 ``fuel_code`` 추가 — 없으면 ``fuel_breakdown`` 키를 만들 수 없다.

``fuel_code``는 DB_SCHEMA ``fuel_type.code``(HFO · LNG · DIESEL_GAS_OIL 등) 값과
일치해야 한다. ``cf_value``는 호출부가 주입한다(엔진은 CF 상수를 갖지 않는다).

dataclass 의존은 공개 진입점 두 곳에만 둔다. 내부 계산부는 ``(fuel_code, fuel_ton,
cf_value)`` 튜플만 받으므로, 입력 형태를 §4.3 원문으로 되돌릴 때 바뀌는 코드는
진입점 함수뿐이다.

required CII(#38)는 :func:`calculate_required_cii`가 담당한다. 분수 지수는
TECH_SPEC §1.2.2의 Decimal ln/exp로 계산하며, §9.4가 float 경유를 금지한다.

중간 단계 자릿수 처리는 하지 않는다. **정본에 중간 처리 규정이 없기 때문이다** —
TECH_SPEC §1.2.1은 ``prec=30``과 ``ROUND_HALF_UP``만 규정한다. 규정 없는 동작을
코드에 넣지 않는다는 기준을 따른 것이며, 규칙 조항 신설은 #166 소관이다.

    **계산 방향 확인: sky01170851.** Fixture 1 기대값이 PRD와 TEST_PLAN에서 갈리는
    원인이 "단계마다 반올림과 내림을 섞어 쓴 것"이며 중간 처리 없이 끝까지 이어
    계산하는 쪽이 맞다는 것을, prec=30 원값 7개를 직접 산출해 확인해 주었다.
    그 결과로 위 판단이 사후 검증됐다 (#166).

등급 판정(#39), capacity 결정 규칙(#41)은 범위 밖이다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cii_platform.calc.precision import layer1_context, validate_layer1_result

#: 연료 소비량 단위(ton) → gCO₂ 환산 계수 (PRD §3.3.2).
GRAMS_PER_TON = Decimal("1000000")


@dataclass(frozen=True)
class FuelUse:
    """항차 단위 연료 사용 1건.

    :param fuel_code: DB_SCHEMA ``fuel_type.code`` 값 (예: ``"HFO"``).
    :param fuel_ton: 소비량(ton).
    :param cf_value: 해당 연료의 CF (gCO₂/g fuel).
    """

    fuel_code: str
    fuel_ton: Decimal
    cf_value: Decimal


@dataclass(frozen=True)
class CiiResult:
    """Layer 1 산출값. 모든 수치는 :class:`~decimal.Decimal`이다 (TECH_SPEC §1.1)."""

    attained_cii: Decimal
    total_co2_g: Decimal
    total_co2_t: Decimal
    fuel_breakdown: dict[str, Decimal]


@dataclass(frozen=True)
class RequiredCiiResult:
    """required CII 산출값 (#38).

    ``cii_ref``를 함께 반환하는 이유는 등급 경계(#39)와 API 응답(#55)이 둘 다
    필요로 하기 때문이다. 호출부가 다시 계산하면 같은 식이 두 곳에 생긴다.
    """

    cii_ref: Decimal
    required_cii: Decimal


def _normalize(fuel_uses: Sequence[FuelUse]) -> list[tuple[str, Decimal, Decimal]]:
    """공개 진입점 전용 — dataclass를 내부 계산부가 쓰는 튜플로 편다."""
    return [(fu.fuel_code, fu.fuel_ton, fu.cf_value) for fu in fuel_uses]


def _voyage_co2(
    entries: Sequence[tuple[str, Decimal, Decimal]],
) -> tuple[Decimal, dict[str, Decimal]]:
    """CO₂ 총량과 연료별 내역을 계산한다 (TECH_SPEC §4.3).

    같은 ``fuel_code``가 여러 번 들어오면 내역에서 합산한다.
    """
    if not entries:
        raise ValueError("fuel_uses must not be empty")

    breakdown: dict[str, Decimal] = {}
    for fuel_code, fuel_ton, cf_value in entries:
        if fuel_ton < 0:
            raise ValueError(f"fuel_ton must be >= 0: '{fuel_code}' → {fuel_ton}")
        if cf_value <= 0:
            raise ValueError(f"cf_value must be > 0: '{fuel_code}' → {cf_value}")
        co2_g = fuel_ton * GRAMS_PER_TON * cf_value
        breakdown[fuel_code] = breakdown.get(fuel_code, Decimal(0)) + co2_g

    # sum()의 기본 시작값은 int 0이라 빈 합계가 Decimal이 아니게 된다. 시작값을 명시한다.
    total_co2_g = sum(breakdown.values(), Decimal(0))

    # [ORACLE-MISS-2] §4.3 출력 가드. 개별 유종 0톤은 정상 입력이므로 총합으로 판정한다
    # (다중 연료 중 한 유종만 0톤인 경우를 막지 않기 위함). TEST_PLAN UT-CII-007.
    validate_layer1_result(total_co2_g, "total_co2_g")
    if total_co2_g <= 0:
        raise ValueError(f"Invalid CO₂ result: {total_co2_g}. Check fuel inputs.")

    return total_co2_g, breakdown


@layer1_context
def calculate_voyage_co2(
    fuel_uses: Sequence[FuelUse],
) -> tuple[Decimal, dict[str, Decimal]]:
    """다중 연료 CO₂ 배출량 계산 (TECH_SPEC §4.3 — Layer 1, Decimal 반환).

    :returns: ``(total_co2_g, fuel_breakdown)``.
    """
    return _voyage_co2(_normalize(fuel_uses))


@layer1_context
def calculate_attained_cii(
    fuel_uses: Sequence[FuelUse],
    transport_capacity: Decimal,
    distance_nm: Decimal,
) -> CiiResult:
    """attained CII를 계산한다 (PRD §3.3.1).

    :param transport_capacity: G1 transport work용 capacity. reference capacity가
        아니다(TECH_SPEC §1.2.4 [EXT-P0-1]). 결정 규칙은 #41 소관이며 여기서는 이미
        해석된 값을 받는다.
    """
    if transport_capacity <= 0:
        raise ValueError(f"transport_capacity must be > 0: got {transport_capacity}")
    if distance_nm <= 0:
        raise ValueError(f"distance_nm must be > 0: got {distance_nm}")

    total_co2_g, fuel_breakdown = _voyage_co2(_normalize(fuel_uses))

    transport_work = transport_capacity * distance_nm
    attained_cii = total_co2_g / transport_work
    total_co2_t = total_co2_g / GRAMS_PER_TON

    # [ORACLE-MISS-2] TECH_SPEC §1.2.5 검증 대상 중 본 이슈 산출물.
    validate_layer1_result(attained_cii, "attained_cii")
    validate_layer1_result(total_co2_t, "total_co2_t")

    return CiiResult(
        attained_cii=attained_cii,
        total_co2_g=total_co2_g,
        total_co2_t=total_co2_t,
        fuel_breakdown=fuel_breakdown,
    )


def _decimal_power(base: Decimal, exp: Decimal) -> Decimal:
    """``base ** exp``를 Decimal ln/exp로 계산한다 (TECH_SPEC §1.2.2).

    ``c``가 분수라 Decimal의 ``**`` 연산을 쓸 수 없다. §9.4가 float 변환을 금지하고
    ln/exp 사용을 지시하므로 ``math.pow``를 경유하지 않는다. 정밀도는 호출 시점의
    context를 따르며, 공개 함수가 :func:`layer1_context`로 고정한다.

    ``ln()``의 정의역이 양수라 0 이하는 여기서 걸린다. 다만 실제 호출 경로에서는
    공개 함수의 입력 가드가 먼저 잡는다.
    """
    if base <= 0:
        raise ValueError(f"base must be > 0 for ln/exp power: got {base}")
    return (base.ln() * exp).exp()


@layer1_context
def calculate_required_cii(
    a: Decimal,
    c: Decimal,
    reference_capacity: Decimal,
    z_factor_percent: Decimal,
) -> RequiredCiiResult:
    """required CII를 계산한다 (PRD §3.3.4~§3.3.5).

    .. code-block:: text

        CII_ref      = a × reference_capacity^(-c)
        required_CII = CII_ref × (1 - z_factor_percent / 100)

    중간 단계에서 자릿수를 자르거나 반올림하지 않는다. ``prec=30`` 원값을 그대로
    반환하며, 표시 시점 반올림은 호출부 책임이다. 근거는 모듈 docstring 참조.

    :param a: 기준선 계수 ``a``. seed의 IMO 과학 표기(``14479E10`` 등)는 호출부가
        :func:`~cii_platform.calc.imo_parser.parse_imo_scientific`로 해석해 넘긴다.
    :param c: 기준선 지수. DB에 **양수**로 저장되며 여기서 ``-c``로 적용한다
        (PRD §3.4.3). ``0``이면 ``CII_ref = a``가 되어 capacity와 무관해진다
        (LNG_CARRIER ``DWT ≥ 100,000``).
    :param reference_capacity: **reference** capacity. transport capacity가 아니다
        (TECH_SPEC §1.2.4). ``fixed`` 규칙 적용은 #41의
        :func:`~cii_platform.calc.capacity.resolve_reference_capacity` 소관이며
        여기서는 이미 해석된 값을 받는다.
    :param z_factor_percent: 감축률을 **퍼센트**로 받는다 (2026년이면 ``11``).
    """
    if reference_capacity <= 0:
        raise ValueError(f"reference_capacity must be > 0: got {reference_capacity}")

    cii_ref = a * _decimal_power(reference_capacity, -c)
    required_cii = cii_ref * (Decimal("1") - z_factor_percent / Decimal("100"))

    # TECH_SPEC §1.2.5 출력 가드. a·c·z의 범위 검증은 정본에 근거가 없어 두지 않는다.
    validate_layer1_result(cii_ref, "cii_ref")
    validate_layer1_result(required_cii, "required_cii")

    return RequiredCiiResult(cii_ref=cii_ref, required_cii=required_cii)
