"""데이터 점검 — 선대 CII 계산에 **실측이 아닌 값이** 어디 들어갔는가 (``UIFLOW 2-11`` · #513).

``API_SPEC §2.16`` ``GET /fleet/data-quality``의 본체다. 판정 규칙은 ``PRD §17.4``이고,
수식은 ``calc/data_quality.py``에 있다.

「빠진 항차」가 아니라 「실측이 아닌 값으로 계산된 항차」다
--------------------------------------------------------
``PRD §12.3``은 실적이 없을 때 항차를 빼지 않고 ``§8.3`` 우선순위에 따라 **계획값을 쓴다.**
그래서 이 화면이 보여 줄 것은 사라진 항차가 아니라 **실측인 척하는 추정값**이다
(``UIFLOW 2-11``).

심각도 다섯 — 무엇을 어디서 가져오나
----------------------------------
=============  =============================================  ====================================
심각도         판정                                          재료
=============  =============================================  ====================================
대체 계산      실적 대신 계획값이 들어갔다                   ``ytd.substitutions`` (#449)
계산 불가      ⑴ 선박 CII를 낼 수 없다 ⑵ 연료 행에 넣을        ⑴ 선대 요약과 같은 사유 (#419)
               값이 하나도 없다                               ⑵ ``ytd.unfilled`` (#513)
이상치         계산됐으나 신뢰도 낮음                        ``calc.data_quality.judge_anomaly``
실적 확정 전   ``COMPLETED``에서 ``CONFIRMED``로 미전이       ``voyage.status`` (``PRD §8.1``)
공적 기록과    넣은 출항·도착·정박 시각이 공적 재항 기록과    ``port_call_record`` (#1197 ·
다름           6시간을 넘게 다르다 — **완결성에 넣지 않는다**  ``port_calls/reconcile.py``)
=============  =============================================  ====================================

**집계 기준은 실적 확정 항차(``INCLUDE_AS_ACTUAL``)이며 진행 중 항차를 넣지 않는다.** 진행분은
시계가 만든 추정이라(``#368``) 「실측이 아니다」가 정의상 참이고, 매 조회마다 값이 바뀐다 —
넣으면 이 화면의 모든 선박이 늘 「대체 계산」을 갖는다.

완결성의 분자·분모와 제외 내역 (`#1532`)
--------------------------------------
비율만 주면 0%든 54.2%든 화면에서 검산할 수 없다 — 분자·분모는 서버만 안다. 그래서
``completeness``에 누적 CO₂ · 실측으로 인정된 CO₂ · 축별로 빠진 CO₂를 함께 싣는다.

한 항차가 여러 심각도에 걸려도 **빠진 CO₂는 한 축에만** 더한다 — 우선순위는
계산 불가 > 대체 계산 > 이상치(:data:`_EXCLUSION_PRIORITY`). 겹치는 항차를 두 축에 다 더하면
「실측 + 제외 합 = 누적」이 성립하지 않아 내역을 검산할 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.data_quality import (
    VoyageObservation,
    co2_grams,
    completeness_ratio,
    judge_anomaly,
)
from cii_platform.calc.precision import SERIALIZATION_ROUNDING, layer1_context
from cii_platform.db.repositories import not_underway as not_underway_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import port_call as port_call_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import AppError, ParameterError, ValidationError
from cii_platform.port_calls.reconcile import (
    FIELD_ARRIVAL,
    FIELD_BERTH_END,
    FIELD_BERTH_START,
    FIELD_DEPARTURE,
    EnteredTime,
    Mismatch,
    RecordedCall,
    reconcile,
)
from cii_platform.services.fleet_summary import (
    UNAVAILABLE_CALCULATION_ERROR,
    UNAVAILABLE_NO_DATA,
    UNAVAILABLE_NO_PARAMETERS,
    spec_gap,
)
from cii_platform.services.request_cache import cached
from cii_platform.services.request_cache import enable as enable_request_cache
from cii_platform.services.request_cache import put as cache_put
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import (
    POLICY_INCLUDE_AS_ACTUAL,
    SUBSTITUTION_AXIS_FUEL,
    YtdCiiOutput,
    compute_ytd_cii,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.db.models.not_underway_period import NotUnderwayPeriod
    from cii_platform.db.models.vessel import Vessel

#: ``API_SPEC §2.16`` ``issues[].severity`` — **목록 순서가 곧 화면의 그룹 순서**다
#: (``DESIGN_SYSTEM §2.3.1`` 표 순서).
SEVERITY_SUBSTITUTED = "SUBSTITUTED"
SEVERITY_UNAVAILABLE = "UNAVAILABLE"
SEVERITY_ANOMALY = "ANOMALY"
SEVERITY_UNCONFIRMED = "UNCONFIRMED"
#: 공적 기록과 다름 (`#1197` · ``PRD §17.4.4``) — 넣은 시각이 공적 재항 기록과 6시간을 넘게
#: 다르다. **완결성에 들어가지 않는다**(:data:`_EXCLUSION_PRIORITY`에 없다) — 계산에 쓰인 값이
#: 실측인지와는 다른 질문이고, 대조 결과는 계산 입력이 아니다.
SEVERITY_PUBLIC_RECORD = "PUBLIC_RECORD"
SEVERITY_ORDER: tuple[str, ...] = (
    SEVERITY_SUBSTITUTED,
    SEVERITY_UNAVAILABLE,
    SEVERITY_ANOMALY,
    SEVERITY_UNCONFIRMED,
    SEVERITY_PUBLIC_RECORD,
)
#: ``PUBLIC_RECORD`` 행의 ``codes`` 접미사 앞머리 — ``PUBLIC_RECORD:ARRIVAL``.
PUBLIC_RECORD_CODE = "PUBLIC_RECORD"


#: 계산 불가 — 연료 행에 실적도 계획값도 없다 (선박 단위 사유와 구분).
UNAVAILABLE_FUEL_UNFILLED = "FUEL_UNFILLED"

#: 계산 불가 — 이 항차에 연료 기록이 **한 행도 없다** (`#1095` ⑵ · 결정요청 v7 §6.2).
#:
#: :data:`UNAVAILABLE_FUEL_UNFILLED`와 **가른다.** 합치면 「행은 있는데 값이 빔」과 「행이
#: 아예 없음」이 같은 문구로 떠, 사용자가 할 행동(「값을 채운다」 / 「행을 추가한다」)이
#: 구분되지 않는다. 유종 접미사가 없다 — 붙일 유종이 없기 때문이다.
UNAVAILABLE_FUEL_NO_RECORD = "FUEL_NO_RECORD"

#: ``cii_impact_reason`` — 영향을 낼 수 없는 이유 (``PRD §17.4.2``).
#: 이 항차 하나뿐이라 빼면 누적 CII 자체가 없다.
IMPACT_ONLY_VOYAGE = "ONLY_VOYAGE"
#: 선박의 누적 CII를 낼 수 없어 비교할 기준이 없다.
IMPACT_BASE_UNAVAILABLE = "BASE_UNAVAILABLE"

_STATUS_COMPLETED = "COMPLETED"
_CII_DIGITS = 4
_RATIO_DIGITS = 4
#: CO₂ 톤 문자열의 소수 자릿수 — `§2.7` ``co2_ton``과 같다. 표시(소수 1)보다 길어 **절사**한다
#: (`#1600` · ``TECH_SPEC §1.2.1`` 「응답 직렬화의 절사」).
_CO2_TON_DIGITS = 2
#: ``PRD §3.3.2`` — 연료 톤 × CF(tCO₂/t) → g. 응답은 t로 되돌려 싣는다.
_GRAMS_PER_TON = Decimal(1_000_000)

#: 완결성에서 빠진 CO₂를 **어느 축에** 더하는가 — 한 항차가 여러 심각도에 걸리면 앞선
#: 것 하나에만 더한다. 순서는 「고칠 수 없는 것」이 먼저다: 계산 불가는 값 자체가 없고,
#: 대체 계산은 계획값이 들어갔으며, 이상치는 값은 있으나 믿기 어려운 것이다.
_EXCLUSION_PRIORITY: tuple[str, ...] = (
    SEVERITY_UNAVAILABLE,
    SEVERITY_SUBSTITUTED,
    SEVERITY_ANOMALY,
)


def _publish(value: Decimal | None, digits: int) -> str | None:
    """CII가 아닌 값(완전성 비율)을 문자열로 확정한다 — ``API_SPEC §1.7`` (선대 요약과 같은 규약).

    **절사한다** (`#1600`). 완전성 비율은 4자리로 보내고 화면은 백분율 1자리(소수 3)로 다시
    반올림한다 — 여기서 반올림하면 두 번 반올림되어 약 5%가 끝자리 1이 틀렸다(20만 건 재현).
    반올림 모드를 명시한다 — ``f"{value:.4f}"``는 호출 스레드의 Decimal 컨텍스트를 따라 갈린다.
    """
    if value is None:
        return None
    return str(value.quantize(Decimal(1).scaleb(-digits), rounding=SERIALIZATION_ROUNDING))


def _publish_cii(value: Decimal | None) -> str | None:
    """CII 값(누적·제외 시·차이)을 소수 4자리로 **절사**한다 (`#1349` · 선대 요약과 같다).

    ``delta``는 음수일 수 있다 — ``ROUND_DOWN``은 0 방향 절사라 부호에 대칭이고, 절사 뒤
    화면의 3자리 반올림은 원값 직접 반올림과 같다(`TECH_SPEC §1.2.1` 「응답 직렬화의 절사」).
    """
    if value is None:
        return None
    return str(value.quantize(Decimal(1).scaleb(-_CII_DIGITS), rounding=SERIALIZATION_ROUNDING))


def _publish_co2_ton(grams: Decimal) -> str:
    """CO₂ g → t 문자열 (소수 2자리 · **절사** · `#1600`) — `§2.7` ``co2_ton``과 같은 규약."""
    return str(
        (grams / _GRAMS_PER_TON).quantize(
            Decimal(1).scaleb(-_CO2_TON_DIGITS), rounding=SERIALIZATION_ROUNDING
        )
    )


def _completeness_block(
    measured_g: Decimal, total_g: Decimal, excluded_g: dict[str, Decimal]
) -> dict[str, str]:
    """``completeness`` — 비율의 분자·분모와 축별 제외 내역 (``API_SPEC §2.16`` · `#1532`).

    ``measured + Σexcluded = total``이 **g 단위에서 정확히** 성립한다 — 각 항차의 CO₂를
    실측 아니면 한 축에만 더하기 때문이다. 톤 문자열은 다섯 값이 **각각** 소수 2자리로
    반올림되므로, 문자열끼리 더하면 누적과 **최대 0.02 t** 어긋날 수 있다(가수 넷의
    반올림 오차가 한쪽으로 쏠릴 때 — 코드 검토에서 재현). 정확한 검산은 g 단위다.
    """
    return {
        "total_co2_ton": _publish_co2_ton(total_g),
        "measured_co2_ton": _publish_co2_ton(measured_g),
        "excluded_unavailable_co2_ton": _publish_co2_ton(excluded_g[SEVERITY_UNAVAILABLE]),
        "excluded_substituted_co2_ton": _publish_co2_ton(excluded_g[SEVERITY_SUBSTITUTED]),
        "excluded_anomaly_co2_ton": _publish_co2_ton(excluded_g[SEVERITY_ANOMALY]),
    }


@dataclass(frozen=True)
class _VesselBase:
    """선박 한 척의 기준 누적값. ``ytd``가 ``None``이면 ``reason``이 사유다."""

    ytd: YtdCiiOutput | None
    reason: str | None


async def _base_ytd(session: AsyncSession, vessel: Vessel, year: int) -> _VesselBase:
    """선대 요약(`#419`)과 **같은 규칙으로** 사유를 만든다.

    사유 어휘를 새로 만들지 않는다 — 대시보드가 「제원 미비」라고 한 선박을 이 화면이
    다른 이름으로 부르면 사용자는 둘을 다른 문제로 읽는다.
    """
    try:
        ytd = await compute_ytd_cii(session, vessel_id=vessel.id, regulation_year=year)
    except ParameterError:
        return _VesselBase(None, UNAVAILABLE_NO_PARAMETERS)
    except ValidationError:
        return _VesselBase(None, spec_gap(vessel) or UNAVAILABLE_CALCULATION_ERROR)
    except AppError:
        return _VesselBase(None, UNAVAILABLE_CALCULATION_ERROR)
    return _VesselBase(ytd, None)


def _sailing_hours(voyage) -> Decimal | None:
    if voyage.actual_departure_at is None or voyage.actual_arrival_at is None:
        return None
    seconds = Decimal(str((voyage.actual_arrival_at - voyage.actual_departure_at).total_seconds()))
    if seconds <= 0:
        return None
    return seconds / Decimal(3600)


def _observation(voyage, fuel_rows, vessel: Vessel) -> VoyageObservation:
    """판정에 **실측값만** 넘긴다 — 대체된 축은 ``None``이다 (``calc`` docstring)."""
    actual_fuels = [row.actual_fuel_ton for row in fuel_rows]
    fuel_ton = (
        sum((Decimal(v) for v in actual_fuels), Decimal(0))
        if fuel_rows and all(v is not None for v in actual_fuels)
        else None
    )
    return VoyageObservation(
        distance_nm=(
            Decimal(voyage.actual_distance_nm) if voyage.actual_distance_nm is not None else None
        ),
        fuel_ton=fuel_ton,
        recorded_speed_kn=(
            Decimal(voyage.actual_avg_speed_kn) if voyage.actual_avg_speed_kn is not None else None
        ),
        sailing_hours=_sailing_hours(voyage),
        reference_speed_kn=(
            Decimal(vessel.reference_speed_kn) if vessel.reference_speed_kn is not None else None
        ),
        reference_daily_foc_ton=(
            Decimal(vessel.reference_daily_foc_ton)
            if vessel.reference_daily_foc_ton is not None
            else None
        ),
    )


@layer1_context
def _voyage_co2(fuel_rows) -> Decimal:
    """집계가 실제로 더한 값 기준의 항차 CO₂(g) — 실적이 없으면 계획값, 둘 다 없으면 0.

    ``ytd_cii._aggregate``와 **같은 선택 규칙**이다. 다르게 고르면 완결성 비율의 분모가
    선박 누적 CO₂와 어긋난다.
    """
    used = []
    for row in fuel_rows:
        ton = row.actual_fuel_ton if row.actual_fuel_ton is not None else row.planned_fuel_ton
        if ton is not None:
            used.append((Decimal(ton), Decimal(row.cf_used)))
    return co2_grams(used)


async def _impact(
    session: AsyncSession, *, vessel: Vessel, year: int, base: YtdCiiOutput | None, voyage_id: UUID
) -> tuple[dict[str, object] | None, str | None]:
    """그 항차를 **뺀** 누적 CII와의 차이 (``PRD §17.4.2``).

    대체값이 맞았을 수도 있다 — 그래서 「틀린 만큼」이 아니라 **「이 항차가 등급을 얼마나
    움직이고 있나」**를 낸다. 둘 중 무엇이 참인지 모르는 상태에서 말할 수 있는 것이 이것뿐이다.
    """
    if base is None or not base.data_available or base.attained_cii is None:
        return None, IMPACT_BASE_UNAVAILABLE
    try:
        without = await compute_ytd_cii(
            session,
            vessel_id=vessel.id,
            regulation_year=year,
            exclude_voyage_ids=frozenset({voyage_id}),
        )
    except AppError:
        return None, IMPACT_BASE_UNAVAILABLE
    if not without.data_available or without.attained_cii is None:
        return None, IMPACT_ONLY_VOYAGE
    return (
        {
            "attained_cii": _publish_cii(base.attained_cii),
            "attained_cii_without": _publish_cii(without.attained_cii),
            "delta": _publish_cii(base.attained_cii - without.attained_cii),
            "rating": base.rating,
            "rating_without": without.rating,
        },
        None,
    )


def _public_record_block(mismatches: list[Mismatch], source: str) -> dict[str, object]:
    """``issues[].public_record`` — 어긋남과 **언제 기준의 공적 기록인가**(출처 표기).

    ``fetched_at``은 짝지은 기록 가운데 **가장 오래 전에 받은 것**이다 — 한 항차의 어긋남이
    여러 기록에 걸치면 가장 낡은 기준을 알려야 「이 시각 이후 정정됐을 수 있다」가 성립한다.
    """
    return {
        "source": source,
        "fetched_at": min(item.fetched_at for item in mismatches).isoformat(),
        "mismatches": [
            {
                "field": item.field,
                "entered_at": item.entered_at.isoformat(),
                "recorded_at": item.recorded_at.isoformat(),
                "difference_minutes": item.difference_minutes,
                "port_authority_code": item.port_authority_code,
                "port_authority_name": item.port_authority_name,
            }
            for item in mismatches
        ],
    }


async def get_fleet_data_quality(
    session: AsyncSession, *, regulation_year: int | None = None
) -> dict[str, object]:
    """선대의 데이터 점검 결과 (``API_SPEC §2.16``).

    **선박이 0척이면 빈 결과다** — 선대 요약(`§2.8`)과 같은 이유로 오류가 아니다.
    """
    year = regulation_year if regulation_year is not None else resolve_as_of(None).year

    enable_request_cache(session)
    vessels = await vessel_repo.list_all_active(session)
    for row in vessels:
        cache_put(session, ("vessel", row.id), row)

    # 연도 파라미터는 선대 공통 — 없으면 요청 전체가 409다(`§2.8`과 같은 규약).
    if (
        vessels
        and await cached(
            session,
            ("regulation_year", year),
            lambda: param_repo.get_regulation_year(session, year),
        )
        is None
    ):
        raise ParameterError(f"해당 연도의 규정 파라미터가 없습니다. (기준연도 {year})")

    # 공적 기록 대조의 재료 (`#1197`) — 호출부호가 있는 배만. 바깥 서비스를 부르지 않고
    # 수집기가 받아 둔 표만 읽는다(``port_calls/collect.py``).
    signed = [vessel for vessel in vessels if vessel.call_sign]
    records_by_sign: dict[str, list[RecordedCall]] = {}
    record_source_by_sign: dict[str, str] = {}
    for row in await port_call_repo.list_for_call_signs(
        session, [str(vessel.call_sign) for vessel in signed]
    ):
        records_by_sign.setdefault(row.call_sign, []).append(
            RecordedCall(
                port_authority_code=row.port_authority_code,
                port_authority_name=row.port_authority_name,
                arrival_at=row.arrival_at,
                departure_at=row.departure_at,
                fetched_at=row.fetched_at,
            )
        )
        record_source_by_sign.setdefault(row.call_sign, row.source)
    periods_by_voyage: dict[UUID, list[NotUnderwayPeriod]] = {}
    signed_with_records = [vessel.id for vessel in signed if vessel.call_sign in records_by_sign]
    if signed_with_records:
        grouped = await not_underway_repo.list_periods_for_year_for_vessels(
            session, vessel_ids=signed_with_records, regulation_year=year
        )
        for periods in grouped.values():
            for period in periods:
                # 항차에 매이지 않은 구간은 항차 단위 목록에 둘 자리가 없다 — 대조하지 않는다.
                if period.voyage_id is not None:
                    periods_by_voyage.setdefault(period.voyage_id, []).append(period)

    issues: list[dict[str, object]] = []
    vessel_rows: list[dict[str, object]] = []
    unjudged = 0
    fleet_measured = Decimal(0)
    fleet_total = Decimal(0)
    fleet_excluded = dict.fromkeys(_EXCLUSION_PRIORITY, Decimal(0))

    for vessel in vessels:
        base = await _base_ytd(session, vessel, year)
        ytd = base.ytd
        voyages = await voyage_repo.list_annual_inclusions(
            session, vessel_id=vessel.id, regulation_year=year, policy=POLICY_INCLUDE_AS_ACTUAL
        )
        fuel_by_voyage = await voyage_repo.list_fuel_uses_by_voyage_ids(
            session, [voyage.id for voyage in voyages]
        )

        vessel_reason = base.reason
        if vessel_reason is None and ytd is not None and not ytd.data_available and voyages:
            # 실적 항차가 있는데 거리·연료 합이 0 — 「아직 항차가 없다」와 다르다.
            vessel_reason = UNAVAILABLE_NO_DATA
        if vessel_reason is not None:
            issues.append(
                {
                    "severity": SEVERITY_UNAVAILABLE,
                    "vessel_id": str(vessel.id),
                    "vessel_name": vessel.name,
                    "voyage_id": None,
                    "voyage_no": None,
                    "codes": [vessel_reason],
                    "cii_impact": None,
                    "cii_impact_reason": None,
                    "public_record": None,
                }
            )

        unfilled_keys = {
            (item.voyage_id, item.fuel_type) for item in (ytd.unfilled if ytd is not None else [])
        }
        measured = Decimal(0)
        total = Decimal(0)
        excluded = dict.fromkeys(_EXCLUSION_PRIORITY, Decimal(0))

        vessel_records = records_by_sign.get(str(vessel.call_sign), []) if vessel.call_sign else []
        for voyage in voyages:
            rows = fuel_by_voyage.get(voyage.id, [])
            voyage_issues: list[tuple[str, list[str]]] = []
            public_record: dict[str, object] | None = None

            substituted = []
            if ytd is not None:
                for item in ytd.substitutions:
                    if item.voyage_id != voyage.id:
                        continue
                    # 넣은 값이 없는 행은 대체가 아니라 계산 불가다(아래).
                    if (
                        item.axis == SUBSTITUTION_AXIS_FUEL
                        and (item.voyage_id, item.fuel_type) in unfilled_keys
                    ):
                        continue
                    substituted.append(
                        item.axis if item.fuel_type is None else f"{item.axis}:{item.fuel_type}"
                    )
            if substituted:
                voyage_issues.append((SEVERITY_SUBSTITUTED, substituted))

            unfilled = [
                # ``fuel_type``이 ``None``이면 **행이 아예 없는** 항차다 (`#1095` ⑵).
                UNAVAILABLE_FUEL_NO_RECORD
                if fuel_type is None
                else f"{UNAVAILABLE_FUEL_UNFILLED}:{fuel_type}"
                for (voyage_id, fuel_type) in sorted(unfilled_keys, key=lambda k: str(k[1]))
                if voyage_id == voyage.id
            ]
            if unfilled:
                voyage_issues.append((SEVERITY_UNAVAILABLE, unfilled))

            judgement = judge_anomaly(_observation(voyage, rows, vessel))
            if not judgement.judged:
                unjudged += 1
            if judgement.codes:
                voyage_issues.append((SEVERITY_ANOMALY, list(judgement.codes)))

            if voyage.status == _STATUS_COMPLETED:
                voyage_issues.append((SEVERITY_UNCONFIRMED, [_STATUS_COMPLETED]))

            if vessel_records:
                entries = [
                    EnteredTime(
                        FIELD_DEPARTURE, voyage.actual_departure_at, voyage.departure_port_name
                    ),
                    EnteredTime(FIELD_ARRIVAL, voyage.actual_arrival_at, voyage.arrival_port_name),
                ]
                for period in periods_by_voyage.get(voyage.id, []):
                    entries.append(
                        EnteredTime(FIELD_BERTH_START, period.started_at, period.port_name)
                    )
                    entries.append(EnteredTime(FIELD_BERTH_END, period.ended_at, period.port_name))
                mismatches = reconcile(entries, vessel_records)
                if mismatches:
                    codes = list(
                        dict.fromkeys(f"{PUBLIC_RECORD_CODE}:{item.field}" for item in mismatches)
                    )
                    voyage_issues.append((SEVERITY_PUBLIC_RECORD, codes))
                    public_record = _public_record_block(
                        mismatches, record_source_by_sign[str(vessel.call_sign)]
                    )

            voyage_co2 = _voyage_co2(rows)
            total += voyage_co2
            # 완결성의 「실측」 — 대체·계산 불가·이상치가 없는 항차 (`PRD §17.4.3`).
            # 실적 확정 전은 값 자체는 실측이므로 빼지 않는다. 빠진 항차의 CO₂는
            # **우선순위상 앞선 한 축에만** 더한다 — 그래야 내역의 합이 누적과 맞는다.
            severities = {severity for severity, _ in voyage_issues}
            axis = next((s for s in _EXCLUSION_PRIORITY if s in severities), None)
            if axis is None:
                measured += voyage_co2
            else:
                excluded[axis] += voyage_co2

            if not voyage_issues:
                continue
            impact, impact_reason = await _impact(
                session, vessel=vessel, year=year, base=ytd, voyage_id=voyage.id
            )
            for severity, codes in voyage_issues:
                issues.append(
                    {
                        "severity": severity,
                        "vessel_id": str(vessel.id),
                        "vessel_name": vessel.name,
                        "voyage_id": str(voyage.id),
                        "voyage_no": voyage.voyage_no,
                        "codes": codes,
                        "cii_impact": impact,
                        "cii_impact_reason": impact_reason,
                        "public_record": (
                            public_record if severity == SEVERITY_PUBLIC_RECORD else None
                        ),
                    }
                )

        ratio: Decimal | None = None
        completeness: dict[str, str] | None = None
        if ytd is not None and ytd.data_available:
            # not under way 연료는 기록된 실측이다 — 분자·분모 모두에 더한다.
            nu = ytd.not_underway_co2_g or Decimal(0)
            ratio = completeness_ratio(measured + nu, total + nu)
            completeness = _completeness_block(measured + nu, total + nu, excluded)
            fleet_measured += measured + nu
            fleet_total += total + nu
            for severity in _EXCLUSION_PRIORITY:
                fleet_excluded[severity] += excluded[severity]

        vessel_rows.append(
            {
                "vessel_id": str(vessel.id),
                "vessel_name": vessel.name,
                "data_available": bool(ytd is not None and ytd.data_available),
                "unavailable_reason": vessel_reason,
                "ytd_attained_cii": _publish_cii(ytd.attained_cii if ytd else None),
                "ytd_rating": ytd.rating if ytd else None,
                "voyage_count": len(voyages),
                "completeness_ratio": _publish(ratio, _RATIO_DIGITS),
                # 비율을 낼 수 없는 선박(누적 없음)은 내역도 없다 — 재료가 같다.
                "completeness": completeness,
            }
        )

    issues.sort(
        key=lambda item: (
            SEVERITY_ORDER.index(str(item["severity"])),
            str(item["vessel_name"]).casefold(),
            str(item["voyage_no"] or ""),
        )
    )
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for item in issues:
        counts[str(item["severity"])] += 1

    return {
        "regulation_year": year,
        "summary": {
            "substituted_count": counts[SEVERITY_SUBSTITUTED],
            "unavailable_count": counts[SEVERITY_UNAVAILABLE],
            "anomaly_count": counts[SEVERITY_ANOMALY],
            "unconfirmed_count": counts[SEVERITY_UNCONFIRMED],
            "public_record_count": counts[SEVERITY_PUBLIC_RECORD],
            # 이상치 0건과 섞지 않는다 — 판정하지 못한 항차 수 (`PRD §17.4.1`).
            "anomaly_unjudged_count": unjudged,
            "completeness_ratio": _publish(
                completeness_ratio(fleet_measured, fleet_total), _RATIO_DIGITS
            ),
            # 선대 값은 선박들의 분자·분모를 각각 더한 것이다(`PRD §17.4.3`) — 내역도 같다.
            "completeness": _completeness_block(fleet_measured, fleet_total, fleet_excluded),
        },
        "vessels": vessel_rows,
        "issues": issues,
    }
