"""YTD 누적 CII 서비스 (#353).

``calc``(수학)와 ``db/repositories``(쿼리)를 잇고 **어떤 데이터를 집계에 넣을지의
규칙**을 적용한다 (TECH_SPEC §16).

분모 스코프 (2026-08-15 원문 대조로 정정)
----------------------------------------
``MEPC.412(84)`` §4.2가 ``Dt``를 *"the total distance travelled **(both under way and
not under way)** in a given calendar year"* 로 정의한다. 따라서 분모에는 항해 거리와
not under way 구간의 이동 거리(``not_underway_period.distance_nm``, 마이그레이션 028)를
**모두** 넣는다. 구판 ``MEPC.352(78)`` §4.2에는 이 한정어가 없어 종전에는 「under way
거리만」으로 잘못 읽고 있었다(#358).

접안·묘박은 이동이 0이라 분모에 기여하지 않으므로 **「정박이 지속되면 등급이 나빠진다」는
그대로 성립**한다. 실제로 분모를 늘리는 것은 운하 통과·표류·STS다.

무엇을 계산하는가
-----------------
IMO attained CII는 **역년(calendar year) 단위 집계 지표**이며, 규제상 「실시간 CII」
라는 개념은 없다. 따라서 화면이 표시할 수 있는 값은 **연초부터 확정 시점까지의
누적값(YTD)** 이다 (``PRD §1 COR-1`` · ``COR-2``).

집계에 무엇을 넣는가 — 정본 근거
--------------------------------
포함 여부의 정본은 ``PRD §8.1.2`` 매트릭스이고, 그 판정 결과가 ``voyage`` 행의
``annual_inclusion_policy`` 컬럼에 이미 들어 있다.

======================  ==========================  =============================
``annual_inclusion_policy``  해당 ``status``        YTD 처리
======================  ==========================  =============================
``INCLUDE_AS_ACTUAL``   COMPLETED · CONFIRMED       **집계에 넣는다** (실적)
``INCLUDE_AS_PLAN``     PLANNED · IN_PROGRESS       넣지 않는다 — 아래 참조
``EXCLUDE``             DRAFT · CANCELLED · ARCHIVED  넣지 않는다
======================  ==========================  =============================

**``INCLUDE_AS_PLAN``을 전액 넣지 않는 이유**는 YTD의 정의 때문이다. 12월에 끝날
예정인 항차의 계획 연료를 1월 조회에 전부 더하면 **아직 발생하지 않은 배출을 이미
발생한 것으로** 계산하게 된다. ``PRD §8.3`` 값 우선순위가 진행 중 항차에 대해
``IN_PROGRESS latest estimate``를 두는데, 그 estimate를 **경과 시간으로부터 만드는
것이 ``#368`` 시뮬레이션 시계**다. 그래서 이 서비스는 그 몫을
:class:`InProgressContribution`이라는 **주입 지점**으로 열어 두고, 스스로 시각에서
누적량을 만들지 않는다 (``#368`` 계약 ⑸ — *"계산 코어는 시각을 모른다"*).

CF를 어디서 가져오는가
----------------------
* **항해 중 연료** → ``voyage_fuel_use.cf_used`` (계산 시점 CF snapshot,
  ``DB_SCHEMA §2.3``). ``PRD §8.4``가 *"연료 CF 변경: 변경 이후 계산에만 적용. 과거
  계산은 snapshot 보존"*을 규정한다.
* **not under way 연료** → ``not_underway_fuel_use.cf_used`` (마이그레이션 030,
  ``#378``). 같은 규정을 두 갈래에 동일하게 적용한다.

두 갈래 모두 snapshot을 쓰므로 CF가 개정돼도 과거 실적의 YTD는 변하지 않는다.
집계는 **유종 × snapshot**으로 묶여 오고, 계산 엔진이 같은 ``fuel_code``의 배출량을
합산하므로 개정 전후 행이 각자의 CF로 곱해진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.capacity import (
    capacity_axis,
    resolve_reference_capacity,
    resolve_transport_capacity,
    select_reference_line,
)
from cii_platform.calc.cii_engine import FuelUse, calculate_required_cii
from cii_platform.calc.precision import layer1_context, validate_layer1_result
from cii_platform.calc.rating_engine import (
    DVector,
    calculate_deterministic_risk,
    calculate_margin_ratio,
    determine_rating,
    select_next_worse_boundary,
    select_rating_boundary,
)
from cii_platform.calc.ytd_engine import YtdCiiResult, calculate_ytd_cii
from cii_platform.db.repositories import not_underway as not_underway_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import (
    CalculationError,
    NotFoundError,
    ParameterError,
    ValidationError,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

# --- 상수 ------------------------------------------------------------------------

#: PRD §8.1.2 — 실적으로 연간 집계에 들어가는 정책 값.
POLICY_INCLUDE_AS_ACTUAL = "INCLUDE_AS_ACTUAL"

#: TECH_SPEC §12.3 — COMPLETED 항차의 actual_fuel_ton이 NULL이라 계획값을 대입했다.
WARNING_COMPLETED_NO_FUEL = "COMPLETED_NO_FUEL"

#: COMPLETED 항차의 actual_distance_nm이 NULL이라 계획거리를 대입했다 (#449).
#:
#: **종전에는 이 대체가 경고조차 없이 일어났다.** 연료 대체는 위 경고가 나가는데
#: 거리는 침묵했다 — 거리는 CII의 **분모**라 영향이 연료 못지않다.
WARNING_COMPLETED_NO_DISTANCE = "COMPLETED_NO_DISTANCE"

#: API_SPEC §1.6 — 모든 계산 결과에 붙는다.
WARNING_REFERENCE_ONLY = "REFERENCE_ONLY"


# --- 입출력 DTO --------------------------------------------------------------------


#: :class:`Substitution.axis` — 무엇을 대체했는가.
SUBSTITUTION_AXIS_FUEL = "FUEL"
SUBSTITUTION_AXIS_DISTANCE = "DISTANCE"


@dataclass(frozen=True)
class Substitution:
    """실적 대신 계획값을 쓴 **한 건**의 기록 (#449).

    ## 왜 항차별로 남기는가

    종전에는 대체 사실이 불리언 하나(``fuel_fallback_used``)로 뭉개져 경고 1건만
    나갔다. 사용자는 「이 값에 계획치가 섞였다」는 것만 알고 **무엇을 고쳐야 하는지는
    몰랐다** — 항차가 40건이면 40건을 전부 열어 봐야 한다.

    선택은 이미 하고 있었고 **결과를 버리고 있었을 뿐**이다. 그래서 버리지 않는다.

    :param voyage_id: 대체가 일어난 항차.
    :param axis: :data:`SUBSTITUTION_AXIS_FUEL` 또는 :data:`SUBSTITUTION_AXIS_DISTANCE`.
    :param fuel_type: 연료 축일 때 어느 유종인지. 거리 축이면 ``None``.
    """

    voyage_id: UUID
    axis: str
    fuel_type: str | None = None


@dataclass(frozen=True)
class InProgressContribution:
    """진행 중 항차의 누적 기여분 — ``#368`` 시뮬레이션 시계의 주입 지점.

    **이 서비스는 이 값을 만들지 않는다.** 경과 시간으로부터 누적 거리·연료를
    파생시키는 것은 ``#368``의 「입력 확정 계층」이고, 여기서는 **확정된 값만**
    받는다. 그래야 계산 코어가 시각을 모르는 상태로 남는다.

    :param distance_nm: 진행 중 항차의 누적 **under way** 거리.
    :param fuel_uses: ``(fuel_type, fuel_ton)`` 목록. CF는 이 서비스가 붙인다.
    """

    distance_nm: Decimal
    fuel_uses: tuple[tuple[str, Decimal], ...] = ()


@dataclass(frozen=True)
class YtdCiiOutput:
    """YTD 산출 결과.

    ``data_available``가 ``False``면 나머지 수치는 전부 ``None``이다 — 항차가 아직
    없는 선박은 **오류가 아니라 정상 상태**이므로 예외로 만들지 않는다. 화면은
    이 플래그를 보고 「데이터 없음」을 표시한다.
    """

    data_available: bool
    regulation_year: int
    capacity_axis: str
    transport_capacity: Decimal
    warnings: list[str] = field(default_factory=list)
    #: 실적 대신 계획값을 쓴 항차별 기록 (#449). 경고는 「있었다」만 말하고
    #: 이 목록이 **어느 항차의 무엇인지**를 말한다.
    substitutions: list[Substitution] = field(default_factory=list)

    attained_cii: Decimal | None = None
    required_cii: Decimal | None = None
    cii_ref: Decimal | None = None
    ratio_to_required: Decimal | None = None
    rating: str | None = None
    boundaries: dict[str, Decimal] | None = None
    next_worse_boundary: Decimal | None = None
    margin: Decimal | None = None
    margin_ratio: Decimal | None = None
    risk_level: str | None = None

    total_co2_t: Decimal | None = None
    underway_co2_g: Decimal | None = None
    not_underway_co2_g: Decimal | None = None
    fuel_breakdown_g: dict[str, Decimal] | None = None
    underway_distance_nm: Decimal | None = None
    not_underway_distance_nm: Decimal | None = None
    total_distance_nm: Decimal | None = None
    #: 두 갈래(항해 중 + not under way) 연료의 톤 합계 (#355 이력 응답용).
    #: ``data_available``가 ``False``여도 값 자체는 계산돼 있어 그대로 실린다 —
    #: 「거리는 없고 정박 연료만 있다」는 상태를 화면이 구분할 수 있게 한다.
    total_fuel_ton: Decimal | None = None
    voyage_count: int = 0
    not_underway_period_count: int = 0


@dataclass(frozen=True)
class _Aggregated:
    """DB에서 긁어 모은 **확정 전** 누적 입력."""

    underway_fuel: dict[str, Decimal]
    #: not under way 연료 — **유종 × CF snapshot**별 묶음 (030 · ``#378``).
    #: dict가 아닌 목록인 이유는 CF 개정 후 같은 유종에 snapshot이 둘 이상 생기기
    #: 때문이다. 엔진이 같은 ``fuel_code``를 합산하므로 묶음을 그대로 넘긴다.
    not_underway_fuel: list[not_underway_repo.NotUnderwayFuelTotal]
    underway_distance_nm: Decimal
    not_underway_distance_nm: Decimal
    voyage_count: int
    warnings: list[str]
    #: 유종별 CF — 항차 쪽 ``voyage_fuel_use.cf_used`` snapshot.
    underway_cf: dict[str, Decimal]
    #: 실적 대신 계획값을 쓴 항차별 기록 (#449).
    substitutions: list[Substitution]


# --- Layer 1 --------------------------------------------------------------------


@dataclass(frozen=True)
class _Layer1Values:
    """작업 정밀도 컨텍스트 안에서 만든 **확정 전** 값들.

    :mod:`cii_platform.services.voyage_cii`의 같은 이름 dataclass와 같은 이유로
    존재한다 — 파생값(``ratio_to_required`` · ``margin_ratio``)을 컨텍스트 **밖**에서
    나누면 27번째 자리부터 갈린다(``#179`` 실측).
    """

    ytd: YtdCiiResult
    cii_ref: Decimal
    required_cii: Decimal
    ratio_to_required: Decimal
    rating: str
    boundaries: dict[str, Decimal]
    next_worse_boundary: Decimal | None
    margin: Decimal | None
    margin_ratio: Decimal | None
    risk_level: str


@layer1_context
def _compute_layer1(
    *,
    underway_fuel_uses: list[FuelUse],
    not_underway_fuel_uses: list[FuelUse],
    transport_capacity: Decimal,
    reference_capacity: Decimal,
    underway_distance_nm: Decimal,
    not_underway_distance_nm: Decimal,
    a_decimal: Decimal,
    c: Decimal,
    z_factor_percent: Decimal,
    d_vector: DVector,
) -> _Layer1Values:
    """Layer 1 전 구간을 **한 컨텍스트 안에서** 계산한다 (TECH_SPEC §1.2.1)."""
    ytd = calculate_ytd_cii(
        underway_fuel_uses=underway_fuel_uses,
        not_underway_fuel_uses=not_underway_fuel_uses,
        transport_capacity=transport_capacity,
        underway_distance_nm=underway_distance_nm,
        not_underway_distance_nm=not_underway_distance_nm,
    )
    required = calculate_required_cii(
        a=a_decimal,
        c=c,
        reference_capacity=reference_capacity,
        z_factor_percent=z_factor_percent,
    )

    # ⚠️ 분모는 **확정 전** required_cii다 (#179 · voyage_cii와 같은 규약).
    ratio = validate_layer1_result(
        ytd.attained_cii / required.required_cii, "ytd_ratio_to_required"
    )

    result = determine_rating(
        attained_cii=ytd.attained_cii,
        required_cii=required.required_cii,
        d_vector=d_vector,
    )
    next_worse = select_next_worse_boundary(result.rating, result.boundaries)

    if next_worse is None:
        margin: Decimal | None = None
        margin_ratio: Decimal | None = None
    else:
        margin = validate_layer1_result(next_worse - ytd.attained_cii, "ytd_margin")
        margin_ratio = calculate_margin_ratio(
            attained_cii=ytd.attained_cii,
            required_cii=required.required_cii,
            next_worse_boundary=next_worse,
        )

    return _Layer1Values(
        ytd=ytd,
        cii_ref=required.cii_ref,
        required_cii=required.required_cii,
        ratio_to_required=ratio,
        rating=result.rating,
        boundaries=result.boundaries,
        next_worse_boundary=next_worse,
        margin=margin,
        margin_ratio=margin_ratio,
        risk_level=calculate_deterministic_risk(result.rating, margin_ratio),
    )


# --- 서비스 진입점 ----------------------------------------------------------------


async def compute_ytd_cii(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime | None = None,
    in_progress: InProgressContribution | None = None,
) -> YtdCiiOutput:
    """선박의 연초~확정 시점 누적 CII를 산출한다.

    :param as_of: 절단 시점. ``None`` 이면 해당 연도 전체를 집계한다. **시각이
        여기까지만 오고 계산 코어로는 넘어가지 않는다** — 이 함수가 시각을 써서 하는
        일은 저장소 WHERE 절을 좁히는 것뿐이다 (``#368`` 계약 ⑸).
    :param in_progress: ``#368``이 확정한 진행 중 항차 기여분. 미지정이면 실적
        확정분만 집계한다.
    """
    vessel = await _load_vessel(session, vessel_id)
    transport_capacity = _resolve_transport_capacity(vessel)

    aggregated = await _aggregate(
        session,
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        as_of=as_of,
        in_progress=in_progress,
    )
    period_count = len(
        await not_underway_repo.list_periods_for_year(
            session, vessel_id=vessel_id, regulation_year=regulation_year, as_of=as_of
        )
    )

    total_fuel_ton = sum(aggregated.underway_fuel.values(), Decimal(0)) + sum(
        (Decimal(row.fuel_ton) for row in aggregated.not_underway_fuel), Decimal(0)
    )

    # 분모는 두 갈래의 **합**이다 (MEPC.412(84) §4.2).
    total_distance_nm = aggregated.underway_distance_nm + aggregated.not_underway_distance_nm

    # M/0 방어 — 「데이터가 아직 없다」는 오류가 아니라 정상 상태다. 예외를 던지면
    # 화면이 500을 받게 되고, 신규 등록 선박이 전부 오류로 보인다.
    if total_distance_nm <= 0 or total_fuel_ton <= 0:
        return YtdCiiOutput(
            data_available=False,
            regulation_year=regulation_year,
            capacity_axis=capacity_axis(vessel.ship_type),
            transport_capacity=transport_capacity,
            warnings=aggregated.warnings,
            substitutions=aggregated.substitutions,
            underway_distance_nm=aggregated.underway_distance_nm,
            not_underway_distance_nm=aggregated.not_underway_distance_nm,
            total_distance_nm=total_distance_nm,
            total_fuel_ton=total_fuel_ton,
            voyage_count=aggregated.voyage_count,
            not_underway_period_count=period_count,
        )

    regulation = await _load_regulation_year(session, regulation_year)
    reference_line = await _select_reference_line(session, vessel)
    rating_boundary = await _select_rating_boundary(session, vessel)
    reference_capacity = _resolve_reference_capacity(vessel, reference_line)

    try:
        layer1 = _compute_layer1(
            underway_fuel_uses=[
                FuelUse(fuel_code=code, fuel_ton=ton, cf_value=aggregated.underway_cf[code])
                for code, ton in aggregated.underway_fuel.items()
            ],
            # 030 (#378) — 각 묶음이 **자기 snapshot CF로** 곱해진다. 같은 유종이
            # 여러 번 들어와도 엔진이 배출량을 합산한다.
            not_underway_fuel_uses=[
                FuelUse(
                    fuel_code=row.fuel_type,
                    fuel_ton=Decimal(row.fuel_ton),
                    cf_value=Decimal(row.cf_used),
                )
                for row in aggregated.not_underway_fuel
            ],
            transport_capacity=transport_capacity,
            reference_capacity=reference_capacity,
            underway_distance_nm=aggregated.underway_distance_nm,
            not_underway_distance_nm=aggregated.not_underway_distance_nm,
            a_decimal=Decimal(reference_line.a_decimal),
            c=Decimal(reference_line.c),
            z_factor_percent=Decimal(regulation.z_factor_percent),
            d_vector=DVector(
                d1=Decimal(rating_boundary.d1),
                d2=Decimal(rating_boundary.d2),
                d3=Decimal(rating_boundary.d3),
                d4=Decimal(rating_boundary.d4),
            ),
        )
    except ValueError as exc:
        # Layer 1 엔진은 ValueError로 중단한다(TECH_SPEC §12.2 1항). 원인이 입력이므로
        # 500이 아니라 422로 바꾼다 — voyage_cii와 같은 규약.
        raise CalculationError(f"YTD 계산 오류: 입력값을 확인하세요. ({exc})") from exc

    return YtdCiiOutput(
        data_available=True,
        regulation_year=regulation_year,
        capacity_axis=capacity_axis(vessel.ship_type),
        transport_capacity=transport_capacity,
        warnings=[WARNING_REFERENCE_ONLY, *aggregated.warnings],
        substitutions=aggregated.substitutions,
        attained_cii=layer1.ytd.attained_cii,
        required_cii=layer1.required_cii,
        cii_ref=layer1.cii_ref,
        ratio_to_required=layer1.ratio_to_required,
        rating=layer1.rating,
        boundaries=layer1.boundaries,
        next_worse_boundary=layer1.next_worse_boundary,
        margin=layer1.margin,
        margin_ratio=layer1.margin_ratio,
        risk_level=layer1.risk_level,
        total_co2_t=layer1.ytd.total_co2_t,
        underway_co2_g=layer1.ytd.underway_co2_g,
        not_underway_co2_g=layer1.ytd.not_underway_co2_g,
        fuel_breakdown_g=layer1.ytd.fuel_breakdown_g,
        underway_distance_nm=aggregated.underway_distance_nm,
        not_underway_distance_nm=aggregated.not_underway_distance_nm,
        total_distance_nm=layer1.ytd.total_distance_nm,
        total_fuel_ton=total_fuel_ton,
        voyage_count=aggregated.voyage_count,
        not_underway_period_count=period_count,
    )


# --- 집계 -------------------------------------------------------------------------


async def _aggregate(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime | None,
    in_progress: InProgressContribution | None,
) -> _Aggregated:
    """실적 확정 항차 + not under way 기록 + ``#368`` 주입분을 하나로 모은다."""
    voyages = await voyage_repo.list_annual_inclusions(
        session,
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        policy=POLICY_INCLUDE_AS_ACTUAL,
        as_of=as_of,
    )
    fuel_by_voyage = await voyage_repo.list_fuel_uses_by_voyage_ids(
        session, [voyage.id for voyage in voyages]
    )

    underway_fuel: dict[str, Decimal] = {}
    underway_cf: dict[str, Decimal] = {}
    distance = Decimal(0)
    warnings: list[str] = []
    substitutions: list[Substitution] = []

    for voyage in voyages:
        # PRD §8.3 값 우선순위 — 실적이 있으면 실적, 없으면 계획값.
        actual_distance = voyage.actual_distance_nm
        if actual_distance is None:
            # 거리도 연료와 같은 대체다. **종전에는 이것만 조용했다** (#449).
            substitutions.append(Substitution(voyage_id=voyage.id, axis=SUBSTITUTION_AXIS_DISTANCE))
        distance += Decimal(
            actual_distance if actual_distance is not None else voyage.planned_distance_nm
        )

        for row in fuel_by_voyage.get(voyage.id, []):
            ton = row.actual_fuel_ton
            if ton is None:
                # [ORACLE-C-4B] COMPLETED인데 실적이 비었으면 계획값을 임시 대입하고
                # 화면에 COMPLETED_NO_FUEL을 띄운다. INCLUDE_AS_PLAN으로 되돌리는 것은
                # §8.1.2 매트릭스(COMPLETED + INCLUDE_AS_PLAN)를 위반한다.
                ton = row.planned_fuel_ton
                substitutions.append(
                    Substitution(
                        voyage_id=voyage.id,
                        axis=SUBSTITUTION_AXIS_FUEL,
                        fuel_type=row.fuel_type,
                    )
                )
            if ton is None:
                # 계획값마저 없으면 더할 것이 없다. 0을 더하는 것과 같으므로 건너뛴다.
                continue
            code = row.fuel_type
            underway_fuel[code] = underway_fuel.get(code, Decimal(0)) + Decimal(ton)
            # cf_used는 NOT NULL이다(DB_SCHEMA §2.3). 같은 유종이 항차마다 다른
            # snapshot을 가질 수 있으나, 유종 하나에 CF 하나만 실을 수 있으므로
            # **가장 최근 항차의 snapshot**을 쓴다 — voyages가 created_at 오름차순이라
            # 나중 항차가 앞선 값을 덮어쓴다.
            underway_cf[code] = Decimal(row.cf_used)

    axes = {item.axis for item in substitutions}
    if SUBSTITUTION_AXIS_FUEL in axes:
        warnings.append(WARNING_COMPLETED_NO_FUEL)
    if SUBSTITUTION_AXIS_DISTANCE in axes:
        warnings.append(WARNING_COMPLETED_NO_DISTANCE)

    if in_progress is not None:
        distance += in_progress.distance_nm
        for code, ton in in_progress.fuel_uses:
            underway_fuel[code] = underway_fuel.get(code, Decimal(0)) + Decimal(ton)

    # #368 주입분과 계획값 대입 경로는 cf_used가 없다 — 현재 CF로 채운다.
    missing_cf = [code for code in underway_fuel if code not in underway_cf]
    if missing_cf:
        rows = await param_repo.get_fuel_types_by_codes(session, missing_cf)
        for code in missing_cf:
            if code not in rows:
                raise ValidationError(
                    f"알 수 없는 연료 종류입니다: {code}",
                    field="fuel_type",
                    field_label="연료 종류",
                )
            underway_cf[code] = Decimal(rows[code].cf)

    not_underway_totals = await not_underway_repo.sum_fuel_by_type(
        session, vessel_id=vessel_id, regulation_year=regulation_year, as_of=as_of
    )
    # 028 — 분모에 더할 not under way 이동 거리 (MEPC.412(84) §4.2).
    not_underway_distance = await not_underway_repo.sum_distance(
        session, vessel_id=vessel_id, regulation_year=regulation_year, as_of=as_of
    )

    return _Aggregated(
        underway_fuel=underway_fuel,
        not_underway_fuel=not_underway_totals,
        underway_distance_nm=distance,
        not_underway_distance_nm=not_underway_distance,
        voyage_count=len(voyages),
        warnings=warnings,
        underway_cf=underway_cf,
        substitutions=substitutions,
    )


# --- 조회 + 규칙 적용 --------------------------------------------------------------


async def _load_vessel(session: AsyncSession, vessel_id: UUID):
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")
    return vessel


async def _load_regulation_year(session: AsyncSession, year: int):
    """VAL-005 — 해당 연도의 규정 파라미터가 있어야 한다 (409, voyage_cii와 같은 근거)."""
    row = await param_repo.get_regulation_year(session, year)
    if row is None:
        raise ParameterError(f"해당 연도의 규정 파라미터가 없습니다. (regulation_year={year})")
    return row


async def _select_reference_line(session: AsyncSession, vessel):
    rows = await param_repo.list_reference_lines(session, vessel.ship_type)
    if not rows:
        raise ParameterError(f"선종의 기준선이 없습니다: {vessel.ship_type}")
    try:
        return select_reference_line(vessel, rows)
    except ValueError as exc:
        raise ParameterError(f"기준선을 선택할 수 없습니다: {exc}") from exc


async def _select_rating_boundary(session: AsyncSession, vessel):
    rows = await param_repo.list_rating_boundaries(session, vessel.ship_type)
    if not rows:
        raise ParameterError(f"선종의 등급 경계가 없습니다: {vessel.ship_type}")
    try:
        return select_rating_boundary(vessel, rows)
    except ValueError as exc:
        raise ParameterError(f"등급 경계를 선택할 수 없습니다: {exc}") from exc


def _resolve_transport_capacity(vessel) -> Decimal:
    try:
        return resolve_transport_capacity(vessel)
    except ValueError as exc:
        raise ValidationError(
            f"선박 제원이 부족해 계산할 수 없습니다: {exc}",
            field="vessel_id",
            field_label="선박",
        ) from exc


def _resolve_reference_capacity(vessel, reference_line) -> Decimal:
    try:
        return resolve_reference_capacity(vessel, reference_line)
    except ValueError as exc:
        raise ValidationError(
            f"선박 제원이 부족해 계산할 수 없습니다: {exc}",
            field="vessel_id",
            field_label="선박",
        ) from exc
