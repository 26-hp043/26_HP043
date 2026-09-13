"""데이터 점검 — 선대 CII 계산에 **실측이 아닌 값이** 어디 들어갔는가 (``UIFLOW 2-11`` · #513).

``API_SPEC §2.16`` ``GET /fleet/data-quality``의 본체다. 판정 규칙은 ``PRD §17.4``이고,
수식은 ``calc/data_quality.py``에 있다.

「빠진 항차」가 아니라 「실측이 아닌 값으로 계산된 항차」다
--------------------------------------------------------
``PRD §12.3``은 실적이 없을 때 항차를 빼지 않고 ``§8.3`` 우선순위에 따라 **계획값을 쓴다.**
그래서 이 화면이 보여 줄 것은 사라진 항차가 아니라 **실측인 척하는 추정값**이다
(``UIFLOW 2-11``).

심각도 넷 — 무엇을 어디서 가져오나
----------------------------------
=============  =============================================  ====================================
심각도         판정                                          재료
=============  =============================================  ====================================
대체 계산      실적 대신 계획값이 들어갔다                   ``ytd.substitutions`` (#449)
계산 불가      ⑴ 선박 CII를 낼 수 없다 ⑵ 연료 행에 넣을        ⑴ 선대 요약과 같은 사유 (#419)
               값이 하나도 없다                               ⑵ ``ytd.unfilled`` (#513)
이상치         계산됐으나 신뢰도 낮음                        ``calc.data_quality.judge_anomaly``
실적 미입력    ``COMPLETED``에서 ``CONFIRMED``로 미전이       ``voyage.status`` (``PRD §8.4``)
=============  =============================================  ====================================

**집계 기준은 실적 확정 항차(``INCLUDE_AS_ACTUAL``)이며 진행 중 항차를 넣지 않는다.** 진행분은
시계가 만든 추정이라(``#368``) 「실측이 아니다」가 정의상 참이고, 매 조회마다 값이 바뀐다 —
넣으면 이 화면의 모든 선박이 늘 「대체 계산」을 갖는다.
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
from cii_platform.calc.precision import layer1_context
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import AppError, ParameterError, ValidationError
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

    from cii_platform.db.models.vessel import Vessel

#: ``API_SPEC §2.16`` ``issues[].severity`` — **목록 순서가 곧 화면의 그룹 순서**다
#: (``DESIGN_SYSTEM §2.3.1`` 표 순서).
SEVERITY_SUBSTITUTED = "SUBSTITUTED"
SEVERITY_UNAVAILABLE = "UNAVAILABLE"
SEVERITY_ANOMALY = "ANOMALY"
SEVERITY_UNCONFIRMED = "UNCONFIRMED"
SEVERITY_ORDER: tuple[str, ...] = (
    SEVERITY_SUBSTITUTED,
    SEVERITY_UNAVAILABLE,
    SEVERITY_ANOMALY,
    SEVERITY_UNCONFIRMED,
)

#: 계산 불가 — 연료 행에 실적도 계획값도 없다 (선박 단위 사유와 구분).
UNAVAILABLE_FUEL_UNFILLED = "FUEL_UNFILLED"

#: ``cii_impact_reason`` — 영향을 낼 수 없는 이유 (``PRD §17.4.2``).
#: 이 항차 하나뿐이라 빼면 누적 CII 자체가 없다.
IMPACT_ONLY_VOYAGE = "ONLY_VOYAGE"
#: 선박의 누적 CII를 낼 수 없어 비교할 기준이 없다.
IMPACT_BASE_UNAVAILABLE = "BASE_UNAVAILABLE"

_STATUS_COMPLETED = "COMPLETED"
_CII_DIGITS = 4
_RATIO_DIGITS = 4


def _publish(value: Decimal | None, digits: int) -> str | None:
    """Layer 1 값을 문자열로 확정한다 — ``API_SPEC §1.7`` (선대 요약과 같은 규약)."""
    if value is None:
        return None
    return f"{value:.{digits}f}"


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
            "attained_cii": _publish(base.attained_cii, _CII_DIGITS),
            "attained_cii_without": _publish(without.attained_cii, _CII_DIGITS),
            "delta": _publish(base.attained_cii - without.attained_cii, _CII_DIGITS),
            "rating": base.rating,
            "rating_without": without.rating,
        },
        None,
    )


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

    issues: list[dict[str, object]] = []
    vessel_rows: list[dict[str, object]] = []
    unjudged = 0
    fleet_measured = Decimal(0)
    fleet_total = Decimal(0)

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
                }
            )

        unfilled_keys = {
            (item.voyage_id, item.fuel_type) for item in (ytd.unfilled if ytd is not None else [])
        }
        measured = Decimal(0)
        total = Decimal(0)

        for voyage in voyages:
            rows = fuel_by_voyage.get(voyage.id, [])
            voyage_issues: list[tuple[str, list[str]]] = []

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
                f"{UNAVAILABLE_FUEL_UNFILLED}:{fuel_type}"
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

            voyage_co2 = _voyage_co2(rows)
            total += voyage_co2
            # 완결성의 「실측」 — 대체·계산 불가·이상치가 없는 항차 (`PRD §17.4.3`).
            # 실적 미입력은 값 자체는 실측이므로 빼지 않는다.
            if not any(
                severity in (SEVERITY_SUBSTITUTED, SEVERITY_UNAVAILABLE, SEVERITY_ANOMALY)
                for severity, _ in voyage_issues
            ):
                measured += voyage_co2

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
                    }
                )

        ratio: Decimal | None = None
        if ytd is not None and ytd.data_available:
            # not under way 연료는 기록된 실측이다 — 분자·분모 모두에 더한다.
            nu = ytd.not_underway_co2_g or Decimal(0)
            ratio = completeness_ratio(measured + nu, total + nu)
            fleet_measured += measured + nu
            fleet_total += total + nu

        vessel_rows.append(
            {
                "vessel_id": str(vessel.id),
                "vessel_name": vessel.name,
                "data_available": bool(ytd is not None and ytd.data_available),
                "unavailable_reason": vessel_reason,
                "ytd_attained_cii": _publish(ytd.attained_cii if ytd else None, _CII_DIGITS),
                "ytd_rating": ytd.rating if ytd else None,
                "voyage_count": len(voyages),
                "completeness_ratio": _publish(ratio, _RATIO_DIGITS),
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
            # 이상치 0건과 섞지 않는다 — 판정하지 못한 항차 수 (`PRD §17.4.1`).
            "anomaly_unjudged_count": unjudged,
            "completeness_ratio": _publish(
                completeness_ratio(fleet_measured, fleet_total), _RATIO_DIGITS
            ),
        },
        "vessels": vessel_rows,
        "issues": issues,
    }
