"""올해 누적 CII 추이 — 항차 경계마다 한 점 (API_SPEC §2.18, #1671).

실시간 CII 화면(`UIFLOW 2-9`)이 지도 아래에 **연초~오늘 실적 · 오늘~연말 계획**의 곡선을
그린다. `§2.14`는 **한 시점**의 값만 주므로 이 선을 그릴 데이터가 없었고, 화면이 항차
목록으로 직접 누적을 계산하면 Layer 1(`Decimal`) 밖 계산이 된다.

## 계산식을 새로 만들지 않는다

점 하나 = :func:`~cii_platform.services.cii_current.resolve_ytd_at` 한 번이다. `§2.14`의 ⑴
연간 누적이 부르는 **바로 그 조립**을 시각만 바꿔 부르므로, 실적 쪽 마지막 점(`as_of`)은
같은 `as_of`의 ``ytd.attained_cii``와 **구성상** 같다. 계획 쪽은 ⑶ 연말 예상과 같은
입력(:func:`collect_annual_inputs`) · 같은 엔진(``project_deterministic``)에 잔여 항차를
도착 예정 순으로 **한 건씩 더해 가며** 점을 찍는다 — 마지막 점이 곧 ``year_end_projection``이다.

## 왜 `/cii/current?as_of=`를 반복하지 않는가 (이슈 「가」)

과거 ``as_of``는 그 뒤에 도착한 항차를 **통째로** 뺀다(저장소 절단이 도착 시각 기준 —
``list_annual_inclusions``). 3월 1일에 항해 중이던 항차가 3월 20일에 도착했다면 3월 1일
점에는 그 항차가 없다가 3월 20일에 한꺼번에 들어온다. 그 자체는 이 곡선에서도 같다
(**확정 항차는 도착 시각에 전량 들어간다** — 아래 「점을 만드는 시각」). 다른 것은 **호출
횟수**(월말마다 9~12회 → 한 번)와 **점의 위치**다 — 등급이 바뀐 시점은 월말이 아니라 항차
경계에 있고, 이 곡선의 목적이 「언제부터 나빠지고 있나」이므로 그 시각을 정확히 찍는다.

## 점을 만드는 시각

======================  ========================================================
 실적(``ACTUAL``)         확정 항차의 도착 시각 ``coalesce(actual_arrival_at,
                         planned_arrival_at)`` — 저장소 절단 술어와 **같은 식**.
                         둘 다 없으면 자기 점이 없다(누적에는 든다).
                         종료된 정박 구간의 ``ended_at``.
 진행(``IN_PROGRESS``)    ``as_of`` 자신. 그 시각의 값에 진행 중 항차의 경과분(시계가
                         만든 **모델값**)이 들었으면 이 종류다 — `PRD §3.3.8` COR-5.
 계획(``PLAN``)           잔여 항차의 도착 예정. 예정이 ``as_of``보다 이르면(도착 예정이
                         지난 진행 중·계획 항차 — `#1323`) ``as_of``에 붙인다.
======================  ========================================================

**연초 첫 점은 만들지 않는다.** 실적이 없는 시각의 값은 ``null``인데, ``attained_cii: null``
인 점을 실으면 화면이 0으로 그린다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.annual_simulation import _boundaries_decimal
from cii_platform.calc.capacity import capacity_axis
from cii_platform.calc.precision import layer1_context
from cii_platform.db.repositories import not_underway as not_underway_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import NotFoundError
from cii_platform.services.annual_simulation import (
    collect_annual_inputs,
    load_projection_context,
)
from cii_platform.services.cii_current import (
    WARNING_NO_REMAINING_PLAN,
    _project_layer1,
    _publish,
    _remaining_days,
    _validate_year,
    resolve_ytd_at,
)
from cii_platform.services.request_cache import as_of_key, cached
from cii_platform.services.request_cache import enable as enable_request_cache
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import (
    POLICY_INCLUDE_AS_ACTUAL,
    WARNING_REFERENCE_ONLY,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: ``points[].kind`` — 확정 실적 · 시계가 만든 경과분 포함 · 잔여 계획.
KIND_ACTUAL = "ACTUAL"
KIND_IN_PROGRESS = "IN_PROGRESS"
KIND_PLAN = "PLAN"


@dataclass(frozen=True)
class _Boundary:
    """실적 쪽 점을 만드는 시각 하나. 같은 시각의 경계는 :func:`_merge`가 한 점으로 합친다."""

    at: datetime
    voyage_id: UUID | None = None
    period_id: UUID | None = None


def _merge(boundaries: list[_Boundary]) -> list[_Boundary]:
    """시각 오름차순 · 같은 시각은 한 점 — 항차와 정박 구간이 같은 순간에 끝나면 둘 다 싣는다."""
    merged: dict[datetime, _Boundary] = {}
    for b in boundaries:
        prev = merged.get(b.at)
        merged[b.at] = (
            b
            if prev is None
            else _Boundary(
                at=b.at,
                voyage_id=prev.voyage_id or b.voyage_id,
                period_id=prev.period_id or b.period_id,
            )
        )
    return [merged[at] for at in sorted(merged)]


async def _actual_boundaries(
    session: AsyncSession, *, vessel_id: UUID, regulation_year: int, as_of: datetime
) -> list[_Boundary]:
    """``as_of`` 이하의 실적 경계 — 확정 항차의 도착 · 종료된 정박 구간 · ``as_of`` 자신.

    확정 항차 조회는 ⑴ 누적(`services/ytd_cii._aggregate`)과 **같은 캐시 키**로 읽는다 —
    ``as_of`` 점을 계산할 때 그 목록을 다시 읽지 않는다.
    """
    voyages = await cached(
        session,
        (
            "annual_inclusions",
            vessel_id,
            regulation_year,
            as_of_key(as_of),
            POLICY_INCLUDE_AS_ACTUAL,
        ),
        lambda: voyage_repo.list_annual_inclusions(
            session,
            vessel_id=vessel_id,
            regulation_year=regulation_year,
            policy=POLICY_INCLUDE_AS_ACTUAL,
            as_of=as_of,
        ),
    )
    periods = await cached(
        session,
        ("not_underway_periods", vessel_id, regulation_year, as_of_key(as_of)),
        lambda: not_underway_repo.list_periods_for_year(
            session, vessel_id=vessel_id, regulation_year=regulation_year, as_of=as_of
        ),
    )

    boundaries: list[_Boundary] = []
    for voyage in voyages:
        # 저장소 절단 술어와 같은 식 — ``COALESCE(actual_arrival_at, planned_arrival_at)``.
        # 둘 다 없으면 누적에는 들지만(시각을 모르는 행을 «아직 아니다»로 단정하지 않는다)
        # 자기 점은 없다 — 어느 시각에 찍을지 알 수 없다.
        arrival = voyage.actual_arrival_at or voyage.planned_arrival_at
        if arrival is None:
            continue
        arrival = resolve_as_of(arrival)
        if arrival <= as_of:
            boundaries.append(_Boundary(at=arrival, voyage_id=voyage.id))
    for period in periods:
        # 진행 중인 구간(``ended_at`` 없음)은 점이 없다 — 끝나는 시각을 모른다. 정박 연료는
        # ``started_at <= as_of``로 누적에 이미 들어 있으므로, 점은 「끝났다」를 찍는 것이다.
        if period.ended_at is None:
            continue
        ended = resolve_as_of(period.ended_at)
        if ended <= as_of:
            boundaries.append(_Boundary(at=ended, period_id=period.id))
    boundaries.append(_Boundary(at=as_of))
    return _merge(boundaries)


@layer1_context
def _boundaries(context) -> dict[str, Decimal]:
    """등급 경계 4종 — ``ytd.boundaries``·``project_deterministic``과 **같은 컨텍스트**에서 낸다."""
    return _boundaries_decimal(context.required_cii, context.d_vector)


def _point(
    *,
    at: datetime,
    kind: str,
    attained_cii: Decimal,
    rating: str,
    voyage_id: UUID | str | None,
    period_id: UUID | None,
    substituted: bool,
) -> dict[str, object]:
    """점 하나. **키 집합은 종류와 무관하게 같다** — ``null``이어도 키는 싣는다."""
    return {
        "at": at.isoformat(),
        "kind": kind,
        "attained_cii": _publish(attained_cii, "cii"),
        "rating": rating,
        "voyage_id": None if voyage_id is None else str(voyage_id),
        "period_id": None if period_id is None else str(period_id),
        "substituted": substituted,
    }


async def get_ytd_series(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    year: int | None = None,
    as_of: datetime | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """올해 누적 CII 추이 (API_SPEC §2.18).

    :returns: ``(data, meta)`` — `§2.14`와 같은 조회 봉투. ``meta``에 ``as_of``·``simulated``.
    """
    # 읽기 전용 요청이다. 점마다 같은 선박·규제 파라미터를 다시 읽지 않는다
    # (`services/request_cache.py` — 켜는 것은 읽기 전용 요청이 스스로 정한다).
    enable_request_cache(session)

    resolved_as_of = resolve_as_of(as_of)
    regulation_year = year if year is not None else resolved_as_of.year
    _validate_year(regulation_year)

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None or vessel.is_deleted:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")

    # 기준선·등급 경계는 ⑶ 연말 예상과 같은 한 벌에서 온다 (`#798`). 규제연도 파라미터가
    # 없으면 여기서 409다 — `§2.14`와 같은 자리다.
    context = await load_projection_context(
        session, vessel_id=vessel_id, regulation_year=regulation_year
    )

    # ── 실적 쪽 ──────────────────────────────────────────────────────────────
    points: list[dict[str, object]] = []
    state_at_as_of = None
    ytd_at_as_of = None
    for boundary in await _actual_boundaries(
        session, vessel_id=vessel_id, regulation_year=regulation_year, as_of=resolved_as_of
    ):
        state, ytd = await resolve_ytd_at(
            session, vessel=vessel, regulation_year=regulation_year, at=boundary.at
        )
        if boundary.at == resolved_as_of:
            state_at_as_of, ytd_at_as_of = state, ytd
        if not ytd.data_available:
            # 실적이 아직 없는 시각 — 점을 만들지 않는다(``attained_cii: null`` 금지).
            continue
        in_progress = state.contribution is not None
        points.append(
            _point(
                at=boundary.at,
                kind=KIND_IN_PROGRESS if in_progress else KIND_ACTUAL,
                attained_cii=ytd.attained_cii,
                rating=ytd.rating,
                # 점을 만든 항차 — 도착한 항차가 있으면 그것, 없고 경과분이 들었으면 진행 중 항차.
                voyage_id=boundary.voyage_id
                or (state.voyage.id if in_progress and state.voyage is not None else None),
                period_id=boundary.period_id,
                # 이 점을 만든 항차가 실적 대신 계획값으로 들어갔는가 — ``ytd.substitutions``와
                # 같은 판정을 **그 항차에 대해** 읽는다. 누적 전체에 대체가 섞였는지는 앞 점들의
                # 이 값으로 알 수 있지만, 반대 방향은 누적 플래그로 알 수 없다.
                substituted=boundary.voyage_id is not None
                and any(item.voyage_id == boundary.voyage_id for item in ytd.substitutions),
            )
        )
    assert state_at_as_of is not None and ytd_at_as_of is not None  # ``as_of`` 경계는 항상 있다

    # ── 계획 쪽 ──────────────────────────────────────────────────────────────
    plan_points: list[dict[str, object]] = []
    plan_warnings: list[str] = []
    if _remaining_days(as_of=resolved_as_of, regulation_year=regulation_year) > 0:
        inputs = await collect_annual_inputs(
            session,
            vessel=context.vessel,
            vessel_id=vessel_id,
            year=regulation_year,
            as_of=resolved_as_of,
        )
        plan_warnings = list(inputs.warnings)
        if inputs.plan_voyage_count == 0:
            plan_warnings.append(WARNING_NO_REMAINING_PLAN)

        def _arrival(voyage) -> datetime | None:
            arrival = inputs.planned_arrivals.get(voyage.voyage_id or "")
            return None if arrival is None else resolve_as_of(arrival)

        # 도착 예정 오름차순 · 예정이 없는 항차는 맨 뒤(등록 순 유지).
        ordered = sorted(
            inputs.remaining,
            key=lambda v: (_arrival(v) is None, _arrival(v) or resolved_as_of),
        )
        cursor = resolved_as_of
        for count in range(1, len(ordered) + 1):
            try:
                # ⑶ 연말 예상과 **같은 함수**에 앞에서 ``count``건까지를 넘긴다 — 마지막
                # 반복이 곧 ``year_end_projection``이다(같은 집합 · 같은 엔진 · 같은 컨텍스트).
                deterministic, _ratio, _risk = _project_layer1(
                    context, replace(inputs, remaining=ordered[:count])
                )
            except ValueError:
                # 거리가 0이면 `PRD §12.8`이 계산 중단을 규정한다 — `§2.14`가 ⑶을 `NO_BASIS`로
                # 비우는 것과 같은 자리다. 계획 점을 통째로 싣지 않는다.
                plan_points = []
                break
            last = ordered[count - 1]
            arrival = _arrival(last)
            # 예정이 지난 항차는 ``as_of``에 붙이고, 예정이 없는 항차는 직전 점의 시각을 잇는다 —
            # ``at``이 뒤로 가는 점을 만들지 않는다.
            cursor = max(cursor, arrival) if arrival is not None else cursor
            plan_points.append(
                _point(
                    at=cursor,
                    kind=KIND_PLAN,
                    attained_cii=deterministic.attained_cii,
                    rating=deterministic.rating,
                    voyage_id=last.voyage_id,
                    period_id=None,
                    substituted=False,
                )
            )

    data: dict[str, object] = {
        "vessel_id": str(vessel.id),
        "vessel_name": vessel.name,
        "regulation_year": regulation_year,
        "transport_capacity_basis": capacity_axis(vessel.ship_type),
        "required_cii": _publish(context.required_cii, "cii"),
        "boundaries": {key: _publish(value, "cii") for key, value in _boundaries(context).items()},
        "ytd_available": ytd_at_as_of.data_available,
        "points": [*points, *plan_points],
        # `§2.14`와 같은 합집합 규칙 — ``as_of`` 시점의 누적 경고 + 진행분 경고 + 잔여 계획 경고.
        "warnings": sorted(
            {
                WARNING_REFERENCE_ONLY,
                *ytd_at_as_of.warnings,
                *state_at_as_of.warnings,
                *plan_warnings,
            }
        ),
    }
    meta = {
        "as_of": resolved_as_of.isoformat(),
        # `§2.14` ``meta.simulated``와 같은 판정 — 같은 화면의 배지가 두 호출 사이에서
        # 흔들리지 않는다.
        "simulated": bool(
            state_at_as_of.progress is not None and state_at_as_of.progress.is_simulated
        ),
    }
    return data, meta
