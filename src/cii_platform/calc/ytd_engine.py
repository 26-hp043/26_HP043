"""Layer 1 YTD 누적 CII 계산 엔진 (#353).

.. code-block:: text

    YTD_M = Σ(항해 중 연료_j × 1,000,000 × CF_j)                    PRD §3.3.2
          + Σ(not under way 연료_j × 1,000,000 × CF_j)              ← #345
    YTD_W = transport_capacity × (under way 거리 + not under way 거리)  PRD §3.3.3
    YTD_attained_CII = YTD_M / YTD_W                                PRD §3.3.1

**분자에도 분모에도 not under way 몫이 들어간다.**

* ``M`` — ``MEPC.352(78)`` §4.1: *"The total mass of CO₂ is the sum of CO₂ emissions
  (in grams) from **all the fuel oil consumed on board a ship in a given calendar
  year**"*. 항해 여부를 가리지 않는다.
* ``Dt`` — ``MEPC.412(84)`` §4.2(2026-05-01 채택, G1 §4.2를 통째로 교체): *"the total
  distance travelled **(both under way and not under way)** in a given calendar year"*.

⚠️ 구판 ``MEPC.352(78)`` §4.2에는 이 한정어가 **없다**(*"the distance travelled in a
given calendar year"*). 한정어가 없어 「under way 거리만」으로 읽었던 것이 이 프로젝트의
종전 전제였고, 개정본 대조로 정정했다(#358). **구판을 출처로 인용하면 오기가 된다.**

**그래도 「정박이 지속되면 등급이 나빠진다」는 그대로 성립한다** — 접안·묘박은 연료만
늘고 이동 거리가 0이라 분자만 커지기 때문이다. 분모에서 실제로 늘어나는 것은 운하
통과(수에즈 약 104 nm·파나마 약 44 nm)·표류·STS처럼 **이동이 있는** 구간이다.
이것은 새로 만든 계산식이 아니라 **규제 계산식이 원래 그렇게 동작하는 것**이며,
``MEPC 82/6/31``(ICS·라이베리아)이 현행 제도를 그렇게 서술한다 — *"emissions continue
to accumulate without corresponding transport work … penalised under the current
system"*.

이 모듈은 **시각을 모른다.** ``as_of``도, ``regulation_year``도 받지 않고 확정된
누적량만 받는다. ``#368``의 시뮬레이션 시계는 「입력 확정 계층」에 있고 계산 코어는
그 결과만 받는다(``#368`` 계약 ⑸ · ``TECH_SPEC §1`` Layer 1 bit-exact 계약 · ``RK-9``
불가침). 시각으로 누적량을 만드는 일은 :mod:`cii_platform.services.ytd_cii`가 한다.

:func:`~cii_platform.calc.cii_engine.calculate_attained_cii`를 그대로 쓰지 않는 이유는
두 가지다.

* **연료 목록이 두 갈래**라서 항해 중 CO₂와 not under way CO₂를 **나눠서도** 돌려줘야
  한다. 화면이 *"정박이 등급에 얼마나 기여했는가"*를 표시하려면 이 분해가 필요하다
  (``UIFLOW 2-9`` 실시간 CII).
* 한쪽 목록이 **빈 리스트일 수 있다.** not under way 기록이 아직 없는 선박은 정상
  상태인데, ``cii_engine._voyage_co2``는 빈 입력을 ``ValueError``로 막는다.

중간 단계 자릿수 처리는 하지 않는다 — 근거는 :mod:`cii_platform.calc.cii_engine`
모듈 docstring과 같다(``TECH_SPEC §1.2.1``에 중간 처리 규정이 없다).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cii_platform.calc.cii_engine import GRAMS_PER_TON, FuelUse
from cii_platform.calc.precision import layer1_context, validate_layer1_result


@dataclass(frozen=True)
class YtdCiiResult:
    """YTD Layer 1 산출값. 모든 수치는 :class:`~decimal.Decimal`이다 (TECH_SPEC §1.1).

    ``underway_co2_g`` + ``not_underway_co2_g`` = ``total_co2_g``이며, 두 항을 따로
    두는 것은 화면이 기여도를 나눠 보여주기 위해서다. ``total_distance_nm``은 분모에
    실제로 쓴 거리의 합(두 갈래)이라 화면이 ``transport_work``를 되짚을 수 있다.
    ``fuel_breakdown_g``는 **두 갈래를 합친** 연료별 내역이다 — 같은 유종을 항해 중에도
    정박 중에도 쓰므로 유종 기준으로는 합치는 것이 맞다.
    """

    attained_cii: Decimal
    total_co2_g: Decimal
    total_co2_t: Decimal
    underway_co2_g: Decimal
    not_underway_co2_g: Decimal
    fuel_breakdown_g: dict[str, Decimal]
    total_distance_nm: Decimal
    transport_work: Decimal


def _accumulate(
    entries: Sequence[FuelUse], breakdown: dict[str, Decimal], *, label: str
) -> Decimal:
    """연료 목록의 gCO₂를 누적하고 ``breakdown``에 유종별로 더한다.

    입력 가드는 :func:`cii_platform.calc.cii_engine._voyage_co2`와 같다. **빈 목록을
    허용하는 것만 다르다** — YTD에서는 한쪽 갈래가 비는 것이 정상이며, 총합이 0인지는
    호출부가 두 갈래를 합친 뒤에 판정한다.

    :param label: 오류 메시지에서 어느 갈래인지 드러내기 위한 이름.
    """
    total = Decimal(0)
    for entry in entries:
        if entry.fuel_ton < 0:
            raise ValueError(
                f"fuel_ton must be >= 0: {label} '{entry.fuel_code}' → {entry.fuel_ton}"
            )
        if entry.cf_value <= 0:
            raise ValueError(
                f"cf_value must be > 0: {label} '{entry.fuel_code}' → {entry.cf_value}"
            )
        co2_g = entry.fuel_ton * GRAMS_PER_TON * entry.cf_value
        breakdown[entry.fuel_code] = breakdown.get(entry.fuel_code, Decimal(0)) + co2_g
        total += co2_g
    return total


@layer1_context
def calculate_ytd_cii(
    *,
    underway_fuel_uses: Sequence[FuelUse],
    not_underway_fuel_uses: Sequence[FuelUse],
    transport_capacity: Decimal,
    underway_distance_nm: Decimal,
    not_underway_distance_nm: Decimal = Decimal(0),
) -> YtdCiiResult:
    """연초부터 확정 시점까지의 누적 attained CII를 계산한다 (PRD §3.3.1).

    :param underway_fuel_uses: 항해 중 소모 연료. ``voyage_fuel_use`` 유래.
    :param not_underway_fuel_uses: not under way 구간 소모 연료. ``not_underway_fuel_use``
        유래 (``#345``). **빈 목록이 정상 입력이다.**
    :param transport_capacity: G1 transport work용 capacity — 선박의 **실제** DWT 또는
        GT다. reference capacity가 아니다 (``PRD §3.3.3 [EXT-P0-1]``).
    :param underway_distance_nm: 항해 중 이동 거리 (``voyage`` 유래).
    :param not_underway_distance_nm: not under way 구간의 이동 거리
        (``not_underway_period.distance_nm`` 합, 마이그레이션 028). **분모에 더한다** —
        ``MEPC.412(84)`` §4.2. 접안·묘박만 있는 선박은 0이며 그것이 정상값이다.
        기본값을 둔 것은 028 이전 데이터·테스트가 이 인자 없이도 성립하게 하기 위함이다.

    :raises ValueError: capacity·거리가 0 이하이거나 연료 총합이 0 이하일 때.
        「아직 데이터가 없는 선박」은 오류가 아니라 정상 상태이므로, 그 판정은
        호출부(:mod:`cii_platform.services.ytd_cii`)가 이 함수를 부르기 **전에** 한다.
    """
    if transport_capacity <= 0:
        raise ValueError(f"transport_capacity must be > 0: got {transport_capacity}")
    if underway_distance_nm < 0:
        raise ValueError(f"underway_distance_nm must be >= 0: got {underway_distance_nm}")
    if not_underway_distance_nm < 0:
        raise ValueError(f"not_underway_distance_nm must be >= 0: got {not_underway_distance_nm}")
    total_distance_nm = underway_distance_nm + not_underway_distance_nm
    # 나눗셈은 **합계**로 막는다. 한쪽이 0인 것은 정상이다 — 연중 내내 운하만 통과한
    # 선박은 없지만, 아직 항차 실적이 없고 정박 이동만 기록된 상태는 있을 수 있다.
    if total_distance_nm <= 0:
        raise ValueError(f"total distance must be > 0: got {total_distance_nm}")

    breakdown: dict[str, Decimal] = {}
    underway_co2_g = _accumulate(underway_fuel_uses, breakdown, label="underway")
    not_underway_co2_g = _accumulate(not_underway_fuel_uses, breakdown, label="not_underway")
    total_co2_g = underway_co2_g + not_underway_co2_g

    # TECH_SPEC §1.2.5 출력 가드. cii_engine과 같은 이유로 총합 기준으로 판정한다 —
    # 한쪽 갈래가 0인 것은 정상이다(정박 기록이 없는 선박, 또는 그 반대).
    validate_layer1_result(total_co2_g, "ytd_total_co2_g")
    if total_co2_g <= 0:
        raise ValueError(f"Invalid YTD CO₂ result: {total_co2_g}. Check fuel inputs.")

    transport_work = transport_capacity * total_distance_nm
    attained_cii = total_co2_g / transport_work
    total_co2_t = total_co2_g / GRAMS_PER_TON

    validate_layer1_result(attained_cii, "ytd_attained_cii")
    validate_layer1_result(total_co2_t, "ytd_total_co2_t")

    return YtdCiiResult(
        attained_cii=attained_cii,
        total_co2_g=total_co2_g,
        total_co2_t=total_co2_t,
        underway_co2_g=underway_co2_g,
        not_underway_co2_g=not_underway_co2_g,
        fuel_breakdown_g=breakdown,
        total_distance_nm=total_distance_nm,
        transport_work=transport_work,
    )
