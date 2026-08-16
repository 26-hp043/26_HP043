"""연도별 CII 이력 서비스 (#355).

선박 상세 화면(``UIFLOW §2-8``)이 표시할 **연도별 CII 이력**을 반환한다. 연도별
집계 자체는 ``#353``의 :func:`~cii_platform.services.ytd_cii.compute_ytd_cii`가
이미 하고 있으므로, 이 모듈이 맡는 것은 **창(窗口) 규칙**이다:

- 어느 연도부터 어느 연도까지 행을 만들 것인가 (기본·상한·검증)
- 각 연도가 **확정(CONFIRMED)** 인지 **진행 중(IN_PROGRESS, YTD)** 인지
- 파라미터가 없는 연도·데이터가 없는 연도를 **오류가 아니라 행**으로 내보낼 것

한 해의 수치가 틀리는 것은 ``#353``의 결함이고, 창·상태 구분이 틀리는 것이 이
모듈의 결함이다 — 그래서 연 수치는 ``compute_ytd_cii`` 위임 그대로 두고 여기서
재계산하지 않는다.

확정/진행 중의 기준은 ``as_of`` 연도다 — ``#368`` 계약 ⑵에 따라 ``resolve_as_of``
가 시각을 확정하고, 그 연도가 곧 「올해」다. 올해의 값은 연말 확정 전이므로 YTD
임을 ``status``로 표시한다(``PRD §3.3.7`` 배너 판정 기준과 같은 축).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.calc.capacity import capacity_axis
from cii_platform.calc.precision import LAYER1_ROUNDING
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import CalculationError, NotFoundError, ValidationError
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import compute_ytd_cii

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: 이력 창 상한. 연도별 집계가 이미 계산된 값을 재쓰는 조회라도 무한 창을
#: 허용하면 요청 하나가 열 개의 연도 집계를 강제한다 — 방어 상한이다.
MAX_YEAR_SPAN = 10

#: ``voyage.regulation_year``의 CHECK 하한(DB_SCHEMA §2.2)과 같은 값.
MIN_REGULATION_YEAR = 2019

#: 기본 창 크기 — 지정이 없으면 최근 3년(``to - 2`` ~ ``to``).
DEFAULT_WINDOW_YEARS = 3

STATUS_CONFIRMED = "CONFIRMED"
STATUS_IN_PROGRESS = "IN_PROGRESS"

#: 해당 연도의 규정 파라미터(``regulation_year`` 행)가 없다 — 409로 요청 전체를
#: 죽이지 않고 그 해만 ``data_available=false`` 행으로 내보낼 때의 사유 코드.
REASON_NO_REGULATION_PARAMS = "NO_REGULATION_PARAMS"

#: 파라미터는 있으나 집계할 실적이 없다.
REASON_NO_DATA = "NO_DATA"

#: 수치 직렬화 자릿수 (API_SPEC §1.7 — 문자열 직렬화).
#: ``voyage_cii.SERIALIZATION_DIGITS``와 같은 기준을 이력 필드에 맞게 재정의한다.
_DIGITS = {"cii": 6, "distance_nm": 2, "fuel_ton": 2}


def _publish(value: Decimal, digits: int) -> str:
    """정본값을 표시 자릿수 문자열로 확정한다 (표시 계약 — 계산 정밀도가 아니다)."""
    return str(value.quantize(Decimal(1).scaleb(-digits), rounding=LAYER1_ROUNDING))


def _validate_window(start: int, end: int) -> None:
    if start < MIN_REGULATION_YEAR:
        raise ValidationError(
            f"from은 {MIN_REGULATION_YEAR} 이상이어야 합니다: got {start}",
            field="from",
            field_label="시작 연도",
        )
    if start > end:
        raise ValidationError(
            f"from은 to보다 크면 안 됩니다: from={start}, to={end}",
            field="from",
            field_label="시작 연도",
        )
    if end - start + 1 > MAX_YEAR_SPAN:
        raise ValidationError(
            f"조회 창은 {MAX_YEAR_SPAN}년을 넘을 수 없습니다: {end - start + 1}년",
            field="to",
            field_label="종료 연도",
        )


def _empty_row(year: int, current_year: int, reason: str) -> dict[str, object]:
    """계산 없이 내보내는 행 — 데이터가 없는 해도 이력 축에서는 한 칸이다."""
    return {
        "regulation_year": year,
        "status": (STATUS_CONFIRMED if year < current_year else STATUS_IN_PROGRESS),
        "data_available": False,
        "reason": reason,
        "attained_cii": None,
        "required_cii": None,
        "rating": None,
        "voyage_count": 0,
        "total_distance_nm": None,
        "total_fuel_ton": None,
    }


async def _year_row(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    year: int,
    current_year: int,
) -> dict[str, object]:
    """연도 1건의 이력 행. 파라미터 확인 → YTD 집계 위임 → 상태·직렬화."""
    params = await param_repo.get_regulation_year(session, year)
    if params is None:
        return _empty_row(year, current_year, REASON_NO_REGULATION_PARAMS)

    result = await compute_ytd_cii(session, vessel_id=vessel_id, regulation_year=year)
    status = STATUS_CONFIRMED if year < current_year else STATUS_IN_PROGRESS
    if not result.data_available:
        row = _empty_row(year, current_year, REASON_NO_DATA)
        # 거리·연료는 0이어도(또는 연료만 있어도) 값 자체를 실어 화면이
        # 「없음」과 「거리 없음」을 구분할 수 있게 한다.
        row["voyage_count"] = result.voyage_count
        row["total_distance_nm"] = (
            None
            if result.total_distance_nm is None
            else _publish(result.total_distance_nm, _DIGITS["distance_nm"])
        )
        row["total_fuel_ton"] = (
            None
            if result.total_fuel_ton is None
            else _publish(result.total_fuel_ton, _DIGITS["fuel_ton"])
        )
        return row

    # data_available=True인데 수치가 비었다는 것은 ytd_cii의 불변식이 깨진 것이다 —
    # None을 그대로 직렬화하면 화면이 조용히 빈 칸을 보이므로 여기서 명시적으로 터뜨린다.
    missing = [
        name
        for name, value in (
            ("attained_cii", result.attained_cii),
            ("required_cii", result.required_cii),
            ("total_distance_nm", result.total_distance_nm),
            ("total_fuel_ton", result.total_fuel_ton),
        )
        if value is None
    ]
    if missing:
        raise CalculationError(
            f"YTD 결과 불변식 위반 — data_available=True인데 비어 있는 필드: {missing}"
        )

    return {
        "regulation_year": year,
        "status": status,
        "data_available": True,
        "reason": None,
        "attained_cii": _publish(result.attained_cii, _DIGITS["cii"]),
        "required_cii": _publish(result.required_cii, _DIGITS["cii"]),
        "rating": result.rating,
        "voyage_count": result.voyage_count,
        "total_distance_nm": _publish(result.total_distance_nm, _DIGITS["distance_nm"]),
        "total_fuel_ton": _publish(result.total_fuel_ton, _DIGITS["fuel_ton"]),
    }


async def list_cii_history(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    from_year: int | None = None,
    to_year: int | None = None,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """선박의 연도별 CII 이력을 반환한다 (API_SPEC §2.7).

    :param from_year: 시작 연도. 기본 ``to - 2`` (최근 3년 창).
    :param to_year: 종료 연도. 기본 ``as_of`` 연도(올해).
    :param as_of: 확정/진행 중 판정의 기준 시각(``#368`` 계약 ⑵). 미지정이면
        서버가 현재 시각을 확정한다. **연도 집계 자체에는 쓰지 않는다** — 집계
        컷은 각 연도 데이터의 존재 범위가 정한다.
    """
    resolved = resolve_as_of(as_of)
    current_year = resolved.year
    end = to_year if to_year is not None else current_year
    start = from_year if from_year is not None else end - (DEFAULT_WINDOW_YEARS - 1)
    _validate_window(start, end)

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")

    years = [
        await _year_row(session, vessel_id=vessel_id, year=year, current_year=current_year)
        for year in range(start, end + 1)
    ]

    return {
        "vessel_id": str(vessel_id),
        "from": start,
        "to": end,
        "as_of": resolved,
        # 표시 단위의 축 — `DESIGN_SYSTEM §4.1`이 `gCO₂/(DWT·nm)`과 `gCO₂/(GT·nm)`을
        # **선종에 따라 갈리는 값**으로 규정하고 고정 문자열을 금지한다(🔒). 화면이
        # 선종→축 매핑을 들고 있으면 선종이 늘 때 서버와 갈라지므로, 축을 정하는
        # `calc.capacity.capacity_axis`(정본 소관)의 결과를 그대로 싣는다.
        # 연도별로 달라지지 않는 선박 속성이라 최상위에 둔다.
        "transport_capacity_basis": capacity_axis(vessel.ship_type),
        "years": years,
    }
