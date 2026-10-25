"""기능② 시나리오 비교 서비스 (#57).

``api/routes``와 ``calc``/``db`` 사이에서 계산 흐름을 조합한다 (TECH_SPEC §16).
기능①(``services.voyage_cii``)이 이미 세운 규칙 — Layer 1 컨텍스트, 직렬화 자릿수,
``parameters_used`` 스키마, warning 규칙 — 을 그대로 재사용한다. 같은 규칙을
다시 쓰면 어느 쪽이 정본인지 알 수 없게 된다.

처리 흐름
---------

1. 선박·규정연도·기준선·등급 경계·연료 조회 (기능①과 같은 규칙)
2. DIRECT 거리 확정 — ``direct_distance_nm`` 또는 좌표 대권거리 (PRD §11.2)
3. 시나리오 계획 확정 — DIRECT · DETOUR(기본 direct × 1.05) ·
   SLOW_STEAMING(기본 ``max(current − 1, 1.0)``). 선석 가용 시각이 있으면 DIRECT_JIT ·
   DETOUR_JIT(거리 ÷ 선석까지 남은 시간)가 붙는다 (#2561 결정 D1)
4. 시나리오별 연료 추정 — cubic speed model (``calc.fuel_estimator``, #75)
5. 시나리오별 Layer 1 계산 — ``voyage_cii._compute_layer1`` 재사용. 선석 시각이 있으면
   선석 대기(시간 · 묘박 연료 · 대기 포함 CII)를 카드마다 따로 낸다 (#2561 결정 D8 「다」)
6. ``voyage_scenario`` 3~5행 + ``calculation_run`` 1건(SCENARIO) 저장
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.capacity import (
    capacity_axis,
    resolve_reference_capacity,
    resolve_transport_capacity,
    select_reference_line,
)
from cii_platform.calc.cii_engine import FuelUse
from cii_platform.calc.distance import great_circle_distance_nm, initial_bearing_deg
from cii_platform.calc.fuel_estimator import MIN_SPEED_KN, estimate_fuel_ton
from cii_platform.calc.hash import (
    compute_parameter_hash,
    compute_scenario_input_hash,
)
from cii_platform.calc.precision import layer1_context
from cii_platform.calc.rating_engine import DVector, select_rating_boundary
from cii_platform.db.repositories import calculation_run as calc_run_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.db.repositories import voyage_scenario as scenario_repo
from cii_platform.errors import NotFoundError, ParameterError, ValidationError
from cii_platform.services.calc_errors import (
    log_calculation_failure,
    regulation_year_missing,
    selection_error,
    spec_error,
)
from cii_platform.services.voyage import PLANNING_STATUSES
from cii_platform.services.voyage_cii import (
    DISCLAIMER,
    _build_warnings,
    _compute_layer1,
    _Layer1Values,
    _model_version,
    _percent,
    _plain,
    _publish,
)
from cii_platform.services.weather import (
    WeatherResolution,
    fetched_at_iso,
    resolve_with_fallback,
)
from cii_platform.validation.bounds import MAX_SPEED_KN, largest
from cii_platform.validation.field_labels import field_label

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: API_SPEC §5.1 예시의 ``scenario_name`` 원문. 프론트엔드 ``SCENARIO_NAME``과 같은 값이다.
SCENARIO_NAMES: dict[str, str] = {
    "DIRECT": "직항",
    "DETOUR": "우회",
    "SLOW_STEAMING": "감속",
    # `#2561` 결정 D1 — 선석 가용 시각을 넣었을 때만 생긴다. 「우회 + 증속」이 아니라 「도착시각
    # 맞춤」인 것은 선석이 넉넉하면 우회도 감속이 되기 때문이다(결정요청 v3 §2).
    "DIRECT_JIT": "직항 · 도착시각 맞춤",
    "DETOUR_JIT": "우회 · 도착시각 맞춤",
}

#: PRD §11.2 — DETOUR 기본 우회 거리 비율.
DETOUR_DISTANCE_RATIO = Decimal("1.05")

#: PRD §11.2 — SLOW_STEAMING 기본 감속량(1 knot).
SLOW_STEAMING_SPEED_DELTA = Decimal("1.0")

#: PRD §9.1 VAL-009 — 최소 속도(``MIN_SPEED_KN``)는 ``calc.fuel_estimator``에서 가져온다.

#: API_SPEC §1.6 — 감속 시나리오가 속도 floor(1.0kn)에 도달했을 때.
WARNING_SLOW_SPEED_FLOOR = "SLOW_SPEED_FLOOR"

#: API_SPEC §1.6 — 기상 모델 요청이 적용되지 않고 NONE으로 계산했을 때.
WARNING_WEATHER_NONE_FALLBACK = "WEATHER_NONE_FALLBACK"

#: API_SPEC §1.6 — 도착시각 맞춤 속력이 최소 속도(1.0kn)보다 낮아 1.0kn로 계산했을 때 (`#2561`).
#: 선석이 아주 멀면 생긴다. 그 시나리오는 선석보다 일찍 닿아 대기가 남는다.
WARNING_ARRIVAL_SPEED_FLOOR = "ARRIVAL_SPEED_FLOOR"

#: `#2561` — 도착시각 맞춤 속력의 상한. 넘으면 그 시나리오를 계산하지 않고 「도달 불가」로 싣는다.
#: 요청의 속력 상한(VAL-009 · ``validation/bounds.py``)과 같은 값이다.
_ARRIVAL_SPEED_MAX = MAX_SPEED_KN

#: 묘박 연료(t/일)를 시간으로 나누는 분모.
_HOURS_PER_DAY = Decimal(24)

#: 선석까지 남은 시간을 정수 마이크로초에서 시간으로.
_MICROS_PER_HOUR = Decimal(3_600_000_000)

#: ``voyage_scenario`` 컬럼 스케일 — INSERT 전 확정 자릿수.
_DB_SCALE = {
    "distance": Decimal("0.01"),
    "speed": Decimal("0.01"),
    "duration": Decimal("0.01"),
    "fuel": Decimal("0.0001"),
    "weather_factor": Decimal("0.0001"),
    "cii": Decimal("0.00000001"),
}

#: ``voyage_scenario`` 파생 열의 상한 — ``duration_hours NUMERIC(10,2)`` ·
#: ``fuel_ton NUMERIC(12,4)``. 요청 거리의 상한(``DISTANCE`` · ``NUMERIC(12,2)``)보다
#: 좁아, 거리 범위 안에서도 넘칠 수 있다(#2513).
_DB_MAX_DURATION = largest(10, 2)
_DB_MAX_FUEL = largest(12, 4)


@dataclass(frozen=True)
class ScenarioCompareInput:
    """기능② 계산 입력.

    Pydantic 모델을 그대로 서비스에 넘기지 않는다 — 그러면 ``services``가 ``api``
    패키지에 의존하게 되어 TECH_SPEC §16의 계층 방향이 뒤집힌다 (기능① ``VoyageCiiInput``
    와 같은 규칙). ``destination_port_name``은 표기용 필드라 계산에 쓰지 않아 여기
    없다.
    """

    vessel_id: UUID
    regulation_year: int
    current_speed_kn: Decimal
    fuel_type: str
    current_lat: Decimal | None = None
    current_lon: Decimal | None = None
    destination_lat: Decimal | None = None
    destination_lon: Decimal | None = None
    base_daily_foc_ton: Decimal | None = None
    direct_distance_nm: Decimal | None = None
    detour_distance_nm: Decimal | None = None
    slow_speed_kn: Decimal | None = None
    weather_model: str | None = None
    # 우회 경유지 (`#1300` · PRD §11.3). 둘 다 있을 때만 DETOUR 거리를 구간 합으로 낸다.
    detour_waypoint_lat: Decimal | None = None
    detour_waypoint_lon: Decimal | None = None
    # 이 비교가 두고 한 항차 (`#2217` · 선택). 계산 재료가 아니다 — 해시에 넣지 않는다.
    voyage_id: UUID | None = None
    # 선체·추진 상태 보정 % (`#2561` 결정 D2 · 선택). 이번 비교에만 쓰는 덮어쓰기 값이다 —
    # 없으면 선박 제원(``vessel.hull_condition_percent``), 그것도 없으면 0%로 계산한다.
    hull_condition_percent: Decimal | None = None
    # 선석 가용 시각과 그 기준 시각 (`#2561` 결정 D1 · 선택). **둘이 함께**만 유효하다 — 서버
    # 시계로 「지금」을 정하지 않는다(`TECH_SPEC §5.4`). 둘 다 재현성 해시 재료다.
    berth_available_at: datetime | None = None
    berth_reference_at: datetime | None = None
    # 묘박 중 일일 연료(t/일 · `#2561` 결정 D3 · 선택). 이번 비교에만 쓰는 덮어쓰기 값이다 —
    # 없으면 선박 제원(``vessel.anchorage_daily_foc_ton``), 그것도 없으면 대기 연료를 내지 않는다.
    anchorage_daily_foc_ton: Decimal | None = None


@dataclass(frozen=True)
class _Berth:
    """선석 조건 — 선석까지 남은 시간과 묘박 연료 (`#2561`). 선석 시각이 없으면 이 객체도 없다."""

    available_at: datetime
    reference_at: datetime
    hours_until: Decimal
    # ``None``이면 「미입력」이다 — 대기 시간은 내되 대기 연료·대기 포함 CII는 내지 않는다.
    anchorage_daily_foc_ton: Decimal | None
    anchorage_source: str


@dataclass(frozen=True)
class _Waiting:
    """한 시나리오의 선석 대기 (`#2561` 결정 D8 「다」). 주된 칸(항해만)과 따로 싣는다."""

    hours_to_berth: Decimal
    waiting_hours: Decimal
    late_hours: Decimal
    # 묘박 연료가 미입력이고 대기가 있으면 둘 다 ``None``이다. 대기가 없으면 연료 0이고
    # CII는 항해만과 같다.
    waiting_fuel_ton: Decimal | None
    layer1_with_waiting: _Layer1Values | None


@dataclass(frozen=True)
class _ScenarioPlan:
    """PRD §11.2 생성 방식을 적용해 확정된 시나리오 계획 1건."""

    scenario_type: str
    distance_nm: Decimal
    speed_kn: Decimal


@dataclass(frozen=True)
class _ScenarioComputed:
    """한 시나리오의 계획 + 추정 연료 + Layer 1 결과."""

    plan: _ScenarioPlan
    fuel_ton: Decimal
    duration_hours: Decimal
    layer1: _Layer1Values
    # 선석 시각을 넣은 비교에서만 있다 (`#2561`).
    waiting: _Waiting | None = None


@layer1_context
def _compute_scenarios(
    *,
    plans: list[_ScenarioPlan],
    reference_speed_kn: Decimal,
    base_daily_foc_ton: Decimal,
    fuel_code: str,
    cf_value: Decimal,
    transport_capacity: Decimal,
    reference_capacity: Decimal,
    a_decimal: Decimal,
    c: Decimal,
    z_factor_percent: Decimal,
    d_vector: DVector,
    weather_factor: Decimal,
    hull_condition_percent: Decimal | None = None,
    berth: _Berth | None = None,
) -> list[_ScenarioComputed]:
    """시나리오 전체를 **한 Layer 1 컨텍스트 안에서** 계산한다.

    컨텍스트를 시나리오마다 새로 열면 중간값이 기본 컨텍스트(``prec=28``)에서
    다뤄질 여지가 생긴다 — ``voyage_cii._compute_layer1``이 한 함수로 묶은 것과
    같은 이유로 여기도 요청 전체를 묶는다.

    ``berth``가 있으면 시나리오마다 선석 대기를 함께 낸다 (`#2561` 결정 D8 「다」) — 주된 값
    (``fuel_ton``·``layer1``)은 **항해만**이고 대기는 :class:`_Waiting`에 따로 둔다. 채택하면
    항차 계획에 들어가는 값이 주된 값이어야 하기 때문이다(`#1072`).
    """

    def layer1_of(fuel_ton: Decimal, distance_nm: Decimal) -> _Layer1Values:
        return _compute_layer1(
            fuel_uses=[FuelUse(fuel_code=fuel_code, fuel_ton=fuel_ton, cf_value=cf_value)],
            transport_capacity=transport_capacity,
            reference_capacity=reference_capacity,
            distance_nm=distance_nm,
            a_decimal=a_decimal,
            c=c,
            z_factor_percent=z_factor_percent,
            d_vector=d_vector,
        )

    computed: list[_ScenarioComputed] = []
    for plan in plans:
        fuel_ton = estimate_fuel_ton(
            distance_nm=plan.distance_nm,
            speed_kn=plan.speed_kn,
            reference_speed_kn=reference_speed_kn,
            base_daily_foc_ton=base_daily_foc_ton,
            weather_factor=weather_factor,
            hull_condition_percent=hull_condition_percent,
        )
        duration_hours = plan.distance_nm / plan.speed_kn
        layer1 = layer1_of(fuel_ton, plan.distance_nm)
        waiting = None
        if berth is not None:
            waiting = _waiting(
                berth=berth,
                duration_hours=duration_hours,
                fuel_ton=fuel_ton,
                layer1=layer1,
                layer1_with=lambda total, distance=plan.distance_nm: layer1_of(total, distance),
            )
        computed.append(
            _ScenarioComputed(
                plan=plan,
                fuel_ton=fuel_ton,
                duration_hours=duration_hours,
                layer1=layer1,
                waiting=waiting,
            )
        )
    return computed


def _waiting(*, berth: _Berth, duration_hours: Decimal, fuel_ton: Decimal, layer1, layer1_with):
    """한 시나리오의 선석 대기 — Layer 1 컨텍스트 안에서만 부른다(:func:`_compute_scenarios`).

    - 선석보다 **일찍** 닿으면 그 차이만큼 묘박하며 기다린다. 늦게 닿으면 대기는 0이고 늦은
      시간을 따로 싣는다 — 「대기 0」과 「선석을 놓침」은 다른 말이다.
    - 대기 연료 = 묘박 일일 연료 × 대기 시간 ÷ 24. **기상·선체 보정을 곱하지 않는다** — 묘박
      중에는 주기관이 서 있어 그 둘이 닿는 추진 연료가 아니다.
    - 대기 포함 CII는 분자에만 대기 연료를 더한다. 대기 중 이동이 없어 분모(거리)는 그대로다
      (``DB_SCHEMA §2.18`` 각주 — ``MEPC 82/6/31``).
    - 묘박 연료가 미입력이면 대기가 있는 시나리오의 대기 연료·대기 포함 CII는 ``None``이다.
      대기가 0이면 연료도 0이라 미입력이어도 낼 수 있다.
    """
    zero = Decimal(0)
    waiting_hours = max(berth.hours_until - duration_hours, zero)
    late_hours = max(duration_hours - berth.hours_until, zero)
    hours_to_berth = duration_hours + waiting_hours
    if waiting_hours == zero:
        waiting_fuel: Decimal | None = zero
        with_waiting = layer1
    elif berth.anchorage_daily_foc_ton is None:
        waiting_fuel = None
        with_waiting = None
    else:
        waiting_fuel = berth.anchorage_daily_foc_ton * waiting_hours / _HOURS_PER_DAY
        with_waiting = layer1_with(fuel_ton + waiting_fuel)
    return _Waiting(
        hours_to_berth=hours_to_berth,
        waiting_hours=waiting_hours,
        late_hours=late_hours,
        waiting_fuel_ton=waiting_fuel,
        layer1_with_waiting=with_waiting,
    )


async def compare_scenarios(
    session: AsyncSession,
    payload: ScenarioCompareInput,
    *,
    weather_provider=None,
    persist: bool = True,
    commit: bool = True,
) -> dict[str, object]:
    """시나리오를 계산·저장하고 API_SPEC §5.1 응답 dict를 반환한다.

    시나리오는 3개다. 선석 가용 시각이 있으면 도착시각 맞춤 2개가 더해져 최대 5개다
    (`#2561` 결정 D1). 그 속력이 상한(60kn)을 넘는 것은 계산하지 않고
    ``data.unreachable_scenarios``에 싣는다.

    ``meta``는 채우지 않는다 — 라우트가 붙인다(기능①과 같은 계층 규칙).

    ``commit=False``는 **커밋을 호출부에 맡기는 경로**다 (`#1625` · `#1349` 선례) —
    근거는 :func:`~cii_platform.services.voyage_cii.estimate_voyage_cii`의 같은 절에
    있다. 시나리오 3행과 ``calculation_run``은 flush돼 있고, 라우트가 감사 로그를 넣은
    뒤 한 번의 커밋으로 함께 확정한다.

    ``weather_provider``는 **테스트가 갈아 끼우는 자리**다(#62). 기본값이 ``None``인
    이유는 조회가 필요할 때만 어댑터를 만들기 위해서다 — 기상 보정을 쓰지 않는
    요청까지 외부 클라이언트 생성 비용을 지불할 이유가 없다.

    ``persist=False``는 **저장하지 않는 경로**다 (`#1334` ⑷) — 근거는
    :func:`~cii_platform.services.voyage_cii.estimate_voyage_cii`의 같은 절에 있다.
    챗봇 도구가 이 함수도 부른다.

    **``voyage_scenario`` 행도 넣지 않는다** (`#2088`). 종전에는 ``calculation_run``만
    건너뛰고 시나리오 3행은 넣었는데, 챗봇 라우트가 답변 뒤 같은 세션을 커밋하므로
    비교 도구가 불릴 때마다 실행에 묶이지 않은 3행이 그 선박에 남았다 — 채택
    (``POST /scenarios/{id}/adopt``) 대상도 됐다. 저장한 행이 없으므로 이 경로의
    응답 ``scenario_id``는 ``None``이다(챗봇 도구는 그 값을 내보내지 않는다).
    """
    if weather_provider is None and payload.weather_model not in (None, "NONE"):
        from cii_platform.weather.open_meteo import OpenMeteoProvider

        weather_provider = OpenMeteoProvider()
    started = time.perf_counter()

    vessel = await _load_vessel(session, payload.vessel_id)
    attributed_voyage_id = await _resolve_attributed_voyage(session, payload, persist=persist)
    regulation = await _load_regulation_year(session, payload.regulation_year)
    reference_line = await _select_reference_line(session, vessel)
    rating_boundary = await _select_rating_boundary(session, vessel)
    fuel_row = await _load_fuel_type(session, payload.fuel_type)

    transport_capacity = _resolve_transport_capacity(vessel)
    reference_capacity = _resolve_reference_capacity(vessel, reference_line)
    base_daily_foc_ton = _resolve_base_daily_foc(payload, vessel)
    reference_speed_kn = _resolve_reference_speed(vessel)
    hull_condition_percent, hull_condition_source = _resolve_hull_condition(payload, vessel)
    berth = _resolve_berth(payload, vessel)

    direct_distance = _resolve_direct_distance(payload)
    waypoint = _waypoint(payload)
    detour_distance = _resolve_detour_distance(payload, direct_distance, waypoint)
    slow_speed = _resolve_slow_speed(payload)
    weather = await _resolve_weather(session, payload, vessel, weather_provider)
    weather_model_used = weather.model_used
    weather_warnings = list(weather.warnings)

    plans = [
        _ScenarioPlan("DIRECT", direct_distance, payload.current_speed_kn),
        _ScenarioPlan("DETOUR", detour_distance, payload.current_speed_kn),
        _ScenarioPlan("SLOW_STEAMING", direct_distance, slow_speed),
    ]
    plans = [_quantize_plan(plan) for plan in plans]
    # `#2561` 결정 D1 — 거리는 위에서 확정한 직항·우회 거리 그대로다(같은 길을 속력만 바꿔 간다).
    jit_plans, floored, unreachable = _arrival_matched_plans(berth, plans[0], plans[1])
    plans = [*plans, *jit_plans]

    try:
        computed = _compute_scenarios(
            plans=plans,
            reference_speed_kn=reference_speed_kn,
            base_daily_foc_ton=base_daily_foc_ton,
            fuel_code=payload.fuel_type,
            cf_value=Decimal(fuel_row.cf),
            transport_capacity=transport_capacity,
            reference_capacity=reference_capacity,
            a_decimal=Decimal(reference_line.a_decimal),
            c=Decimal(reference_line.c),
            z_factor_percent=Decimal(regulation.z_factor_percent),
            d_vector=DVector(
                d1=Decimal(rating_boundary.d1),
                d2=Decimal(rating_boundary.d2),
                d3=Decimal(rating_boundary.d3),
                d4=Decimal(rating_boundary.d4),
            ),
            weather_factor=weather.factor,
            hull_condition_percent=hull_condition_percent,
            berth=berth,
        )
    except ValueError as exc:
        raise ValidationError(log_calculation_failure("기능② 시나리오", exc)) from exc

    warnings = [
        *_build_warnings(vessel),
        *weather_warnings,
        *_slow_floor_warnings(plans[2]),
        *([WARNING_ARRIVAL_SPEED_FLOOR] if floored else []),
    ]
    parameters_used = _build_parameters_used(
        regulation=regulation,
        reference_line=reference_line,
        rating_boundary=rating_boundary,
        fuel_row=fuel_row,
    )
    input_hash = compute_scenario_input_hash(
        {
            "vessel_id": str(payload.vessel_id),
            "regulation_year": payload.regulation_year,
            "ship_type": vessel.ship_type,
            "transport_capacity": transport_capacity,
            "reference_capacity": reference_capacity,
            "base_daily_foc_ton": base_daily_foc_ton,
            "reference_speed_kn": reference_speed_kn,
            "fuel_type": payload.fuel_type,
            "fuel_cf": Decimal(fuel_row.cf),
            "scenarios": [
                {
                    "scenario_type": p.scenario_type,
                    "distance_nm": p.distance_nm,
                    "speed_kn": p.speed_kn,
                }
                for p in plans
            ],
            "weather_model": payload.weather_model or "NONE",
            # `[ORACLE-S-5]` — 해시 전에 확정돼 있어야 한다. fallback으로 NONE이 된
            # 경우도 그 결과값(1.0)이 들어간다: **보정 여부가 다르면 다른 계산**이라는
            # 것이 `§5.4`가 정한 재현성 단위다.
            "weather_factor": weather.factor,
            # `#1300` — 경유지는 요청 재료이자 해시 재료다(`TECH_SPEC §5.3`). 없으면 키를
            # 넣지 않는다 — `_filter_fields`가 있는 키만 담으므로 종전 해시가 그대로다.
            **_waypoint_hash_material(waypoint),
            **_hull_condition_hash_material(hull_condition_percent),
            **_berth_hash_material(berth),
        }
    )
    parameter_hash = compute_parameter_hash(parameters_used)
    model_version = _model_version()

    # 시나리오 행을 먼저 저장한다 — PK가 컬럼 기본값(`default=uuid.uuid4`)이라 flush를
    # 해야 id를 알 수 있고, 그 id가 응답 시나리오 객체와 result_json 양쪽에
    # 들어간다(§5.2 adopt가 이 id를 참조한다).
    #
    # ``persist=False``면 **넣지 않는다** (`#2088`) — 저장하지 않는 경로가 남기는 행은
    # 실행(``calculation_run``)에 묶이지 않은 채 호출부의 커밋으로 확정된다.
    scenario_ids: list[UUID | None] = []
    db_rows = _db_rows(computed, _distance_sources(payload, waypoint))
    for plan, item, row in zip(plans, computed, db_rows, strict=True):
        if not persist:
            scenario_ids.append(None)
            continue
        scenario = await scenario_repo.insert(
            session,
            vessel_id=payload.vessel_id,
            scenario_type=plan.scenario_type,
            scenario_name=SCENARIO_NAMES[plan.scenario_type],
            distance_nm=row["distance_nm"],
            speed_kn=row["speed_kn"],
            duration_hours=row["duration_hours"],
            fuel_ton=row["fuel_ton"],
            weather_factor=weather.factor,
            weather_snapshot_id=weather.snapshot_id,
            cii_value=item.layer1.attained_cii.quantize(_DB_SCALE["cii"], rounding=ROUND_HALF_UP),
            estimated_rating=item.layer1.rating,
            risk_level=item.layer1.risk_level,
        )
        scenario_ids.append(scenario.id)

    scenarios_json = _serialize_scenarios(
        computed=computed,
        scenario_ids=scenario_ids,
        vessel=vessel,
        reference_line=reference_line,
        regulation=regulation,
        transport_capacity=transport_capacity,
        reference_capacity=reference_capacity,
        weather_model_used=weather_model_used,
        weather_factor=weather.factor,
        floored=floored,
    )
    data = {
        "scenarios": scenarios_json,
        "summary": _build_summary(computed),
        # 도착시각 맞춤 속력이 상한(60kn)을 넘어 **계산하지 않은** 시나리오 (`#2561`). 선석 시각이
        # 없거나 모두 계산했으면 빈 목록이다 — 키는 늘 있다. 「도달 불가」는 숫자가 아니라 이유다.
        "unreachable_scenarios": unreachable,
        # 이 비교가 **붙은** 항차 (`#2217`). 요청이 밝히지 않았거나, 밝혔어도 계획 단계가
        # 아니었거나, 저장하지 않는 경로면 ``None``이다 — 키는 늘 있다. 호출부가 「붙었는가」를
        # 키의 유무가 아니라 값으로 읽게 하려는 것이다.
        "voyage_id": None if attributed_voyage_id is None else str(attributed_voyage_id),
        # 보정에 쓴 기상을 **언제 받았는가** (`#2135` · `PRD §6.3`). 기상 보정을 하지 않은
        # 결과(요청이 NONE · 좌표 없음 · 캐시 없음 · 24시간 초과)는 ``fetched_at``이 ``None``이다 —
        # 키는 늘 있다. 화면이 「보정했는가」를 키의 유무가 아니라 값으로 읽게 하려는 것이다.
        "weather": {"fetched_at": fetched_at_iso(weather.synced_at)},
        # 세 시나리오에 **공통으로** 건 계산 조건 (`#2561`). 화면 머리가 「선체 상태 +20%
        # (선박 제원)」처럼 한 줄로 보인다. 키는 늘 있다 — ``weather``와 같은 이유다.
        "conditions": _conditions_json(hull_condition_percent, hull_condition_source, berth),
    }

    duration_ms = max(1, round((time.perf_counter() - started) * 1000))
    run_id: str | None = None
    if persist:
        run_id = await _persist_scenario_run(
            session,
            commit=commit,
            vessel_id=payload.vessel_id,
            input_hash=input_hash,
            parameter_hash=parameter_hash,
            model_version=model_version,
            # 요청한 기상 모델을 **저장본에만** 더한다 (`#2012`). 요청은 입력 해시 재료일 뿐
            # 어디에도 남지 않아, fallback이 일어나면 「무엇을 요청했나」를 사후에 답할 수
            # 없었다. 응답 ``data``에는 넣지 않는다 — `POST /scenarios/compare` 계약은 그대로다.
            # ``parameters_used``에 넣지 않는 것은 그것이 **파라미터 해시 재료**이기 때문이다.
            result_json={**data, "weather_model_requested": payload.weather_model or "NONE"},
            parameters_used=parameters_used,
            warnings=warnings,
            duration_ms=duration_ms,
            weather_snapshot_id=weather.snapshot_id,
            voyage_id=attributed_voyage_id,
        )

    return {
        "data": data,
        "parameters_used": parameters_used,
        "calculation_run_id": run_id,
        "model_version": model_version,
        "input_hash": input_hash,
        "parameter_hash": parameter_hash,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
        "_duration_ms": duration_ms,
    }


async def _persist_scenario_run(session: AsyncSession, *, commit: bool = True, **fields) -> str:
    """계산 이력 한 행을 남긴다.

    ``weather_snapshot_id``는 시나리오 3행과 **같은 스냅샷**이다 — 한 요청이 한 번
    조회한 기상으로 세 계획을 모두 보정한다. 보정 인자 자체는
    ``result_json.scenarios[].weather_factor``에 있다(``TECH_SPEC §5.4`` 4항 · #904).

    ``commit=False``면 저장소의 flush까지만 — 커밋은 호출부가 감사 로그와 함께 한다
    (`#1625`).
    """
    run = await calc_run_repo.insert_scenario(session, **fields)
    if commit:
        await session.commit()
    return str(run.id)


# --- 조회 + 입력 확정 ----------------------------------------------------------------


async def _resolve_attributed_voyage(
    session: AsyncSession, payload: ScenarioCompareInput, *, persist: bool
) -> UUID | None:
    """이 비교의 계산 이력을 붙일 항차를 정한다 (`#2217`). 붙이지 않으면 ``None``.

    요청이 항차를 밝히면 **이 선박의 살아 있는 항차**인지 먼저 본다 — 없으면 404, 다른
    선박의 항차면 422다(기능①의 ``voyage_id``와 같은 검사 · `#817`).

    붙이는 것은 **계획 단계 항차**(``DRAFT`` · ``PLANNED``)뿐이다. ``PRD §25.2.1``이 리포트에
    싣는 것을 「항차 착수 전 저장된」 비교로 정했기 때문이다 — 떠났거나 끝난 항차를 골라 둔
    채 돌린 비교가 붙으면 리포트가 사후의 비교를 착수 전 근거로 인용한다. 그때 요청을
    거부하지는 않는다: 비교는 선박 단위로 성립하고, 화면은 상단에 고른 항차를 그대로 실어
    보낸다. 붙지 않았다는 것은 응답 ``data.voyage_id``가 ``None``인 것으로 드러난다.

    저장하지 않는 경로(``persist=False``)는 붙일 이력이 없으므로 ``None``이다.
    """
    if payload.voyage_id is None:
        return None
    voyage = await voyage_repo.get_by_id(session, payload.voyage_id)
    if voyage is None or voyage.is_deleted:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {payload.voyage_id}")
    if voyage.vessel_id != payload.vessel_id:
        raise ValidationError(
            "이 선박의 항차가 아닙니다.", field="voyage_id", field_label="대상 항차"
        )
    if not persist or voyage.status not in PLANNING_STATUSES:
        return None
    return voyage.id


async def _load_vessel(session, vessel_id: UUID):
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")
    return vessel


async def _load_regulation_year(session, year: int):
    row = await param_repo.get_regulation_year(session, year)
    if row is None:
        raise regulation_year_missing(year)
    return row


async def _select_reference_line(session, vessel):
    rows = await param_repo.list_reference_lines(session, vessel.ship_type)
    if not rows:
        raise ParameterError(f"선종의 기준선이 없습니다: {vessel.ship_type}")
    try:
        return select_reference_line(vessel, rows)
    except ValueError as exc:
        raise selection_error("기준선", exc) from exc


async def _select_rating_boundary(session, vessel):
    # ⚠️ **선종으로 걸러 조회하지 않는다** (`#834` 실측).
    #
    # :func:`select_rating_boundary`는 HSC 폴백을 갖는다 — `RO_RO_PASSENGER_HSC`는
    # G4 원문에 행이 없고, `PRD §3.4.4` 각주(`#126` · 원문 대조 확인 sky01170851)가
    # **`RO_RO_PASSENGER` 행을 적용한다**로 정했다.
    #
    # 그런데 선종으로 걸러서 주면 **폴백 대상 행이 목록에 없어 폴백이 실행될 기회조차
    # 없다.** 실제로 HSC 선박이 409로 거부됐다. 그 함수의 docstring이 *「걸러지지 않은
    # 전체 목록이어도 된다」*로 적은 이유가 이것이다.
    #
    # 표가 25행이라 거르지 않아도 비용 차이가 없고, 요청 캐시(`#989`)는 선종별로
    # 따로 담던 것을 **한 번만** 담게 된다.
    rows = await param_repo.list_rating_boundaries(session)
    if not rows:
        raise ParameterError("등급 경계 파라미터가 비어 있습니다.")
    try:
        return select_rating_boundary(vessel, rows)
    except ValueError as exc:
        raise selection_error("등급 경계", exc) from exc


async def _load_fuel_type(session, fuel_type: str):
    rows = await param_repo.get_fuel_types_by_codes(session, [fuel_type])
    if fuel_type not in rows:
        raise ValidationError(
            f"알 수 없는 연료 종류입니다: {fuel_type}",
            field="fuel_type",
            field_label="연료 종류",
        )
    return rows[fuel_type]


def _resolve_transport_capacity(vessel) -> Decimal:
    try:
        return resolve_transport_capacity(vessel)
    except ValueError as exc:
        raise spec_error(exc) from exc


def _resolve_reference_capacity(vessel, reference_line) -> Decimal:
    try:
        return resolve_reference_capacity(vessel, reference_line)
    except ValueError as exc:
        raise spec_error(exc) from exc


def _resolve_base_daily_foc(payload, vessel) -> Decimal:
    """PRD §11.4 우선순위 — 요청값 → 선박 기준값 → 계산 불가(422).

    **3단계(「샘플 선박 기본값」)는 여기 없다 — 선박 등록 시점에 실현된다** (#997 ·
    ``PRD §11.4`` 각주). 등록 화면이 샘플을 고르면 그 기준 연료를 선박에 옮기므로 샘플에서
    채워 등록한 선박은 2단계(선박 기준값)로 계산된다. 여기서 샘플 값을 따로 찾으면 사용자가
    일부러 비운 값을 몰래 채우거나 다른 배의 연료로 CII를 만든다.
    """
    value = payload.base_daily_foc_ton
    if value is None:
        value = vessel.reference_daily_foc_ton
    if value is None or Decimal(value) <= 0:
        # 필드명 원문을 문장에 섞지 않는다 — `API_SPEC §1.3.2` 언어 규정(#900 · #997).
        raise ValidationError(
            "기준 일일 연료소모량이 필요합니다. 비교할 때 입력하거나 선박 제원에 등록해 주세요.",
            field="base_daily_foc_ton",
            field_label="기준 일일 연료소모량",
        )
    return Decimal(value)


#: 선체 상태 보정 %의 출처 (`#2561`). 「미입력」과 「0%를 넣음」을 화면이 구분하게 한다 —
#: 계산은 같아도 사용자가 그 배를 「깨끗하다고 확인했다」와 「모른다」는 다른 말이다.
HULL_CONDITION_SOURCE_REQUEST = "REQUEST"
HULL_CONDITION_SOURCE_VESSEL = "VESSEL"
HULL_CONDITION_SOURCE_NOT_SET = "NOT_SET"


def _resolve_hull_condition(payload, vessel) -> tuple[Decimal | None, str]:
    """선체·추진 상태 보정 %와 그 출처 — 요청 → 선박 제원 → 미입력 (`#2561` 결정 D2).

    미입력이면 ``None``을 돌려준다. 계산은 0%와 같다(``estimate_fuel_ton``이 곱하지 않는다).
    """
    if payload.hull_condition_percent is not None:
        return Decimal(payload.hull_condition_percent), HULL_CONDITION_SOURCE_REQUEST
    if vessel.hull_condition_percent is not None:
        return Decimal(vessel.hull_condition_percent), HULL_CONDITION_SOURCE_VESSEL
    return None, HULL_CONDITION_SOURCE_NOT_SET


def _hull_condition_hash_material(percent: Decimal | None) -> dict[str, object]:
    """0이 아닐 때만 해시 재료에 넣는다 — 미입력·0%는 종전과 같은 계산이다(`#2561`)."""
    if not percent:
        return {}
    return {"hull_condition_percent": percent}


def _conditions_json(
    percent: Decimal | None, source: str, berth: _Berth | None = None
) -> dict[str, object]:
    """응답 ``data.conditions`` (`API_SPEC §5.1` · `#2561`). 키는 늘 있다 — 값으로 읽게 한다.

    선석 시각이 없으면 선석 칸 넷은 ``None``이고 묘박 연료 출처는 ``NOT_SET``이다 — 선석이 없으면
    묘박 연료를 쓰지 않으므로 「무엇을 썼는가」의 답이 없다.
    """
    return {
        "hull_condition_percent": None if percent is None else float(percent),
        "hull_condition_source": source,
        "berth_available_at": None if berth is None else _instant_iso(berth.available_at),
        "berth_reference_at": None if berth is None else _instant_iso(berth.reference_at),
        "hours_until_berth": (
            None if berth is None else _publish(berth.hours_until, "duration_hours")
        ),
        "anchorage_daily_foc_ton": (
            None
            if berth is None or berth.anchorage_daily_foc_ton is None
            else float(berth.anchorage_daily_foc_ton)
        ),
        "anchorage_daily_foc_source": (
            HULL_CONDITION_SOURCE_NOT_SET if berth is None else berth.anchorage_source
        ),
    }


def _instant_iso(value: datetime) -> str:
    """시각 → 응답·해시 문자열 (UTC, ``Z`` 접미). 요청 스키마(``Instant``)가 이미 UTC로 맞췄다."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@layer1_context
def _resolve_berth(payload, vessel) -> _Berth | None:
    """선석 조건을 확정한다 (`#2561` 결정 D1·D3). 선석 시각이 없으면 ``None`` — 종전 3장 그대로다.

    - 선석 가용 시각과 기준 시각은 **함께**만 받는다. 한쪽만 오면 빠진 쪽 칸에 422다 — 기준
      시각을 서버 시계로 채우면 같은 요청이 보낸 시각에 따라 다른 결과를 낸다(`TECH_SPEC §5.4`).
    - 선석이 기준 시각보다 뒤가 아니면 422다. 남은 시간이 0 이하이면 맞출 속력이 없다.
    - 묘박 연료는 요청 → 선박 제원 → 미입력 순이다(선체 상태 %와 같은 규율 · 결정 D3).

    남은 시간은 마이크로초까지 정수로 세어 나눈다 — ``total_seconds()``의 float을 거치지 않는다.
    """
    available = payload.berth_available_at
    reference = payload.berth_reference_at
    if available is None and reference is None:
        return None
    if available is None or reference is None:
        missing = "berth_available_at" if available is None else "berth_reference_at"
        raise ValidationError(
            "선석 가용 시각과 기준 시각은 함께 입력해 주세요.",
            field=missing,
            field_label=field_label(missing),
        )
    micros = (available - reference) // timedelta(microseconds=1)
    if micros <= 0:
        raise ValidationError(
            "선석 가용 시각은 기준 시각보다 뒤여야 합니다.",
            field="berth_available_at",
            field_label=field_label("berth_available_at"),
        )
    if payload.anchorage_daily_foc_ton is not None:
        anchorage, source = Decimal(payload.anchorage_daily_foc_ton), HULL_CONDITION_SOURCE_REQUEST
    elif vessel.anchorage_daily_foc_ton is not None:
        anchorage, source = Decimal(vessel.anchorage_daily_foc_ton), HULL_CONDITION_SOURCE_VESSEL
    else:
        anchorage, source = None, HULL_CONDITION_SOURCE_NOT_SET
    return _Berth(
        available_at=available,
        reference_at=reference,
        hours_until=Decimal(micros) / _MICROS_PER_HOUR,
        anchorage_daily_foc_ton=anchorage,
        anchorage_source=source,
    )


@layer1_context
def _arrival_matched_plans(
    berth: _Berth | None, direct: _ScenarioPlan, detour: _ScenarioPlan
) -> tuple[list[_ScenarioPlan], set[str], list[dict[str, object]]]:
    """도착시각 맞춤 계획 — (계산할 계획, 1.0kn로 올린 종류, 도달 불가 목록) (`#2561` 결정 D1).

    속력 = 거리 ÷ 선석까지 남은 시간. 저장 자릿수(0.01kn)로 **올린다** — 반올림으로 내려가면
    선석 시각보다 늦게 닿아 「맞춤」이 아니게 된다. 올린 만큼 몇 분 일찍 닿아 대기가 조금 남을
    수 있다.

    - 1.0kn 아래면 1.0kn로 계산하고 경고한다(VAL-009 하한 · ``ARRIVAL_SPEED_FLOOR``). 선석이 아주
      멀면 생기고, 그 시나리오는 일찍 닿아 대기가 남는다.
    - 상한(60kn)을 넘으면 **계산하지 않는다** — 그 속력의 연료 추정은 모델 밖이다. 필요 속력만
      싣고 화면이 「도달 불가」로 보인다.
    """
    if berth is None:
        return [], set(), []
    plans: list[_ScenarioPlan] = []
    floored: set[str] = set()
    unreachable: list[dict[str, object]] = []
    for scenario_type, route in (("DIRECT_JIT", direct), ("DETOUR_JIT", detour)):
        required = route.distance_nm / berth.hours_until
        speed = required.quantize(_DB_SCALE["speed"], rounding=ROUND_CEILING)
        if speed > _ARRIVAL_SPEED_MAX:
            unreachable.append(
                {
                    "scenario_type": scenario_type,
                    "scenario_name": SCENARIO_NAMES[scenario_type],
                    "distance_nm": float(route.distance_nm),
                    # 속력 에코와 같은 JSON 숫자다. 올린 값이다 — 이보다 느리면 닿지 못한다.
                    "required_speed_kn": float(speed),
                }
            )
            continue
        if speed < MIN_SPEED_KN:
            speed = MIN_SPEED_KN
            floored.add(scenario_type)
        plans.append(_ScenarioPlan(scenario_type, route.distance_nm, speed))
    return plans, floored, unreachable


def _berth_hash_material(berth: _Berth | None) -> dict[str, object]:
    """해시 재료 조각 — 선석 시각이 있을 때만 ``berth`` 키를 낸다 (`#2561`).

    없으면 키를 넣지 않는다 — 경유지(`#1300`)와 같은 방식이라 종전 요청의 해시가 그대로다.
    두 시각을 **둘 다** 담는다: 남은 시간이 같아도 기준이 다른 요청은 다른 시점의 질문이다.
    도착시각 맞춤 계획의 속력은 ``scenarios``에 이미 있지만, 대기 연료가 쓰는 묘박 연료는
    거기 없으므로 여기 담는다(미입력이면 키 없음).
    """
    if berth is None:
        return {}
    material: dict[str, object] = {
        "available_at": _instant_iso(berth.available_at),
        "reference_at": _instant_iso(berth.reference_at),
    }
    if berth.anchorage_daily_foc_ton is not None:
        material["anchorage_daily_foc_ton"] = berth.anchorage_daily_foc_ton
    return {"berth": material}


def _resolve_reference_speed(vessel) -> Decimal:
    """cubic speed model의 분모 — PRD §11.4.1은 ``vessel.reference_speed_kn``만 본다."""
    value = vessel.reference_speed_kn
    if value is None or Decimal(value) <= 0:
        raise ValidationError(
            "선박에 기준속도가 등록되어 있지 않아 연료를 추정할 수 없습니다. "
            "선박 제원에 기준속도를 입력해 주세요.",
            field="vessel_id",
            field_label="선박",
        )
    return Decimal(value)


def _resolve_direct_distance(payload) -> Decimal:
    """PRD §11.2 DIRECT — 사용자 입력 거리가 우선, 없으면 좌표 대권거리."""
    if payload.direct_distance_nm is not None:
        return payload.direct_distance_nm
    coords = (
        payload.current_lat,
        payload.current_lon,
        payload.destination_lat,
        payload.destination_lon,
    )
    if all(v is not None for v in coords):
        distance = great_circle_distance_nm(*coords)
        if distance <= 0:
            # 좌표에서 구한 거리다 — 고칠 곳은 「직항 거리」 칸이 아니라 좌표다 (#2476 결정 10 다).
            raise ValidationError(
                "출발지와 목적지가 같은 위치입니다. 현재 위치나 목적지 좌표를 확인해 주세요.",
                field="current_lat",
                field_label=field_label("current_lat"),
            )
        return distance
    raise ValidationError(
        "직항 거리가 필요합니다. 직항 거리를 입력하거나 현재 위치와 목적지 좌표를"
        " 모두 입력해 주세요.",
        field="direct_distance_nm",
        field_label="직항 거리",
    )


@layer1_context
def _resolve_detour_distance(
    payload, direct_distance: Decimal, waypoint: tuple[Decimal, Decimal] | None
) -> Decimal:
    """PRD §11.2 DETOUR — 입력 거리 > 경유지 구간 합 > ``직항 × 1.05`` 순 (`#1300`).

    경유지가 있으면 「현재 위치 → 경유지 → 목적항」 **대권거리의 합**이다(`PRD §15.2`의
    다중 구간 합산 · `TECH_SPEC §6.3`). 해상 경로망의 길이가 아니다 — 지도의 선은 표시이고
    계산 거리의 출처는 바뀌지 않는다(재현성 계약 `§5.4`).

    **경유지의 검증은 우회 거리 입력과 무관하게 먼저 한다**(`API_SPEC §5.1`). 좌표 넷이
    없으면 어디서 어디로 도는지 알 수 없고, 경유지가 현재 위치나 목적항과 같으면 도는 것이
    아니다 — 우회 거리를 직접 넣었어도 그 경유지는 지도에 그려지므로 같은 규칙을 받는다.

    곱과 합을 **적용 지점 안에서** 낸다 (`#2254` · `TECH_SPEC §1.2.1`) — 부르는 쪽
    (:func:`compare_scenarios`)이 코루틴이라 거기서는 컨텍스트가 걸려 있지 않다.
    """
    if waypoint is not None:
        _check_waypoint_legs(payload, waypoint)
    if payload.detour_distance_nm is not None:
        return payload.detour_distance_nm
    if waypoint is None:
        return direct_distance * DETOUR_DISTANCE_RATIO
    first, second = _waypoint_legs(payload, waypoint)
    return first + second


def _waypoint_legs(payload, waypoint: tuple[Decimal, Decimal]) -> tuple[Decimal, Decimal]:
    """두 구간의 대권거리 — (현재 위치 → 경유지, 경유지 → 목적항). 좌표 넷이 있을 때만 부른다."""
    lat, lon = waypoint
    return (
        great_circle_distance_nm(payload.current_lat, payload.current_lon, lat, lon),
        great_circle_distance_nm(lat, lon, payload.destination_lat, payload.destination_lon),
    )


def _check_waypoint_legs(payload, waypoint: tuple[Decimal, Decimal]) -> None:
    """경유지가 쓸 수 있는 자리인가 — 좌표 넷이 있고, 어느 끝과도 같은 점이 아니다.

    **어느 쪽과 같은지를 문구가 말한다** — 「출발지·목적지와 같다」로 뭉뚱그리면 사용자가
    두 칸 중 어느 것을 고칠지 모른다.
    """
    corners = (
        payload.current_lat,
        payload.current_lon,
        payload.destination_lat,
        payload.destination_lon,
    )
    if any(value is None for value in corners):
        raise ValidationError(
            "우회 경유지를 쓰려면 현재 위치와 목적항 좌표가 모두 필요합니다.",
            field="detour_waypoint_lat",
            field_label="우회 경유지",
        )
    first, second = _waypoint_legs(payload, waypoint)
    if first <= 0 and second <= 0:
        message = "우회 경유지가 현재 위치·목적항과 모두 같은 위치입니다. 경유지를 확인해 주세요."
    elif first <= 0:
        message = "우회 경유지가 현재 위치와 같은 위치입니다. 경유지를 확인해 주세요."
    elif second <= 0:
        message = "우회 경유지가 목적항과 같은 위치입니다. 경유지를 확인해 주세요."
    else:
        return
    raise ValidationError(message, field="detour_waypoint_lat", field_label="우회 경유지")


def _waypoint(payload) -> tuple[Decimal, Decimal] | None:
    """경유지 좌표 쌍. **한쪽만 있으면 422** — 반쪽 좌표는 위치가 아니다. 요청당 한 번 부른다."""
    lat = payload.detour_waypoint_lat
    lon = payload.detour_waypoint_lon
    if lat is None and lon is None:
        return None
    if lat is None or lon is None:
        raise ValidationError(
            "우회 경유지의 위도와 경도는 함께 입력해 주세요.",
            field="detour_waypoint_lat" if lat is None else "detour_waypoint_lon",
            field_label="우회 경유지",
        )
    return lat, lon


def _waypoint_hash_material(waypoint: tuple[Decimal, Decimal] | None) -> dict[str, object]:
    """해시 재료 조각 — 경유지가 있을 때만 ``detour_waypoint`` 키를 낸다."""
    if waypoint is None:
        return {}
    return {"detour_waypoint": {"lat": waypoint[0], "lon": waypoint[1]}}


def _resolve_slow_speed(payload) -> Decimal:
    """PRD §11.2 — 기본 ``max(current − 1, 1.0)``. VAL-009 floor는 1.0kn."""
    if payload.slow_speed_kn is not None:
        return payload.slow_speed_kn
    return max(payload.current_speed_kn - SLOW_STEAMING_SPEED_DELTA, MIN_SPEED_KN)


async def _resolve_weather(
    session: AsyncSession,
    payload: ScenarioCompareInput,
    vessel,
    provider,
) -> WeatherResolution:
    """기상 보정을 확정한다 (`PRD §11.6` fallback 체인, #62).

    **좌표가 없으면 조회하지 않는다.** `API_SPEC §5.1`이 `current_lat`·`current_lon`을
    선택으로 두고 있어(스키마 주석 참조) 위치 없는 요청이 정상적으로 들어온다 —
    어느 바다인지 모르는 채 기상을 물을 수는 없다.

    요청이 ``NONE``(또는 생략)이면 fallback이 아니다: 경고 없이 정상 NONE 계산이다.
    """
    return await resolve_with_fallback(
        session,
        weather_model=payload.weather_model,
        lat=payload.current_lat,
        lon=payload.current_lon,
        ship_type=vessel.ship_type,
        # #966 — CB는 선박 제원이다. 없으면 선종 기본값 + CB_ESTIMATED가 계약.
        block_coefficient=vessel.block_coefficient,
        provider=provider,
        course_deg=_course_deg(payload),
    )


def _course_deg(payload) -> float | None:
    """현재 위치 → 목적항의 **초기 방위각**. 넷 중 하나라도 없으면 ``None`` (`#766` ⑴).

    이 값이 기상 보정의 입사각이 된다 — 파향(스냅샷)과의 상대각이 `TECH_SPEC §3.3.1`의
    β다. 목적항 좌표는 `#1005`가 화면에 붙였고 `API_SPEC §5.1`이 이미 받고 있었다.

    ``None``이면 종전대로 head sea(β=0)로 계산한다 — **없는 값을 지어내지 않는다.**
    """
    corners = (
        payload.current_lat,
        payload.current_lon,
        payload.destination_lat,
        payload.destination_lon,
    )
    if any(value is None for value in corners):
        return None
    return initial_bearing_deg(*corners)


def _slow_floor_warnings(slow_plan: _ScenarioPlan) -> list[str]:
    """PRD §11.2 — 감속 속도가 floor(1.0kn)에 도달하면 경고를 표시한다."""
    if slow_plan.speed_kn == MIN_SPEED_KN:
        return [WARNING_SLOW_SPEED_FLOOR]
    return []


def _quantize_plan(plan: _ScenarioPlan) -> _ScenarioPlan:
    """시나리오 계획을 ``voyage_scenario`` 컬럼 스케일로 확정한다.

    확정된 계획으로 계산·해싱·저장·응답을 모두 해야 같은 요청에 같은 결과가
    나온다 — 반올림 전 값으로 계산하고 저장할 때만 반올림하면 응답과 DB가 어긋난다.
    """
    return _ScenarioPlan(
        scenario_type=plan.scenario_type,
        distance_nm=plan.distance_nm.quantize(_DB_SCALE["distance"], rounding=ROUND_HALF_UP),
        speed_kn=plan.speed_kn.quantize(_DB_SCALE["speed"], rounding=ROUND_HALF_UP),
    )


# --- 직렬화 --------------------------------------------------------------------------


def _distance_sources(payload, waypoint: tuple[Decimal, Decimal] | None) -> dict[str, str]:
    """시나리오마다 거리가 **어디서 왔는가** — 너무 짧을 때 고칠 칸을 고르는 데 쓴다 (#2476).

    직항은 입력 또는 좌표, 감속은 직항과 같은 거리, 우회는 입력 · 경유지 좌표 구간 합 ·
    직항 × 1.05 중 하나다(:func:`_resolve_detour_distance`와 같은 순서).
    """
    direct = "DIRECT_INPUT" if payload.direct_distance_nm is not None else "COORDINATES"
    if payload.detour_distance_nm is not None:
        detour = "DETOUR_INPUT"
    elif waypoint is not None:
        detour = "WAYPOINT"
    else:
        detour = direct
    # 도착시각 맞춤(`#2561`)은 제 길(직항·우회)의 거리를 그대로 쓴다.
    return {
        "DIRECT": direct,
        "DETOUR": detour,
        "SLOW_STEAMING": direct,
        "DIRECT_JIT": direct,
        "DETOUR_JIT": detour,
    }


def _too_short(source: str) -> ValidationError:
    """소요시간이 저장 자릿수(0.01시간) 밑인 시나리오 — **거리의 출처**에 맞춰 칸과 문구를 고른다.

    종전에는 출처와 무관하게 「거리를 늘리거나 속력을 낮춰 주세요」를 「직항 거리」 칸에 붙였다.
    좌표로 거리를 구한 경우 그 칸은 비어 있어, 사용자가 고칠 곳이 없는 칸에 오류가 섰다
    (#2476 결정 10 다 · 두 좌표가 0.01~0.06 nm쯤 떨어진 경우 · 14 kn 기준). 판정 기준은 그대로다.
    """
    if source == "COORDINATES":
        return ValidationError(
            "출발지와 목적지가 너무 가까워 비교할 수 없습니다. "
            "현재 위치나 목적지 좌표를 확인해 주세요.",
            field="current_lat",
            field_label=field_label("current_lat"),
        )
    if source == "WAYPOINT":
        # 경유지 오류는 다른 경유지 검증(:func:`_check_waypoint_legs`)과 같은 칸 · 같은 라벨이다.
        return ValidationError(
            "우회 경유지가 현재 위치·목적항과 너무 가까워 비교할 수 없습니다. "
            "경유지 좌표를 확인해 주세요.",
            field="detour_waypoint_lat",
            field_label="우회 경유지",
        )
    if source == "DETOUR_INPUT":
        return ValidationError(
            "우회 항로의 소요시간이 0.01시간 미만이라 시나리오를 저장할 수 없습니다. "
            "우회 거리를 늘리거나 속력을 낮춰 주세요.",
            field="detour_distance_nm",
            field_label=field_label("detour_distance_nm"),
        )
    return ValidationError(
        "항차 소요시간이 0.01시간 미만이라 시나리오를 저장할 수 없습니다. "
        "거리를 늘리거나 속력을 낮춰 주세요.",
        field="direct_distance_nm",
        field_label="직항 거리",
    )


def _db_rows(
    computed: list[_ScenarioComputed], sources: dict[str, str] | None = None
) -> list[dict[str, Decimal]]:
    """``voyage_scenario`` INSERT용 확정값 — 컬럼 스케일로 반올림한다.

    응답(``_serialize_scenarios``)과 같은 확정 원본에서 만들어야 자릿수가 어긋나지
    않는다. ``cii_value``는 [M-8] denormalized 캐시로 컬럼 스케일(15,8)이다.

    ``sources``는 :func:`_distance_sources` — 소요시간이 너무 짧을 때 고칠 칸을 고른다.
    없으면 종전처럼 직항 거리 입력으로 본다.
    """
    rows = [
        {
            "distance_nm": item.plan.distance_nm,
            "speed_kn": item.plan.speed_kn,
            "duration_hours": item.duration_hours.quantize(
                _DB_SCALE["duration"], rounding=ROUND_HALF_UP
            ),
            "fuel_ton": item.fuel_ton.quantize(_DB_SCALE["fuel"], rounding=ROUND_HALF_UP),
        }
        for item in computed
    ]
    # 1 nm를 250 kn으로 가면 0.004 h → 컬럼 스케일(0.01)로 0.00 → `chk_scenario_duration_positive`
    # 위반으로 500이었다 (#1086 ④). 저장할 수 없는 결과는 계산 단계에서 422로 끝낸다.
    for item, row in zip(computed, rows, strict=True):
        if row["duration_hours"] <= 0 or row["fuel_ton"] <= 0:
            source = sources.get(item.plan.scenario_type, "DIRECT_INPUT") if sources else None
            raise _too_short(source or "DIRECT_INPUT")
        # 반대쪽 끝(#2513) — 거리가 아주 길면 소요시간·연료가 열 상한을 넘어 INSERT가
        # 500이었다. 하한과 같이 저장 전에 422로 끝낸다.
        if row["duration_hours"] > _DB_MAX_DURATION or row["fuel_ton"] > _DB_MAX_FUEL:
            raise ValidationError(
                "항차 소요시간이나 연료가 저장할 수 있는 범위를 넘어 시나리오를 저장할 수 "
                "없습니다. 거리를 줄여 주세요.",
                field="direct_distance_nm",
                field_label="직항 거리",
            )
    return rows


def _serialize_scenarios(
    *,
    computed: list[_ScenarioComputed],
    scenario_ids: list[UUID | None],
    vessel,
    reference_line,
    regulation,
    transport_capacity: Decimal,
    reference_capacity: Decimal,
    weather_model_used: str,
    weather_factor: Decimal,
    floored: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, object]]:
    """API_SPEC §5.1 ``scenarios[]`` 블록. ``scenario_ids``는 저장된 행의 PK다.

    저장하지 않는 경로(``persist=False``)에서는 ``None``이다 — 가리킬 행이 없다 (`#2088`).

    ``warnings``는 **그 시나리오에 붙는 경고**다 (`#2561` 결정요청 §12 「경고의 시나리오 귀속」).
    카드가 5장이 되면 화면 전체의 한 목록으로는 어느 카드의 얘기인지 모른다. 응답 최상위
    ``warnings``는 그대로 전부를 싣는다 — 이쪽은 귀속만 더한 것이다.
    """
    calculation_basis = {
        "ship_type": vessel.ship_type,
        "transport_capacity": _plain(transport_capacity),
        "transport_capacity_basis": capacity_axis(vessel.ship_type),
        "reference_capacity": _plain(reference_capacity),
        # enum이 아니다 — 파라미터 테이블 값 그대로.
        "reference_capacity_rule": reference_line.capacity_rule,
        "z_factor_percent": _percent(Decimal(regulation.z_factor_percent)),
        "a_decimal": _plain(Decimal(reference_line.a_decimal)),
        "c": _plain(Decimal(reference_line.c)),
    }

    json_list: list[dict[str, object]] = []
    for scenario_id, item in zip(scenario_ids, computed, strict=True):
        layer1 = item.layer1
        json_list.append(
            {
                # §5.2 adopt가 참조하는 id다.
                "scenario_id": None if scenario_id is None else str(scenario_id),
                "scenario_type": item.plan.scenario_type,
                "scenario_name": SCENARIO_NAMES[item.plan.scenario_type],
                # 입력 에코는 숫자다 (API_SPEC §5.1 응답 예시).
                "distance_nm": float(item.plan.distance_nm),
                "speed_kn": float(item.plan.speed_kn),
                "duration_hours": _publish(item.duration_hours, "duration_hours"),
                "fuel_ton": _publish(item.fuel_ton, "fuel_ton"),
                "co2_emission_ton": _publish(layer1.total_co2_t, "co2_ton"),
                "attained_cii": _publish(layer1.attained_cii, "attained_cii"),
                "required_cii": _publish(layer1.required_cii, "required_cii"),
                "ratio_to_required": _publish(layer1.ratio_to_required, "ratio_to_required"),
                "estimated_rating": layer1.rating,
                # 등급 E는 악화 방향 경계가 없어 null이다 (#171 결론).
                "next_worse_boundary_margin": (
                    None if layer1.margin is None else _publish(layer1.margin, "margin")
                ),
                "next_worse_boundary_margin_ratio": (
                    None
                    if layer1.margin_ratio is None
                    else _publish(layer1.margin_ratio, "margin_ratio")
                ),
                "risk_level": layer1.risk_level,
                "weather_factor": float(weather_factor),
                "weather_model_used": weather_model_used,
                "calculation_basis": dict(calculation_basis),
                "warnings": _scenario_warnings(item.plan, floored),
                # 선석 대기 (`#2561` 결정 D8 「다」). 선석 시각이 없으면 ``None`` — 키는 늘 있다.
                "berth": _waiting_json(item.waiting),
            }
        )
    return json_list


def _scenario_warnings(plan: _ScenarioPlan, floored: set[str] | frozenset[str]) -> list[str]:
    """그 시나리오에 붙는 경고 코드 — 최상위 ``warnings``와 같은 판정이다."""
    if plan.scenario_type == "SLOW_STEAMING":
        return _slow_floor_warnings(plan)
    if plan.scenario_type in floored:
        return [WARNING_ARRIVAL_SPEED_FLOOR]
    return []


def _waiting_json(waiting: _Waiting | None) -> dict[str, object] | None:
    """``scenarios[].berth`` — 대기 연료·대기 포함 CII를 못 내면 ``None``이다(묘박 연료 미입력)."""
    if waiting is None:
        return None
    with_waiting = waiting.layer1_with_waiting
    return {
        # 접안까지 = 항해 + 대기. 늦게 닿으면 항해 시간이다.
        "hours_to_berth": _publish(waiting.hours_to_berth, "duration_hours"),
        "waiting_hours": _publish(waiting.waiting_hours, "duration_hours"),
        "late_hours": _publish(waiting.late_hours, "duration_hours"),
        "waiting_fuel_ton": (
            None
            if waiting.waiting_fuel_ton is None
            else _publish(waiting.waiting_fuel_ton, "fuel_ton")
        ),
        "attained_cii_with_waiting": (
            None if with_waiting is None else _publish(with_waiting.attained_cii, "attained_cii")
        ),
        "estimated_rating_with_waiting": None if with_waiting is None else with_waiting.rating,
    }


def _build_summary(computed: list[_ScenarioComputed]) -> dict[str, list[str]]:
    """지표별 최소값만 중립적으로 표시한다 (``PRD §11.2``, AC-F2-005).

    ## 동률이면 **전부** 싣는다 (#799)

    종전에는 ``min``이 먼저 등장한 시나리오 하나를 골랐다. **같은 값 중 하나만
    지목하는 것은 그 자체가 추천**이고, 같은 절의 「추천 시나리오를 표시하지
    않는다」에 어긋난다 — 사용자는 두 시나리오의 CII가 화면에 같게 찍혀 있는데
    한쪽만 「가장 낮은」으로 불리는 것을 보고 그쪽이 낫다고 읽는다.

    **동률은 드문 일이 아니라 정의상 필연인 경우가 있다.** ``PRD §11.4.1`` cubic
    speed model에서 연료는 거리에 비례하고 AER은 거리로 나누므로, 같은 속도의
    직항과 우회는 ``attained_cii``가 **정확히 같다**. 자릿수를 늘려도 차이가 0이다.

    순서는 ``computed``의 순서(``PRD §11.2`` 표 순서 — DIRECT · DETOUR ·
    SLOW_STEAMING)를 따르므로 결정론적이다.
    """

    def lowest(key, field: str) -> list[str]:
        # **응답에 실리는 자릿수로 비교한다** (#799). 내부 ``Decimal``은 `prec=30`
        # 이라, 거리가 분자·분모에서 소거되는 직항·우회도 끝자리가 미세하게 갈린다 —
        # 그대로 비교하면 **화면에 같은 값이 찍혀 있는데 동률이 아니라고 판정**한다.
        # 사용자가 보는 것과 판정이 어긋나면 안 된다는 원칙은 `#739`·`#820`이 세웠다.
        # 문자열이 아니라 **숫자로** 비교한다. ``_publish``가 낸 문자열을 그대로
        # ``min``에 넣으면 사전순이 되어 `'154.61'` < `'99.00'`처럼 자릿수가 다를 때
        # 뒤집힌다 — 기존 계약 테스트가 이 실수를 잡았다.
        published = [
            (item.plan.scenario_type, Decimal(_publish(key(item), field))) for item in computed
        ]
        best = min(value for _, value in published)
        return [scenario for scenario, value in published if value == best]

    def duration(item: _ScenarioComputed) -> Decimal:
        # 선석 시각이 있으면 **접안까지** 시간으로 견준다 (`#2561` 결정 D8). 항해 시간으로 견주면
        # 선석보다 먼저 닿아 기다리는 직항이 「가장 짧음」을 받는다 — 그 전에는 접안할 수 없다.
        return item.duration_hours if item.waiting is None else item.waiting.hours_to_berth

    return {
        "lowest_cii_scenarios": lowest(lambda item: item.layer1.attained_cii, "attained_cii"),
        "shortest_duration_scenarios": lowest(duration, "duration_hours"),
        "lowest_fuel_scenarios": lowest(lambda item: item.fuel_ton, "fuel_ton"),
    }


def _build_parameters_used(
    *, regulation, reference_line, rating_boundary, fuel_row
) -> dict[str, object]:
    """§5.1 ``parameters_used`` — 기능①과 같은 스키마(TECH_SPEC §5.2.1).

    기능②는 단일 연료만 받으므로 ``fuel_types``는 1행이다.
    """
    return {
        "regulation_year": {
            "year": str(regulation.year),
            "z_factor_percent": _percent(Decimal(regulation.z_factor_percent)),
        },
        "fuel_types": [{"code": fuel_row.code, "cf": _plain(Decimal(fuel_row.cf))}],
        "reference_line": {
            "ship_type": reference_line.ship_type,
            "reference_capacity_rule": reference_line.capacity_rule,
            "a_decimal": _plain(Decimal(reference_line.a_decimal)),
            "c": _plain(Decimal(reference_line.c)),
        },
        "rating_boundary": {
            "d1": _plain(Decimal(rating_boundary.d1)),
            "d2": _plain(Decimal(rating_boundary.d2)),
            "d3": _plain(Decimal(rating_boundary.d3)),
            "d4": _plain(Decimal(rating_boundary.d4)),
        },
        "parameter_source_version": reference_line.source_ref,
    }
