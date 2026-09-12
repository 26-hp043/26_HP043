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

## 연료축을 여기에 붙인다 (`#769`)

``PRD §21`` 「통계 분석 — 선박별·항로별·연료별 CII 추세」 중 **연료별** 축을 이
엔드포인트의 연도 행에 실었다(``fuels``). 새 화면을 만들지 않은 이유는 셋이다 —
⑴ 선박별 축은 이 화면이 이미 연도로 열고 있고, ⑵ 항로별 축은 항만명이 자유
텍스트라 ``BUSAN``·``Busan``·``부산``이 서로 다른 항로가 되어 집계가 성립하지 않으며,
⑶ 화면 신설은 ``AGENTS §3.2.3``상 ``PRD §5`` 판정이 선행한다.

**추세는 연도 축이 만든다.** 연료별 수치를 연도 행 안에 두면 같은 표에서 연도를
가로질러 읽을 수 있고, 축이 하나 더 생기지 않는다.

확정/진행 중의 기준은 ``as_of`` 연도다 — ``#368`` 계약 ⑵에 따라 ``resolve_as_of``
가 시각을 확정하고, 그 연도가 곧 「올해」다. 올해의 값은 연말 확정 전이므로 YTD
임을 ``status``로 표시한다(``PRD §3.3.7`` 배너 판정 기준과 같은 축).
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.calc.capacity import capacity_axis
from cii_platform.calc.precision import LAYER1_ROUNDING
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import CalculationError, NotFoundError, ValidationError
from cii_platform.services.cii_current import InProgressState, resolve_in_progress_state
from cii_platform.services.request_cache import cached
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import compute_ytd_cii

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

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
_DIGITS = {"cii": 6, "distance_nm": 2, "fuel_ton": 2, "co2_ton": 2, "share_percent": 1}

#: 그램 → 톤. ``calc.annual_simulation.GRAMS_PER_TON``과 같은 값이되, 여기서는
#: **표시 단위 환산**에만 쓴다(계산은 Layer 1이 이미 끝냈다).
_GRAMS_PER_TON = Decimal(1_000_000)


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


def _fuel_rows(
    ton_breakdown: dict[str, Decimal],
    co2_breakdown_g: dict[str, Decimal] | None,
) -> list[dict[str, object]]:
    """연료축 한 해치 — 유종별 투입 톤·CO₂·비중 (`#769`).

    ``PRD §21`` 「통계 분석」의 **연료별** 축이다. 선박축은 이미 이 엔드포인트가
    연도로 열고 있고, 항로축은 항만명이 자유 텍스트라 집계가 성립하지 않는다.

    ## 비중은 CO₂ 기준이다 — 톤 기준이 아니다

    CII의 분자는 배출량이므로, **어느 연료가 등급을 끌고 있는지**를 말하려면 CO₂
    비중이어야 한다. 톤 비중으로 적으면 CF가 낮은 연료를 많이 쓴 해가 실제보다
    나빠 보인다(같은 톤이라도 LNG는 HFO보다 CO₂가 적다 — ``PRD §8.3`` CF 표).

    ## 배출을 모르는 해에도 톤은 싣는다

    거리가 0인 해는 Layer 1을 타지 않아 CO₂가 없다. 그렇다고 행을 빼면 **「정박만
    한 해」가 연료축에서 통째로 사라진다** — 연료는 실제로 들어갔는데도.
    """
    total_co2_g = sum((co2_breakdown_g or {}).values(), Decimal(0))
    rows: list[dict[str, object]] = []
    for fuel_type, ton in ton_breakdown.items():
        co2_g = (co2_breakdown_g or {}).get(fuel_type)
        rows.append(
            {
                "fuel_type": fuel_type,
                "fuel_ton": _publish(ton, _DIGITS["fuel_ton"]),
                "co2_ton": (
                    None if co2_g is None else _publish(co2_g / _GRAMS_PER_TON, _DIGITS["co2_ton"])
                ),
                "co2_share_percent": (
                    None
                    if co2_g is None or total_co2_g <= 0
                    else _publish(co2_g / total_co2_g * 100, _DIGITS["share_percent"])
                ),
            }
        )
    # 큰 것부터 — 화면이 정렬을 다시 하지 않게 서버가 순서를 정한다. 배출량이 없는
    # 해는 톤으로 견주고, 같으면 유종 이름으로 고정한다(순서가 요청마다 흔들리면
    # 표를 눈으로 대조할 수 없다).
    rows.sort(
        key=lambda row: (
            -(co2_breakdown_g or {}).get(str(row["fuel_type"]), Decimal(0)),
            -ton_breakdown[str(row["fuel_type"])],
            str(row["fuel_type"]),
        )
    )
    return rows


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
        "in_progress_voyage_count": 0,
        "total_distance_nm": None,
        "total_fuel_ton": None,
        # 연료축은 **늘 배열**이다 (`#769`). 없는 해에 `null`을 주면 화면이 배열과
        # null 둘 다를 다뤄야 하고, 한쪽을 잊으면 그 해에서만 터진다.
        "fuels": [],
    }


async def _year_row(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    year: int,
    current_year: int,
    as_of: datetime,
    in_progress: InProgressState,
) -> dict[str, object]:
    """연도 1건의 이력 행. 파라미터 확인 → YTD 집계 위임 → 상태·직렬화.

    ``in_progress``는 **그 항차가 선언한 연도의 행에만** 실린다 (`#750` · `#815`).
    다른 해에 넣으면 그 해에는 없던 항차가 확정 이력을 흔든다.
    """
    params = await cached(
        session, ("regulation_year", year), lambda: param_repo.get_regulation_year(session, year)
    )
    if params is None:
        return _empty_row(year, current_year, REASON_NO_REGULATION_PARAMS)

    result = await compute_ytd_cii(
        session,
        vessel_id=vessel_id,
        regulation_year=year,
        as_of=as_of,
        # **그 해에 속하는 진행분만** 넣는다 (`#815`). `#750`은 「올해 행에만」이라는
        # 약한 기준을 썼는데, 그것은 진행 중 항차가 늘 올해 것이라는 가정에 기댄다.
        in_progress=in_progress.for_year(year).contribution,
    )
    status = STATUS_CONFIRMED if year < current_year else STATUS_IN_PROGRESS
    if not result.data_available:
        row = _empty_row(year, current_year, REASON_NO_DATA)
        # 거리·연료는 0이어도(또는 연료만 있어도) 값 자체를 실어 화면이
        # 「없음」과 「거리 없음」을 구분할 수 있게 한다.
        row["voyage_count"] = result.voyage_count
        row["in_progress_voyage_count"] = result.in_progress_voyage_count
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
        # 거리가 0이라 CII는 못 내도 **연료는 들어갔을 수 있다**(정박만 한 해).
        row["fuels"] = _fuel_rows(result.fuel_ton_breakdown, result.fuel_breakdown_g)
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
        # 서버 결함이다 — 사용자에게는 VAL-008 원문만, 어느 필드가 비었는지는 로그로 (#999).
        _log.error("YTD 결과 불변식 위반 — data_available=True인데 비어 있는 필드: %s", missing)
        raise CalculationError("계산 오류: 입력값을 확인하세요.")

    return {
        "regulation_year": year,
        "status": status,
        "data_available": True,
        "reason": None,
        "attained_cii": _publish(result.attained_cii, _DIGITS["cii"]),
        "required_cii": _publish(result.required_cii, _DIGITS["cii"]),
        "rating": result.rating,
        "voyage_count": result.voyage_count,
        # 거리·연료에 들어간 진행분을 센다 — 없으면 한 행 안에서 검산이 안 맞는다 (`#800`).
        "in_progress_voyage_count": result.in_progress_voyage_count,
        "total_distance_nm": _publish(result.total_distance_nm, _DIGITS["distance_nm"]),
        "total_fuel_ton": _publish(result.total_fuel_ton, _DIGITS["fuel_ton"]),
        "fuels": _fuel_rows(result.fuel_ton_breakdown, result.fuel_breakdown_g),
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
    :param as_of: 기준 시각(``#368`` 계약 ⑵). 미지정이면 서버가 현재 시각을 확정한다.
        확정/진행 중 판정에 쓰고, **올해 행의 집계 컷으로도 쓴다** (`#750`).

    ## 올해 행은 진행 중 항차 기여분을 포함한다 (`PRD §3.3.8`, `#750`)

    종전에는 :func:`compute_ytd_cii`에 ``as_of``도 ``in_progress``도 넘기지 않아
    **실적 확정분만** 집계했다. 같은 선박·같은 연도를 두고 실시간 CII 화면은 진행분을
    포함한 값을, 이 이력은 포함하지 않은 값을 냈다 — 심사에서 대시보드 → 선박 상세 →
    실시간 CII로 드릴다운하면 **같은 라벨의 숫자가 설명 없이 바뀌었다.**

    ``PRD §3.3.8``이 정본이다. ``INCLUDE_AS_PLAN``의 계획 전량은 넣지 않되, ``§8.3``이
    요구하는 ``IN_PROGRESS latest estimate``(경과 시간에서 산출)는 넣는다.

    **과거 연도는 영향이 없다** — 진행 중 항차는 올해에만 존재한다.

    ``as_of``를 함께 넘기는 것도 같은 이유다. 종전에는 「확정/진행 중」은 ``as_of``로
    판정하면서 집계는 연도 전체를 훑어, 상태와 숫자가 다른 시점을 가리켰다.
    """
    resolved = resolve_as_of(as_of)
    current_year = resolved.year
    end = to_year if to_year is not None else current_year
    start = from_year if from_year is not None else end - (DEFAULT_WINDOW_YEARS - 1)
    _validate_window(start, end)

    vessel = await cached(
        session, ("vessel", vessel_id), lambda: vessel_repo.get_by_id(session, vessel_id)
    )
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")

    # 진행분은 **한 번만** 구해 올해 행에 넘긴다 — 연도마다 다시 구하면 같은 값을
    # 연도 수만큼 조회하게 되고, 과거 연도에는 쓰이지도 않는다.
    state = await resolve_in_progress_state(session, vessel=vessel, as_of=resolved)

    years = [
        await _year_row(
            session,
            vessel_id=vessel_id,
            year=year,
            current_year=current_year,
            as_of=resolved,
            in_progress=state,
        )
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
