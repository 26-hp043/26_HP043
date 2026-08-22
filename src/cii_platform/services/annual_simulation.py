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
from dataclasses import dataclass
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
from cii_platform.calc.hash import compute_annual_input_hash, compute_parameter_hash
from cii_platform.calc.precision import LAYER1_ROUNDING
from cii_platform.calc.rating_engine import DVector, calculate_probability_risk
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import (
    NotFoundError,
    ParameterError,
    ReproducibilityError,
    ValidationError,
)
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


# ─── 스냅샷 → 계산 입력 ───────────────────────────────────────────────────────


def _decimal_or(*values: str | None) -> Decimal:
    """앞에서부터 **0이 아닌 첫 값**. 전부 비었으면 ``Decimal(0)``.

    원본 코드의 ``fu.actual_fuel_ton or fu.planned_fuel_ton or 0``과 같은 규칙이다.
    `or` 연쇄는 ``0``도 건너뛰므로, 스냅샷 문자열로 옮길 때 그 성질을 함께 옮긴다 —
    ``Decimal("0")``을 「값이 있다」로 읽으면 실적 0인 항차에서 계획값이 무시된다.
    """
    for value in values:
        if value is None:
            continue
        parsed = Decimal(value)
        if parsed:
            return parsed
    return Decimal(0)


#: 계산이 ``vessel``에서 읽는 **전부**다 (`#493`).
#:
#: `#493` 본문은 ``reference_*`` 둘을 들었으나 실측하면 다섯이다 —
#: :func:`_recompute`가 capacity도 살아 있는 행에서 읽는다. 세 값이 **CII 분모**를
#: 바꾸므로 영향이 앞의 둘보다 크다.
VESSEL_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "ship_type",
    "deadweight",
    "gross_tonnage",
    "reference_speed_kn",
    "reference_daily_foc_ton",
)


@dataclass(frozen=True)
class VesselSnapshot:
    """스냅샷에 담긴 선박 제원 (`#493`).

    ``vessel`` ORM 행과 **같은 속성 이름**을 갖는다 — ``resolve_transport_capacity``
    같은 기존 함수가 그대로 받아들이도록 하려는 것이다. 계산부를 고치지 않는 것이
    요점이다: 고치면 실행 경로와 재현 경로가 또 갈린다.
    """

    ship_type: str
    deadweight: Decimal | None
    gross_tonnage: Decimal | None
    reference_speed_kn: Decimal | None
    reference_daily_foc_ton: Decimal | None


def _vessel_snapshot_payload(vessel) -> dict[str, str | None]:
    """``simulation_snapshot.vessel_json``에 넣을 제원 사본.

    **수치를 문자열로 담는다.** ``NUMERIC`` 값을 float으로 거치면 ``0.1``이
    ``0.1000000000000000055``가 되어 들어가고, 그러면 스냅샷이 원본과 다른 값을
    보관하게 된다 (`API_SPEC §1.7`이 응답에 문자열을 쓰는 것과 같은 이유).
    """
    payload: dict[str, str | None] = {}
    for field in VESSEL_SNAPSHOT_FIELDS:
        value = getattr(vessel, field)
        payload[field] = None if value is None else str(value)
    return payload


def _vessel_from_snapshot(payload: dict) -> VesselSnapshot:
    """제원 사본을 계산이 받는 모양으로 되돌린다."""

    def number(name: str) -> Decimal | None:
        value = payload.get(name)
        return None if value is None else Decimal(str(value))

    return VesselSnapshot(
        ship_type=payload["ship_type"],
        deadweight=number("deadweight"),
        gross_tonnage=number("gross_tonnage"),
        reference_speed_kn=number("reference_speed_kn"),
        reference_daily_foc_ton=number("reference_daily_foc_ton"),
    )


def _inputs_from_snapshot(
    rows: list[dict], vessel
) -> tuple[CompletedTotals, list[RemainingVoyage]]:
    """스냅샷 항차 사본에서 계산 입력을 만든다 (``TECH_SPEC §11.4`` 2항).

    **계산은 원본 ``voyage`` 테이블이 아니라 이 사본에서 나온다.** 실행 경로와 재현
    경로가 같은 함수를 쓰게 하는 것이 요점이다 — 두 경로가 각자 입력을 조립하면
    ``reproduce``가 「원본과 다르다」고 보고할 때 그것이 **엔진 문제인지 조립 문제인지**
    구분되지 않는다.

    ``vessel``은 이제 **스냅샷에서 복원한** :class:`VesselSnapshot`이다 (`#493`).
    종전에는 살아 있는 ``vessel`` 행을 받아 제원을 읽었고, 그래서 제원을 고치면 같은
    스냅샷·같은 seed로도 결과가 달라졌다 — ``input_hash``가 항차만 덮어 그 변화가
    해시에도 드러나지 않았다.
    """
    completed_co2_g = Decimal(0)
    completed_distance_nm = Decimal(0)
    remaining: list[RemainingVoyage] = []

    reference_speed_kn = (
        None if vessel.reference_speed_kn is None else float(vessel.reference_speed_kn)
    )
    base_daily_foc_ton = (
        None if vessel.reference_daily_foc_ton is None else float(vessel.reference_daily_foc_ton)
    )

    for row in rows:
        fuel_uses = row.get("fuel_uses") or []
        if row.get("kind") == "ACTUAL":
            for fuel_use in fuel_uses:
                completed_co2_g += (
                    _decimal_or(fuel_use.get("actual_fuel_ton"), fuel_use.get("planned_fuel_ton"))
                    * Decimal(1_000_000)
                    * Decimal(fuel_use["cf_used"])
                )
            completed_distance_nm += _decimal_or(
                row.get("actual_distance_nm"), row.get("planned_distance_nm")
            )
            continue

        planned_distance = float(Decimal(row.get("planned_distance_nm") or "0"))
        planned_speed = row.get("planned_speed_kn")
        for fuel_use in fuel_uses:
            remaining.append(
                RemainingVoyage(
                    distance_nm=planned_distance,
                    fuel_ton=float(Decimal(fuel_use.get("planned_fuel_ton") or "0")),
                    cf=float(Decimal(fuel_use["cf_used"])),
                    speed_kn=None if planned_speed is None else float(Decimal(planned_speed)),
                    reference_speed_kn=reference_speed_kn,
                    base_daily_foc_ton=base_daily_foc_ton,
                )
            )

    completed = CompletedTotals(
        co2_g=float(completed_co2_g), distance_nm=float(completed_distance_nm)
    )
    return completed, remaining


def _plan_voyage_count(rows: list[dict]) -> int:
    """스냅샷에서 **잔여 계획 항차 수**. 연료 행이 아니라 항차를 센다."""
    return sum(1 for row in rows if row.get("kind") == "PLAN")


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

    live_vessel = await _load_vessel(session, vessel_id)
    # 제원을 **여기서 사본으로 고정**하고, 이후 계산은 전부 그 사본으로 한다 (`#493`).
    # 실행 경로가 살아 있는 행을 쓰고 재현 경로가 사본을 쓰면 두 경로가 갈린다 —
    # `_inputs_from_snapshot` docstring이 항차에 대해 적은 것과 같은 이유다.
    vessel_json = _vessel_snapshot_payload(live_vessel)
    vessel = _vessel_from_snapshot(vessel_json)

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

    #
    # **스냅샷을 먼저 만들고 그 사본에서 계산 입력을 뽑는다** (``TECH_SPEC §11.4`` 2항:
    # 「원본 Voyage 테이블이 아닌 SimulationSnapshot.voyages 사용」).
    #
    # 종전에는 계산은 ORM 행에서, 스냅샷은 따로 직렬화해서 만들었다. 값이 같으니
    # 결과는 같았지만 **조립 경로가 둘**이었고, 그러면 `reproduce`(§6.4)가 스냅샷에서
    # 조립한 값과 어긋날 때 원인을 가릴 수 없다. 지금은 두 경로가 같은 함수를 쓴다.
    #
    voyages_json = _snapshot_payload(actual, planned, fuel_by_voyage)
    completed, remaining = _inputs_from_snapshot(voyages_json, vessel)

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

    payload = _payload(
        deterministic=deterministic,
        outcome=outcome,
        sensitivity=sensitivity,
        transport_capacity=transport_capacity,
        completed_voyage_count=len(actual),
        remaining_voyage_count=len(planned),
        target_rating=target_rating,
        warnings=[*outcome.warnings, *sensitivity_warnings],
    )

    snapshot_id, calculation_run_id, simulation_id, snapshot_created_at = await _persist(
        session,
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        target_rating=target_rating,
        runs=outcome.runs,
        voyages_json=voyages_json,
        vessel_json=vessel_json,
        parameters_used=parameters_used,
        result_json=payload,
        warnings=payload["warnings"],
        seed=seed,
    )

    return _envelope(
        simulation_id=simulation_id,
        calculation_run_id=calculation_run_id,
        payload=payload,
        snapshot={
            "snapshot_id": str(snapshot_id),
            "created_at": snapshot_created_at.isoformat(),
            "voyage_count": len(voyages_json),
        },
    )


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


def _payload(
    *,
    deterministic,
    outcome,
    sensitivity,
    transport_capacity: Decimal,
    completed_voyage_count: int,
    remaining_voyage_count: int,
    target_rating: str,
    warnings: list[str],
) -> dict[str, object]:
    """``API_SPEC §6.1`` 응답의 본문 — **식별자와 스냅샷 블록을 뺀 나머지**다.

    ## 왜 이 형태로 저장하는가 (#443)

    종전 ``result_json``은 「재현 확인에 필요한 것만」 담았다(확률·백분위·민감도 **키**).
    그런데 ``API_SPEC §6.2``는 조회 응답이 **§6.1과 동일**해야 한다고 규정한다 —
    담아 두지 않은 것(``rng_metadata``·항차 수·민감도 **값**·``risk_level``)은
    다시 계산하지 않는 한 돌려줄 수 없고, 다시 계산하면 그것은 조회가 아니라 재실행이다.

    그래서 응답 본문을 **그대로** 저장한다. 값이 두 벌 생기지 않도록 실행 경로도 같은
    함수를 쓴다 — 조회가 실행과 다른 모양을 내는 일이 구조적으로 불가능해진다.

    식별자(``simulation_id``·``calculation_run_id``)와 ``snapshot`` 블록은 넣지 않는다.
    **행에 이미 있는 것을 JSON에 복사해 두면 두 값이 갈릴 수 있다** — 스냅샷 정보의
    정본은 ``simulation_snapshot`` 테이블이다.
    """
    return {
        "deterministic": {
            "projected_attained_cii": _publish(deterministic.attained_cii),
            "projected_rating": deterministic.rating,
            "completed_voyage_count": completed_voyage_count,
            "remaining_voyage_count": remaining_voyage_count,
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
        "warnings": sorted(set(warnings)),
    }


def _envelope(*, simulation_id, calculation_run_id, payload: dict, snapshot: dict) -> dict:
    """저장된 본문에 식별자·스냅샷을 붙여 ``API_SPEC §6.1`` 응답을 만든다.

    키 순서를 §6.1 예시와 같게 둔다. **실행(§6.1)·조회(§6.2)·재실행(§6.4)이 모두 이
    함수를 지나므로 셋의 응답 모양이 갈릴 수 없다.**
    """
    return {
        "simulation_id": str(simulation_id),
        "calculation_run_id": str(calculation_run_id),
        "deterministic": payload["deterministic"],
        "monte_carlo": payload["monte_carlo"],
        "risk_level": payload["risk_level"],
        "sensitivity_analysis": payload["sensitivity_analysis"],
        "snapshot": snapshot,
        "warnings": payload["warnings"],
    }


def _input_hash(
    *,
    vessel_id: UUID,
    regulation_year: int,
    target_rating: str,
    runs: int,
    seed: int,
    voyages_json: list[dict],
    vessel_json: dict,
) -> str:
    """``input_hash``의 재료를 한 곳에 둔다 (``TECH_SPEC §5.3``).

    **저장할 때와 재현할 때가 같은 재료를 써야 한다.** 두 곳에 적으면 한쪽만 바뀌었을
    때 ``reproduce``가 「재현 실패」를 보고하는데, 실제로 다른 것은 결과가 아니라 해시
    계산식이다 — 가장 찾기 어려운 종류의 오보다.

    ``vessel``이 재료에 있다 (`#493`). 제원이 계산 입력이므로 해시가 덮어야 한다 —
    덮지 않으면 「스냅샷은 immutable인데 해시가 다르다」 검사가 **제원 변화를 보지
    못한다.** 이 재료가 바뀌었으므로 `037` **이전 실행의 해시는 이 식으로 재현되지
    않는다**; 그 행들은 ``vessel_json``이 NULL이라 재현 경로가 앞에서 끊는다.
    """
    return compute_annual_input_hash(
        {
            "vessel_id": str(vessel_id),
            "regulation_year": regulation_year,
            "target_rating": target_rating,
            "simulation_runs": runs,
            "random_seed": str(seed),
            "voyages": voyages_json,
            "vessel": vessel_json,
        }
    )


async def _persist(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    target_rating: str,
    runs: int,
    voyages_json: list[dict],
    vessel_json: dict,
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

    input_hash = _input_hash(
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        target_rating=target_rating,
        runs=runs,
        seed=seed,
        voyages_json=voyages_json,
        vessel_json=vessel_json,
    )
    parameter_hash = compute_parameter_hash(parameters_used)

    snapshot_row = (
        await session.execute(
            text(
                "INSERT INTO simulation_snapshot "
                "(vessel_id, regulation_year, voyages_json, vessel_json, "
                " input_hash, parameter_hash) "
                "VALUES (:vessel_id, :year, CAST(:voyages AS jsonb), "
                " CAST(:vessel AS jsonb), :input_hash, :parameter_hash) "
                "RETURNING id, created_at"
            ),
            {
                "vessel_id": vessel_id,
                "year": regulation_year,
                "voyages": _json(voyages_json),
                "vessel": _json(vessel_json),
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


# ─── 조회·재실행 (API_SPEC §6.2~§6.4, #443) ──────────────────────────────────
#
# **스냅샷을 남기는 이유가 조회에 있다.** `TECH_SPEC §11.1`이 격리를 요구한 것은
# 「몇 달 뒤에도 그때 무슨 데이터로 돌렸나」에 답하기 위해서인데(`§5.4` 재현성 계약),
# 그 스냅샷을 꺼내 볼 경로가 없으면 남긴 것이 쓰이지 않는다.


async def _load_run(session: AsyncSession, simulation_id: UUID):
    """실행 1건 + 계산 이력 + 스냅샷 메타를 한 번에 읽는다.

    ``voyages_json``은 여기서 읽지 않는다 — 항차가 많으면 큰 값이고, 조회(§6.2)와
    재실행(§6.4)에는 **개수만** 필요하다. 본문이 필요한 §6.3은 따로 읽는다.
    """
    from sqlalchemy import text

    row = (
        await session.execute(
            text(
                "SELECT r.id AS simulation_id, r.calculation_run_id, r.vessel_id, "
                "       r.regulation_year, r.target_rating, r.simulation_runs, r.snapshot_id, "
                "       c.result_json, c.parameters_used, c.input_hash, c.parameter_hash, "
                "       s.created_at AS snapshot_created_at, "
                "       jsonb_array_length(s.voyages_json) AS voyage_count "
                "FROM annual_simulation_run r "
                "JOIN calculation_run c ON c.id = r.calculation_run_id "
                "JOIN simulation_snapshot s ON s.id = r.snapshot_id "
                "WHERE r.id = :id"
            ),
            {"id": simulation_id},
        )
    ).one_or_none()

    if row is None:
        raise NotFoundError(f"연간 시뮬레이션 실행을 찾을 수 없습니다: {simulation_id}")
    return row


def _stored_payload(row) -> dict:
    """저장된 응답 본문. 옛 형식이면 **조용히 반쪽을 돌려주지 않는다.**

    `#443` 이전의 실행은 ``result_json``에 확률·백분위만 담았다(민감도는 **키만**).
    그 행으로 §6.2의 「§6.1과 동일한 응답」을 만들 수 없고, 없는 값을 그때 다시 계산하면
    그것은 조회가 아니라 **재실행**이다 — 스냅샷 이후 파라미터가 바뀌었다면 조회했을
    뿐인데 다른 값이 나온다.

    그래서 404로 끊는다. 요청한 **표현**이 존재하지 않는다는 뜻이며, 메시지에 그
    사실과 조치를 함께 적는다.
    """
    payload = row.result_json or {}
    if "deterministic" not in payload:
        raise NotFoundError(
            "이 실행은 결과 본문을 저장하기 전(#443)에 만들어져 조회할 수 없습니다. "
            "다시 실행해 주세요."
        )
    return payload


def _snapshot_block(row) -> dict[str, object]:
    return {
        "snapshot_id": str(row.snapshot_id),
        "created_at": row.snapshot_created_at.isoformat(),
        "voyage_count": row.voyage_count,
    }


async def get_annual_simulation(session: AsyncSession, simulation_id: UUID) -> dict[str, object]:
    """저장된 실행 결과를 다시 돌려준다 (``API_SPEC §6.2``).

    **다시 계산하지 않는다.** §6.2가 「§6.1의 응답과 동일」로 규정하는데, 계산을 다시
    하면 그 사이 규정 파라미터가 바뀌었을 때 **조회했을 뿐인데 값이 달라진다.** 재현
    확인은 §6.4의 일이다.
    """
    row = await _load_run(session, simulation_id)
    return _envelope(
        simulation_id=row.simulation_id,
        calculation_run_id=row.calculation_run_id,
        payload=_stored_payload(row),
        snapshot=_snapshot_block(row),
    )


async def list_snapshot_voyages(
    session: AsyncSession, simulation_id: UUID
) -> list[dict[str, object]]:
    """실행 당시 스냅샷에 담긴 항차를 돌려준다 (``API_SPEC §6.3``).

    ## 저장 형태를 그대로 내보내지 않는다

    ``voyages_json``은 계산 입력을 만들기 위한 내부 형태이고(``kind``·계획/실적 두 벌),
    §6.3이 규정한 응답은 **읽는 사람을 위한 형태**다(``status_at_snapshot`` ·
    실제 쓰인 ``distance_nm``·``fuel_ton`` 한 벌). 옮기는 규칙은 계산과 같다 —
    **실적이 있으면 실적, 없으면 계획**(``PRD §8.3``).

    ``snapshot_voyage_id``는 항차 사본에 별도 ID가 없으므로 ``{snapshot_id}:{voyage_id}``로
    만든다. **없는 UUID를 지어내지 않는다** — 지어내면 그 값으로 조회할 수 있는 것처럼
    보인다.
    """
    from sqlalchemy import text

    row = (
        await session.execute(
            text(
                "SELECT s.id AS snapshot_id, s.voyages_json "
                "FROM annual_simulation_run r "
                "JOIN simulation_snapshot s ON s.id = r.snapshot_id "
                "WHERE r.id = :id"
            ),
            {"id": simulation_id},
        )
    ).one_or_none()

    if row is None:
        raise NotFoundError(f"연간 시뮬레이션 실행을 찾을 수 없습니다: {simulation_id}")

    return [_snapshot_voyage_view(row.snapshot_id, item) for item in (row.voyages_json or [])]


def _snapshot_voyage_view(snapshot_id, item: dict) -> dict[str, object]:
    """스냅샷 항차 1건을 ``API_SPEC §6.3`` 형태로 옮긴다."""
    distance = _decimal_or(item.get("actual_distance_nm"), item.get("planned_distance_nm"))
    speed = item.get("planned_speed_kn")
    return {
        "snapshot_voyage_id": f"{snapshot_id}:{item.get('voyage_id')}",
        "original_voyage_id": item.get("voyage_id"),
        "voyage_no": item.get("voyage_no"),
        # 스냅샷 시점의 상태다. 지금의 상태가 아니다 — 그 구분이 이 API의 목적이다.
        "status_at_snapshot": item.get("status"),
        "distance_nm": float(distance),
        "speed_kn": None if speed is None else float(Decimal(speed)),
        "fuel_uses": [
            {
                "fuel_type": fuel_use.get("fuel_type"),
                "fuel_ton": float(
                    _decimal_or(fuel_use.get("actual_fuel_ton"), fuel_use.get("planned_fuel_ton"))
                ),
                # CF는 그때 쓴 값이다. 지금의 `fuel_type.cf`가 아니다 (#378).
                "cf_used": float(Decimal(fuel_use["cf_used"])),
            }
            for fuel_use in (item.get("fuel_uses") or [])
        ],
        "annual_inclusion_policy": item.get("annual_inclusion_policy"),
    }


async def reproduce_annual_simulation(
    session: AsyncSession, simulation_id: UUID
) -> dict[str, object]:
    """같은 스냅샷·같은 seed로 다시 계산해 결과가 같은지 확인한다 (``API_SPEC §6.4``).

    ## 무엇을 다시 하고 무엇을 다시 하지 않는가

    ``TECH_SPEC §11.4``가 정한 대로 **계산은 스냅샷 사본에서** 한다. 원본 항차를 다시
    읽으면 그 사이의 편집이 섞여 「재현 실패」가 되는데, 그것은 재현성 계약이 깨진
    것이 아니라 **다른 입력으로 돌린 것**이다.

    규정 파라미터는 반대로 **지금 값을 읽는다.** 바뀌었다면 그 사실이 드러나야 하기
    때문이다 — ``parameter_hash``가 어긋나면 409로 끊는다(§6.4 오류 표).

    ## 새 실행 기록을 남기지 않는다

    이것은 **검증**이지 실행이 아니다. 기록을 남기면 같은 결과가 이력에 여러 벌 쌓이고,
    그 중 무엇이 원본인지 구분이 흐려진다. 그래서 응답의 식별자도 **원본의 것**이다 —
    「원본 실행을 다시 돌려 확인했다」가 이 응답의 뜻이다.
    """
    row = await _load_run(session, simulation_id)
    stored = _stored_payload(row)

    seed = (stored.get("monte_carlo") or {}).get("rng_metadata", {}).get("seed")
    if seed is None:
        raise NotFoundError("이 실행은 seed가 기록되지 않아 재현할 수 없습니다(#443 이전 실행).")

    # **제원은 스냅샷에서 읽는다** (`#493`). 살아 있는 행을 읽으면 그 사이의 제원
    # 수정이 섞여 「재현 실패」가 되는데, 그것은 재현성 계약이 깨진 것이 아니라
    # **다른 입력으로 돌린 것**이다 — 항차에 대해 이미 같은 판단을 해 두었다.
    vessel = _vessel_from_snapshot(await _load_snapshot_vessel(session, row.snapshot_id))

    regulation = await _load_regulation_year(session, row.regulation_year)
    reference_line = await _select_reference_line(session, vessel)
    rating_boundary = await _select_rating_boundary(session, vessel)

    profile_name = (
        (row.parameters_used or {}).get("simulation_profile", {}).get("profile", "DEFAULT")
    )
    profile_rows = await param_repo.load_distribution_profile(session, profile_name)

    parameters_used = _parameters_used(
        regulation=regulation,
        reference_line=reference_line,
        rating_boundary=rating_boundary,
        profile_name=profile_name,
        profile_rows=profile_rows,
    )
    if compute_parameter_hash(parameters_used) != row.parameter_hash:
        raise ParameterError(
            "원본 실행 이후 규정 파라미터가 변경되어 같은 조건으로 재현할 수 없습니다. "
            "새로 실행하면 현재 파라미터 기준의 결과를 얻을 수 있습니다."
        )

    voyages_json = await _load_snapshot_voyages(session, row.snapshot_id)
    if (
        _input_hash(
            vessel_id=row.vessel_id,
            regulation_year=row.regulation_year,
            target_rating=row.target_rating,
            runs=row.simulation_runs,
            seed=seed,
            voyages_json=voyages_json,
            vessel_json=await _load_snapshot_vessel(session, row.snapshot_id),
        )
        != row.input_hash
    ):
        # 스냅샷은 immutable인데 해시가 다르다 — 저장된 것과 계산식 중 하나가 어긋났다.
        raise ReproducibilityError(
            "재현 입력의 해시가 원본과 다릅니다. 재현성 검증 실패 — 관리자에게 문의하세요."
        )

    payload = _recompute(
        vessel=vessel,
        regulation=regulation,
        reference_line=reference_line,
        rating_boundary=rating_boundary,
        voyages_json=voyages_json,
        target_rating=row.target_rating,
        runs=row.simulation_runs,
        seed=seed,
        profile_rows=profile_rows,
    )

    _assert_same_outcome(stored, payload)

    return _envelope(
        simulation_id=row.simulation_id,
        calculation_run_id=row.calculation_run_id,
        payload=payload,
        snapshot=_snapshot_block(row),
    )


async def _load_snapshot_vessel(session: AsyncSession, snapshot_id) -> dict:
    """스냅샷의 선박 제원 사본 (`#493`).

    **없으면 끊는다.** `037` 이전 실행은 이 값이 NULL이고, 그 행으로 재현하면 계산이
    **살아 있는 제원**을 쓰게 되어 「같은 스냅샷으로 다시 돌렸다」가 거짓이 된다.

    조용히 살아 있는 행으로 넘어가지 않는 이유는 이 이슈(`#493`)가 보고한 증상이
    정확히 그것이기 때문이다 — 결과가 달라지는데 원인이 **엔진·환경 문제**로 보고돼
    운영자가 잘못된 방향으로 조사하게 된다. `#443` 이전 실행을 :func:`_stored_payload`가
    끊는 것과 같은 선례다.
    """
    from sqlalchemy import text

    payload = (
        await session.execute(
            text("SELECT vessel_json FROM simulation_snapshot WHERE id = :id"),
            {"id": snapshot_id},
        )
    ).scalar_one()

    if payload is None:
        raise NotFoundError(
            "이 실행은 선박 제원을 스냅샷하기 전(#493)에 만들어져 재현할 수 없습니다. "
            "다시 실행하면 지금 제원 기준의 결과를 얻을 수 있습니다."
        )
    return payload


async def _load_snapshot_voyages(session: AsyncSession, snapshot_id) -> list[dict]:
    from sqlalchemy import text

    return (
        await session.execute(
            text("SELECT voyages_json FROM simulation_snapshot WHERE id = :id"),
            {"id": snapshot_id},
        )
    ).scalar_one() or []


def _recompute(
    *,
    vessel,
    regulation,
    reference_line,
    rating_boundary,
    voyages_json: list[dict],
    target_rating: str,
    runs: int,
    seed: int,
    profile_rows,
) -> dict[str, object]:
    """스냅샷으로 계산만 다시 한다. 저장하지 않는다.

    실행 경로(:func:`run_annual_simulation`)와 **같은 함수들을 같은 순서로** 부른다 —
    한쪽만 바뀌면 재현이 실패하는데 원인이 엔진이 아니라 이 조립부에 있게 된다.
    """
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

    completed, remaining = _inputs_from_snapshot(voyages_json, vessel)
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
        runs=runs,
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

    return _payload(
        deterministic=deterministic,
        outcome=outcome,
        sensitivity=sensitivity,
        transport_capacity=transport_capacity,
        completed_voyage_count=len(voyages_json) - _plan_voyage_count(voyages_json),
        remaining_voyage_count=_plan_voyage_count(voyages_json),
        target_rating=target_rating,
        warnings=[*outcome.warnings, *sensitivity_warnings],
    )


def _assert_same_outcome(stored: dict, reproduced: dict) -> None:
    """Monte Carlo 결과가 원본과 같은지 본다 (``API_SPEC §6.4`` 오류 표).

    **확률 분포와 결정론 등급만 본다.** ``rng_metadata``에는 ``numpy_version``·
    ``platform``처럼 **환경이 달라지면 당연히 달라지는 값**이 들어 있어, 전체를 비교하면
    다른 머신에서 돌렸다는 이유만으로 재현 실패가 된다. 재현성 계약이 요구하는 것은
    **값이 같은가**다(``TEST_PLAN`` IT-SNAP-004 「동일 rating_probabilities」).
    """
    checks = (
        ("rating_probabilities", stored["monte_carlo"].get("rating_probabilities")),
        ("target_success_probability", stored["monte_carlo"].get("target_success_probability")),
        ("p50", stored["monte_carlo"].get("p50")),
    )
    for key, original in checks:
        if reproduced["monte_carlo"].get(key) != original:
            raise ReproducibilityError(
                f"재현 결과가 원본과 다릅니다({key}). 재현성 검증 실패 — 관리자에게 문의하세요."
            )
    if reproduced["deterministic"].get("projected_rating") != stored["deterministic"].get(
        "projected_rating"
    ):
        raise ReproducibilityError(
            "재현 결과의 예상 등급이 원본과 다릅니다. 재현성 검증 실패 — 관리자에게 문의하세요."
        )
