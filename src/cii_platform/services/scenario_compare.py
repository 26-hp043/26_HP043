"""기능② 시나리오 비교 서비스 (#57).

``api/routes``와 ``calc``/``db`` 사이에서 계산 흐름을 조합한다 (TECH_SPEC §16).
기능①(``services.voyage_cii``)이 이미 세운 규칙 — Layer 1 컨텍스트, 직렬화 자릿수,
``parameters_used`` 스키마, warning 규칙 — 을 그대로 재사용한다. 같은 규칙을
다시 쓰면 어느 쪽이 정본인지 알 수 없게 된다.

처리 흐름
---------

1. 선박·규정연도·기준선·등급 경계·연료 조회 (기능①과 같은 규칙)
2. DIRECT 거리 확정 — ``direct_distance_nm`` 또는 좌표 대권거리 (PRD §11.2)
3. 시나리오 계획 3건 확정 — DIRECT · DETOUR(기본 direct × 1.05) ·
   SLOW_STEAMING(기본 ``max(current − 1, 1.0)``)
4. 시나리오별 연료 추정 — cubic speed model (``calc.fuel_estimator``, #75)
5. 시나리오별 Layer 1 계산 — ``voyage_cii._compute_layer1`` 재사용
6. ``voyage_scenario`` 3행 + ``calculation_run`` 1건(SCENARIO) 저장
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.capacity import (
    capacity_axis,
    resolve_reference_capacity,
    resolve_transport_capacity,
    select_reference_line,
)
from cii_platform.calc.cii_engine import FuelUse
from cii_platform.calc.distance import great_circle_distance_nm
from cii_platform.calc.fuel_estimator import estimate_fuel_ton
from cii_platform.calc.hash import (
    compute_parameter_hash,
    compute_scenario_input_hash,
)
from cii_platform.calc.precision import layer1_context
from cii_platform.calc.rating_engine import DVector, select_rating_boundary
from cii_platform.db.repositories import calculation_run as calc_run_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage_scenario as scenario_repo
from cii_platform.errors import NotFoundError, ParameterError, ValidationError
from cii_platform.services.voyage_cii import (
    DISCLAIMER,
    SERIALIZATION_DIGITS,
    _build_warnings,
    _compute_layer1,
    _Layer1Values,
    _model_version,
    _percent,
    _plain,
    _publish,
)
from cii_platform.services.weather import WeatherResolution, resolve_with_fallback

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: API_SPEC §5.1 예시의 ``scenario_name`` 원문. 프론트엔드 ``SCENARIO_NAME``과 같은 값이다.
SCENARIO_NAMES: dict[str, str] = {
    "DIRECT": "직항",
    "DETOUR": "우회",
    "SLOW_STEAMING": "감속",
}

#: PRD §11.2 — DETOUR 기본 우회 거리 비율.
DETOUR_DISTANCE_RATIO = Decimal("1.05")

#: PRD §11.2 — SLOW_STEAMING 기본 감속량(1 knot).
SLOW_STEAMING_SPEED_DELTA = Decimal("1.0")

#: PRD §9.1 VAL-009 — 최소 속도.
MIN_SPEED_KN = Decimal("1.0")

#: API_SPEC §1.6 — 감속 시나리오가 속도 floor(1.0kn)에 도달했을 때.
WARNING_SLOW_SPEED_FLOOR = "SLOW_SPEED_FLOOR"

#: API_SPEC §1.6 — 기상 모델 요청이 적용되지 않고 NONE으로 계산했을 때.
WARNING_WEATHER_NONE_FALLBACK = "WEATHER_NONE_FALLBACK"

#: ``voyage_scenario`` 컬럼 스케일 — INSERT 전 확정 자릿수.
_DB_SCALE = {
    "distance": Decimal("0.01"),
    "speed": Decimal("0.01"),
    "duration": Decimal("0.01"),
    "fuel": Decimal("0.0001"),
    "weather_factor": Decimal("0.0001"),
    "cii": Decimal("0.00000001"),
}

#: 응답의 ``duration_hours`` 자릿수 — 프론트엔드 ``serializeHours``(toFixed(4))와 같다.
_DURATION_DIGITS = 4


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
) -> list[_ScenarioComputed]:
    """시나리오 3건 전체를 **한 Layer 1 컨텍스트 안에서** 계산한다.

    컨텍스트를 시나리오마다 새로 열면 중간값이 기본 컨텍스트(``prec=28``)에서
    다뤄질 여지가 생긴다 — ``voyage_cii._compute_layer1``이 한 함수로 묶은 것과
    같은 이유로 여기도 요청 전체를 묶는다.
    """
    computed: list[_ScenarioComputed] = []
    for plan in plans:
        fuel_ton = estimate_fuel_ton(
            distance_nm=plan.distance_nm,
            speed_kn=plan.speed_kn,
            reference_speed_kn=reference_speed_kn,
            base_daily_foc_ton=base_daily_foc_ton,
            weather_factor=weather_factor,
        )
        duration_hours = plan.distance_nm / plan.speed_kn
        layer1 = _compute_layer1(
            fuel_uses=[FuelUse(fuel_code=fuel_code, fuel_ton=fuel_ton, cf_value=cf_value)],
            transport_capacity=transport_capacity,
            reference_capacity=reference_capacity,
            distance_nm=plan.distance_nm,
            a_decimal=a_decimal,
            c=c,
            z_factor_percent=z_factor_percent,
            d_vector=d_vector,
        )
        computed.append(
            _ScenarioComputed(
                plan=plan,
                fuel_ton=fuel_ton,
                duration_hours=duration_hours,
                layer1=layer1,
            )
        )
    return computed


async def compare_scenarios(
    session: AsyncSession,
    payload: ScenarioCompareInput,
    *,
    weather_provider=None,
) -> dict[str, object]:
    """3개 시나리오를 계산·저장하고 API_SPEC §5.1 응답 dict를 반환한다.

    ``meta``는 채우지 않는다 — 라우트가 붙인다(기능①과 같은 계층 규칙).

    ``weather_provider``는 **테스트가 갈아 끼우는 자리**다(#62). 기본값이 ``None``인
    이유는 조회가 필요할 때만 어댑터를 만들기 위해서다 — 기상 보정을 쓰지 않는
    요청까지 외부 클라이언트 생성 비용을 지불할 이유가 없다.
    """
    if weather_provider is None and payload.weather_model not in (None, "NONE"):
        from cii_platform.weather.open_meteo import OpenMeteoProvider

        weather_provider = OpenMeteoProvider()
    started = time.perf_counter()

    vessel = await _load_vessel(session, payload.vessel_id)
    regulation = await _load_regulation_year(session, payload.regulation_year)
    reference_line = await _select_reference_line(session, vessel)
    rating_boundary = await _select_rating_boundary(session, vessel)
    fuel_row = await _load_fuel_type(session, payload.fuel_type)

    transport_capacity = _resolve_transport_capacity(vessel)
    reference_capacity = _resolve_reference_capacity(vessel, reference_line)
    base_daily_foc_ton = _resolve_base_daily_foc(payload, vessel)
    reference_speed_kn = _resolve_reference_speed(vessel)

    direct_distance = _resolve_direct_distance(payload)
    slow_speed = _resolve_slow_speed(payload)
    weather = await _resolve_weather(session, payload, vessel, weather_provider)
    weather_model_used = weather.model_used
    weather_warnings = list(weather.warnings)

    plans = [
        _ScenarioPlan("DIRECT", direct_distance, payload.current_speed_kn),
        _ScenarioPlan(
            "DETOUR",
            payload.detour_distance_nm
            if payload.detour_distance_nm is not None
            else direct_distance * DETOUR_DISTANCE_RATIO,
            payload.current_speed_kn,
        ),
        _ScenarioPlan("SLOW_STEAMING", direct_distance, slow_speed),
    ]
    plans = [_quantize_plan(plan) for plan in plans]

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
        )
    except ValueError as exc:
        raise ValidationError(f"시나리오 계산 오류: 입력값을 확인하세요. ({exc})") from exc

    warnings = [
        *_build_warnings(vessel),
        *weather_warnings,
        *_slow_floor_warnings(plans[2]),
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
        }
    )
    parameter_hash = compute_parameter_hash(parameters_used)
    model_version = _model_version()

    # 시나리오 행을 먼저 저장한다 — PK가 gen_random_uuid() server_default라 flush를
    # 해야 id를 알 수 있고, 그 id가 응답 시나리오 객체와 result_json 양쪽에
    # 들어간다(§5.2 adopt가 이 id를 참조한다).
    scenario_ids: list[UUID] = []
    for plan, item, row in zip(plans, computed, _db_rows(computed), strict=True):
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
    )
    data = {
        "scenarios": scenarios_json,
        "summary": _build_summary(computed),
    }

    duration_ms = max(1, round((time.perf_counter() - started) * 1000))
    run = await calc_run_repo.insert_scenario(
        session,
        vessel_id=payload.vessel_id,
        input_hash=input_hash,
        parameter_hash=parameter_hash,
        model_version=model_version,
        result_json=data,
        parameters_used=parameters_used,
        warnings=warnings,
        duration_ms=duration_ms,
    )
    await session.commit()

    return {
        "data": data,
        "parameters_used": parameters_used,
        "calculation_run_id": str(run.id),
        "model_version": model_version,
        "input_hash": input_hash,
        "parameter_hash": parameter_hash,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
        "_duration_ms": duration_ms,
    }


# --- 조회 + 입력 확정 ----------------------------------------------------------------


async def _load_vessel(session, vessel_id: UUID):
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")
    return vessel


async def _load_regulation_year(session, year: int):
    row = await param_repo.get_regulation_year(session, year)
    if row is None:
        raise ParameterError(f"해당 연도의 규정 파라미터가 없습니다. (regulation_year={year})")
    return row


async def _select_reference_line(session, vessel):
    rows = await param_repo.list_reference_lines(session, vessel.ship_type)
    if not rows:
        raise ParameterError(f"선종의 기준선이 없습니다: {vessel.ship_type}")
    try:
        return select_reference_line(vessel, rows)
    except ValueError as exc:
        raise ParameterError(f"기준선을 선택할 수 없습니다: {exc}") from exc


async def _select_rating_boundary(session, vessel):
    rows = await param_repo.list_rating_boundaries(session, vessel.ship_type)
    if not rows:
        raise ParameterError(f"선종의 등급 경계가 없습니다: {vessel.ship_type}")
    try:
        return select_rating_boundary(vessel, rows)
    except ValueError as exc:
        raise ParameterError(f"등급 경계를 선택할 수 없습니다: {exc}") from exc


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


def _resolve_base_daily_foc(payload, vessel) -> Decimal:
    """PRD §11.4 우선순위 — 요청값 → 선박 기준값 → 계산 불가(422)."""
    value = payload.base_daily_foc_ton
    if value is None:
        value = vessel.reference_daily_foc_ton
    if value is None or Decimal(value) <= 0:
        raise ValidationError(
            "기준 일일 연료소모량이 필요합니다. base_daily_foc_ton을 입력하거나 선박에"
            " reference_daily_foc_ton을 등록해 주세요.",
            field="base_daily_foc_ton",
            field_label="기준 일일 연료소모량",
        )
    return Decimal(value)


def _resolve_reference_speed(vessel) -> Decimal:
    """cubic speed model의 분모 — PRD §11.4.1은 ``vessel.reference_speed_kn``만 본다."""
    value = vessel.reference_speed_kn
    if value is None or Decimal(value) <= 0:
        raise ValidationError(
            "선박에 reference_speed_kn(기준 속력)이 등록되어 있지 않아 연료를 추정할 수 없습니다.",
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
            raise ValidationError(
                "출발지와 목적지가 같은 위치입니다. 항해거리를 확인해 주세요.",
                field="direct_distance_nm",
                field_label="직항 거리",
            )
        return distance
    raise ValidationError(
        "직항 거리가 필요합니다. direct_distance_nm을 입력하거나 현재·목적항 좌표를"
        " 모두 보내주세요.",
        field="direct_distance_nm",
        field_label="직항 거리",
    )


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
        provider=provider,
    )


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


def _db_rows(computed: list[_ScenarioComputed]) -> list[dict[str, Decimal]]:
    """``voyage_scenario`` INSERT용 확정값 — 컬럼 스케일로 반올림한다.

    응답(``_serialize_scenarios``)과 같은 확정 원본에서 만들어야 자릿수가 어긋나지
    않는다. ``cii_value``는 [M-8] denormalized 캐시로 컬럼 스케일(15,8)이다.
    """
    return [
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


def _serialize_scenarios(
    *,
    computed: list[_ScenarioComputed],
    scenario_ids: list[UUID],
    vessel,
    reference_line,
    regulation,
    transport_capacity: Decimal,
    reference_capacity: Decimal,
    weather_model_used: str,
    weather_factor: Decimal,
) -> list[dict[str, object]]:
    """API_SPEC §5.1 ``scenarios[]`` 블록. ``scenario_ids``는 저장된 행의 PK다."""
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
                "scenario_id": str(scenario_id),
                "scenario_type": item.plan.scenario_type,
                "scenario_name": SCENARIO_NAMES[item.plan.scenario_type],
                # 입력 에코는 숫자다 (API_SPEC §5.1 응답 예시).
                "distance_nm": float(item.plan.distance_nm),
                "speed_kn": float(item.plan.speed_kn),
                "duration_hours": _publish(item.duration_hours, _DURATION_DIGITS),
                "fuel_ton": _publish(item.fuel_ton, SERIALIZATION_DIGITS["fuel_ton"]),
                "co2_emission_ton": _publish(layer1.total_co2_t, SERIALIZATION_DIGITS["co2_ton"]),
                "attained_cii": _publish(layer1.attained_cii, SERIALIZATION_DIGITS["attained_cii"]),
                "required_cii": _publish(layer1.required_cii, SERIALIZATION_DIGITS["required_cii"]),
                "ratio_to_required": _publish(
                    layer1.ratio_to_required, SERIALIZATION_DIGITS["ratio_to_required"]
                ),
                "estimated_rating": layer1.rating,
                # 등급 E는 악화 방향 경계가 없어 null이다 (#171 결론).
                "next_worse_boundary_margin": (
                    None
                    if layer1.margin is None
                    else _publish(layer1.margin, SERIALIZATION_DIGITS["margin"])
                ),
                "next_worse_boundary_margin_ratio": (
                    None
                    if layer1.margin_ratio is None
                    else _publish(layer1.margin_ratio, SERIALIZATION_DIGITS["margin_ratio"])
                ),
                "risk_level": layer1.risk_level,
                "weather_factor": float(weather_factor),
                "weather_model_used": weather_model_used,
                "calculation_basis": dict(calculation_basis),
            }
        )
    return json_list


def _build_summary(computed: list[_ScenarioComputed]) -> dict[str, str]:
    """지표별 최소값만 중립적으로 표시한다 (PRD §11.2, AC-F2-005).

    동률이면 ``min``이 **먼저 등장한** 시나리오를 고른다 — 시나리오 순서가
    DIRECT · DETOUR · SLOW_STEAMING(PRD §11.2 표 순서)로 정해져 있어 결과가
    결정론적이다.
    """
    return {
        "lowest_cii_scenario": min(
            computed, key=lambda item: item.layer1.attained_cii
        ).plan.scenario_type,
        "shortest_duration_scenario": min(
            computed, key=lambda item: item.duration_hours
        ).plan.scenario_type,
        "lowest_fuel_scenario": min(computed, key=lambda item: item.fuel_ton).plan.scenario_type,
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
