"""실시간 CII 3종 값 서비스 (API_SPEC §2.14, #354).

실시간 화면(``UIFLOW 2-9``)이 표시할 값 셋을 **한 번의 호출로** 반환한다.

## 왜 3종인가 (``PRD §3.3`` 표)

===  ==========================  ==========  ==================================
 #    값                          등급         화면 표기
===  ==========================  ==========  ==================================
 ⑴   **연간 누적 (YTD)**          **가능**    「현재 누적 기준 예상 등급」 · 주 표시
 ⑵   항차 구간값                  **불가**    「항차 CII 기여도」 (``COR-1``)
 ⑶   연말 예상                    가능        「연말 예상 등급」 · 보조 표시
===  ==========================  ==========  ==================================

**등급이 붙는 값은 ⑴이 유일한 규제 지표**라서다. ⑵는 항차 하나의 효율 참고값이라
등급 경계와 비교할 대상이 아니고, ⑶은 가정에 의존하는 추정이라 ``COR-2``가 표기를
「연말 예상 등급」으로 못박는다.

## 계산식을 새로 만들지 않는다

⑴과 ⑶은 모두 ``#353``의 :func:`~cii_platform.services.ytd_cii.compute_ytd_cii`를
**그대로 부른다.** 다른 것은 주입하는 ``InProgressContribution``뿐이다 —

* ⑴ ← ``#368`` 시뮬레이션 시계가 확정한 **지금까지의** 누적
* ⑶ ← 거기에 **남은 기간의 외삽분을 더한** 누적

같은 함수를 두 번 부르는 것이 두 번째 계산식을 쓰는 것보다 안전하다. 식이 갈리면
「⑴은 C인데 ⑶이 이미 C보다 좋다」 같은 모순이 조용히 생긴다.

⑵는 항차 구간만의 ``M``/``W``라 ``calculate_attained_cii``를 직접 부른다.

## 시각은 한 번만 확정한다

화면이 여러 값을 동시에 보는데 기준 시점이 어긋나면 셋이 서로 모순된다. 이
서비스는 ``resolve_as_of``로 시각을 **한 번** 확정하고 응답에 실어 보낸다
(``#368`` 계약 ⑵·⑶). 화면은 그 값으로 다시 물어 같은 결과를 얻을 수 있다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.capacity import capacity_axis
from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii
from cii_platform.calc.precision import LAYER1_ROUNDING
from cii_platform.db.repositories import not_underway as not_underway_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import CalculationError, NotFoundError, ValidationError
from cii_platform.services.simulation_clock import (
    NotUnderwayWindow,
    compute_progress,
    resolve_as_of,
)
from cii_platform.services.ytd_cii import (
    WARNING_REFERENCE_ONLY,
    InProgressContribution,
    compute_ytd_cii,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: 수치 직렬화 자릿수 (``API_SPEC §1.7``). ``cii_history``와 같은 기준이다.
_DIGITS = {"cii": 6, "ratio": 5, "distance_nm": 2, "fuel_ton": 2, "co2_ton": 2, "hours": 4}

#: ``voyage.regulation_year``의 CHECK 하한(``DB_SCHEMA §2.2``).
MIN_REGULATION_YEAR = 2019
MAX_REGULATION_YEAR = 2100

#: ⑶의 외삽 근거가 없다 — 올해 실적이 아직 없어 일평균을 낼 수 없다.
REASON_NO_BASIS = "NO_BASIS"

#: 선박에 ``reference_daily_foc_ton``이 없어 시뮬레이션 시계가 연료를 만들지
#: 못했다. 그래서 진행 중 항차분을 YTD에 **넣지 않았다** — 거리만 넣으면 항해할수록
#: 등급이 좋아지는 쪽으로 틀린다. 화면은 이 코드를 보고 제원 입력을 안내한다.
WARNING_SIM_NO_FUEL_RATE = "SIMULATION_NO_FUEL_RATE"

#: 진행 중 항차의 유종을 알 수 없다(항차 연료 기록도 선박 기본 연료도 없음).
#: CF를 붙일 수 없어 같은 이유로 진행분을 넣지 않았다.
WARNING_SIM_NO_FUEL_TYPE = "SIMULATION_NO_FUEL_TYPE"

#: ⑶을 낼 수 없다 — 연말이 지났거나 ``as_of``가 연말이다. 남은 기간이 0이면
#: 외삽분도 0이고, 그때 ⑶은 ⑴과 같은 값이라 따로 낼 이유가 없다.
REASON_YEAR_COMPLETE = "YEAR_COMPLETE"


def _publish(value: Decimal | None, kind: str) -> str | None:
    """``API_SPEC §1.7`` 문자열 직렬화. ``float``으로 되돌리면 정밀도가 사라진다."""
    if value is None:
        return None
    return str(value.quantize(Decimal(1).scaleb(-_DIGITS[kind]), rounding=LAYER1_ROUNDING))


def _validate_year(year: int) -> None:
    if not MIN_REGULATION_YEAR <= year <= MAX_REGULATION_YEAR:
        raise ValidationError(
            f"규제연도는 {MIN_REGULATION_YEAR}~{MAX_REGULATION_YEAR} 범위여야 합니다.",
            field="year",
            field_label="규제연도",
        )


# ─── ⑴ 연간 누적 (YTD) ───────────────────────────────────────────────────────


def _ytd_to_dict(ytd) -> dict[str, object]:
    """``YtdCiiOutput`` → 응답 ⑴.

    **등급이 붙는 유일한 값**이다(``PRD §3.3`` 표). ``data_available``가 거짓이면
    수치는 전부 ``null``이고, 그것은 오류가 아니라 「올해 실적이 아직 없다」는 뜻이다.
    """
    return {
        "data_available": ytd.data_available,
        "attained_cii": _publish(ytd.attained_cii, "cii"),
        "required_cii": _publish(ytd.required_cii, "cii"),
        "ratio_to_required": _publish(ytd.ratio_to_required, "ratio"),
        "rating": ytd.rating,
        "risk_level": ytd.risk_level,
        "margin_ratio": _publish(ytd.margin_ratio, "ratio"),
        "boundaries": (
            None
            if ytd.boundaries is None
            else {key: _publish(value, "cii") for key, value in ytd.boundaries.items()}
        ),
        "total_co2_ton": _publish(ytd.total_co2_t, "co2_ton"),
        "total_fuel_ton": _publish(ytd.total_fuel_ton, "fuel_ton"),
        "underway_distance_nm": _publish(ytd.underway_distance_nm, "distance_nm"),
        "not_underway_distance_nm": _publish(ytd.not_underway_distance_nm, "distance_nm"),
        "total_distance_nm": _publish(ytd.total_distance_nm, "distance_nm"),
        "voyage_count": ytd.voyage_count,
        "not_underway_period_count": ytd.not_underway_period_count,
        #
        # 대체 내역 (#449). 경고(`warnings`)는 「있었다」만 말한다 — **무엇을 고쳐야
        # 하는지는 어느 항차의 무엇이 대체됐는지를 알아야** 나온다.
        #
        "substitutions": [
            {
                "voyage_id": str(item.voyage_id),
                "axis": item.axis,
                "fuel_type": item.fuel_type,
            }
            for item in ytd.substitutions
        ],
    }


# ─── ⑵ 항차 구간값 ───────────────────────────────────────────────────────────


def _voyage_segment(
    *,
    voyage,
    progress,
    transport_capacity: Decimal,
    cf_by_fuel: dict[str, Decimal],
    fuel_code: str | None,
) -> dict[str, object]:
    """진행 중 항차 **구간만**의 CII (``PRD §3.3`` ⑵ · ``COR-1``).

    **등급을 붙이지 않는다.** 등급 경계는 연간 누적 지표에 대해 정의된 것이고,
    항차 하나에 갖다 대면 「이 항차는 D등급」이라는 규제에 없는 말이 만들어진다.

    거리나 연료가 0이면 ``attained_cii``는 ``null``이다 — 분모 0을 계산으로
    밀어 넣지 않는다. 출항 직후가 정상적으로 그 상태이며, 오류가 아니다.
    """
    base: dict[str, object] = {
        "voyage_id": str(voyage.id),
        "voyage_no": voyage.voyage_no,
        "status": voyage.status,
        "departure_port_name": voyage.departure_port_name,
        "arrival_port_name": voyage.arrival_port_name,
        "planned_distance_nm": _publish(voyage.planned_distance_nm, "distance_nm"),
        "underway_hours": _publish(progress.underway_hours, "hours"),
        "distance_nm": _publish(progress.distance_nm, "distance_nm"),
        "fuel_ton": _publish(progress.fuel_ton, "fuel_ton"),
        "fuel_type": fuel_code,
        "is_simulated": progress.is_simulated,
        # 등급이 없다는 것을 **응답에 명시**한다. 필드를 빼면 화면이 「아직 안 온
        # 값」으로 오해해 기다리거나, 스스로 등급을 만들어 낸다.
        "rating": None,
        "attained_cii": None,
        "co2_ton": None,
    }

    if fuel_code is None or fuel_code not in cf_by_fuel:
        # 유종을 모르면 CO₂를 만들 수 없다. 임의의 CF를 넣으면 화면은 깨지지 않고
        # 값만 틀린다.
        return base
    if progress.distance_nm <= 0 or progress.fuel_ton <= 0:
        return base

    result = calculate_attained_cii(
        fuel_uses=[
            FuelUse(
                fuel_code=fuel_code,
                fuel_ton=progress.fuel_ton,
                cf_value=cf_by_fuel[fuel_code],
            )
        ],
        transport_capacity=transport_capacity,
        distance_nm=progress.distance_nm,
    )
    base["attained_cii"] = _publish(result.attained_cii, "cii")
    base["co2_ton"] = _publish(result.total_co2_t, "co2_ton")
    return base


# ─── ⑶ 연말 예상 ─────────────────────────────────────────────────────────────


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    """규제연도의 시작·끝(UTC). 끝은 **다음 해 1월 1일 00:00**(열린 경계)이다."""
    return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)


def _projection_basis(
    *, ytd, as_of: datetime, regulation_year: int
) -> tuple[Decimal, Decimal, Decimal, Decimal] | str:
    """외삽의 근거 넷을 만든다 — ``(경과일, 잔여일, 일평균 거리, 일평균 연료)``.

    **가정은 「지금까지의 일평균이 연말까지 이어진다」 하나다.** 선박 제원의
    설계 속력·설계 소모율을 쓰지 않는 이유는, 그 값이 실적과 다를 때 ⑶이 ⑴과
    **반대 방향으로** 움직이기 때문이다 — 실적이 나쁜 배의 연말 예상이 좋게 나오면
    화면은 사용자를 안심시키는 쪽으로 틀린다.

    이 함수는 근거만 만들고 판단은 하지 않는다. 근거를 세울 수 없으면 사유 문자열을
    돌려주고, 호출부가 그 사유를 그대로 화면에 싣는다 — **왜 못 냈는지 말하지 않는
    빈칸은 「아직 로딩 중」으로 읽힌다.**

    :returns: 넷의 튜플, 또는 ``REASON_*`` 문자열.
    """
    year_start, year_end = _year_bounds(regulation_year)
    # as_of가 그 해 밖이면 경계로 자른다 — 과거 연도를 조회하면 연중 어느 시점이
    # 아니라 그 해 전체가 대상이다.
    cursor = min(max(as_of, year_start), year_end)

    elapsed_days = Decimal(str((cursor - year_start).total_seconds())) / Decimal("86400")
    remaining_days = Decimal(str((year_end - cursor).total_seconds())) / Decimal("86400")

    if remaining_days <= 0:
        return REASON_YEAR_COMPLETE
    if (
        not ytd.data_available
        or elapsed_days <= 0
        or ytd.total_distance_nm is None
        or ytd.total_distance_nm <= 0
        or ytd.total_fuel_ton is None
        or ytd.total_fuel_ton <= 0
    ):
        # 실적이 없으면 외삽할 비율이 없다. 0으로 두면 「연말에도 A등급」이라는
        # 근거 없는 낙관이 나온다.
        return REASON_NO_BASIS

    return (
        elapsed_days,
        remaining_days,
        ytd.total_distance_nm / elapsed_days,
        ytd.total_fuel_ton / elapsed_days,
    )


async def _project_year_end(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime,
    ytd,
    base_contribution: InProgressContribution | None,
    fuel_code: str | None,
) -> dict[str, object]:
    """⑶ 연말 예상 — ⑴에 남은 기간의 외삽분을 더해 **같은 엔진으로** 다시 낸다.

    외삽분을 ``InProgressContribution``에 실어 ``compute_ytd_cii``를 한 번 더 부른다.
    ``M``과 ``Dt``의 합만 달라지므로 등급 판정 경로는 ⑴과 **완전히 같다.**

    (그 결과 외삽분이 응답 안에서 「항해 중」 갈래에 잡힌다. ⑶은 항해/정박 내역을
    내보내지 않으므로 표시에 영향이 없고, 합계는 어느 갈래든 같다.)
    """
    basis = _projection_basis(ytd=ytd, as_of=as_of, regulation_year=regulation_year)
    if isinstance(basis, str):
        return {"data_available": False, "reason": basis}

    elapsed_days, remaining_days, daily_distance, daily_fuel = basis

    if fuel_code is None:
        # CF를 붙일 유종이 없으면 연료를 더할 수 없다. 거리만 늘리면 CII가 좋아지는
        # 쪽으로만 틀린다 — 아예 내지 않는 편이 맞다.
        return {"data_available": False, "reason": REASON_NO_BASIS}

    extra_distance = daily_distance * remaining_days
    extra_fuel = daily_fuel * remaining_days

    base_distance = base_contribution.distance_nm if base_contribution else Decimal(0)
    base_fuels = list(base_contribution.fuel_uses) if base_contribution else []

    projected = await compute_ytd_cii(
        session,
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        as_of=as_of,
        in_progress=InProgressContribution(
            distance_nm=base_distance + extra_distance,
            fuel_uses=(*base_fuels, (fuel_code, extra_fuel)),
        ),
    )

    if not projected.data_available:
        return {"data_available": False, "reason": REASON_NO_BASIS}

    return {
        "data_available": True,
        "reason": None,
        "attained_cii": _publish(projected.attained_cii, "cii"),
        "required_cii": _publish(projected.required_cii, "cii"),
        "ratio_to_required": _publish(projected.ratio_to_required, "ratio"),
        "rating": projected.rating,
        "risk_level": projected.risk_level,
        # 가정을 함께 싣는다 — `PRD §3.3` ⑶이 요구한다. 「⑶만 단독으로 크게
        # 표시하지 않는다」를 화면이 지키려면 근거가 응답에 있어야 한다.
        "assumptions": {
            "method": "YTD_DAILY_AVERAGE",
            "elapsed_days": _publish(elapsed_days, "distance_nm"),
            "remaining_days": _publish(remaining_days, "distance_nm"),
            "daily_distance_nm": _publish(daily_distance, "distance_nm"),
            "daily_fuel_ton": _publish(daily_fuel, "fuel_ton"),
            "projected_extra_distance_nm": _publish(extra_distance, "distance_nm"),
            "projected_extra_fuel_ton": _publish(extra_fuel, "fuel_ton"),
            "fuel_type": fuel_code,
        },
    }


# ─── 진행 중 항차 → 시뮬레이션 시계 ──────────────────────────────────────────


async def _resolve_progress(session: AsyncSession, *, vessel, voyage, as_of: datetime):
    """``#368`` 시뮬레이션 시계로 진행 중 항차의 누적량을 확정한다.

    속도·일일 소모율은 **항차 계획값을 먼저** 보고 없으면 선박 제원으로 내려간다.
    항차에 계획이 있는데 선박 기본값을 쓰면 그 항차의 계획이 무시되고, 두 값이
    다를 때 화면과 계획서가 어긋난다.
    """
    periods = await not_underway_repo.list_periods_for_year(
        session,
        vessel_id=vessel.id,
        regulation_year=voyage.regulation_year or as_of.year,
        as_of=as_of,
    )
    return compute_progress(
        as_of=as_of,
        departure_at=voyage.actual_departure_at or voyage.planned_departure_at,
        arrival_at=voyage.actual_arrival_at,
        speed_kn=voyage.planned_speed_kn or vessel.reference_speed_kn,
        daily_foc_ton=vessel.reference_daily_foc_ton,
        not_underway_periods=[
            NotUnderwayWindow(started_at=p.started_at, ended_at=p.ended_at) for p in periods
        ],
    )


def _dominant_fuel(ytd) -> str | None:
    """올해 **가장 많이 태운** 유종.

    ⑶의 외삽에 쓴다. 선박의 `default_fuel_type`보다 이쪽을 먼저 보는 이유는 둘이다 —
    그 열이 nullable이라 비어 있는 선박이 실제로 있고(시드의 `DONGJIN ENDURANCE`),
    **등록된 기본 연료와 실제로 태운 연료가 다를 수 있기** 때문이다. 연말까지 무엇을
    태울지 가장 잘 말해 주는 것은 올해 실적이다.

    배출량(g) 기준으로 고른다 — 톤 기준으로 고르면 CF가 낮은 연료가 과대 대표된다.
    """
    breakdown = ytd.fuel_breakdown_g
    if not breakdown:
        return None
    return max(breakdown.items(), key=lambda item: item[1])[0]


async def _voyage_fuel_code(session: AsyncSession, *, voyage, vessel) -> str | None:
    """진행 중 항차가 태우는 유종.

    항차 연료 기록의 첫 유종을 쓰고, 없으면 선박 기본 연료로 내려간다. 둘 다 없으면
    ``None`` — **임의로 ``HFO``를 채우지 않는다.** CF가 달라 CO₂가 틀리고, 화면은
    그 사실을 알 수 없다.
    """
    for fuel_use in await voyage_repo.list_fuel_uses(session, voyage.id):
        return fuel_use.fuel_type
    return vessel.default_fuel_type


# ─── 진입점 ──────────────────────────────────────────────────────────────────


async def get_current_cii(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    year: int | None = None,
    as_of: datetime | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """실시간 CII 3종 값 (API_SPEC §2.14).

    :returns: ``(data, meta)``. ``meta``에 ``as_of``·``simulated``가 들어간다 —
        라우트가 그대로 응답 ``meta``에 합친다.
    """
    resolved_as_of = resolve_as_of(as_of)
    regulation_year = year if year is not None else resolved_as_of.year
    _validate_year(regulation_year)

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None or vessel.is_deleted:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")

    voyage = await voyage_repo.find_in_progress(session, vessel_id)

    progress = None
    contribution: InProgressContribution | None = None
    fuel_code: str | None = None
    live_warnings: list[str] = []

    if voyage is not None:
        fuel_code = await _voyage_fuel_code(session, voyage=voyage, vessel=vessel)
        progress = await _resolve_progress(
            session, vessel=vessel, voyage=voyage, as_of=resolved_as_of
        )
        # 진행분은 **거리와 연료가 둘 다 있을 때만** 넣는다.
        #
        # 한쪽만 넣으면 CII가 한 방향으로만 틀린다. 특히 거리만 넣는 경우가
        # 위험하다 — 분모 Dt만 늘고 분자 M은 그대로라 **항해할수록 등급이
        # 좋아진다.** vessel.reference_daily_foc_ton은 nullable이라(DB_SCHEMA
        # §2.1) 소모율이 없는 선박에서 시계가 연료를 0으로 내놓고, 그때 이
        # 상태가 된다.
        #
        # 넣지 않은 이유를 경고로 싣는다. 값이 안 변하는 것을 화면이 「아직 출항
        # 전」으로 오해하면 사용자는 없는 제원을 채울 생각을 하지 못한다.
        if progress.distance_nm > 0 and progress.fuel_ton > 0 and fuel_code is not None:
            contribution = InProgressContribution(
                distance_nm=progress.distance_nm,
                fuel_uses=((fuel_code, progress.fuel_ton),),
            )
        elif progress.distance_nm > 0 and progress.fuel_ton <= 0:
            live_warnings.append(WARNING_SIM_NO_FUEL_RATE)
        elif progress.distance_nm > 0 and fuel_code is None:
            live_warnings.append(WARNING_SIM_NO_FUEL_TYPE)

    try:
        ytd = await compute_ytd_cii(
            session,
            vessel_id=vessel_id,
            regulation_year=regulation_year,
            as_of=resolved_as_of,
            in_progress=contribution,
        )
    except ValueError as exc:  # pragma: no cover - 방어
        raise CalculationError(str(exc)) from exc

    # ⑶은 **YTD를 근거로 외삽**하므로 진행 중 항차가 없어도 낼 수 있다. 항차가
    # 없다고 ⑶까지 비면 「연말 예상」이 정박 중에만 사라지는데, 그때야말로 사용자가
    # 가장 보고 싶어 하는 값이다.
    projection_fuel_code = fuel_code or _dominant_fuel(ytd) or vessel.default_fuel_type

    cf_by_fuel: dict[str, Decimal] = {}
    if fuel_code is not None:
        rows = await param_repo.get_fuel_types_by_codes(session, [fuel_code])
        cf_by_fuel = {code: Decimal(str(row.cf)) for code, row in rows.items()}

    data: dict[str, object] = {
        "vessel_id": str(vessel.id),
        "vessel_name": vessel.name,
        "regulation_year": regulation_year,
        "transport_capacity_basis": capacity_axis(vessel.ship_type),
        "underway_state": vessel.underway_state,
        "ytd": _ytd_to_dict(ytd),
        "current_voyage": (
            None
            if voyage is None or progress is None
            else _voyage_segment(
                voyage=voyage,
                progress=progress,
                transport_capacity=ytd.transport_capacity,
                cf_by_fuel=cf_by_fuel,
                fuel_code=fuel_code,
            )
        ),
        "year_end_projection": await _project_year_end(
            session,
            vessel_id=vessel_id,
            regulation_year=regulation_year,
            as_of=resolved_as_of,
            ytd=ytd,
            base_contribution=contribution,
            fuel_code=projection_fuel_code,
        ),
        # `API_SPEC §1.6` — 모든 계산 결과에 붙는다. `#353`이 붙인 경고를 함께 싣되
        # 중복은 제거한다.
        "warnings": sorted({WARNING_REFERENCE_ONLY, *ytd.warnings, *live_warnings}),
    }

    meta = {
        "as_of": resolved_as_of.isoformat(),
        # `PRD R-5` 「시뮬레이션 데이터」 배지의 근거. 시계가 만든 값이 하나라도
        # 섞여 있으면 참이다 — 화면이 배지를 조건부로 감출 근거를 스스로 만들지
        # 않게 서버가 판정해 준다.
        "simulated": bool(progress is not None and progress.is_simulated),
    }
    return data, meta
