"""연간 시뮬레이션 실행 서비스 (API_SPEC §6.1, PRD §12, #64).

``#63``이 만든 계산 엔진(``calc.annual_simulation``)에 **데이터를 물려 주고 결과를
저장**한다. 계산 자체는 여기서 하지 않는다.

## 스냅샷을 먼저 뜬다

``TECH_SPEC §11``이 요구하는 격리다. 시뮬레이션이 도는 동안 항차가 수정돼도 결과가
흔들리면 안 된다.

**트랜잭션 격리(`REPEATABLE READ`)가 아니라 테이블에 복사한다** (`#105` 결론).
트랜잭션은 끝나면 사라지지만, ``TECH_SPEC §5.4`` 재현성 계약은 **몇 달 뒤에도 「그때
무슨 데이터로 돌렸나」를 볼 수 있어야** 한다고 요구한다. ``simulation_snapshot``이
immutable인 것도 같은 이유다 — 근거가 나중에 바뀌면 재현이 성립하지 않는다.

## 항차를 status로 다시 판정하지 않는다

포함 여부의 정본은 ``PRD §8.1.2`` 매트릭스이고, 그 결과가 ``annual_inclusion_policy``
컬럼에 이미 들어 있다. ``status``로 다시 거르면 같은 규칙이 DB CHECK·저장소·여기 세
곳에 생긴다.

=====================  ==========================================
 ``INCLUDE_AS_ACTUAL``  확정 실적 — **변하지 않는다** (표본추출 대상 아님)
 ``INCLUDE_AS_PLAN``    잔여 계획 — 삼각분포로 흔든다
 ``EXCLUDE``            집계에 넣지 않는다
=====================  ==========================================

## 분포를 코드에서 읽지 않는다

``#434``가 만든 ``simulation_parameter``에서 읽어 엔진에 넘긴다. 그 내용을
``parameters_used``에 함께 실어야 ``parameter_hash``가 분포 변경을 덮는다
(``TECH_SPEC §5.2.1.1``) — 그러지 않으면 분포가 바뀐 뒤 같은 seed로 돌려도 결과가
달라지는데 해시는 같아진다.
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.calc.annual_simulation import (
    MAX_REMAINING_VOYAGES,
    CompletedTotals,
    RemainingVoyage,
    analyze_sensitivity,
    profile_from_rows,
    project_deterministic,
    simulate_annual,
)
from cii_platform.calc.cii_engine import calculate_required_cii
from cii_platform.calc.hash import compute_input_hash, compute_parameter_hash
from cii_platform.calc.precision import LAYER1_ROUNDING
from cii_platform.calc.rating_engine import DVector, calculate_probability_risk
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import ValidationError
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import (
    POLICY_INCLUDE_AS_ACTUAL,
    _load_regulation_year,
    _load_vessel,
    _resolve_reference_capacity,
    _resolve_transport_capacity,
    _select_rating_boundary,
    _select_reference_line,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

#: ``PRD §8.1.2`` — 잔여 계획 항차의 집계 정책. ``ytd_cii``는 이 값을 집계에 넣지
#: 않으므로 상수를 두지 않았다(연중 누적에 계획 전량을 더하면 「누적」의 정의가 깨진다).
#: 기능③은 **잔여 계획을 흔들어 연말을 보는 것**이 목적이라 이쪽이 대상이다.
POLICY_INCLUDE_AS_PLAN = "INCLUDE_AS_PLAN"

#: ``PRD §12.8`` — 목표 등급 E는 실행 거부.
_ALLOWED_TARGETS = ("A", "B", "C", "D")

#: ``API_SPEC §6.1`` — 미지정 시 서버가 생성하는 seed의 비트 수.
#: ``PRD §12.4.3``이 「자동 seed」를 요구하고, 결과에 표시해 재실행할 수 있어야 한다.
_SEED_BITS = 128

#: ``PRD §12.8`` — one-at-a-time이라 변수 간 상호작용은 포함되지 않는다.
INTERACTION_NOTE = "각 변수의 개별 효과만 표시합니다. 복합 효과는 포함되지 않습니다."

#: ``API_SPEC §6.1`` 민감도 키. 엔진의 ``(variable, change)``를 응답 키로 옮긴다.
_SENSITIVITY_KEYS = {
    ("speed", "-1kn"): "speed_minus_1kn",
    ("speed", "+1kn"): "speed_plus_1kn",
    ("fuel", "-10%"): "fuel_minus_10pct",
    ("fuel", "+10%"): "fuel_plus_10pct",
    ("distance", "-5%"): "distance_minus_5pct",
    ("distance", "+5%"): "distance_plus_5pct",
    ("voyage_count", "-1"): "voyage_minus_1",
    ("voyage_count", "+1"): "voyage_plus_1",
}

#: 이 지렛대들만 목표 확률 변화를 함께 낸다 (``API_SPEC §6.1`` 응답 예시).
#: 나머지는 등급 변화만 보인다 — 확률을 내려면 Monte Carlo를 다시 돌려야 한다.
_PROBABILITY_LEVERS = frozenset(
    {"speed_minus_1kn", "speed_plus_1kn", "fuel_minus_10pct", "fuel_plus_10pct"}
)

_DIGITS = {"cii": 6, "probability": 4}


def _publish(value: Decimal | None, kind: str = "cii") -> str | None:
    """``API_SPEC §1.7`` 문자열 직렬화."""
    if value is None:
        return None
    return str(value.quantize(Decimal(1).scaleb(-_DIGITS[kind]), rounding=LAYER1_ROUNDING))


# ─── 입력 확정 ───────────────────────────────────────────────────────────────


def _voyage_co2_g(voyage, fuel_uses) -> Decimal:
    """항차 하나의 CO₂(g). ``M = Σ(연료 × 1,000,000 × CF)`` (``PRD §3.3.1``)."""
    return sum(
        (
            Decimal(str(fu.actual_fuel_ton or fu.planned_fuel_ton or 0))
            * Decimal(1_000_000)
            * Decimal(str(fu.cf_used))
            for fu in fuel_uses
        ),
        Decimal(0),
    )


async def _collect_voyages(session: AsyncSession, *, vessel_id: UUID, year: int, as_of: datetime):
    """확정분과 잔여분을 ``annual_inclusion_policy``로 갈라 온다.

    **``status``를 다시 해석하지 않는다** — 모듈 docstring 참조.
    """
    actual = await voyage_repo.list_annual_inclusions(
        session, vessel_id=vessel_id, regulation_year=year, policy=POLICY_INCLUDE_AS_ACTUAL
    )
    planned = await voyage_repo.list_annual_inclusions(
        session, vessel_id=vessel_id, regulation_year=year, policy=POLICY_INCLUDE_AS_PLAN
    )
    return actual, planned


def _snapshot_payload(actual, planned, fuel_by_voyage) -> list[dict]:
    """``simulation_snapshot.voyages_json``에 넣을 항차 사본 (``TECH_SPEC §11.2``).

    **계산에 쓴 값을 그대로 담는다.** 나중에 「그때 무슨 데이터로 돌렸나」에 답해야
    하므로, 원본을 다시 조회하면 알 수 없는 것(확정 시점의 실적·CF snapshot)을 함께
    남긴다.
    """
    rows = []
    for voyage, kind in ((v, "ACTUAL") for v in actual):
        rows.append(_snapshot_row(voyage, kind, fuel_by_voyage.get(voyage.id, [])))
    for voyage in planned:
        rows.append(_snapshot_row(voyage, "PLAN", fuel_by_voyage.get(voyage.id, [])))
    return rows


def _snapshot_row(voyage, kind: str, fuel_uses) -> dict:
    return {
        "voyage_id": str(voyage.id),
        "kind": kind,
        "voyage_no": voyage.voyage_no,
        "status": voyage.status,
        "annual_inclusion_policy": voyage.annual_inclusion_policy,
        "planned_distance_nm": str(voyage.planned_distance_nm or 0),
        "actual_distance_nm": (
            None if voyage.actual_distance_nm is None else str(voyage.actual_distance_nm)
        ),
        "planned_speed_kn": (
            None if voyage.planned_speed_kn is None else str(voyage.planned_speed_kn)
        ),
        "fuel_uses": [
            {
                "fuel_type": fu.fuel_type,
                "planned_fuel_ton": str(fu.planned_fuel_ton or 0),
                "actual_fuel_ton": (
                    None if fu.actual_fuel_ton is None else str(fu.actual_fuel_ton)
                ),
                # CF snapshot을 함께 남긴다 — CF가 개정되면 원본으로는 재현할 수 없다(#378).
                "cf_used": str(fu.cf_used),
            }
            for fu in fuel_uses
        ],
    }


# ─── 민감도 조립 ─────────────────────────────────────────────────────────────


def _rating_change(before: str, after: str) -> str:
    """``"C→B"``. 화살표 하나로 방향이 드러난다 (``API_SPEC §6.1``)."""
    return f"{before}→{after}"


def _signed(value: Decimal) -> str:
    """확률 변화는 부호를 붙인다 — ``+0.12``/``-0.08``."""
    return f"{'+' if value >= 0 else ''}{value}"


# ─── 진입점 ──────────────────────────────────────────────────────────────────


async def run_annual_simulation(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    target_rating: str,
    simulation_runs: int = 5_000,
    random_seed: int | None = None,
    distribution_profile: str = "DEFAULT",
    as_of: datetime | None = None,
) -> dict[str, object]:
    """연간 시뮬레이션을 실행하고 결과를 저장한다 (``API_SPEC §6.1``).

    순서가 중요하다 — **스냅샷을 먼저 뜨고 그 사본으로 계산한다.** 계산 중에 원본이
    바뀌어도 결과가 흔들리지 않게 하는 것이 ``TECH_SPEC §11``의 요구다.
    """
    if target_rating not in _ALLOWED_TARGETS:
        raise ValidationError(
            "목표 등급 E는 의미 있는 분석이 아닙니다. A~C를 목표로 설정하세요."
            if target_rating == "E"
            else f"목표 등급이 올바르지 않습니다: {target_rating}",
            field="target_rating",
            field_label="목표 등급",
        )

    resolved_as_of = resolve_as_of(as_of)
    # `PRD §12.4.3` 자동 seed — 결과에 실어 「이 seed로 다시 실행」이 가능하게 한다.
    seed = random_seed if random_seed is not None else secrets.randbits(_SEED_BITS)

    vessel = await _load_vessel(session, vessel_id)
    regulation = await _load_regulation_year(session, regulation_year)
    reference_line = await _select_reference_line(session, vessel)
    rating_boundary = await _select_rating_boundary(session, vessel)
    transport_capacity = _resolve_transport_capacity(vessel)
    reference_capacity = _resolve_reference_capacity(vessel, reference_line)

    required = calculate_required_cii(
        a=Decimal(str(reference_line.a_decimal)),
        c=Decimal(str(reference_line.c)),
        reference_capacity=reference_capacity,
        z_factor_percent=Decimal(str(regulation.z_factor_percent)),
    )
    d_vector = DVector(
        d1=Decimal(str(rating_boundary.d1)),
        d2=Decimal(str(rating_boundary.d2)),
        d3=Decimal(str(rating_boundary.d3)),
        d4=Decimal(str(rating_boundary.d4)),
    )

    actual, planned = await _collect_voyages(
        session, vessel_id=vessel_id, year=regulation_year, as_of=resolved_as_of
    )
    if len(planned) > MAX_REMAINING_VOYAGES:
        raise ValidationError(
            f"잔여 항차가 {MAX_REMAINING_VOYAGES}건을 초과했습니다 ({len(planned)}건). "
            "계산을 거부합니다.",
            field="vessel_id",
            field_label="선박",
        )

    fuel_by_voyage = await voyage_repo.list_fuel_uses_by_voyage_ids(
        session, [v.id for v in (*actual, *planned)]
    )

    completed = CompletedTotals(
        co2_g=float(
            sum(
                (_voyage_co2_g(v, fuel_by_voyage.get(v.id, [])) for v in actual),
                Decimal(0),
            )
        ),
        distance_nm=float(
            sum(
                (Decimal(str(v.actual_distance_nm or v.planned_distance_nm or 0)) for v in actual),
                Decimal(0),
            )
        ),
    )

    remaining = []
    for voyage in planned:
        fuel_uses = fuel_by_voyage.get(voyage.id, [])
        for fuel_use in fuel_uses:
            remaining.append(
                RemainingVoyage(
                    distance_nm=float(voyage.planned_distance_nm or 0),
                    fuel_ton=float(fuel_use.planned_fuel_ton or 0),
                    cf=float(fuel_use.cf_used),
                    speed_kn=(
                        None if voyage.planned_speed_kn is None else float(voyage.planned_speed_kn)
                    ),
                    reference_speed_kn=(
                        None
                        if vessel.reference_speed_kn is None
                        else float(vessel.reference_speed_kn)
                    ),
                    base_daily_foc_ton=(
                        None
                        if vessel.reference_daily_foc_ton is None
                        else float(vessel.reference_daily_foc_ton)
                    ),
                )
            )

    # 분포는 코드가 아니라 테이블에서 읽는다 (#434).
    profile_rows = await param_repo.load_distribution_profile(session, distribution_profile)
    profile = profile_from_rows(profile_rows)

    deterministic = project_deterministic(
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required.required_cii,
        d_vector=d_vector,
    )
    outcome = simulate_annual(
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required.required_cii,
        d_vector=d_vector,
        target_rating=target_rating,
        seed=seed,
        runs=simulation_runs,
        profile=profile,
    )
    entries, sensitivity_warnings = analyze_sensitivity(
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required.required_cii,
        d_vector=d_vector,
    )

    sensitivity = _build_sensitivity(
        entries=entries,
        base_rating=deterministic.rating,
        base_probability=outcome.target_success_probability,
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required.required_cii,
        d_vector=d_vector,
        target_rating=target_rating,
        seed=seed,
        runs=outcome.runs,
        profile=profile,
    )

    parameters_used = _parameters_used(
        regulation=regulation,
        reference_line=reference_line,
        rating_boundary=rating_boundary,
        profile_name=distribution_profile,
        profile_rows=profile_rows,
    )

    snapshot_id, calculation_run_id, simulation_id, snapshot_created_at = await _persist(
        session,
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        target_rating=target_rating,
        runs=outcome.runs,
        voyages_json=_snapshot_payload(actual, planned, fuel_by_voyage),
        parameters_used=parameters_used,
        result_json=_result_json(deterministic, outcome, sensitivity),
        warnings=[*outcome.warnings, *sensitivity_warnings],
        seed=seed,
    )

    return {
        "simulation_id": str(simulation_id),
        "calculation_run_id": str(calculation_run_id),
        "deterministic": {
            "projected_attained_cii": _publish(deterministic.attained_cii),
            "projected_rating": deterministic.rating,
            "completed_voyage_count": len(actual),
            "remaining_voyage_count": len(planned),
            "completed_M_gco2": _publish(deterministic.completed_co2_g),
            "completed_W_capacity_nm": _publish(
                transport_capacity * deterministic.completed_distance_nm
            ),
            "planned_M_gco2": _publish(deterministic.planned_co2_g),
            "planned_W_capacity_nm": _publish(
                transport_capacity * deterministic.planned_distance_nm
            ),
        },
        "monte_carlo": {
            "rng_metadata": outcome.rng_metadata,
            "runs": outcome.runs,
            "rating_probabilities": {
                key: str(value) for key, value in outcome.rating_probabilities.items()
            },
            "target_success_probability": str(outcome.target_success_probability),
            "target_rating": target_rating,
            "p10": str(outcome.p10),
            "p50": str(outcome.p50),
            "p90": str(outcome.p90),
            "mean_cii": str(outcome.mean),
        },
        #
        # `PRD §9.4.2` — 기능③의 위험도는 **목표 달성 확률** 기반이다.
        # `calculate_deterministic_risk`(마진 기반)는 기능①·②의 것이라 여기서 쓰면
        # 안 된다 — 그쪽은 등급마다 margin_ratio를 요구하고, 연간 시뮬레이션에는
        # 「경계까지의 마진」이 아니라 분포가 있다.
        #
        "risk_level": calculate_probability_risk(outcome.target_success_probability),
        "sensitivity_analysis": sensitivity,
        "snapshot": {
            "snapshot_id": str(snapshot_id),
            "created_at": snapshot_created_at.isoformat(),
            "voyage_count": len(actual) + len(planned),
        },
        "warnings": sorted({*outcome.warnings, *sensitivity_warnings}),
    }


def _build_sensitivity(
    *,
    entries,
    base_rating: str,
    base_probability: Decimal,
    completed,
    remaining,
    transport_capacity: Decimal,
    required_cii: Decimal,
    d_vector: DVector,
    target_rating: str,
    seed: int,
    runs: int,
    profile,
) -> dict[str, object]:
    """엔진 결과 → ``API_SPEC §6.1`` 민감도 블록.

    ## 확률 변화는 **같은 seed로** 다시 돌려 낸다

    지렛대 넷(속도·연료 ±)은 ``target_probability_change``를 함께 낸다. 그러려면
    Monte Carlo를 다시 돌려야 하는데, **seed를 바꾸지 않는다** — 같은 난수열을 쓰면
    두 결과의 차이가 온전히 지렛대 때문이다(common random numbers). seed를 새로
    뽑으면 「이 변수 때문에 바뀐 것」과 「표본이 달라서 바뀐 것」을 가를 수 없다.

    나머지 지렛대는 등급 변화만 낸다 — ``API_SPEC §6.1`` 응답 예시가 그렇고,
    확률까지 내면 실행 시간이 지렛대 수만큼 는다.
    """
    from cii_platform.calc.annual_simulation import (
        _shift_distance,
        _shift_fuel,
        _shift_speed,
    )

    shifted_for = {
        "speed_minus_1kn": lambda: _shift_speed(remaining, -1.0),
        "speed_plus_1kn": lambda: _shift_speed(remaining, +1.0),
        "fuel_minus_10pct": lambda: _shift_fuel(remaining, 0.90),
        "fuel_plus_10pct": lambda: _shift_fuel(remaining, 1.10),
    }

    block: dict[str, object] = {"interaction_note": INTERACTION_NOTE}
    for entry in entries:
        key = _SENSITIVITY_KEYS.get((entry.variable, entry.change))
        if key is None:  # pragma: no cover - 엔진이 새 지렛대를 늘리면
            continue

        item: dict[str, object] = {
            "projected_cii": _publish(entry.attained_cii),
            "rating_change": _rating_change(base_rating, entry.rating),
        }

        if key in _PROBABILITY_LEVERS:
            shifted = shifted_for[key]()
            moved = simulate_annual(
                completed=completed,
                remaining=shifted,
                transport_capacity=transport_capacity,
                required_cii=required_cii,
                d_vector=d_vector,
                target_rating=target_rating,
                seed=seed,  # ← 같은 seed. 차이가 지렛대 때문이어야 한다.
                runs=runs,
                profile=profile,
            )
            item["target_probability_change"] = _signed(
                moved.target_success_probability - base_probability
            )

        block[key] = item

    # `_shift_distance`는 위 표에 쓰지 않지만 import를 남겨 두면 lint가 잡는다.
    _ = _shift_distance
    return block


def _parameters_used(
    *, regulation, reference_line, rating_boundary, profile_name: str, profile_rows
) -> dict[str, object]:
    """``TECH_SPEC §5.2.1`` + ``§5.2.1.1``.

    **분포 프로파일을 함께 싣는 것이 이 함수의 요점**이다(``#434``). 싣지 않으면
    ``simulation_parameter``가 바뀐 뒤 같은 seed로 돌려도 결과가 달라지는데
    ``parameter_hash``는 같아진다 — 재현성 계약이 성립하지 않는다.

    ``parameters_used``는 실행마다 따로 기록되므로 **기능①·②의 기존 해시는 영향받지
    않는다.** ``§5.2.1`` 전역 스키마를 건드렸다면 과거 계산의 해시가 전부 무효가 된다.
    """
    return {
        "regulation_year": {
            "year": str(regulation.year),
            "z_factor_percent": str(regulation.z_factor_percent),
        },
        "reference_line": {
            "ship_type": reference_line.ship_type,
            "reference_capacity_rule": reference_line.capacity_rule,
            "a_decimal": str(reference_line.a_decimal),
            "c": str(reference_line.c),
        },
        "rating_boundary": {
            "ship_type": rating_boundary.ship_type,
            "d1": str(rating_boundary.d1),
            "d2": str(rating_boundary.d2),
            "d3": str(rating_boundary.d3),
            "d4": str(rating_boundary.d4),
        },
        "simulation_profile": {
            "profile": profile_name,
            "version": (profile_rows[0].version if profile_rows else "DEFAULT_CONSTANT"),
            "parameters": [
                {
                    "variable": row.variable,
                    "bound_type": row.bound_type,
                    "min": str(row.min_value),
                    "mode": str(row.mode_value),
                    "max": str(row.max_value),
                }
                for row in profile_rows
            ],
        },
    }


def _result_json(deterministic, outcome, sensitivity) -> dict[str, object]:
    """``calculation_run.result_json``. 재현 확인에 필요한 것만 담는다."""
    return {
        "projected_attained_cii": str(deterministic.attained_cii),
        "projected_rating": deterministic.rating,
        "rating_probabilities": {
            key: str(value) for key, value in outcome.rating_probabilities.items()
        },
        "target_success_probability": str(outcome.target_success_probability),
        "p10": str(outcome.p10),
        "p50": str(outcome.p50),
        "p90": str(outcome.p90),
        "sensitivity_keys": sorted(k for k in sensitivity if k != "interaction_note"),
    }


async def _persist(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    target_rating: str,
    runs: int,
    voyages_json: list[dict],
    parameters_used: dict,
    result_json: dict,
    warnings: list[str],
    seed: int,
):
    """스냅샷 → 계산 이력 → 시뮬레이션 실행 순으로 저장한다.

    **순서가 강제돼 있다.** ``annual_simulation_run``이 두 행을 모두 NOT NULL로
    참조하므로(``snapshot_id``·``calculation_run_id``) 먼저 만들어야 한다.

    ``simulation_snapshot``은 immutable이라(``trg_snapshot_immutable``) 한 번 넣으면
    고칠 수 없다 — 계산에 쓴 값이 확정된 뒤에 넣는 이유다.
    """
    from sqlalchemy import text

    input_hash = compute_input_hash(
        {
            "vessel_id": str(vessel_id),
            "regulation_year": regulation_year,
            "target_rating": target_rating,
            "simulation_runs": runs,
            "random_seed": str(seed),
            "voyages": voyages_json,
        }
    )
    parameter_hash = compute_parameter_hash(parameters_used)

    snapshot_row = (
        await session.execute(
            text(
                "INSERT INTO simulation_snapshot "
                "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
                "VALUES (:vessel_id, :year, CAST(:voyages AS jsonb), :input_hash, :parameter_hash) "
                "RETURNING id, created_at"
            ),
            {
                "vessel_id": vessel_id,
                "year": regulation_year,
                "voyages": _json(voyages_json),
                "input_hash": input_hash,
                "parameter_hash": parameter_hash,
            },
        )
    ).one()

    run_row = (
        await session.execute(
            text(
                # chk_calculation_type의 4값 중 하나여야 한다(마이그레이션 006).
                # 이 실행은 결정론과 Monte Carlo를 **함께** 내지만, 사용자가 고른 것은
                # 확률 분석이므로 MONTE_CARLO로 기록한다 — 결정론 값은 그 결과에
                # 포함돼 있고, 별도 행으로 나누면 같은 실행이 이력에서 둘로 보인다.
                "INSERT INTO calculation_run "
                "(calculation_type, vessel_id, input_hash, parameter_hash, model_version, "
                " result_json, parameters_used, warnings_json) "
                "VALUES ('ANNUAL_MONTE_CARLO', :vessel_id, :input_hash, :parameter_hash, "
                " CAST(:model_version AS jsonb), CAST(:result AS jsonb), "
                " CAST(:parameters AS jsonb), CAST(:warnings AS jsonb)) "
                "RETURNING id"
            ),
            {
                "vessel_id": vessel_id,
                "input_hash": input_hash,
                "parameter_hash": parameter_hash,
                "model_version": _json({"engine": "annual_simulation", "issue": "#63"}),
                "result": _json(result_json),
                "parameters": _json(parameters_used),
                "warnings": _json(warnings),
            },
        )
    ).one()

    simulation_row = (
        await session.execute(
            text(
                "INSERT INTO annual_simulation_run "
                "(calculation_run_id, vessel_id, regulation_year, target_rating, "
                " simulation_runs, snapshot_id) "
                "VALUES (:run_id, :vessel_id, :year, :target, :runs, :snapshot_id) "
                "RETURNING id"
            ),
            {
                "run_id": run_row.id,
                "vessel_id": vessel_id,
                "year": regulation_year,
                "target": target_rating,
                "runs": runs,
                "snapshot_id": snapshot_row.id,
            },
        )
    ).one()

    await session.commit()
    return snapshot_row.id, run_row.id, simulation_row.id, snapshot_row.created_at


def _json(value: object) -> str:
    """JSONB 파라미터용 직렬화. ``ensure_ascii=False``로 한글을 그대로 남긴다."""
    import json

    return json.dumps(value, ensure_ascii=False)
