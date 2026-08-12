"""기능① 항차 CII 추정 서비스 (#55).

``api/routes``와 ``calc``/``db`` 사이에서 **계산 흐름을 조합**한다 (TECH_SPEC §16).
수학은 ``calc``가, 쿼리는 ``db/repositories``가 하며 여기서는 둘을 잇고 규칙을 적용한다.

처리 흐름 (#55 이슈 본문)
--------------------------

1. ``vessel_id``로 선박 조회
2. ``select_reference_line(vessel)`` → 기준선 선택
3. ``resolve_reference_capacity(vessel, capacity_rule)`` → reference capacity
4. ``calculate_attained_cii(...)``
5. ``calculate_required_cii(...)``
6. ``determine_rating(...)``
7. 위험도 산정
8. ``CalculationRun`` 저장
9. ``parameter_hash`` · ``input_hash`` 계산

⚠️ Layer 1 정밀도 — 이 모듈에서 가장 틀리기 쉬운 곳
---------------------------------------------------

``ratio_to_required``와 ``next_worse_boundary_margin_ratio``는 **파생값**이다.
`TECH_SPEC §1.2.1`은 이런 값을 **작업 정밀도 컨텍스트 안에서, 확정 전 원값으로**
계산하도록 규정한다. 밖에서 나누거나 확정값(30자리)을 분모로 쓰면 **27번째 자리부터
갈린다** — `#179`가 실측으로 남긴 경고다.

그래서 :func:`_compute_layer1`이 ``@layer1_context``를 달고 있고, 그 안에서
확정 전 ``Decimal``만 다룬다. **확정(``publish_layer1_canonical``)은 이 함수 밖에서,
응답에 실을 때만** 한다.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy

from cii_platform.calc.capacity import (
    capacity_axis,
    resolve_reference_capacity,
    resolve_transport_capacity,
    select_reference_line,
)
from cii_platform.calc.cii_engine import (
    FuelUse,
    calculate_attained_cii,
    calculate_required_cii,
)
from cii_platform.calc.hash import compute_input_hash, compute_parameter_hash
from cii_platform.calc.precision import (
    LAYER1_CANONICAL_SIGNIFICANT_DIGITS,
    LAYER1_ROUNDING,
    layer1_context,
    publish_layer1_canonical,
    validate_layer1_result,
)
from cii_platform.calc.rating_engine import (
    DVector,
    calculate_deterministic_risk,
    calculate_margin_ratio,
    determine_rating,
    select_next_worse_boundary,
    select_rating_boundary,
)
from cii_platform.db.repositories import calculation_run as calc_run_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import (
    CalculationError,
    NotFoundError,
    ParameterError,
    ValidationError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

# --- 상수 ------------------------------------------------------------------------

#: PRD §6.3 「모든 결과 화면」 문구. 값의 정본은 PRD이며 여기서 재작성하지 않는다.
DISCLAIMER = "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다."

#: API_SPEC §1.6 — 모든 계산 결과에 붙는다.
WARNING_REFERENCE_ONLY = "REFERENCE_ONLY"

#: API_SPEC §1.6 — GT < 5,000.
WARNING_NON_CII_VESSEL = "NON_CII_VESSEL"

#: PRD §3.1 — MARPOL Annex VI Reg.28 적용 하한. GT 기준이다.
CII_APPLICABLE_GT_THRESHOLD = Decimal("5000")

#: 응답 직렬화 자릿수 — **API_SPEC §4.1 예시에서 필드별로 읽어 왔다.**
#:
#: 화면 표시 자릿수(DESIGN_SYSTEM §4.2)와 다른 층이다. 여기는 응답에 싣는 자릿수이고
#: 표시는 프론트엔드가 다시 줄인다(CII 3자리 등).
#:
#: **필드마다 다르다.** 하나로 묶으면 계약 예시와 어긋난다 —
#: ``ratio_to_required``는 ``"0.98758"``(5자리)인데 ``next_worse_boundary_margin_ratio``는
#: ``"0.0724"``(4자리)이고, ``fuel_consumption_ton``은 ``"80.00"``(2자리)인데
#: ``calculation_basis.fuel_cf_details[].fuel_ton``은 ``"80.0"``(1자리)이다.
#:
#: 프론트엔드 demo provider(``frontend/src/features/voyage-cii/demoProvider.ts``)의
#: ``SERIALIZATION_DIGITS``와 **같은 값이어야 한다** — 실 API로 바꿔도 화면이 받는
#: 문자열이 같아야 #138 전환이 무손상이다.
SERIALIZATION_DIGITS = {
    "attained_cii": 6,
    "required_cii": 6,
    "ratio_to_required": 5,
    "margin": 6,
    "margin_ratio": 4,
    "co2_ton": 2,
    "fuel_ton": 2,
    #: ``calculation_basis.fuel_cf_details[].fuel_ton`` — 계약 예시가 ``"80.0"``이다.
    "detail_fuel_ton": 1,
}

#: TECH_SPEC §5.4 재현성 계약이 응답에 싣도록 규정한 엔진 식별자.
ENGINE_NAME = "dual-precision-v1"
RNG_ALGORITHM = "PCG64DXSM"


# --- 입력 DTO --------------------------------------------------------------------


@dataclass(frozen=True)
class FuelUseInput:
    """요청의 ``fuel_uses[]`` 한 건. API 스키마와 서비스를 분리하기 위한 DTO."""

    fuel_type: str
    fuel_ton: Decimal


@dataclass(frozen=True)
class VoyageCiiInput:
    """기능① 계산 입력.

    Pydantic 모델을 그대로 서비스에 넘기지 않는다 — 그러면 ``services``가 ``api``
    패키지에 의존하게 되어 TECH_SPEC §16의 계층 방향이 뒤집힌다.
    """

    vessel_id: UUID
    regulation_year: int
    distance_nm: Decimal
    speed_kn: Decimal
    fuel_uses: tuple[FuelUseInput, ...]
    weather_model: str | None = None


# --- Layer 1 계산 결과 -------------------------------------------------------------


@dataclass(frozen=True)
class _Layer1Values:
    """작업 정밀도 컨텍스트 안에서 만든 **확정 전** 값들.

    확정(30자리 유효숫자)은 응답 직렬화 시점에만 한다 — 이 dataclass의 값을 그대로
    다음 계산에 넣어도 §1.2.1을 위반하지 않는다.
    """

    attained_cii: Decimal
    total_co2_t: Decimal
    fuel_breakdown_g: dict[str, Decimal]
    fuel_total_ton: Decimal
    cii_ref: Decimal
    required_cii: Decimal
    ratio_to_required: Decimal
    rating: str
    boundaries: dict[str, Decimal]
    next_worse_boundary: Decimal | None
    margin: Decimal | None
    margin_ratio: Decimal | None
    risk_level: str


@layer1_context
def _compute_layer1(
    *,
    fuel_uses: list[FuelUse],
    transport_capacity: Decimal,
    reference_capacity: Decimal,
    distance_nm: Decimal,
    a_decimal: Decimal,
    c: Decimal,
    z_factor_percent: Decimal,
    d_vector: DVector,
) -> _Layer1Values:
    """Layer 1 전 구간을 **한 컨텍스트 안에서** 계산한다.

    함수를 나누어 각각 ``@layer1_context``를 달면 컨텍스트를 여러 번 들락거리게 되고,
    그 사이에 만든 중간값이 기본 컨텍스트(``prec=28``)에서 다뤄질 여지가 생긴다.
    **파생값을 적용 지점 밖에서 계산하면 27번째 자리부터 갈린다**(#179 실측).
    """
    cii = calculate_attained_cii(
        fuel_uses=fuel_uses,
        transport_capacity=transport_capacity,
        distance_nm=distance_nm,
    )
    required = calculate_required_cii(
        a=a_decimal,
        c=c,
        reference_capacity=reference_capacity,
        z_factor_percent=z_factor_percent,
    )

    # ⚠️ 분모는 **확정 전** required_cii다. publish_layer1_canonical()을 거친 값을
    # 쓰면 …012580이 나오고 정본은 …012581이다 (#179 · #45 회귀로 고정됨).
    ratio = validate_layer1_result(cii.attained_cii / required.required_cii, "ratio_to_required")

    result = determine_rating(
        attained_cii=cii.attained_cii,
        required_cii=required.required_cii,
        d_vector=d_vector,
    )
    next_worse = select_next_worse_boundary(result.rating, result.boundaries)

    if next_worse is None:
        margin: Decimal | None = None
        margin_ratio: Decimal | None = None
    else:
        margin = validate_layer1_result(next_worse - cii.attained_cii, "next_worse_boundary_margin")
        margin_ratio = calculate_margin_ratio(
            attained_cii=cii.attained_cii,
            required_cii=required.required_cii,
            next_worse_boundary=next_worse,
        )

    fuel_total_ton = sum((fu.fuel_ton for fu in fuel_uses), Decimal(0))

    return _Layer1Values(
        attained_cii=cii.attained_cii,
        total_co2_t=cii.total_co2_t,
        fuel_breakdown_g=cii.fuel_breakdown,
        fuel_total_ton=fuel_total_ton,
        cii_ref=required.cii_ref,
        required_cii=required.required_cii,
        ratio_to_required=ratio,
        rating=result.rating,
        boundaries=result.boundaries,
        next_worse_boundary=next_worse,
        margin=margin,
        margin_ratio=margin_ratio,
        risk_level=calculate_deterministic_risk(result.rating, margin_ratio),
    )


# --- 직렬화 헬퍼 ------------------------------------------------------------------


def _publish(value: Decimal, digits: int) -> str:
    """Layer 1 값을 응답 문자열로 확정한다.

    **두 단계다.** 먼저 §1.2.1의 공표 확정(유효숫자 30)을 거치고, 그 다음 API_SPEC
    §4.1 예시가 쓰는 자릿수로 형식화한다. 앞 단계를 건너뛰면 응답에 50자리가 그대로
    실리고, 뒤 단계를 건너뛰면 계약 예시(``"4.982400"``)와 형태가 달라진다.

    ``quantize``의 반올림은 §1.2.1과 같은 ``ROUND_HALF_UP``이다.
    """
    canonical = publish_layer1_canonical(value)
    quantum = Decimal(1).scaleb(-digits)
    return str(canonical.quantize(quantum, rounding=LAYER1_ROUNDING))


def _plain(value: Decimal) -> str:
    """Decimal을 지수 표기 없이 문자열로 만든다.

    ``transport_capacity``처럼 **확정·반올림 대상이 아닌 값**에 쓴다.
    ``Decimal("50000.00")``이 ``"5E+4"`` 형태로 나가는 것을 막는다 — 계약 예시는
    ``"50000"``이다.
    """
    normalized = value.normalize()
    # normalize()는 50000 → 5E+4로 만든다. 지수가 양수면 원래 자리로 되돌린다.
    if normalized == normalized.to_integral_value():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _percent(value: Decimal) -> str:
    """Z계수를 응답 문자열로 만든다. **소수 자릿수를 최소 1자리 유지한다.**

    ``regulation_year.z_factor_percent``는 ``NUMERIC(8,4)``라 DB에서 ``11.0000``으로
    온다. :func:`_plain`을 그대로 쓰면 ``"11"``이 되는데, **프론트엔드 고정표와
    `#132` 계약이 ``"11.0"``을 쓴다**(``referenceTable.ts``의 ``zFactorPercent``).
    실 API로 바꿔도 화면이 받는 문자열이 같아야 `#138` 전환이 무손상이다.

    ⚠️ **API_SPEC §4.1 예시가 두 곳에서 서로 다르다.**

    - ``data.calculation_basis.z_factor_percent`` → ``"11.0"``
    - ``parameters_used.regulation_year.z_factor_percent`` → ``"11"``

    같은 컬럼에서 온 같은 값인데 표기가 갈린 것이라 **예시의 오기로 본다.** 한쪽을
    따라 두 형태를 만들면 같은 값이 응답 안에서 다르게 보인다. 프론트엔드 demo
    provider가 **양쪽 모두 ``"11.0"``**을 쓰므로 그쪽으로 통일한다.
    이 불일치는 별건으로 제기한다.
    """
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        # 11 → 11.0. 정수부만 남으면 소수 1자리를 되살린다.
        return str(normalized.quantize(Decimal("0.1")))
    return format(normalized, "f")


def _model_version() -> dict[str, object]:
    """TECH_SPEC §5.4 재현성 계약이 요구하는 엔진 식별 정보.

    ``decimal_precision``은 **공표 자릿수(30)**를 싣는다. 작업 정밀도(50)가 아니다 —
    API_SPEC §4.1 예시가 30이고, 클라이언트가 알아야 하는 것은 「응답 값이 몇 자리로
    확정됐는가」이기 때문이다(#179가 두 값을 분리한 이유와 같다).
    """
    return {
        "engine": ENGINE_NAME,
        "decimal_precision": LAYER1_CANONICAL_SIGNIFICANT_DIGITS,
        "decimal_rounding": LAYER1_ROUNDING,
        "rng_algorithm": RNG_ALGORITHM,
        "numpy_version": numpy.__version__,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro}",
    }


# --- 서비스 진입점 ----------------------------------------------------------------


async def estimate_voyage_cii(session: AsyncSession, payload: VoyageCiiInput) -> dict[str, object]:
    """항차 CII를 추정하고 이력을 저장한 뒤 API_SPEC §4.1 응답 dict를 반환한다.

    ``meta``는 채우지 않는다 — ``request_id``·``timestamp``는 미들웨어가 요청 단위로
    만들고 라우트가 붙인다. 서비스가 ``request`` 객체를 알면 계층이 뒤집힌다.
    ``duration_ms``만 여기서 잰다(계산 시간이 서비스의 관심사다).
    """
    started = time.perf_counter()

    vessel = await _load_vessel(session, payload.vessel_id)
    regulation = await _load_regulation_year(session, payload.regulation_year)
    reference_line = await _select_reference_line(session, vessel)
    rating_boundary = await _select_rating_boundary(session, vessel)
    fuel_rows = await _load_fuel_types(session, payload)

    transport_capacity = _resolve_transport_capacity(vessel)
    reference_capacity = _resolve_reference_capacity(vessel, reference_line)

    fuel_uses = [
        FuelUse(
            fuel_code=item.fuel_type,
            fuel_ton=item.fuel_ton,
            cf_value=Decimal(fuel_rows[item.fuel_type].cf),
        )
        for item in payload.fuel_uses
    ]

    try:
        layer1 = _compute_layer1(
            fuel_uses=fuel_uses,
            transport_capacity=transport_capacity,
            reference_capacity=reference_capacity,
            distance_nm=payload.distance_nm,
            a_decimal=Decimal(reference_line.a_decimal),
            c=Decimal(reference_line.c),
            z_factor_percent=Decimal(regulation.z_factor_percent),
            d_vector=DVector(
                d1=Decimal(rating_boundary.d1),
                d2=Decimal(rating_boundary.d2),
                d3=Decimal(rating_boundary.d3),
                d4=Decimal(rating_boundary.d4),
            ),
        )
    except ValueError as exc:
        # Layer 1 엔진은 ValueError로 중단한다(TECH_SPEC §12.2 1항). 그대로 올리면
        # 500이 되지만 원인은 입력이므로 422로 바꾼다.
        raise CalculationError(f"계산 오류: 입력값을 확인하세요. ({exc})") from exc

    parameters_used = _build_parameters_used(
        regulation=regulation,
        reference_line=reference_line,
        rating_boundary=rating_boundary,
        fuel_rows=fuel_rows,
        payload=payload,
    )
    data = _build_data(
        vessel=vessel,
        reference_line=reference_line,
        regulation=regulation,
        transport_capacity=transport_capacity,
        reference_capacity=reference_capacity,
        payload=payload,
        fuel_rows=fuel_rows,
        layer1=layer1,
    )
    warnings = _build_warnings(vessel)

    input_hash = compute_input_hash(
        _build_hash_input(
            payload=payload,
            vessel=vessel,
            transport_capacity=transport_capacity,
            reference_capacity=reference_capacity,
            fuel_rows=fuel_rows,
        )
    )
    parameter_hash = compute_parameter_hash(parameters_used)
    model_version = _model_version()
    duration_ms = max(1, round((time.perf_counter() - started) * 1000))

    run = await calc_run_repo.insert_voyage_estimate(
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


# --- 조회 + 규칙 적용 --------------------------------------------------------------


async def _load_vessel(session: AsyncSession, vessel_id: UUID):
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")
    return vessel


async def _load_regulation_year(session: AsyncSession, year: int):
    """VAL-005 — 해당 연도의 규정 파라미터가 있어야 한다.

    **422가 아니라 409다.** 사용자가 요청을 고쳐도 해결되지 않고, 서버에 그 연도의
    Z계수 행이 없는 상태이기 때문이다(TECH_SPEC §12.1 ``ParameterError``).
    """
    row = await param_repo.get_regulation_year(session, year)
    if row is None:
        raise ParameterError(f"해당 연도의 규정 파라미터가 없습니다. (regulation_year={year})")
    return row


async def _select_reference_line(session: AsyncSession, vessel):
    """선종·크기에 맞는 기준선 1행을 고른다.

    ``select_reference_line()``이 던지는 ``ValueError``는 **선종 미등록** 또는
    **구간 미매칭**이며, 둘 다 seed 데이터의 문제라 ``ParameterError``(409)다.
    """
    rows = await param_repo.list_reference_lines(session, vessel.ship_type)
    if not rows:
        raise ParameterError(f"선종의 기준선이 없습니다: {vessel.ship_type}")
    try:
        return select_reference_line(vessel, rows)
    except ValueError as exc:
        raise ParameterError(f"기준선을 선택할 수 없습니다: {exc}") from exc


async def _select_rating_boundary(session: AsyncSession, vessel):
    rows = await param_repo.list_rating_boundaries(session, vessel.ship_type)
    if not rows:
        raise ParameterError(f"선종의 등급 경계가 없습니다: {vessel.ship_type}")
    try:
        return select_rating_boundary(vessel, rows)
    except ValueError as exc:
        raise ParameterError(f"등급 경계를 선택할 수 없습니다: {exc}") from exc


async def _load_fuel_types(session: AsyncSession, payload: VoyageCiiInput):
    """VAL-006 — 요청의 연료 코드가 전부 active여야 한다.

    **이건 사용자 입력 문제라 422다.** 없는 코드를 필드 경로와 함께 알려 준다 —
    화면이 해당 입력창 아래에 메시지를 붙일 수 있어야 한다(API_SPEC §1.3.2).
    """
    codes = [item.fuel_type for item in payload.fuel_uses]
    rows = await param_repo.get_fuel_types_by_codes(session, codes)
    for index, item in enumerate(payload.fuel_uses):
        if item.fuel_type not in rows:
            raise ValidationError(
                f"알 수 없는 연료 종류입니다: {item.fuel_type}",
                field=f"fuel_uses[{index}].fuel_type",
                field_label="연료 종류",
            )
    return rows


def _resolve_transport_capacity(vessel) -> Decimal:
    """attained CII의 분모에 쓰는 capacity (G1).

    선종의 축(DWT/GT)에 해당하는 컬럼이 NULL이면 ``ValueError``가 난다. 그건 선박
    데이터의 문제이므로 ``ParameterError``가 아니라 **입력 선박이 계산 불가 상태**임을
    알리는 422다 — 사용자가 다른 선박을 고르면 해결된다.
    """
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


# --- 응답 조립 --------------------------------------------------------------------


def _normalized_fuel_details(payload: VoyageCiiInput, fuel_rows) -> list[dict[str, str]]:
    """``fuel_cf_details`` — **연료 종류별 한 행으로 정규화한다** (API_SPEC §4.1).

    같은 ``fuel_type``이 여러 행으로 들어오면 합산한다. 합산 대상은 요청의
    ``fuel_ton``이며, ``layer1.fuel_breakdown_g``(CO₂ 그램)와는 다른 값이다.
    """
    totals: dict[str, Decimal] = {}
    for item in payload.fuel_uses:
        totals[item.fuel_type] = totals.get(item.fuel_type, Decimal(0)) + item.fuel_ton

    # 첫 등장 순서를 유지한다 — dict가 삽입 순서를 보존하므로 totals가 이미 그 순서다.
    return [
        {
            "fuel_type": code,
            "cf": _plain(Decimal(fuel_rows[code].cf)),
            "fuel_ton": _publish(total, SERIALIZATION_DIGITS["detail_fuel_ton"]),
        }
        for code, total in totals.items()
    ]


def _build_data(
    *,
    vessel,
    reference_line,
    regulation,
    transport_capacity: Decimal,
    reference_capacity: Decimal,
    payload: VoyageCiiInput,
    fuel_rows,
    layer1: _Layer1Values,
) -> dict[str, object]:
    """API_SPEC §4.1 ``data`` 블록."""
    return {
        "attained_cii": _publish(layer1.attained_cii, SERIALIZATION_DIGITS["attained_cii"]),
        "required_cii": _publish(layer1.required_cii, SERIALIZATION_DIGITS["required_cii"]),
        "ratio_to_required": _publish(
            layer1.ratio_to_required, SERIALIZATION_DIGITS["ratio_to_required"]
        ),
        "estimated_rating": layer1.rating,
        # 등급 E는 악화 방향 경계가 없어 null이다 (#171 결론 · PRD §9.2).
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
        "co2_emission_ton": _publish(layer1.total_co2_t, SERIALIZATION_DIGITS["co2_ton"]),
        "fuel_consumption_ton": _publish(layer1.fuel_total_ton, SERIALIZATION_DIGITS["fuel_ton"]),
        # 입력 에코는 **숫자**다 (API_SPEC §4.1 응답 타입 표).
        "distance_nm": float(payload.distance_nm),
        "risk_level": layer1.risk_level,
        "transport_capacity": _plain(transport_capacity),
        "transport_capacity_basis": capacity_axis(vessel.ship_type),
        "reference_capacity": _plain(reference_capacity),
        # enum이 아니다 — 파라미터 테이블 값 그대로 (`fixed 279000` 등).
        "reference_capacity_rule": reference_line.capacity_rule,
        "calculation_basis": {
            "ship_type": vessel.ship_type,
            "z_factor_percent": _percent(Decimal(regulation.z_factor_percent)),
            "fuel_cf_details": _normalized_fuel_details(payload, fuel_rows),
            "a_decimal": _plain(Decimal(reference_line.a_decimal)),
            "c": _plain(Decimal(reference_line.c)),
        },
    }


def _build_parameters_used(
    *, regulation, reference_line, rating_boundary, fuel_rows, payload: VoyageCiiInput
) -> dict[str, object]:
    """API_SPEC §4.1 ``parameters_used`` 블록.

    **``parameter_hash``의 입력이기도 하다.** 여기 담기는 것이 바뀌면 해시가 바뀌고,
    그것이 재현성 추적의 근거다(TECH_SPEC §5.2.1). 따라서 요청마다 달라지는 값
    (거리·연료량 등)을 넣으면 안 된다 — 그건 ``input_hash``의 몫이다.
    """
    # 요청에 등장한 연료만, 첫 등장 순서로 싣는다. 8종 전체를 실으면 같은 파라미터
    # 세트에서도 요청과 무관한 행이 해시에 들어간다.
    seen: list[str] = []
    for item in payload.fuel_uses:
        if item.fuel_type not in seen:
            seen.append(item.fuel_type)

    return {
        "regulation_year": {
            "year": str(regulation.year),
            "z_factor_percent": _percent(Decimal(regulation.z_factor_percent)),
        },
        "fuel_types": [{"code": code, "cf": _plain(Decimal(fuel_rows[code].cf))} for code in seen],
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


def _build_hash_input(
    *,
    payload: VoyageCiiInput,
    vessel,
    transport_capacity: Decimal,
    reference_capacity: Decimal,
    fuel_rows,
) -> dict[str, object]:
    """``input_hash``의 입력 (TECH_SPEC §5.3).

    ``calc.hash.INPUT_FIELDS``가 **11개 키**를 정하며, 그 목록이 바뀌면 저장된 모든
    해시가 무효가 된다. 여기서는 그 목록이 요구하는 키를 채우기만 한다.

    요청 필드만으로는 부족하다 — ``ship_type`` · ``transport_capacity`` ·
    ``reference_capacity``는 **선박과 기준선에서 파생**되고, 그것이 `[EXT-P0-1]`이
    이 셋을 목록에 넣은 이유다. 같은 요청이라도 선박 제원이나 기준선이 바뀌면 계산
    결과가 달라지므로, 그 변화가 해시에 드러나야 재현성 추적이 성립한다.

    ``fuel_uses``의 각 항목에 ``cf``를 함께 넣는다(``INPUT_FIELDS`` 주석의
    ``[{fuel_type, fuel_ton, cf}]``). CF가 개정되면 같은 연료·같은 양이라도 결과가
    달라진다.

    ``weather_factor``는 ``None``으로 넘긴다 — 기본값 치환은 ``compute_input_hash()``의
    책임이라고 그 docstring이 명시한다. 여기서 먼저 대입하면 같은 규약이 두 곳에 생긴다.
    """
    return {
        "vessel_id": str(payload.vessel_id),
        "regulation_year": payload.regulation_year,
        "ship_type": vessel.ship_type,
        "transport_capacity": transport_capacity,
        "reference_capacity": reference_capacity,
        "distance_nm": payload.distance_nm,
        "speed_kn": payload.speed_kn,
        "fuel_uses": [
            {
                "fuel_type": item.fuel_type,
                "fuel_ton": item.fuel_ton,
                "cf": Decimal(fuel_rows[item.fuel_type].cf),
            }
            for item in payload.fuel_uses
        ],
        "weather_model": payload.weather_model or "NONE",
        "weather_factor": None,
    }


def _build_warnings(vessel) -> list[str]:
    """API_SPEC §1.6 warning 코드.

    ``REFERENCE_ONLY``는 「모든 계산 결과」라 항상 붙는다. ``NON_CII_VESSEL``은
    **GT를 알고 그것이 5,000 미만일 때만** 붙인다 — GT가 NULL이면 판정 근거가 없어
    「적용 대상이 아니다」라고 단정할 수 없다.
    """
    warnings = [WARNING_REFERENCE_ONLY]
    if (
        vessel.gross_tonnage is not None
        and Decimal(vessel.gross_tonnage) < CII_APPLICABLE_GT_THRESHOLD
    ):
        warnings.append(WARNING_NON_CII_VESSEL)
    return warnings
