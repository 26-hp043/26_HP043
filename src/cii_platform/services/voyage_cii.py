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

from cii_platform.calc.annual_simulation import RemainingVoyage, project_deterministic
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
    CII_SERIALIZATION_ROUNDING,
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
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import (
    CalculationError,
    NotFoundError,
    ParameterError,
    ValidationError,
)
from cii_platform.services import applicability
from cii_platform.services.calc_errors import log_calculation_failure, selection_error, spec_error
from cii_platform.services.simulation_clock import resolve_as_of

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

# --- 상수 ------------------------------------------------------------------------

#: PRD §6.3 「모든 결과 화면」 문구. 값의 정본은 PRD이며 여기서 재작성하지 않는다.
DISCLAIMER = "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다."

#: API_SPEC §1.6 — 모든 계산 결과에 붙는다.
WARNING_REFERENCE_ONLY = "REFERENCE_ONLY"

#: CII 적용 대상 판정 어휘. 정의는 ``services.applicability``가 단독으로 소유한다
#: (`#653`) — 이 모듈이 값을 다시 적으면 두 곳이 갈린다. 이름을 여기 남겨 두는 것은
#: 기존 호출부·테스트가 ``voyage_cii.WARNING_NON_CII_VESSEL``로 참조하기 때문이다.
WARNING_NON_CII_VESSEL = applicability.WARNING_NON_CII_VESSEL
WARNING_CII_APPLICABILITY_UNKNOWN = applicability.WARNING_CII_APPLICABILITY_UNKNOWN
CII_APPLICABLE_GT_THRESHOLD = applicability.CII_APPLICABLE_GT_THRESHOLD

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
#: 종전에는 프론트엔드 demo provider의 같은 이름 상수와 대조하는 테스트가 있었다.
#: ``#542``가 데모 모드를 폐기하면서 대조 대상이 사라져 그 테스트도 함께 지웠다.
#: 화면이 그리는 자릿수는 ``DESIGN_SYSTEM §4``이 정하며 ``frontend/src/display/format.ts``와
#: ``voyage-cii/apiPath.test.ts``가 잠근다 — 이 표는 **서버가 내보내는 자릿수**다.
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
    #: 등급 경계 CII 4종 (`#1371`). ``attained_cii``·``required_cii``와 **같은 6자리**다 —
    #: 셋이 같은 축(CII)의 값이라 자릿수가 다르면 화면에서 나란히 놓을 수 없다.
    "boundary_cii": 6,
    #: 기능② ``duration_hours`` (``services/scenario_compare``) — 프론트엔드
    #: ``serializeHours``(``toFixed(4)``)와 같다.
    "duration_hours": 4,
}

#: :data:`SERIALIZATION_DIGITS` 가운데 **CII 값을 싣는 필드** — 자릿수를 줄일 때 반올림이
#: 아니라 **절사**한다(`TECH_SPEC §1.2.1` 「응답 직렬화의 절사」 · `#1349`). 반올림 모드를
#: 호출 자리마다 넘기지 않고 이 표에서 정하는 것은, 필드를 하나 더할 때 **빠뜨릴 수 없게**
#: 하기 위해서다 — 여기 없으면 :data:`LAYER1_ROUNDING`이다.
#:
#: ``margin``(``next_worse_boundary_margin``)은 CII 축의 차이라 같은 축이다.
#: ``margin_ratio``·``ratio_to_required``는 비율이고, ``detail_fuel_ton``은 전송 자릿수가
#: 표시 자릿수와 같아 절사하면 그 문자열이 곧 표시가 된다 — 둘 다 그대로 반올림이다.
SERIALIZATION_CII_FIELDS = frozenset({"attained_cii", "required_cii", "boundary_cii", "margin"})

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
    #: 귀속 항차 (#817). 결과·``input_hash``에 영향이 없다 — 이력의 주소일 뿐이다.
    voyage_id: UUID | None = None


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


def _publish(value: Decimal, field: str) -> str:
    """Layer 1 값을 응답 문자열로 확정한다.

    **두 단계다.** 먼저 §1.2.1의 공표 확정(유효숫자 30)을 거치고, 그 다음 API_SPEC
    §4.1 예시가 쓰는 자릿수(:data:`SERIALIZATION_DIGITS`)로 형식화한다. 앞 단계를
    건너뛰면 응답에 50자리가 그대로 실리고, 뒤 단계를 건너뛰면 계약 예시
    (``"4.982400"``)와 형태가 달라진다.

    뒤 단계의 반올림은 **필드가 정한다** (`#1349`). CII 필드
    (:data:`SERIALIZATION_CII_FIELDS`)는 ``ROUND_DOWN``으로 절사하고, 나머지는 §1.2.1의
    ``ROUND_HALF_UP``이다 — 절사는 화면의 3자리 반올림과 합쳐 두 번 반올림되는 것을
    막는 장치라(`TECH_SPEC §1.2.1` 「응답 직렬화의 절사」), 전송 자릿수가 표시
    자릿수와 같은 필드에는 걸지 않는다.
    """
    canonical = publish_layer1_canonical(value)
    quantum = Decimal(1).scaleb(-SERIALIZATION_DIGITS[field])
    rounding = CII_SERIALIZATION_ROUNDING if field in SERIALIZATION_CII_FIELDS else LAYER1_ROUNDING
    return str(canonical.quantize(quantum, rounding=rounding))


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
    온다. :func:`_plain`을 그대로 쓰면 ``"11"``이 되는데, **`#132` 계약이
    ``"11.0"``을 쓴다.** 프론트엔드 고정표도 같은 값을 복사해 두었으나 ``#542``가
    그 표를 없앴다 — 기준은 계약 fixture다.

    **응답 안의 두 자리 모두 ``"11.0"``이다** — ``data.calculation_basis.z_factor_percent``
    와 ``parameters_used.regulation_year.z_factor_percent``. 같은 컬럼에서 온 같은 값이라
    표기가 갈리면 문자열 비교에서 **다른 값으로 읽힌다**(`API_SPEC §1.7` — Layer 1 수치는
    문자열이라 표기가 곧 값이다). ``tests/test_voyage_cii_api.py``가 두 자리를 함께 잠근다.

    > 이 자리에는 종전에 「`API_SPEC §4.1` 예시가 두 곳에서 서로 다르다(``"11.0"`` ·
    > ``"11"``) — 별건으로 제기한다」가 적혀 있었다. **예시는 2026-08-12 `PR #218`에서
    > 이미 ``"11.0"``으로 통일됐는데 이 주석만 남아**, 8/29 전수 검토가 이 문장을 근거로
    > `#774`를 등록했다. 정본이 아니라 **낡은 주석이 이슈를 만든** 사례라 경위를 남긴다.
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

    ``decimal_rounding``도 같은 층이다 — **Layer 1 계산과 공표 확정**의 반올림
    (``ROUND_HALF_UP``)이며, 그 30자리 공표값을 전송 자릿수(소수 6)로 줄이는 직렬화
    단계의 절사(:func:`_publish` · `#1349`)를 말하지 않는다. 저장된 옛 결과의
    ``ROUND_HALF_UP`` 문자열도 그대로 둔다(§1.2.1 — 재현은 해시만 비교한다).
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


async def estimate_voyage_cii(
    session: AsyncSession, payload: VoyageCiiInput, *, persist: bool = True
) -> dict[str, object]:
    """항차 CII를 추정하고 이력을 저장한 뒤 API_SPEC §4.1 응답 dict를 반환한다.

    ``meta``는 채우지 않는다 — ``request_id``·``timestamp``는 미들웨어가 요청 단위로
    만들고 라우트가 붙인다. 서비스가 ``request`` 객체를 알면 계층이 뒤집힌다.
    ``duration_ms``만 여기서 잰다(계산 시간이 서비스의 관심사다).

    ## ``persist=False`` — 저장하지 않는 경로 (`#1334` ⑷)

    챗봇 도구가 이 함수를 부른다. ``services/chat_tools`` 머리말은 *「쓰기 도구를
    넣지 않는다 … ``PRD §16.2`` 격리」* 라고 적는데, **읽기 도구가 쓰고 있었다** —
    ``calculation_run``에 행이 남고 턴 중간에 ``commit``까지 했다.

    ``calculation_run``은 **출처 열이 없고 삭제 금지 트리거**가 걸려 있다. 시연 중
    「14노트로 1000마일이면?」 한 번마다 모델이 만든 입력의 계산 행이 그 선박의 계산
    이력과 ``§8.1 type=calculations`` 내보내기에 **화면 계산과 구별 없이** 쌓이고
    지울 수 없다. **답변이 폐기돼도 행은 남는다.**

    「저장 유지 + 출처 표시」는 고르지 않았다 — 출처 열을 새로 만들고(마이그레이션)
    이력 화면과 내보내기가 그 열을 읽게 해야 하는데, 그러고도 **행이 쌓이는 것 자체는
    남는다.**

    저장하지 않으면 ``calculation_run_id``가 ``None``이다. 키를 빼지 않는 이유는
    호출부가 **키의 유무가 아니라 값**을 보게 하기 위해서다.
    """
    started = time.perf_counter()

    vessel = await _load_vessel(session, payload.vessel_id)
    if payload.voyage_id is not None:
        await _require_voyage_of_vessel(session, payload.voyage_id, payload.vessel_id)
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
        raise CalculationError(log_calculation_failure("기능① 항차 CII", exc)) from exc

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

    # `PRD §10.3` ⑨ · `§10.4` — 「연간 반영 시 변화」 (`#1338`).
    # 계산 **뒤에** 낸다 — 이 값이 없어도 항차 CII는 답이 나와야 한다.
    data["annual_impact"] = await _annual_impact(session, payload=payload, fuel_uses=fuel_uses)

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

    run_id: str | None = None
    if persist:
        run = await calc_run_repo.insert_voyage_estimate(
            session,
            vessel_id=payload.vessel_id,
            voyage_id=payload.voyage_id,
            input_hash=input_hash,
            parameter_hash=parameter_hash,
            model_version=model_version,
            result_json=data,
            parameters_used=parameters_used,
            warnings=warnings,
            duration_ms=duration_ms,
        )
        await session.commit()
        run_id = str(run.id)

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


# --- 연간 반영 시 변화 (`PRD §10.3` ⑨ · `#1338`) ------------------------------------


@layer1_context
def _impact_layer1(context, completed, remaining, extra):
    """반영 **전/후** 연말 예상을 **한 컨텍스트 안에서** 낸다 (`TECH_SPEC §1.2.1`).

    두 값을 각각 다른 컨텍스트에서 내면 **차이가 컨텍스트 차이인지 항차 때문인지**
    구분되지 않는다 — 이 블록이 보여 주는 것이 바로 그 차이다.
    """
    before = project_deterministic(
        completed=completed,
        remaining=remaining,
        transport_capacity=context.transport_capacity,
        required_cii=context.required_cii,
        d_vector=context.d_vector,
    )
    after = project_deterministic(
        completed=completed,
        remaining=[*remaining, extra],
        transport_capacity=context.transport_capacity,
        required_cii=context.required_cii,
        d_vector=context.d_vector,
    )
    return before, after


def _effective_cf(fuel_uses: list[FuelUse]) -> tuple[Decimal, Decimal] | None:
    """여러 유종을 :class:`RemainingVoyage`의 ``(fuel_ton, cf)`` 한 쌍으로 모은다.

    ``RemainingVoyage``는 항차당 CF **하나**를 갖는다(`PRD §12.4.1` — 연료 종류는
    MVP에서 항차별 고정). 질량가중 평균을 쓰면 ``Σ(fuel_j × cf_j)``가 **정확히
    보존**되므로 분자 ``M``이 기능①의 값과 같아진다 — 평균을 산술로 내면 유종별
    사용량이 다를 때 갈린다.
    """
    total = sum((use.fuel_ton for use in fuel_uses), Decimal(0))
    if total <= 0:
        return None
    weighted = sum((use.fuel_ton * use.cf_value for use in fuel_uses), Decimal(0))
    return total, weighted / total


async def _annual_impact(
    session: AsyncSession, *, payload: VoyageCiiInput, fuel_uses: list[FuelUse]
) -> dict[str, object] | None:
    """「이 항차를 반영하면 연말 예상 등급이 어떻게 되나」 (`PRD §10.3` ⑨ · `§10.4`).

    ⚠️ **기능①의 항차 CII와는 다른 질문이다.** 항차 CII는 *「이 항차 하나」*를, 이
    블록은 *「그 배의 한 해 전체」*를 본다. 실측(데모 시드 · 같은 항차 3,000 nm ·
    HFO 250 t)에서 **항차 등급이 좋은 배의 연말이 나쁘고 그 반대도 나온다** —
    벌크 50,000은 항차 ``C``에 연말 ``E``, 컨테이너는 항차 ``E``에 연말 ``B``다.
    **수준이 어긋나는 것이 정상**이므로 화면이 둘을 같은 값으로 다루면 안 된다.

    ## 조립을 새로 만들지 않는다

    `§2.14` ⑶(실시간 CII의 연말 예상)과 기능③이 쓰는
    :func:`~cii_platform.services.annual_simulation.load_projection_context`·
    :func:`~cii_platform.services.annual_simulation.collect_annual_inputs`를 그대로
    부른다. 조립이 둘이면 **같은 선박·같은 연도에서 두 화면이 다른 숫자**를 낸다
    (`#798` 실측: 7.654488 vs 8.971119).

    ## 기초 자료가 없으면 ``None``이다

    정본이 *「연간 시뮬레이터에 **이미 동일 선박·연도 데이터가 있으면**」*으로 조건을
    달았다. 확정 실적도 잔여 계획도 없으면 비교할 「기존 연말 예상」이 없다 —
    **0과 비교한 숫자를 지어내지 않는다.**

    ⚠️ **그 판정을 여기서 다시 쓰지 않는다.** 확정도 잔여도 없다는 것은 곧 분모
    거리가 0이라는 뜻이고, :func:`project_deterministic`이 그때 ``ValueError``를
    올린다(`PRD §12.8`). 조건을 따로 적으면 **둘 중 하나만 고쳐질 자리**가 생기고,
    실제로 앞선 초안의 `if`문은 아래 ``except``가 이미 덮는 **죽은 갈래**였다
    (돌연변이 검사에서 드러났다 — 지워도 아무것도 실패하지 않았다).

    ## 계산을 막지 않는다

    여기서 실패해도 항차 CII는 답이 나와야 한다(`PRD §16.2` 오류 격리). 규정
    파라미터·연료 조회 실패는 이미 위에서 걸렀고, 여기 남는 것은 **연말 예상에만
    필요한 자료**다.
    """
    from cii_platform.services.annual_simulation import (
        collect_annual_inputs,
        load_projection_context,
    )

    pair = _effective_cf(fuel_uses)
    if pair is None or payload.distance_nm <= 0:
        return None
    fuel_ton, cf = pair

    try:
        context = await load_projection_context(
            session, vessel_id=payload.vessel_id, regulation_year=payload.regulation_year
        )
        inputs = await collect_annual_inputs(
            session,
            vessel=context.vessel,
            vessel_id=payload.vessel_id,
            year=payload.regulation_year,
            as_of=resolve_as_of(None),
        )
    except (NotFoundError, ParameterError, ValidationError):
        return None

    extra = RemainingVoyage(
        distance_nm=float(payload.distance_nm),
        fuel_ton=float(fuel_ton),
        cf=float(cf),
    )
    try:
        before, after = _impact_layer1(context, inputs.completed, inputs.remaining, extra)
    except ValueError:
        # 거리가 0이면 `PRD §12.8`이 계산 중단을 규정한다. 이 블록은 부가 출력이므로
        # 500으로 올리지 않고 **없는 것으로 둔다.**
        return None

    # 자릿수는 이 응답의 다른 CII 값과 **같게** 둔다 — 한 응답 안에서 같은 양이
    # 다른 자릿수로 실리면 화면이 둘을 다른 종류의 값으로 다루게 된다.
    return {
        "before": {
            "attained_cii": _publish(before.attained_cii, "attained_cii"),
            "rating": before.rating,
        },
        "after": {
            "attained_cii": _publish(after.attained_cii, "attained_cii"),
            "rating": after.rating,
        },
        "rating_changed": before.rating != after.rating,
    }


# --- 조회 + 규칙 적용 --------------------------------------------------------------


async def _require_voyage_of_vessel(
    session: AsyncSession, voyage_id: UUID, vessel_id: UUID
) -> None:
    """귀속 항차가 **이 선박의 살아 있는 항차**인지 확인한다 (#817).

    다른 선박의 항차에 붙으면 그 항차의 계획이 바뀔 때 **엉뚱한 선박의 계산**이 재계산
    필요로 표시된다. 없는 항차면 404 — 선박이 없을 때와 같다.
    """
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None or voyage.is_deleted:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")
    if voyage.vessel_id != vessel_id:
        raise ValidationError(
            "이 선박의 항차가 아닙니다.", field="voyage_id", field_label="귀속 항차"
        )


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
        raise ParameterError(f"해당 연도의 규정 파라미터가 없습니다. (기준연도 {year})")
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
        raise selection_error("기준선", exc) from exc


async def _select_rating_boundary(session: AsyncSession, vessel):
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
        raise spec_error(exc) from exc


def _resolve_reference_capacity(vessel, reference_line) -> Decimal:
    try:
        return resolve_reference_capacity(vessel, reference_line)
    except ValueError as exc:
        raise spec_error(exc) from exc


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
            "fuel_ton": _publish(total, "detail_fuel_ton"),
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
        "attained_cii": _publish(layer1.attained_cii, "attained_cii"),
        "required_cii": _publish(layer1.required_cii, "required_cii"),
        "ratio_to_required": _publish(layer1.ratio_to_required, "ratio_to_required"),
        "estimated_rating": layer1.rating,
        # 등급 경계 CII 4종 (`#1371`). **화면이 다시 곱하지 않게 서버가 싣는다** —
        # 종전에는 화면이 `required_cii`(표시용 6자리 문자열)를 float로 바꿔 d-vector를
        # 곱했고, 411,120건 중 87건에서 끝자리가 갈렸다(`PRD §9.3` 「내부 계산값은 화면
        # 표시 반올림값을 다시 사용하지 않는다」 · `TECH_SPEC [ORACLE-S-2]` 위반).
        # 값은 `determine_rating`이 Layer 1 컨텍스트 안에서 낸 것 그대로다.
        "rating_boundary_cii": {
            name: _publish(value, "boundary_cii") for name, value in layer1.boundaries.items()
        },
        # 등급 E는 악화 방향 경계가 없어 null이다 (#171 결론 · PRD §9.2).
        "next_worse_boundary_margin": (
            None if layer1.margin is None else _publish(layer1.margin, "margin")
        ),
        "next_worse_boundary_margin_ratio": (
            None if layer1.margin_ratio is None else _publish(layer1.margin_ratio, "margin_ratio")
        ),
        "co2_emission_ton": _publish(layer1.total_co2_t, "co2_ton"),
        "fuel_consumption_ton": _publish(layer1.fuel_total_ton, "fuel_ton"),
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

    ``REFERENCE_ONLY``는 「모든 계산 결과」라 항상 붙는다. 적용 대상 판정은
    ``services.applicability``에 위임한다 — 같은 판정을 YTD·실시간 CII·리포트가
    함께 쓰기 때문이다 (`#653`).

    **``NON_CII_VESSEL``은 GT를 알고 그것이 5,000 미만일 때만** 붙는다. GT가 NULL이면
    판정 근거가 없어 「적용 대상이 아니다」라고 단정할 수 없고, 대신
    ``CII_APPLICABILITY_UNKNOWN``이 붙어 **판정하지 못했다는 사실**을 남긴다.
    종전에는 이 경우 아무 경고도 붙지 않아, 규제상 무의미할 수 있는 계산 결과가
    아무 표시 없이 나갔다.
    """
    return [WARNING_REFERENCE_ONLY, *applicability.applicability_warnings(vessel)]
