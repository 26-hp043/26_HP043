"""함대 감축 계획 — 계산 · 저장 · 조회 (``API_SPEC §2.17`` · ``PRD §12.3.2`` · #513).

선박별 감속률을 받아 **조정 전/후의 결정론 연말 예상**과 **비용 요약**을 낸다. 수식은
``calc/fleet_reduction.py``에 있다.

기능③(연간 등급 관리)과 **같은 입력 조립**을 쓴다
----------------------------------------------
``load_projection_context`` · ``collect_annual_inputs`` · ``project_deterministic``을 그대로 부른다.
조정 전 값이 연간 등급 관리의 결정론 예상과 다르면, 사용자는 두 화면 중 어느 쪽이 맞는지부터
따져야 한다. **감속률 0%면 조정 후도 조정 전과 같다** — 검사가 잠근다(`#513` 완료 기준).

⚠️ 연간 등급 관리의 **확률 분포 중앙값과는 다를 수 있다** — 이 화면은 Monte Carlo를 부르지 않는다
(``UIFLOW 2-10``). 그 사실을 화면이 적는다(``PRD §6.3``).
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select

from cii_platform.calc.annual_simulation import backsolve_required_cut, project_deterministic
from cii_platform.calc.fleet_reduction import (
    PlannedLeg,
    apply_slowdown,
    meets_target,
    summarize_costs,
    target_rating_for,
)
from cii_platform.calc.precision import layer1_context
from cii_platform.db.models.fleet_reduction_plan import FleetReductionPlan
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import AppError, NotFoundError, ParameterError, ValidationError
from cii_platform.services.annual_simulation import collect_annual_inputs, load_projection_context
from cii_platform.services.fleet_summary import (
    UNAVAILABLE_CALCULATION_ERROR,
    UNAVAILABLE_NO_DATA,
    UNAVAILABLE_NO_PARAMETERS,
    prior_confirmed_ratings,
    spec_gap,
)
from cii_platform.services.pagination import normalize_limit
from cii_platform.services.request_cache import enable as enable_request_cache
from cii_platform.services.request_cache import put as cache_put
from cii_platform.services.simulation_clock import resolve_as_of

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: 선박 한 척에 감속을 적용하지 못한 항차가 있다 — 제원(기준 속력·기준 일일 연료)이 없다.
WARNING_SLOWDOWN_SKIPPED = "SLOWDOWN_SKIPPED_NO_SPEED_MODEL"

_RATINGS = ("A", "B", "C", "D", "E")
_CII_DIGITS = 4
_MONEY_DIGITS = 2
_TON_DIGITS = 2

#: 커서 인코딩 구분자 — ISO 8601·UUID에 등장할 수 없는 제어문자 (`calculation_run`과 같다).
_PLAN_CURSOR_SEP = "\x00"
_DAY_DIGITS = 2

#: 목록 조회 기본 건수 (`API_SPEC §1.5` · `§1.9`와 같은 20).
PLAN_LIST_LIMIT = 20

#: 목록 조회 최대 건수. `API_SPEC §1.9`의 다른 목록과 같다.
PLAN_LIST_MAX = 100


def _publish(value: Decimal | None, digits: int) -> str | None:
    if value is None:
        return None
    return f"{value:.{digits}f}"


def _legs(voyages_json: list[dict]) -> list[PlannedLeg]:
    """스냅샷 PLAN 행 → :class:`PlannedLeg`.

    ⚠️ ``services/annual_simulation._inputs_from_snapshot``과 **같은 행을 같은 순서로** 고른다 —
    연료 합이 0 이하인 계획 항차는 뺀다(`#812`). 규칙이 갈리면 ``apply_slowdown``이 길이가
    다르다고 거부한다(조용히 어긋나지 않는다).
    """
    legs: list[PlannedLeg] = []
    for row in voyages_json:
        if row.get("kind") != "PLAN":
            continue
        by_type: dict[str, Decimal] = {}
        for fuel_use in row.get("fuel_uses") or []:
            ton = Decimal(fuel_use.get("planned_fuel_ton") or "0")
            by_type[fuel_use["fuel_type"]] = by_type.get(fuel_use["fuel_type"], Decimal(0)) + ton
        if sum(by_type.values(), Decimal(0)) <= 0:
            continue
        speed = row.get("planned_speed_kn")
        legs.append(
            PlannedLeg(
                distance_nm=Decimal(row.get("planned_distance_nm") or "0"),
                speed_kn=None if speed is None else Decimal(speed),
                fuel_ton_by_type=by_type,
            )
        )
    return legs


def _parse_money(mapping: dict[str, object] | None, field: str) -> dict[str, Decimal]:
    parsed: dict[str, Decimal] = {}
    for key, raw in (mapping or {}).items():
        try:
            value = Decimal(str(raw))
        except ArithmeticError as exc:
            raise ValidationError(f"{field}.{key} 값이 숫자가 아닙니다.", field=field) from exc
        if value < 0:
            raise ValidationError(f"{field}.{key} 값은 0 이상이어야 합니다.", field=field)
        parsed[key] = value
    return parsed


@layer1_context
def _evaluate_vessel(ctx, inputs, reduction: Decimal, target_rating: str):
    """한 척의 조정 전/후 — Layer 1 컨텍스트 안에서 한 번에 낸다(`TECH_SPEC §1.2.1`)."""
    legs = _legs(inputs.voyages_json)
    before = project_deterministic(
        completed=inputs.completed,
        remaining=inputs.remaining,
        transport_capacity=ctx.transport_capacity,
        required_cii=ctx.required_cii,
        d_vector=ctx.d_vector,
    )
    slowed = apply_slowdown(inputs.remaining, legs, reduction)
    after = project_deterministic(
        completed=inputs.completed,
        remaining=slowed.remaining,
        transport_capacity=ctx.transport_capacity,
        required_cii=ctx.required_cii,
        d_vector=ctx.d_vector,
    )
    cut = backsolve_required_cut(
        projection=after,
        remaining=slowed.remaining,
        transport_capacity=ctx.transport_capacity,
        target_rating=target_rating,
    )
    return before, after, slowed, cut


async def evaluate_reduction_plan(
    session: AsyncSession,
    *,
    regulation_year: int,
    target: str,
    adjustments: list[dict[str, object]],
    prices: dict[str, object],
) -> dict[str, object]:
    """감축 계획안을 **계산만** 한다 — 저장하지 않는다 (``API_SPEC §2.17.1``).

    :param adjustments: ``[{"vessel_id": …, "speed_reduction_percent": …}]``. 목록에 없는 선박은 0%.
    :param prices: ``{"charter_usd_per_day": {vessel_id: …}, "fuel_usd_per_ton": {fuel_type: …}}``.
    """
    as_of = resolve_as_of(None)
    enable_request_cache(session)
    vessels = await vessel_repo.list_all_active(session)
    for row in vessels:
        cache_put(session, ("vessel", row.id), row)
    known = {str(v.id) for v in vessels}

    reductions: dict[str, Decimal] = {}
    for item in adjustments:
        vessel_id = str(item.get("vessel_id"))
        if vessel_id not in known:
            raise ValidationError(
                f"선박을 찾을 수 없습니다: {vessel_id}",
                field="adjustments",
                field_label="선박별 감속",
            )
        reductions[vessel_id] = Decimal(str(item.get("speed_reduction_percent", "0")))

    charter = _parse_money(prices.get("charter_usd_per_day"), "prices.charter_usd_per_day")  # type: ignore[arg-type]
    fuel_price = _parse_money(prices.get("fuel_usd_per_ton"), "prices.fuel_usd_per_ton")  # type: ignore[arg-type]

    rows: list[dict[str, object]] = []
    before_dist = {r: 0 for r in _RATINGS}
    after_dist = {r: 0 for r in _RATINGS}
    extra_days_by_vessel: dict[str, Decimal] = {}
    fuel_saved: dict[str, Decimal] = {}
    warnings: list[str] = []
    all_met = True
    evaluated = 0

    for vessel in vessels:
        vessel_id = str(vessel.id)
        reduction = reductions.get(vessel_id, Decimal(0))
        base_row: dict[str, object] = {
            "vessel_id": vessel_id,
            "vessel_name": vessel.name,
            "speed_reduction_percent": _publish(reduction, 1),
        }
        try:
            prior = await prior_confirmed_ratings(
                session, vessel_id=vessel.id, current_year=regulation_year, as_of=as_of
            )
        except AppError:
            prior = []
        target_rating = target_rating_for(target, prior_ratings=prior)

        try:
            ctx = await load_projection_context(
                session, vessel_id=vessel.id, regulation_year=regulation_year
            )
            inputs = await collect_annual_inputs(
                session, vessel=ctx.vessel, vessel_id=vessel.id, year=regulation_year, as_of=as_of
            )
            before, after, slowed, cut = _evaluate_vessel(ctx, inputs, reduction, target_rating)
        except ParameterError:
            rows.append({**base_row, "unavailable_reason": UNAVAILABLE_NO_PARAMETERS})
            continue
        except ValidationError:
            rows.append(
                {
                    **base_row,
                    "unavailable_reason": spec_gap(vessel) or UNAVAILABLE_CALCULATION_ERROR,
                }
            )
            continue
        except ValueError:
            # `PRD §12.8` — 거리가 0(확정 실적도 잔여 계획도 없음)이면 결정론 계산이 멈춘다.
            rows.append({**base_row, "unavailable_reason": UNAVAILABLE_NO_DATA})
            continue
        except AppError:
            rows.append({**base_row, "unavailable_reason": UNAVAILABLE_CALCULATION_ERROR})
            continue

        evaluated += 1
        met = meets_target(after.rating, target_rating)
        all_met = all_met and met
        before_dist[before.rating] += 1
        after_dist[after.rating] += 1
        extra_days_by_vessel[vessel_id] = slowed.extra_days
        for fuel_type, ton in slowed.fuel_saved_ton_by_type.items():
            fuel_saved[fuel_type] = fuel_saved.get(fuel_type, Decimal(0)) + ton
        if slowed.skipped_voyages and WARNING_SLOWDOWN_SKIPPED not in warnings:
            warnings.append(WARNING_SLOWDOWN_SKIPPED)
        # 입력 조립이 뺀 항차(연료 없는 계획 항차 → `SIMULATION_PLAN_NO_FUEL` · #812)를 조용히
        # 버리지 않는다 — 연간 등급 관리는 같은 경고를 싣는다 (#1070 ⑷).
        for code in inputs.warnings:
            if code not in warnings:
                warnings.append(code)

        rows.append(
            {
                **base_row,
                "unavailable_reason": None,
                "before": {
                    "attained_cii": _publish(before.attained_cii, _CII_DIGITS),
                    "rating": before.rating,
                },
                "after": {
                    "attained_cii": _publish(after.attained_cii, _CII_DIGITS),
                    "rating": after.rating,
                },
                "target_rating": target_rating,
                "meets_target": met,
                "extra_days": _publish(slowed.extra_days, _DAY_DIGITS),
                "fuel_saved_ton": _publish(
                    sum(slowed.fuel_saved_ton_by_type.values(), Decimal(0)), _TON_DIGITS
                ),
                "skipped_voyages": slowed.skipped_voyages,
                # 스냅샷의 계획 항차 수 — 연간 등급 관리(`API_SPEC §6.1`)와 같은 기준이다
                # (#1070 ⑷). 계산에서 뺀 항차가 있으면 `warnings`가 그 사실을 말한다.
                "remaining_voyage_count": inputs.plan_voyage_count,
                # 조정 **후**에도 남는 필요 감축량 — 목표까지 연료를 더 줄여야 하는 양(`§12.3.1`).
                "required_cut_fuel_ton": _publish(cut.required_cut_fuel_ton, _TON_DIGITS),
                "achievable": cut.achievable,
            }
        )

    costs = summarize_costs(
        extra_days_by_vessel=extra_days_by_vessel,
        fuel_saved_by_type=fuel_saved,
        charter_usd_per_day=charter,
        fuel_usd_per_ton=fuel_price,
    )
    return {
        "regulation_year": regulation_year,
        "target": target,
        # 계산할 수 있는 선박이 한 척도 없으면 「달성」이라 말할 근거가 없다.
        "target_met": all_met if evaluated > 0 else None,
        "vessels": rows,
        "rating_distribution": {"before": before_dist, "after": after_dist},
        "costs": {
            "currency": "USD",
            "extra_days": _publish(costs.extra_days, _DAY_DIGITS),
            "charter_loss": _publish(costs.charter_loss_usd, _MONEY_DIGITS),
            "fuel_saving": _publish(costs.fuel_saving_usd, _MONEY_DIGITS),
            "net": _publish(costs.net_usd, _MONEY_DIGITS),
            "fuel_saved_ton_by_type": {
                k: _publish(v, _TON_DIGITS) for k, v in sorted(fuel_saved.items())
            },
            "missing_charter_rates": list(costs.missing_charter_rates),
            "missing_fuel_prices": list(costs.missing_fuel_prices),
        },
        "warnings": warnings,
    }


def _plan_body(plan: FleetReductionPlan) -> dict[str, object]:
    return {
        "plan_id": str(plan.id),
        "plan_name": plan.name,
        "regulation_year": plan.regulation_year,
        "target": plan.target,
        "adjustments": plan.adjustments,
        "prices": plan.prices,
        "result": plan.result,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


async def save_reduction_plan(
    session: AsyncSession,
    *,
    plan_name: str,
    regulation_year: int,
    target: str,
    adjustments: list[dict[str, object]],
    prices: dict[str, object],
    user_id: UUID | None,
) -> dict[str, object]:
    """계획안을 **서버가 다시 계산해** 저장한다 (``API_SPEC §2.17.2``).

    화면이 보낸 결과를 받아 저장하지 않는다 — 화면 값을 믿으면 저장본이 서버 계산과 갈릴 수 있다.
    """
    result = await evaluate_reduction_plan(
        session,
        regulation_year=regulation_year,
        target=target,
        adjustments=adjustments,
        prices=prices,
    )
    plan = FleetReductionPlan(
        name=plan_name.strip(),
        regulation_year=regulation_year,
        target=target,
        adjustments=adjustments,
        prices=prices,
        result=result,
        created_by=user_id,
    )
    session.add(plan)
    await session.flush()
    await session.refresh(plan)
    return _plan_body(plan)


async def list_reduction_plans(
    session: AsyncSession,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> tuple[list[dict], dict[str, object]]:
    """최근 저장순 한 페이지와 페이지네이션 메타 (`API_SPEC §1.5` · `§2.17.3`).

    ``result``는 싣지 않는다 — 목록에는 무거워서다(단건 조회에 있다).

    ## 왜 커서가 생겼나 (`#1367`)

    종전에는 **20건에서 자르면서 그 사실을 응답이 말하지 않았다.** 21번째 계획은
    볼 방법이 없었고, 화면에는 「계획이 20개뿐」과 구분되지 않았다 — `#1076`이
    계산 이력에서 고친 것과 **같은 형태**다(「없다」와 「아직 다 주지 않았다」를
    같은 모양으로 그린다).

    keyset 커서를 쓰는 이유도 같다 — 앞 페이지에서 행이 지워지면 offset은 다음
    페이지가 한 건을 건너뛴다. 정렬 키가 ``(created_at desc, id)``이고 저장이
    같은 순간에 겹칠 수 있어 ``id``를 2차 키로 둔다.
    """
    page_size = normalize_limit(limit, default=PLAN_LIST_LIMIT, maximum=PLAN_LIST_MAX)

    stmt = select(FleetReductionPlan).order_by(
        FleetReductionPlan.created_at.desc(), FleetReductionPlan.id.desc()
    )
    if cursor is not None:
        parsed = decode_plan_cursor(cursor)
        if parsed is None:
            raise ValidationError(
                "cursor 형식이 올바르지 않습니다.",
                field="cursor",
                field_label="커서",
            )
        created_at, plan_id = parsed
        stmt = stmt.where(
            sa.tuple_(FleetReductionPlan.created_at, FleetReductionPlan.id)
            < sa.tuple_(created_at, plan_id)
        )

    # 한 건을 더 받아 **초과분의 존재 여부**로 has_more를 정한다 — 따로 COUNT를
    # 돌리면 두 쿼리 사이에 저장이 끼어들어 답이 어긋난다.
    rows = (await session.execute(stmt.limit(page_size + 1))).scalars().all()
    has_more = len(rows) > page_size
    page = list(rows[:page_size])

    next_cursor = (
        encode_plan_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
    )
    data = [{k: v for k, v in _plan_body(plan).items() if k != "result"} for plan in page]
    return data, {"next_cursor": next_cursor, "has_more": has_more}


def encode_plan_cursor(created_at: datetime, plan_id: UUID) -> str:
    """``(created_at, id)``를 URL-safe base64로 (`calculation_run`과 같은 정책)."""
    raw = f"{created_at.isoformat()}{_PLAN_CURSOR_SEP}{plan_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_plan_cursor(token: str) -> tuple[datetime, UUID] | None:
    """되돌린다. 형식이 깨졌으면 ``None`` — **예외를 던지지 않는다.**

    잘못된 커서는 사용자가 URL을 손댄 경우가 대부분이고, 그때 500이 나가면 안 된다.
    오류로 볼지 첫 페이지로 볼지는 호출부가 정한다(여기서는 422다).
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    created_raw, sep, id_raw = raw.partition(_PLAN_CURSOR_SEP)
    if not sep or not id_raw:
        return None
    try:
        return datetime.fromisoformat(created_raw), UUID(id_raw)
    except ValueError:
        return None


async def get_reduction_plan(session: AsyncSession, plan_id: UUID) -> dict[str, object]:
    plan = await session.get(FleetReductionPlan, plan_id)
    if plan is None:
        raise NotFoundError(f"감축 계획을 찾을 수 없습니다: {plan_id}")
    return _plan_body(plan)
