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

import logging
import secrets
import time
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

# `_model_version`을 기능①에서 가져온다 — 기능②도 같은 방식이다
# (`services/scenario_compare.py:53`). 세 기능이 같은 함수를 써야
# `TECH_SPEC:1236-1243`의 6필드가 갈리지 않는다 (#816).
from cii_platform.services.voyage_cii import DISCLAIMER, _model_version
from cii_platform.services.ytd_cii import (
    POLICY_INCLUDE_AS_ACTUAL,
    _load_regulation_year,
    _load_vessel,
    _resolve_reference_capacity,
    _resolve_transport_capacity,
    _select_rating_boundary,
    _select_reference_line,
)

#: 계획 항차에 연료 정보가 없어 그 항차를 연말 예상에서 제외했다 (`TECH_SPEC §12.3`, #812).
#:
#: 거리만 넣는 대안을 쓰지 않는 이유는 그것이 「거리는 가는데 배출은 0」이라는 거짓
#: 진술이 되어 분모만 키우고, 연말 예상 CII를 **실제보다 좋게** 만들기 때문이다.
#: 빼되 **조용히 빼지 않는다** — 응답의 ``remaining_voyage_count``는 스냅샷의 PLAN
#: 행을 세므로, 이 경고가 없으면 일부만 계산했다는 사실이 드러날 자리가 없다.
WARNING_PLAN_NO_FUEL = "SIMULATION_PLAN_NO_FUEL"

logger = logging.getLogger(__name__)


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


def _snapshot_payload(actual, planned, fuel_by_voyage, live_cf: dict[str, Decimal]) -> list[dict]:
    """``simulation_snapshot.voyages_json``에 넣을 항차 사본 (``TECH_SPEC §11.2``).

    **계산에 쓴 값을 그대로 담는다.** 나중에 「그때 무슨 데이터로 돌렸나」에 답해야
    하므로, 원본을 다시 조회하면 알 수 없는 것(확정 시점의 실적·CF snapshot)을 함께
    남긴다. 계획 항차의 CF는 이 실행에 쓴 활성 CF다(#832) — 스냅샷이 그 기록이 된다.
    """
    rows = []
    for voyage, kind in ((v, "ACTUAL") for v in actual):
        rows.append(_snapshot_row(voyage, kind, fuel_by_voyage.get(voyage.id, []), live_cf))
    for voyage in planned:
        rows.append(_snapshot_row(voyage, "PLAN", fuel_by_voyage.get(voyage.id, []), live_cf))
    return rows


def _snapshot_row(voyage, kind: str, fuel_uses, live_cf: dict[str, Decimal]) -> dict:
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
                # 계획 항차는 **이 실행의 활성 CF**를 쓴다(#832). 확정 실적은 행의
                # cf_used — 그때 실제로 그 계수로 배출했다(#863).
                "cf_used": str(live_cf[fu.fuel_type] if kind == "PLAN" else fu.cf_used),
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
) -> tuple[CompletedTotals, list[RemainingVoyage], list[str]]:
    """스냅샷 항차 사본에서 계산 입력을 만든다 (``TECH_SPEC §11.4`` 2항).

    **계산은 원본 ``voyage`` 테이블이 아니라 이 사본에서 나온다.** 실행 경로와 재현
    경로가 같은 함수를 쓰게 하는 것이 요점이다 — 두 경로가 각자 입력을 조립하면
    ``reproduce``가 「원본과 다르다」고 보고할 때 그것이 **엔진 문제인지 조립 문제인지**
    구분되지 않는다.

    ``vessel``은 이제 **스냅샷에서 복원한** :class:`VesselSnapshot`이다 (`#493`).
    종전에는 살아 있는 ``vessel`` 행을 받아 제원을 읽었고, 그래서 제원을 고치면 같은
    스냅샷·같은 seed로도 결과가 달라졌다 — ``input_hash``가 항차만 덮어 그 변화가
    해시에도 드러나지 않았다.

    ## 계획 항차는 **연료 종류 수와 무관하게 한 줄**이다 (#812)

    종전에는 ``fuel_uses``마다 한 줄을 만들면서 **항차 전체 거리를 그대로 복사**했다.
    연료가 2종이면 그 항차 거리가 2배로 계상되어 분모만 커지고, 연말 예상 CII가
    1/N로 낮아져 **목표 달성 확률이 0%↔100%로 뒤집혔다.** 확정(ACTUAL) 분기는 거리를
    항차당 한 번만 더하는데 계획(PLAN) 분기만 규칙이 달랐다.

    연료는 **CO₂ 기여로 합쳐** 유효 CF 하나로 만든다.

    .. code-block:: text

        fuel_ton = Σ fuel_ton_i
        cf_eff   = Σ(fuel_ton_i × cf_i) / Σ fuel_ton_i

    결정론 경로의 ``planned_co2``는 ``fuel_ton × cf_eff``이므로 **연료별 합과 같다.**
    Monte Carlo도 이쪽이 옳다 — ``_sample_band``는 줄마다 독립으로 뽑는데, 한 항차의
    두 연료가 따로 흔들리는 것은 실제 성질이 아니다(엔진 docstring의 「항차마다
    독립으로 뽑는다」가 이제 성립한다).

    항차 1건 = 1줄이 되면서 **두 가지가 함께 맞는다** — 서비스의 항차 수 가드와
    엔진의 ``len(remaining)`` 가드가 같은 단위가 되고, 민감도 ``voyage_count ±1``이
    연료 행이 아니라 항차를 가감한다.

    :returns: ``(확정 누계, 잔여 항차, 경고)``
    """
    completed_co2_g = Decimal(0)
    completed_distance_nm = Decimal(0)
    remaining: list[RemainingVoyage] = []
    skipped_no_fuel = 0

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

        # 연료를 CO₂ 기여로 합친다. Decimal로 더한 뒤 마지막에 한 번만 float로
        # 내린다 — 줄마다 float로 바꿔 더하면 오차가 연료 종류 수만큼 쌓인다.
        fuel_ton = Decimal(0)
        co2_g = Decimal(0)
        for fuel_use in fuel_uses:
            ton = Decimal(fuel_use.get("planned_fuel_ton") or "0")
            fuel_ton += ton
            co2_g += ton * Decimal(fuel_use["cf_used"])

        if fuel_ton <= 0:
            # 연료를 알 수 없는 계획 항차는 **계산에서 뺀다** (#812).
            #
            # 거리만 넣으면 「거리는 가는데 배출은 0」이 되어 분모만 커지고, 연말
            # 예상 CII가 실제보다 **좋게** 나온다 — 이 이슈가 고치는 결함과 같은
            # 방향의 오류다. 빼면 비율(M/W)이 왜곡되지 않는다.
            #
            # 대신 **조용히 빠지지 않게** 경고를 남긴다. 응답의
            # `remaining_voyage_count`는 스냅샷의 PLAN 행을 세므로, 경고가 없으면
            # 「4건 중 3건만 계산했다」는 사실이 어디에도 드러나지 않는다.
            skipped_no_fuel += 1
            continue

        remaining.append(
            RemainingVoyage(
                distance_nm=planned_distance,
                fuel_ton=float(fuel_ton),
                cf=float(co2_g / fuel_ton),
                speed_kn=None if planned_speed is None else float(Decimal(planned_speed)),
                reference_speed_kn=reference_speed_kn,
                base_daily_foc_ton=base_daily_foc_ton,
            )
        )

    completed = CompletedTotals(
        co2_g=float(completed_co2_g), distance_nm=float(completed_distance_nm)
    )
    warnings = [WARNING_PLAN_NO_FUEL] if skipped_no_fuel else []
    return completed, remaining, warnings


@dataclass(frozen=True)
class ProjectionContext:
    """연말 예상에 필요한 **선박 제원 + 규제 파라미터** 한 벌 (#798).

    기능③과 실시간 CII가 같은 값을 내려면 항차 집계뿐 아니라 **분모(capacity)와
    등급 경계(d-vector)**도 같은 방식으로 골라야 한다. 선택 규칙이 두 곳에 있으면
    선박 유형·연도 경계에서 조용히 갈린다.
    """

    #: 스냅샷에서 복원한 제원 사본. 살아 있는 ORM 행이 아니다 (`#493`).
    vessel: VesselSnapshot
    #: ``simulation_snapshot.vessel_json``에 들어가는 원본 사본.
    vessel_json: dict[str, str | None]
    transport_capacity: Decimal
    reference_capacity: Decimal
    required_cii: Decimal
    d_vector: DVector
    regulation: object
    reference_line: object
    rating_boundary: object


async def load_projection_context(
    session: AsyncSession, *, vessel_id: UUID, regulation_year: int
) -> ProjectionContext:
    """선박 제원과 규제 파라미터를 확정한다 (#798).

    ``run_annual_simulation``과 ``services/cii_current``의 ⑶ 연말 예상이 **이 함수를
    공유한다.** 종전에는 실시간 CII가 자기 경로로 파라미터를 골랐고, 두 화면의
    「연말 예상」이 갈리는 원인 중 하나였다.
    """
    live_vessel = await _load_vessel(session, vessel_id)
    # 제원을 **사본으로 고정**하고 이후 계산은 전부 그 사본으로 한다 (`#493`).
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

    return ProjectionContext(
        vessel=vessel,
        vessel_json=vessel_json,
        transport_capacity=transport_capacity,
        reference_capacity=reference_capacity,
        required_cii=required.required_cii,
        d_vector=DVector(
            d1=Decimal(str(rating_boundary.d1)),
            d2=Decimal(str(rating_boundary.d2)),
            d3=Decimal(str(rating_boundary.d3)),
            d4=Decimal(str(rating_boundary.d4)),
        ),
        regulation=regulation,
        reference_line=reference_line,
        rating_boundary=rating_boundary,
    )


@dataclass(frozen=True)
class AnnualInputs:
    """연말 예상 계산의 입력 한 벌 (#798).

    기능③(연간 등급 관리)과 실시간 CII의 ⑶ 연말 예상이 **이 한 벌을 공유한다.**
    종전에는 두 화면이 각자 집계해 같은 선박·같은 연도에서 **다른 숫자**를 냈다
    (`#798` 실측: 7.654488 vs 8.971119).

    ``#493``이 실행 경로와 재현 경로의 조립을 하나로 모은 것과 같은 판단이다 —
    조립이 둘이면 값이 갈릴 때 **엔진 문제인지 조립 문제인지** 구분되지 않는다.
    """

    #: ``simulation_snapshot.voyages_json``에 그대로 들어가는 항차 사본.
    #: 기능③만 저장한다 — 실시간 CII는 스냅샷을 뜨지 않는다(조회 요청이다).
    voyages_json: list[dict]
    completed: CompletedTotals
    remaining: list[RemainingVoyage]
    #: 연료를 알 수 없어 제외한 계획 항차가 있으면 ``WARNING_PLAN_NO_FUEL``.
    warnings: list[str]
    #: 스냅샷의 PLAN 행 수. **제외된 항차도 센다** — 「4건 중 3건만 계산했다」를
    #: 경고와 함께 읽을 수 있어야 한다.
    plan_voyage_count: int


async def collect_annual_inputs(
    session: AsyncSession, *, vessel, vessel_id: UUID, year: int, as_of: datetime
) -> AnnualInputs:
    """살아 있는 항차에서 연말 예상의 계산 입력을 만든다 (#798).

    **스냅샷 사본을 먼저 만들고 그 사본에서 입력을 뽑는다** (``TECH_SPEC §11.4`` 2항).
    실시간 CII는 그 사본을 저장하지 않지만 **같은 경로로 만든 값**을 쓴다 — 저장 여부와
    무관하게 조립이 하나여야 두 화면의 숫자가 갈리지 않는다.

    :param vessel: :func:`_vessel_from_snapshot`이 복원한 제원 사본. 살아 있는 ORM 행을
        넘기지 않는다 — `#493`이 그 차이로 「같은 스냅샷·같은 seed인데 결과가 달라지는」
        상태를 만들었다.
    """
    actual, planned = await _collect_voyages(session, vessel_id=vessel_id, year=year, as_of=as_of)
    fuel_by_voyage = await voyage_repo.list_fuel_uses_by_voyage_ids(
        session, [v.id for v in (*actual, *planned)]
    )

    # #832 — 계획 항차의 CF는 **계산 실행 시점의 활성 CF**다(PRD §8.4 「연료 CF
    # 변경 → 변경 이후 계산에만 적용」). 아직 배출되지 않은 항차를 항차 생성 시점에
    # 박힌 CF로 예측하면, CF가 개정된 뒤 새로 실행해도 옛 계수로 계산된다. 확정
    # 실적은 그때 실제로 그 계수로 배출했으므로 행의 cf_used(#863)를 유지한다.
    # 스냅샷은 실행 시점에 쓴 값을 기록하므로(#378) 재현성은 그대로다.
    live_cf: dict[str, Decimal] = {}
    if planned:
        codes = sorted({fu.fuel_type for v in planned for fu in fuel_by_voyage.get(v.id, [])})
        fuel_rows = await param_repo.get_fuel_types_by_codes(session, codes)
        for code in codes:
            if code not in fuel_rows:
                raise ValidationError(
                    f"알 수 없는 연료 종류입니다: {code}",
                    field="fuel_type",
                    field_label="연료 종류",
                )
            live_cf[code] = Decimal(str(fuel_rows[code].cf))
    voyages_json = _snapshot_payload(actual, planned, fuel_by_voyage, live_cf)
    completed, remaining, warnings = _inputs_from_snapshot(voyages_json, vessel)

    return AnnualInputs(
        voyages_json=voyages_json,
        completed=completed,
        remaining=remaining,
        warnings=warnings,
        plan_voyage_count=_plan_voyage_count(voyages_json),
    )


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

    ``duration_ms``는 여기서 잰다 (#752). 계산 시간은 서비스의 관심사이고, 라우트가
    재면 요청 파싱·직렬화까지 섞여 ``PRD §16.1``의 「Monte Carlo 5,000회 p95 < 3초」와
    다른 것을 재게 된다 — 기능①(``services/voyage_cii.py:337-339``)과 같은 자리다.
    """
    started = time.perf_counter()

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

    # 제원·파라미터 확정은 실시간 CII의 ⑶ 연말 예상과 **같은 함수**를 쓴다 (`#798`).
    context = await load_projection_context(
        session, vessel_id=vessel_id, regulation_year=regulation_year
    )
    vessel = context.vessel
    vessel_json = context.vessel_json
    regulation = context.regulation
    reference_line = context.reference_line
    rating_boundary = context.rating_boundary
    transport_capacity = context.transport_capacity
    required_cii = context.required_cii
    d_vector = context.d_vector

    #
    # **스냅샷을 먼저 만들고 그 사본에서 계산 입력을 뽑는다** (``TECH_SPEC §11.4`` 2항:
    # 「원본 Voyage 테이블이 아닌 SimulationSnapshot.voyages 사용」).
    #
    # 종전에는 계산은 ORM 행에서, 스냅샷은 따로 직렬화해서 만들었다. 값이 같으니
    # 결과는 같았지만 **조립 경로가 둘**이었고, 그러면 `reproduce`(§6.4)가 스냅샷에서
    # 조립한 값과 어긋날 때 원인을 가릴 수 없다. 지금은 두 경로가 같은 함수를 쓴다.
    #
    inputs = await collect_annual_inputs(
        session, vessel=vessel, vessel_id=vessel_id, year=regulation_year, as_of=resolved_as_of
    )
    if inputs.plan_voyage_count > MAX_REMAINING_VOYAGES:
        raise ValidationError(
            f"잔여 항차가 {MAX_REMAINING_VOYAGES}건을 초과했습니다 "
            f"({inputs.plan_voyage_count}건). 계산을 거부합니다.",
            field="vessel_id",
            field_label="선박",
        )

    voyages_json = inputs.voyages_json
    completed, remaining, input_warnings = inputs.completed, inputs.remaining, inputs.warnings

    # 분포는 코드가 아니라 테이블에서 읽는다 (#434).
    profile_rows = await param_repo.load_distribution_profile(session, distribution_profile)
    #
    # **행이 하나도 없으면 그 프로파일은 존재하지 않는 것이다** (#870).
    #
    # 저장소는 없는 프로파일에 빈 목록을 돌려주고, 그 판단을 서비스에 넘긴다
    # (``load_distribution_profile`` docstring). 종전에는 그대로 넘겨
    # ``profile_from_rows([])``가 상수 기본값으로 조용히 폴백했다 — 오타나 없는
    # 이름(`CONSERVATIVE`·소문자 `default`)이 **200으로 통과**하고, 응답의
    # ``parameters_used.simulation_profile.profile``에는 **사용자가 보낸 이름이
    # 그대로** 실렸다. 보수적 분포를 고른 줄 아는 목표 달성 확률·P10/P50/P90이
    # 기본 분포 값인데 화면은 고른 이름을 보여 준다 — 오인을 확인할 방법이 없다.
    #
    # **일부 변수만 빠진 경우는 종전대로 기본값으로 채운다** — 그것은 「행 하나가
    # 비었다」이지 「프로파일이 없다」가 아니고, 파라미터 한 줄 때문에 시뮬레이션
    # 전체를 죽일 이유가 없다(``profile_from_rows`` docstring).
    #
    # 모르는 선종을 422로 거부하는 ``services/parameters.py``와 같은 판단이다.
    #
    if not profile_rows:
        raise ValidationError(
            f"알 수 없는 분포 프로파일입니다: {distribution_profile}",
            field="distribution_profile",
            field_label="분포 프로파일",
        )
    profile = profile_from_rows(profile_rows)

    deterministic = project_deterministic(
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required_cii,
        d_vector=d_vector,
    )
    outcome = simulate_annual(
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required_cii,
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
        required_cii=required_cii,
        d_vector=d_vector,
    )

    sensitivity = _build_sensitivity(
        entries=entries,
        base_rating=deterministic.rating,
        base_probability=outcome.target_success_probability,
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required_cii,
        d_vector=d_vector,
        target_rating=target_rating,
        seed=seed,
        runs=outcome.runs,
        profile=profile,
    )

    # 새 실행은 최신 스키마로 만든다. 지금은 v1뿐이다 (#816).
    parameters_used = build_parameters_used(
        PARAMETERS_SCHEMA_V1,
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
        # 항차 수도 **스냅샷 사본에서 센다** (`#798`). 종전에는 ORM 목록
        # (`actual`·`planned`)을 셌는데, 조립은 사본에서 하므로 출처가 둘이었다.
        completed_voyage_count=sum(1 for row in voyages_json if row.get("kind") == "ACTUAL"),
        remaining_voyage_count=inputs.plan_voyage_count,
        target_rating=target_rating,
        warnings=[*outcome.warnings, *sensitivity_warnings, *input_warnings],
    )

    # **저장 전에 잰다.** DB 왕복은 계산 시간이 아니다 — 기능①도 계산이 끝난 지점에서
    # 끊는다(`services/voyage_cii.py:410`). 0ms로 내려가지 않게 최소 1을 준다.
    duration_ms = max(1, round((time.perf_counter() - started) * 1000))

    (
        snapshot_id,
        calculation_run_id,
        simulation_id,
        snapshot_created_at,
        input_hash,
        parameter_hash,
    ) = await _persist(
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
        duration_ms=duration_ms,
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
        parameters_used=parameters_used,
        model_version=_model_version(),
        input_hash=input_hash,
        parameter_hash=parameter_hash,
        duration_ms=duration_ms,
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


#: ``parameters_used`` 스키마 버전. 버전 필드가 **없는** 저장 행은 ``v1``이다 (#816).
#:
#: 왜 버전이 필요한가 — ``reproduce``는 저장된 해시를 그대로 두고 **지금 코드로**
#: ``parameters_used``를 다시 만들어 비교한다. 따라서 빌더 출력이 한 글자만 바뀌어도
#: **과거 실행 전부**가 재실행에서 ``ParameterError``(409)를 받는다 — 실제로 바뀐 것은
#: 규정이 아니라 우리 코드인데 사용자에게는 「규정 파라미터가 변경되어 재현할 수
#: 없습니다」가 나간다.
#:
#: ``calculation_run``은 ``calc_run_guard()``(마이그레이션 024)가 UPDATE를 막으므로
#: **저장된 해시를 소급해 고칠 수도 없다.** 그래서 옛 형식을 빌더로 동결해 둔다.
PARAMETERS_SCHEMA_V1 = 1


def parameters_schema_version(stored: dict | None) -> int:
    """저장된 ``parameters_used``가 어느 스키마 버전인지 판정한다 (#816).

    버전 필드가 **없으면** ``v1``이다 — `#816` 이전에 저장된 행이 전부 그렇다.

    필드가 **있는데** 정수가 아니면 :class:`ValueError`다. ``null``·``"abc"``·
    ``1.5``·``true``를 v1으로 흡수하면 손상된 행이 옛 형식으로 오인된다.

    :raises ValueError: 버전 필드가 있으나 정수가 아닐 때.
    """
    if not stored:
        return PARAMETERS_SCHEMA_V1
    if "parameter_schema_version" not in stored:
        # 필드 자체가 없다 = `#816` 이전 행 = v1. **이것만이 유일한 암묵 판정이다.**
        return PARAMETERS_SCHEMA_V1

    raw = stored["parameter_schema_version"]
    # 필드가 **있는데** 읽을 수 없으면 조용히 v1로 떨어뜨리지 않는다 (#816).
    # 떨어뜨리면 손상된 행이 「옛 형식」으로 오인되어, 해시가 맞지 않는 이유가
    # 「버전이 다르다」인지 「값이 손상됐다」인지 가려진다.
    #
    # `bool`을 먼저 막는다 — 파이썬에서 `isinstance(True, int)`는 참이라
    # `True`가 버전 1로 읽힌다.
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"parameter_schema_version이 정수가 아닙니다: {raw!r} "
            f"({type(raw).__name__}). 저장 행이 손상됐을 수 있습니다."
        )
    return raw


def build_parameters_used(version: int, **kwargs) -> dict[str, object]:
    """스키마 버전에 맞는 빌더를 고른다 (#816).

    ``reproduce``가 **저장된 행의 버전으로** 다시 만들어야 옛 해시가 재현된다.
    새 실행은 최신 버전을 쓴다.

    :raises ValueError: 모르는 버전. 조용히 v1로 떨어뜨리지 않는다 — 그러면 해시가
        맞지 않는 이유가 「버전이 다르다」인지 「값이 다르다」인지 가려지지 않는다.
    """
    if version == PARAMETERS_SCHEMA_V1:
        return _parameters_used_v1(**kwargs)
    raise ValueError(f"알 수 없는 parameters_used 스키마 버전: {version}")


def _parameters_used_v1(
    *, regulation, reference_line, rating_boundary, profile_name: str, profile_rows
) -> dict[str, object]:
    """``TECH_SPEC §5.2.1`` + ``§5.2.1.1`` — **v1 형식으로 동결** (#816).

    ⚠️ **이 함수를 고치면 과거 실행의 ``parameter_hash``가 재현되지 않는다.**
    새 필드는 ``v2`` 빌더를 신설해 거기 넣는다.

    v1에 손대지 않고 남겨 둔 미결 (근거는 `#816` 코멘트):

    * ``fuel_types`` — 넣을지가 `#832`(CF 적용 시점) 판정에 달려 있다
    * ``parameter_source_version`` — 기준선 하나의 ``source_ref``만 담아 이름이 실제
      의미보다 넓다. ``parameter_sources`` 객체로 바꾸는 안과 함께 v2에서 정한다
    * ``rating_boundary.ship_type`` — 사양서에 없으나 **선택된 경계 행의 식별 근거**
      이고 제거하면 과거 해시가 깨지므로 유지한다. 정본 등재 대상이다

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


def _envelope(
    *,
    simulation_id,
    calculation_run_id,
    payload: dict,
    snapshot: dict,
    parameters_used: dict,
    model_version: dict,
    input_hash: str,
    parameter_hash: str,
    duration_ms: int,
) -> dict:
    """``API_SPEC §1.3.1`` 계산 결과 응답 봉투를 만든다 (#752).

    키 순서를 ``§6.1`` 예시와 같게 둔다. **실행(§6.1)·조회(§6.2)·재실행(§6.4)이 모두 이
    함수를 지나므로 셋의 응답 모양이 갈릴 수 없다.**

    ## ``warnings``와 ``calculation_run_id``는 ``data`` 밖이다 (#752)

    종전에는 둘 다 ``data`` 안에 있었다. ``§1.3.1``과 ``§6.1`` 예시가 **최상위**로
    규정하고 기능①·②(``services/voyage_cii.py:425-435``)가 그렇게 낸다. 양쪽에 두면
    같은 값이 한 응답에 두 번 실려, 어긋났을 때 어느 쪽이 정본인지 알 수 없다.

    ``simulation_id``는 ``data`` 안에 남는다 — 최상위는 ``§1.3.1`` 공통 필드의 자리이고
    ``simulation_id``는 그 목록에 없다. ``§6.1`` 예시도 ``data`` 첫머리에 적는다(`#840` — 종전에는
    예시가 이 필드를 아예 적지 않았다).

    ``duration_ms``는 ``_duration_ms``라는 내부 키로 넘긴다. ``meta``를 만드는 것은
    라우트의 일이므로(``TECH_SPEC §16.1`` 계층 분리) 서비스는 값만 실어 보내고,
    라우트가 꺼내 ``meta.duration_ms``에 넣는다 — 기능①과 같은 방식이다.
    """
    return {
        "data": {
            "simulation_id": str(simulation_id),
            "deterministic": payload["deterministic"],
            "monte_carlo": payload["monte_carlo"],
            "risk_level": payload["risk_level"],
            "sensitivity_analysis": payload["sensitivity_analysis"],
            "snapshot": snapshot,
        },
        "parameters_used": parameters_used,
        "calculation_run_id": str(calculation_run_id),
        "model_version": model_version,
        "input_hash": input_hash,
        "parameter_hash": parameter_hash,
        "warnings": payload["warnings"],
        "disclaimer": DISCLAIMER,
        "_duration_ms": duration_ms,
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
    duration_ms: int,
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
                " result_json, parameters_used, warnings_json, duration_ms) "
                "VALUES ('ANNUAL_MONTE_CARLO', :vessel_id, :input_hash, :parameter_hash, "
                " CAST(:model_version AS jsonb), CAST(:result AS jsonb), "
                " CAST(:parameters AS jsonb), CAST(:warnings AS jsonb), :duration_ms) "
                "RETURNING id"
            ),
            {
                "vessel_id": vessel_id,
                "input_hash": input_hash,
                "parameter_hash": parameter_hash,
                # `TECH_SPEC:1236-1243`이 규정한 6필드를 그대로 싣는다 (#816).
                # 종전에는 `{"engine", "issue"}` 둘뿐이라 **하필 Monte Carlo 경로에서**
                # `rng_algorithm`·`numpy_version`이 빠져 있었다 — `§10.2`의 「NumPy
                # 마이너 변경 → model_version에 명시」가 성립하지 않았다.
                # 기능①·②와 같은 함수를 써서 셋이 갈릴 수 없게 한다.
                "model_version": _json(_model_version()),
                "result": _json(result_json),
                "parameters": _json(parameters_used),
                "warnings": _json(warnings),
                # `#752` 이전에는 이 컬럼을 비워 두었다. `PRD §16.1`의 「Monte Carlo
                # 5,000회 p95 < 3초」를 나중에 되짚으려면 실행마다 남아 있어야 한다 —
                # 응답에만 실으면 그 순간 말고는 확인할 길이 없다.
                "duration_ms": duration_ms,
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
    return (
        snapshot_row.id,
        run_row.id,
        simulation_row.id,
        snapshot_row.created_at,
        input_hash,
        parameter_hash,
    )


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
                "       c.model_version, c.duration_ms, "
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
        # **저장된 값을 그대로 낸다.** 지금 값을 읽으면 조회했을 뿐인데 파라미터가
        # 달라 보인다 — 이 함수가 다시 계산하지 않는 것과 같은 이유다 (#752).
        parameters_used=row.parameters_used or {},
        model_version=row.model_version or {},
        input_hash=row.input_hash,
        parameter_hash=row.parameter_hash,
        # **원본 실행에 걸린 시간**이다. 조회에 걸린 몇 ms를 「계산 시간」 자리에
        # 넣으면 `PRD §16.1` 성능 판단이 오도된다. `#752` 이전 행은 이 컬럼이
        # 비어 있으므로 0으로 낸다 — 「측정되지 않았다」는 뜻이다.
        duration_ms=row.duration_ms or 0,
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


def _seed_from_metadata(metadata: dict) -> int | None:
    """저장된 ``rng_metadata``에서 seed를 되읽는다 (#751).

    ``TECH_SPEC §2.2.2``가 규정하는 키는 ``seed_entropy``이고 값은 **128-bit hex
    문자열**이다. 종전 구현이 ``seed``(int)로 저장했으므로 **두 형태를 모두 읽는다.**

    옛 행을 마이그레이션으로 고칠 수 없기 때문이다 — ``calculation_run``은
    ``calc_run_guard()``(마이그레이션 024)가 ``needs_recalc`` false→true 외의
    UPDATE를 전부 거부한다. 폴백을 두지 않으면 **이 변경 이전에 실행된 시뮬레이션이
    전부 재현 불가**가 된다.

    :returns: seed 정수. 어느 키도 없으면 ``None``.
    """
    entropy = metadata.get("seed_entropy")
    if isinstance(entropy, str) and entropy:
        # `f"{seed:#034x}"`가 만든 `0x…` 표기. int()가 접두어를 그대로 받는다.
        return int(entropy, 16)
    legacy = metadata.get("seed")
    if isinstance(legacy, int):
        return legacy
    return None


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
    started = time.perf_counter()

    row = await _load_run(session, simulation_id)
    stored = _stored_payload(row)

    seed = _seed_from_metadata((stored.get("monte_carlo") or {}).get("rng_metadata") or {})
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

    # **저장된 행의 스키마 버전으로** 다시 만든다 (#816). 최신 버전으로 만들면
    # 빌더가 바뀐 순간 과거 실행이 전부 `ParameterError`(409)를 받는다 — 규정이
    # 아니라 우리 코드가 바뀐 것인데 「규정 파라미터가 변경되었다」로 나간다.
    parameters_used = build_parameters_used(
        parameters_schema_version(row.parameters_used),
        regulation=regulation,
        reference_line=reference_line,
        rating_boundary=rating_boundary,
        profile_name=profile_name,
        profile_rows=profile_rows,
    )
    # ⚠️ **두 해시를 모두 검사한 뒤 판정한다** (`#837`). 종전에는 파라미터 해시가
    # 어긋나면 곧바로 409를 던져 **입력 해시 검사가 실행조차 되지 않았다.** 두 조건이
    # 겹치면 늘 409만 나가고, 스냅샷 무결성이 깨졌다는 신호(500)가 사라졌다.
    #
    # `API_SPEC §6.4`가 둘을 **다른 실패**로 규정한다 — 409는 「새로 실행하세요」,
    # 500은 「관리자에게 문의하세요」. 사용자는 409 안내대로 새로 실행하고 정상 결과를
    # 받으므로, 무결성 실패는 **아무 데도 드러나지 않은 채** 묻힌다.
    #
    # 비용은 늘지 않는다 — 스냅샷 항차는 아래 재계산에 어차피 필요해 **읽는 순서만**
    # 앞당겨진다.
    parameters_changed = compute_parameter_hash(parameters_used) != row.parameter_hash

    voyages_json = await _load_snapshot_voyages(session, row.snapshot_id)
    input_mismatch = (
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
    )

    # 더 심각한 쪽이 이긴다. 스냅샷은 immutable(`009` `trg_snapshot_immutable`)인데
    # 해시가 다르다는 것은 **저장된 값과 계산식 중 하나가 어긋났다**는 뜻이다.
    if input_mismatch:
        if parameters_changed:
            # 가려진 쪽도 기록한다 — 관리자가 조사할 때 파라미터 변경이 함께 있었다는
            # 사실이 원인 판단을 바꾼다.
            logger.warning(
                "reproduce %s: input_hash와 parameter_hash가 모두 어긋남 — 500을 우선한다",
                simulation_id,
            )
        raise ReproducibilityError(
            "재현 입력의 해시가 원본과 다릅니다. 재현성 검증 실패 — 관리자에게 문의하세요."
        )
    if parameters_changed:
        raise ParameterError(
            "원본 실행 이후 규정 파라미터가 변경되어 같은 조건으로 재현할 수 없습니다. "
            "새로 실행하면 현재 파라미터 기준의 결과를 얻을 수 있습니다."
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
        # 재구성한 것을 싣는다 — 위에서 해시가 원본과 같음을 확인했으므로 저장분과
        # 같은 값이고, **이번 계산이 실제로 쓴 것**이 무엇인지가 응답의 뜻이다 (#752).
        parameters_used=parameters_used,
        # 반대로 ``model_version``은 **저장된 것**이다. 지금 값을 실으면 원본이 어느
        # 환경에서 돌았는지가 응답에서 사라진다 — 재현 판정의 근거가 그쪽이다.
        model_version=row.model_version or {},
        input_hash=row.input_hash,
        parameter_hash=row.parameter_hash,
        # **이번 재계산에 걸린 시간**이다. 실제로 다시 돌렸으므로 그 값이 정직하다
        # (조회 §6.2가 저장분을 내는 것과 갈리는 지점).
        duration_ms=max(1, round((time.perf_counter() - started) * 1000)),
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
    required_cii = calculate_required_cii(
        a=Decimal(str(reference_line.a_decimal)),
        c=Decimal(str(reference_line.c)),
        reference_capacity=reference_capacity,
        z_factor_percent=Decimal(str(regulation.z_factor_percent)),
    ).required_cii
    d_vector = DVector(
        d1=Decimal(str(rating_boundary.d1)),
        d2=Decimal(str(rating_boundary.d2)),
        d3=Decimal(str(rating_boundary.d3)),
        d4=Decimal(str(rating_boundary.d4)),
    )

    completed, remaining, input_warnings = _inputs_from_snapshot(voyages_json, vessel)
    profile = profile_from_rows(profile_rows)

    deterministic = project_deterministic(
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required_cii,
        d_vector=d_vector,
    )
    outcome = simulate_annual(
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required_cii,
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
        required_cii=required_cii,
        d_vector=d_vector,
    )
    sensitivity = _build_sensitivity(
        entries=entries,
        base_rating=deterministic.rating,
        base_probability=outcome.target_success_probability,
        completed=completed,
        remaining=remaining,
        transport_capacity=transport_capacity,
        required_cii=required_cii,
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
        warnings=[*outcome.warnings, *sensitivity_warnings, *input_warnings],
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
