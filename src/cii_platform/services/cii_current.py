"""실시간 CII 3종 값 서비스 (API_SPEC §2.14, #354).

실시간 화면(``UIFLOW 2-9``)이 표시할 값 셋을 **한 번의 호출로** 반환한다.

## 왜 3종인가 (``PRD §3.3`` 표)

===  ==========================  ==========  ==================================
 #    값                          등급         화면 표기
===  ==========================  ==========  ==================================
 ⑴   **연간 누적 (YTD)**          **가능**    「현재 누적 기준 예상 등급」 · 주 표시
 ⑵   항차 구간값                  **불가**    「항차 CII 기여도」 (``COR-1``)
 ⑶   연말 예상                    가능        「연말 예상 등급」 · 보조 표시
===  ==========================  ==========  ==================================

**등급이 붙는 값은 ⑴이 유일한 규제 지표**라서다. ⑵는 항차 하나의 효율 참고값이라
등급 경계와 비교할 대상이 아니고, ⑶은 가정에 의존하는 추정이라 ``COR-2``가 표기를
「연말 예상 등급」으로 못박는다.

## 계산식을 새로 만들지 않는다

⑴과 ⑶은 모두 ``#353``의 :func:`~cii_platform.services.ytd_cii.compute_ytd_cii`를
**그대로 부른다.** 다른 것은 주입하는 ``InProgressContribution``뿐이다 —

* ⑴ ← ``#368`` 시뮬레이션 시계가 확정한 **지금까지의** 누적
* ⑶ ← 거기에 **남은 기간의 외삽분을 더한** 누적

같은 함수를 두 번 부르는 것이 두 번째 계산식을 쓰는 것보다 안전하다. 식이 갈리면
「⑴은 C인데 ⑶이 이미 C보다 좋다」 같은 모순이 조용히 생긴다.

⑵는 항차 구간만의 ``M``/``W``라 ``calculate_attained_cii``를 직접 부른다.

## 시각은 한 번만 확정한다

화면이 여러 값을 동시에 보는데 기준 시점이 어긋나면 셋이 서로 모순된다. 이
서비스는 ``resolve_as_of``로 시각을 **한 번** 확정하고 응답에 실어 보낸다
(``#368`` 계약 ⑵·⑶). 화면은 그 값으로 다시 물어 같은 결과를 얻을 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.annual_simulation import RemainingVoyage, project_deterministic
from cii_platform.calc.capacity import capacity_axis
from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii
from cii_platform.calc.precision import (
    SERIALIZATION_ROUNDING,
    layer1_context,
)
from cii_platform.calc.rating_engine import (
    calculate_deterministic_risk,
    calculate_margin_ratio,
    select_next_worse_boundary,
)
from cii_platform.db.repositories import not_underway as not_underway_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import CalculationError, NotFoundError, ValidationError
from cii_platform.services.annual_simulation import (
    _inputs_from_snapshot,
    collect_annual_inputs,
    load_projection_context,
)
from cii_platform.services.request_cache import as_of_key, cached
from cii_platform.services.simulation_clock import (
    NotUnderwayWindow,
    compute_progress,
    resolve_as_of,
)
from cii_platform.services.ytd_cii import (
    WARNING_REFERENCE_ONLY,
    InProgressContribution,
    compute_ytd_cii,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: 수치 직렬화 자릿수 (``API_SPEC §1.7``). ``cii_history``와 같은 기준이다.
_DIGITS = {"cii": 6, "ratio": 5, "distance_nm": 2, "fuel_ton": 2, "co2_ton": 2, "hours": 4}

#: ``voyage.regulation_year``의 CHECK 하한(``DB_SCHEMA §2.2``).
MIN_REGULATION_YEAR = 2019
MAX_REGULATION_YEAR = 2100

#: ⑶의 외삽 근거가 없다 — 올해 실적이 아직 없어 일평균을 낼 수 없다.
REASON_NO_BASIS = "NO_BASIS"

#: 선박에 ``reference_daily_foc_ton``이 없어 시뮬레이션 시계가 연료를 만들지
#: 못했다. 그래서 진행 중 항차분을 YTD에 **넣지 않았다** — 거리만 넣으면 항해할수록
#: 등급이 좋아지는 쪽으로 틀린다. 화면은 이 코드를 보고 제원 입력을 안내한다.
WARNING_SIM_NO_FUEL_RATE = "SIMULATION_NO_FUEL_RATE"

#: 진행 중 항차의 유종을 알 수 없다(항차 연료 기록도 선박 기본 연료도 없음).
#: CF를 붙일 수 없어 같은 이유로 진행분을 넣지 않았다.
WARNING_SIM_NO_FUEL_TYPE = "SIMULATION_NO_FUEL_TYPE"

#: 기준 속도가 없어 진행분 연료에 cubic speed model 보정을 못 했다
#: (`TECH_SPEC §12.3`, #796).
#:
#: 배수 1로 쌓되 **조용히 넘어가지 않는다.** 소모율도 속도도 있고 모르는 것이
#: 보정 계수 하나뿐이라 기여를 통째로 빼지는 않지만, 값이 정확하지 않다는 사실은
#: 화면이 말할 수 있어야 사용자가 제원을 채운다 — `SIMULATION_NO_FUEL_RATE`와
#: 같은 방식이다.
WARNING_SIM_NO_REFERENCE_SPEED = "SIMULATION_NO_REFERENCE_SPEED"

#: 진행 중 항차가 **도착 예정일을 지났는데 도착 실적이 없다** (`#649`).
#: 누적은 예정일까지만 반영했다 — 상한이 없으면 계획을 아무리 넘겨도 거리·연료가
#: 계속 자란다(출항 90일 뒤면 계획의 7배). 실사용에서 이 상태는 「운항이 계속되고
#: 있다」가 아니라 **「도착 실적 입력을 잊었다」**이므로, 값을 자르는 것만으로는
#: 부족하고 **왜 멈췄는지**를 함께 알려야 한다.
WARNING_IN_PROGRESS_PAST_ETA = "IN_PROGRESS_PAST_ETA"
WARNING_IN_PROGRESS_PLANNED_DISTANCE_REACHED = "IN_PROGRESS_PLANNED_DISTANCE_REACHED"

#: ⑶을 낼 수 없다 — 연말이 지났거나 ``as_of``가 연말이다. 남은 기간이 0이면
#: 잔여 계획도 남지 않아 ⑶은 ⑴과 같은 값이 되고, 따로 낼 이유가 없다.
REASON_YEAR_COMPLETE = "YEAR_COMPLETE"

#: ⑶의 산출 방식 (`API_SPEC §2.7`, #798).
#:
#: 종전 값은 ``"YTD_DAILY_AVERAGE"``였다 — 지금까지의 **일평균**을 잔여 기간에 그대로
#: 곱하는 방식이다. 거리와 연료를 **같은 비율로** 더하므로 ``M/W``가 보존되어 ⑶이
#: **구조적으로 ⑴과 항상 같은 값**이 됐다(데모 4척 전부에서 실측). 예측이 아무 정보를
#: 주지 못했고, 리포트는 같은 숫자를 「2026년 누적」과 「연말 예상」 두 제목으로
#: 나란히 인쇄했다 — `PRD §3.3.8`이 요구한 「구분해 표시」가 성립하지 않았다.
#:
#: 그 이름은 정본 어디에도 근거가 없었다(`API_SPEC` 응답 **예시에만** 있었다).
#: `PRD §5.1`·사용자 여정은 **「남은 거리 기반」**을 규정한다.
PROJECTION_METHOD = "REMAINING_PLAN"

#: 잔여 계획 항차가 0건이라 ⑶이 ⑴과 같은 값이다 (`TECH_SPEC §12.3`, #798).
#:
#: **값을 내지 않는 것이 아니라 값의 성격을 말한다.** 잔여 계획이 없으면 「연말 =
#: 지금」이 맞는 답이고, 빈칸을 두면 「아직 로딩 중」으로 읽힌다. 다만 그 답과
#: 종전 결함(항상 ⑴과 같음)은 화면에서 구분되지 않으므로, **왜 같은지**를 말한다.
WARNING_NO_REMAINING_PLAN = "PROJECTION_NO_REMAINING_PLAN"

#: ⑶ 연말 예상을 무엇이 올리는가 — ``year_end_projection.drivers[]``의 키 (`#1673` ·
#: `API_SPEC §2.14` · `PRD §12.3`). **시간 순으로 하나씩 더한 누적 분해**다.
#:
#: CII는 비율이라 요인을 나누는 순서에 따라 값이 달라진다. 그래서 순서를 시간 순서로
#: 고정한다 — ⑴ 올해 누적에서 시작해, 진행 중 항차의 남은 몫을 더하고, 남은 계획 항차를
#: 더한다. 각 단계는 :func:`project_deterministic`을 한 번 더 부르는 것이라 **새 가정이
#: 들어가지 않고**, 단계별 변화의 합은 정의상 정확히 「⑶ − ⑴」이다.
#:
#: * ``BASIS_DIFFERENCE`` — ⑶의 조립(확정 항차 + 정박 몫 + 진행 중 항차의 **경과분**)으로
#:   ⑴을 다시 만든 값과 ⑴의 차이. 두 조립이 같은 집합을 세면 0이고 **그때는 싣지 않는다.**
#:   다른 요인에 녹이지 않고 따로 두는 것은, 숨기면 합은 맞아도 설명이 틀리기 때문이다.
#: * ``CURRENT_VOYAGE`` — 진행 중 항차의 경과분을 ⑶이 세는 **계획 전량**으로 바꿨을 때의
#:   변화. 「남은 몫」 = 계획 전량 − 경과분이다. 경과분이 계획 거리 상한에 닿은 뒤에는
#:   거리는 같고 연료만 다르므로(시계 cubic 연료 vs 계획 연료) **음수도 양수도 가능**하다.
#:   진행 중 항차가 ⑴에도 ⑶에도 없으면 싣지 않는다.
#: * ``REMAINING_PLAN`` — 남은 계획 항차를 더했을 때의 변화. ⑴이 있으면 **항상** 싣는다 —
#:   잔여 계획이 0건이면 ``"0.000000"``이고 ``PROJECTION_NO_REMAINING_PLAN``이 그 뜻을 말한다.
DRIVER_BASIS_DIFFERENCE = "BASIS_DIFFERENCE"
DRIVER_CURRENT_VOYAGE = "CURRENT_VOYAGE"
DRIVER_REMAINING_PLAN = "REMAINING_PLAN"


def _publish(value: Decimal | None, kind: str) -> str | None:
    """``API_SPEC §1.7`` 문자열 직렬화. ``float``으로 되돌리면 정밀도가 사라진다.

    **모든 종류를 절사한다** (`#1349` → `#1600`). 이 표의 종류는 전부 전송 자릿수가 표시
    자릿수보다 크다 — CII 6>3 · 비율 5>백분율 1(소수 3) · 거리·일수 2>0 · 연료·CO₂ 2>1 ·
    시간 4>1. 절사는 화면의 표시 반올림과 겹쳐 두 번 반올림되는 것을 막는 장치다
    (`TECH_SPEC §1.2.1` 「응답 직렬화의 절사」).
    """
    if value is None:
        return None
    return str(_truncate(value, kind))


def _truncate(value: Decimal, kind: str) -> Decimal:
    """종류별 전송 자릿수로 절사한 ``Decimal``. :func:`_publish`가 문자열로 만들기 직전의 값이며,
    연말 예상 분해(`#1673`)가 **같은 절사**를 문자열이 아닌 수로 쓴다."""
    return value.quantize(Decimal(1).scaleb(-_DIGITS[kind]), rounding=SERIALIZATION_ROUNDING)


def _validate_year(year: int) -> None:
    if not MIN_REGULATION_YEAR <= year <= MAX_REGULATION_YEAR:
        raise ValidationError(
            f"규제연도는 {MIN_REGULATION_YEAR}~{MAX_REGULATION_YEAR} 범위여야 합니다.",
            field="year",
            field_label="규제연도",
        )


# ─── ⑴ 연간 누적 (YTD) ───────────────────────────────────────────────────────


def _ytd_to_dict(ytd) -> dict[str, object]:
    """``YtdCiiOutput`` → 응답 ⑴.

    **등급이 붙는 유일한 값**이다(``PRD §3.3`` 표). ``data_available``가 거짓이면
    수치는 전부 ``null``이고, 그것은 오류가 아니라 「올해 실적이 아직 없다」는 뜻이다.
    """
    return {
        "data_available": ytd.data_available,
        "attained_cii": _publish(ytd.attained_cii, "cii"),
        "required_cii": _publish(ytd.required_cii, "cii"),
        "ratio_to_required": _publish(ytd.ratio_to_required, "ratio"),
        "rating": ytd.rating,
        "risk_level": ytd.risk_level,
        "margin_ratio": _publish(ytd.margin_ratio, "ratio"),
        "boundaries": (
            None
            if ytd.boundaries is None
            else {key: _publish(value, "cii") for key, value in ytd.boundaries.items()}
        ),
        "total_co2_ton": _publish(ytd.total_co2_t, "co2_ton"),
        "total_fuel_ton": _publish(ytd.total_fuel_ton, "fuel_ton"),
        #
        # 정박 몫 (`#1658`). 화면은 **이 값이 0보다 클 때만** 「정박이 등급을 밀고 있다」고
        # 그린다 — 구간 수만 보면 연료가 없는 구간도 악화로 그려진다(`UIFLOW 2-9`의 구분
        # 기준은 「정박 연료 기록」이다). 값은 계층 1이 이미 계산한 것을 옮길 뿐이다.
        #
        "not_underway_fuel_ton": _publish(ytd.not_underway_fuel_ton, "fuel_ton"),
        "not_underway_co2_ton": _publish(
            None if ytd.not_underway_co2_g is None else ytd.not_underway_co2_g / Decimal(1_000_000),
            "co2_ton",
        ),
        "underway_distance_nm": _publish(ytd.underway_distance_nm, "distance_nm"),
        "not_underway_distance_nm": _publish(ytd.not_underway_distance_nm, "distance_nm"),
        "total_distance_nm": _publish(ytd.total_distance_nm, "distance_nm"),
        "voyage_count": ytd.voyage_count,
        "in_progress_voyage_count": ytd.in_progress_voyage_count,
        "not_underway_period_count": ytd.not_underway_period_count,
        #
        # 대체 내역 (#449). 경고(`warnings`)는 「있었다」만 말한다 — **무엇을 고쳐야
        # 하는지는 어느 항차의 무엇이 대체됐는지를 알아야** 나온다.
        #
        "substitutions": [
            {
                "voyage_id": str(item.voyage_id),
                "axis": item.axis,
                "fuel_type": item.fuel_type,
            }
            for item in ytd.substitutions
        ],
    }


# ─── ⑵ 항차 구간값 ───────────────────────────────────────────────────────────


def _voyage_segment(
    *,
    voyage,
    progress,
    transport_capacity: Decimal,
    cf_by_fuel: dict[str, Decimal],
    fuel_code: str | None,
    fuel_split: FuelSplit | None = None,
) -> dict[str, object]:
    """진행 중 항차 **구간만**의 CII (``PRD §3.3`` ⑵ · ``COR-1``).

    **등급을 붙이지 않는다.** 등급 경계는 연간 누적 지표에 대해 정의된 것이고,
    항차 하나에 갖다 대면 「이 항차는 D등급」이라는 규제에 없는 말이 만들어진다.

    거리나 연료가 0이면 ``attained_cii``는 ``null``이다 — 분모 0을 계산으로
    밀어 넣지 않는다. 출항 직후가 정상적으로 그 상태이며, 오류가 아니다.
    """
    base: dict[str, object] = {
        "voyage_id": str(voyage.id),
        "voyage_no": voyage.voyage_no,
        "status": voyage.status,
        "departure_port_name": voyage.departure_port_name,
        "arrival_port_name": voyage.arrival_port_name,
        "planned_distance_nm": _publish(voyage.planned_distance_nm, "distance_nm"),
        "underway_hours": _publish(progress.underway_hours, "hours"),
        "distance_nm": _publish(progress.distance_nm, "distance_nm"),
        "fuel_ton": _publish(progress.fuel_ton, "fuel_ton"),
        "fuel_type": fuel_code,
        "is_simulated": progress.is_simulated,
        # 등급이 없다는 것을 **응답에 명시**한다. 필드를 빼면 화면이 「아직 안 온
        # 값」으로 오해해 기다리거나, 스스로 등급을 만들어 낸다.
        "rating": None,
        "attained_cii": None,
        "co2_ton": None,
    }

    split = fuel_split or (((fuel_code, Decimal(1)),) if fuel_code is not None else ())
    if not split or any(code not in cf_by_fuel for code, _ in split):
        # 유종을 모르면 CO₂를 만들 수 없다. 임의의 CF를 넣으면 화면은 깨지지 않고
        # 값만 틀린다.
        return base
    if progress.distance_nm <= 0 or progress.fuel_ton <= 0:
        return base

    result = calculate_attained_cii(
        # YTD 기여분과 **같은 몫**으로 나눈다 (`#885`). 한쪽만 나누면 같은 항차의 구간
        # CO₂와 누적에 들어간 CO₂가 설명 없이 다르다.
        fuel_uses=[
            FuelUse(fuel_code=code, fuel_ton=ton, cf_value=cf_by_fuel[code])
            for code, ton in _split_fuel(progress.fuel_ton, split)
        ],
        transport_capacity=transport_capacity,
        distance_nm=progress.distance_nm,
    )
    base["attained_cii"] = _publish(result.attained_cii, "cii")
    base["co2_ton"] = _publish(result.total_co2_t, "co2_ton")
    return base


# ─── ⑶ 연말 예상 ─────────────────────────────────────────────────────────────


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    """규제연도의 시작·끝(UTC). 끝은 **다음 해 1월 1일 00:00**(열린 경계)이다."""
    return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)


def _remaining_days(*, as_of: datetime, regulation_year: int) -> Decimal:
    """규제연도의 잔여 일수. ``as_of``가 그 해 밖이면 경계로 자른다.

    과거 연도를 조회하면 연중 어느 시점이 아니라 **그 해 전체**가 대상이므로 0이다.
    """
    year_start, year_end = _year_bounds(regulation_year)
    cursor = min(max(as_of, year_start), year_end)
    return Decimal(str((year_end - cursor).total_seconds())) / Decimal("86400")


@layer1_context
def _project_layer1(context, inputs) -> tuple[object, Decimal, str]:
    """⑶의 Layer 1 전 구간을 **한 컨텍스트 안에서** 낸다 (`TECH_SPEC §1.2.1` · `#1372`).

    종전에는 ``ratio``를 이 컨텍스트 **밖에서** 나눴다. 나눗셈은 컨텍스트 precision에서
    잘리므로 기본값(``prec=28``)으로 계산되어 정본과 **27번째 자리부터 갈렸다** —
    실측 ``…012600`` vs 정본 ``…012581``. 응답 자릿수(5자리)에서는 드러나지 않지만,
    「자릿수가 맞다고 정밀도가 맞는 것은 아니다」가 `TECH_SPEC §1.2.1`의 경고다.

    ``voyage_cii._compute_layer1`` · ``ytd_cii``와 같은 틀이다 — 함수를 나누어 각각
    데코레이터를 달면 컨텍스트를 들락거리며 중간값이 기본 컨텍스트에서 다뤄진다.

    :raises ValueError: 거리가 0일 때 :func:`project_deterministic`이 올린다.
    """
    deterministic = project_deterministic(
        completed=inputs.completed,
        remaining=inputs.remaining,
        transport_capacity=context.transport_capacity,
        required_cii=context.required_cii,
        d_vector=context.d_vector,
    )
    ratio = deterministic.attained_cii / context.required_cii
    # 위험도는 ⑴과 **같은 방식**(마진 기반)으로 낸다. 기능③의 `risk_level`은 목표
    # 달성 확률 기반이라 여기 쓰면 같은 열 이름에 다른 척도가 섞인다.
    next_worse = select_next_worse_boundary(deterministic.rating, deterministic.boundaries)
    margin_ratio = (
        None
        if next_worse is None
        else calculate_margin_ratio(
            attained_cii=deterministic.attained_cii,
            required_cii=context.required_cii,
            next_worse_boundary=next_worse,
        )
    )
    return deterministic, ratio, calculate_deterministic_risk(deterministic.rating, margin_ratio)


def _cii_step(value: Decimal) -> Decimal:
    """분해의 한 단계 누적값을 **전송 자릿수로 먼저** 절사한다 (`#1673`).

    합이 「⑶ − ⑴」과 **문자열 단위로** 같으려면 차이를 절사하는 것이 아니라 **각 단계의
    누적값을 절사한 뒤 빼야** 한다. 차이를 따로 절사하면 단계마다 최대 1 ulp가 버려져
    합이 문자열 차이와 2 ulp까지 어긋난다. 누적값을 먼저 절사하면 합은 망원경처럼 접혀
    ``trunc(⑶) − trunc(⑴)``, 즉 응답에 실린 두 문자열의 차이 그 자체가 된다.
    """
    return _truncate(value, "cii")


def _year_end_drivers(
    context,
    inputs,
    deterministic,
    *,
    ytd_attained_cii: Decimal | None,
    current_voyage_id: UUID | None,
    contribution: InProgressContribution | None,
    cf_by_fuel: dict[str, Decimal],
) -> list[dict[str, str]]:
    """⑶을 무엇이 올리는지 **시간 순 누적 분해**로 나눈다 (`#1673` · :data:`DRIVER_REMAINING_PLAN`).

    .. code-block:: text

        S0  = ⑴ 올해 누적                                    (응답 ytd.attained_cii)
        S0' = 확정분 + 진행 중 항차 경과분   ← ⑶의 조립으로 ⑴을 다시 만든 값
        S1  = 확정분 + 진행 중 항차 계획 전량
        S2  = 확정분 + 진행 중 항차 계획 전량 + 남은 계획     (응답 attained_cii)

        BASIS_DIFFERENCE = S0' − S0     (0이면 싣지 않는다)
        CURRENT_VOYAGE   = S1  − S0'    (⑴·⑶ 어느 쪽도 세지 않는 진행 항차면 싣지 않는다)
        REMAINING_PLAN   = S2  − S1

    각 값은 :func:`_cii_step`으로 **먼저 절사한 뒤** 뺀다 — 합이 응답의 두 문자열 차이와
    정확히 같아지는 유일한 방식이다.

    **S1을 만들 수 없는 상태가 하나 있다** — 확정 거리가 0이고 ⑶이 진행 중 항차를 세지
    않을 때(계획 연료가 없어 `#812`로 뺐다). 그때 S1은 「거리 0」이라 CII가 정의되지 않으므로
    ``CURRENT_VOYAGE``를 싣지 않고 ``REMAINING_PLAN = S2 − S0'``로 잇는다 — 사슬을 끊지 않아
    합은 그대로 ⑶ − ⑴이고, 진행 항차가 빠졌다는 사실은 ⑶의 ``SIMULATION_PLAN_NO_FUEL``이
    말한다. ``[]``로 비우면 ⑴·⑶이 둘 다 있는데 「분해할 것이 없다」로 읽힌다.

    **⑴이 없으면 빈 목록이다.** 출발점이 없는데 분해를 만들면 「합 = ⑶ − ⑴」이 성립할
    자리가 없다. 확정 실적 없이 계획만 있는 선박이 그 상태이며, 그때 ⑶ 전체가 계획이다.

    확정분(``inputs.completed``)은 ⑶이 이미 만든 것을 그대로 쓴다. 진행 중 항차의 계획
    전량은 같은 스냅샷 사본에서 **그 항차의 PLAN 행만** 골라 같은 조립 함수로 만든다 —
    행이 없으면(연료를 몰라 `#812`가 뺐거나 정책이 ``INCLUDE_AS_PLAN``이 아니면) ⑶이 그
    항차를 세지 않는 것이고, 그 사실이 ``CURRENT_VOYAGE``에 그대로 드러난다.
    """
    if ytd_attained_cii is None:
        return []

    elapsed: list[RemainingVoyage] = []
    if contribution is not None:
        fuel_ton = sum((ton for _, ton in contribution.fuel_uses), Decimal(0))
        co2 = sum((ton * cf_by_fuel[code] for code, ton in contribution.fuel_uses), Decimal(0))
        # ⑶의 조립(`_inputs_from_snapshot`)과 같은 모양이다 — 연료를 CO₂ 기여로 합쳐
        # 유효 CF 하나로 만들고 마지막에 float로 내린다.
        elapsed.append(
            RemainingVoyage(
                distance_nm=float(contribution.distance_nm),
                fuel_ton=float(fuel_ton),
                cf=float(co2 / fuel_ton),
            )
        )

    current_rows = [
        row
        for row in inputs.voyages_json
        if current_voyage_id is not None
        and row.get("kind") == "PLAN"
        and row.get("voyage_id") == str(current_voyage_id)
    ]
    _completed, current_full, _warnings = _inputs_from_snapshot(current_rows, context.vessel)

    def step(remaining: list[RemainingVoyage]) -> Decimal:
        return _cii_step(
            project_deterministic(
                completed=inputs.completed,
                remaining=remaining,
                transport_capacity=context.transport_capacity,
                required_cii=context.required_cii,
                d_vector=context.d_vector,
            ).attained_cii
        )

    try:
        basis = step(elapsed)
    except ValueError:  # pragma: no cover - ⑴이 있으면 같은 거리가 여기에도 있다
        return []
    try:
        with_current: Decimal | None = step(current_full)
    except ValueError:
        # 확정 거리 0인데 ⑶이 진행 중 항차를 세지 않는다 — S1은 거리 0이라 정의되지 않는다.
        with_current = None

    start = _cii_step(ytd_attained_cii)
    end = _cii_step(deterministic.attained_cii)

    drivers: list[dict[str, str]] = []
    if basis != start:
        drivers.append({"key": DRIVER_BASIS_DIFFERENCE, "delta_cii": str(basis - start)})
    if with_current is not None and (contribution is not None or current_rows):
        drivers.append({"key": DRIVER_CURRENT_VOYAGE, "delta_cii": str(with_current - basis)})
    previous = basis if with_current is None else with_current
    drivers.append({"key": DRIVER_REMAINING_PLAN, "delta_cii": str(end - previous)})
    return drivers


async def _project_year_end(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int,
    as_of: datetime,
    ytd_attained_cii: Decimal | None = None,
    in_progress: InProgressState | None = None,
    cf_by_fuel: dict[str, Decimal] | None = None,
) -> dict[str, object]:
    """⑶ 연말 예상 — **확정 실적 + 잔여 계획 항차**로 낸다 (`PRD §5.1`, #798).

    ## 종전 방식과 무엇이 다른가

    종전에는 ``YTD_DAILY_AVERAGE``였다 — 지금까지의 일평균을 잔여 기간에 곱해
    ⑴에 더했다.

    .. code-block:: text

        daily_distance = YTD_Dt / elapsed_days
        daily_fuel     = YTD_M  / elapsed_days
        projected      = (YTD_M + daily_fuel × remaining)
                       / (cap × (YTD_Dt + daily_distance × remaining))
                       = YTD_M / (cap × YTD_Dt)          ← 강도가 보존된다

    **거리와 연료를 같은 비율로 더하므로 ``M/W``가 변하지 않는다.** 그래서 ⑶이
    구조적으로 ⑴과 **항상 같은 값**이었다 — 데모 4척 전부에서 실측됐다. 예측이
    아무 정보를 주지 못했고, 연간 리포트는 같은 숫자를 「누적」과 「연말 예상」 두
    제목으로 나란히 인쇄했다(``PRD §3.3.8``의 「구분해 표시」가 성립하지 않았다).

    지금은 **DB에 등록된 잔여 계획 항차의 실제 거리·연료**를 쓴다. 비가 달라지므로
    ⑶이 ⑴과 갈린다.

    ## 왜 기능③과 같은 함수를 부르는가

    같은 이름의 값이 두 화면에서 **다른 숫자**였다(`#798` 실측: 7.654488 vs
    8.971119). 실시간 CII는 진행 중 항차를 경과분만 세고 잔여 계획을 통째로
    무시했으며, 기능③은 진행 중 항차를 계획 전량으로 셌다.

    ``annual_simulation``의 :func:`load_projection_context`·
    :func:`collect_annual_inputs`·``project_deterministic``을 그대로 부르면 **값이
    갈릴 수 없다.** 「이름을 다르게 붙인다」는 대안은 *같은 질문에 두 답을 준다*는
    문제를 그대로 남긴다.

    ## 진행 중 항차의 경과분을 ⑶에 쓰지 않는 이유

    ⑶은 진행 중 항차를 **계획 전량**으로 센다(기능③과 같다). ⑴이 쓰는 경과 누적은
    측정값이 아니라 **계획에서 나온 모델값**이다 — 시뮬레이션 시계(`#368`)가
    ``planned_speed_kn``·``reference_daily_foc_ton``으로 만든다. 따라서
    ``경과 누적 + 잔여 계획 ≈ 계획 전량``이고, 둘이 실질적으로 갈리는 것은 실적이
    입력된 항차뿐인데 그런 항차는 ``INCLUDE_AS_ACTUAL``로 넘어가 확정분에 들어간다.

    쪼개는 대안은 ``RemainingVoyage``의 거리·연료를 깎아야 하는데, 그 목록이 기능③
    **Monte Carlo 표본추출의 입력**이자 ``simulation_snapshot``의 근거다. 재현성
    계약(`#816`)이 열려 있는 경로라 이 이슈에서 건드리지 않는다.

    ## 무엇이 올리는지를 함께 싣는다 (`#1673`)

    「연말 예상이 D」라는 결론만 주면 사용자가 할 수 있는 일이 없다. ``drivers[]``가
    ⑴에서 ⑶까지를 **시간 순으로** 나눈다 — 이 항해를 마치면 얼마, 남은 계획까지 하면
    얼마(:func:`_year_end_drivers`). 위 문단의 「경과분 대신 계획 전량」이 정확히 첫 단계
    ``CURRENT_VOYAGE``이고, 재현성 계약 경로(스냅샷·해시)는 그대로다 — 분해는 같은
    엔진을 읽기 전용으로 더 부를 뿐이다. ⑴·``in_progress``·``cf_by_fuel``을 받는 것은
    그 때문이며, 셋이 없으면(다른 호출자) 분해만 비운다.

    ## 잔여 계획이 0건이면

    **값을 내되 그 사실을 말한다.** 잔여 계획이 없으면 「연말 = 지금」이 맞는 답이고,
    빈칸을 두면 「아직 로딩 중」으로 읽힌다. 다만 그 답은 종전 결함(항상 ⑴과 같음)과
    화면에서 구분되지 않으므로 :data:`WARNING_NO_REMAINING_PLAN`을 함께 싣는다.
    """
    remaining_days = _remaining_days(as_of=as_of, regulation_year=regulation_year)
    if remaining_days <= 0:
        return {"data_available": False, "reason": REASON_YEAR_COMPLETE}

    context = await load_projection_context(
        session, vessel_id=vessel_id, regulation_year=regulation_year
    )
    inputs = await collect_annual_inputs(
        session,
        vessel=context.vessel,
        vessel_id=vessel_id,
        year=regulation_year,
        as_of=as_of,
    )

    try:
        deterministic, ratio, risk = _project_layer1(context, inputs)
    except ValueError:
        # 거리가 0이면 ``PRD §12.8``이 계산 중단을 규정한다. ⑶은 조회 응답의 한
        # 갈래이므로 500으로 올리지 않고 **못 낸 사유를 싣는다.**
        return {"data_available": False, "reason": REASON_NO_BASIS}

    warnings = list(inputs.warnings)
    if inputs.plan_voyage_count == 0:
        warnings.append(WARNING_NO_REMAINING_PLAN)

    return {
        "data_available": True,
        "reason": None,
        "attained_cii": _publish(deterministic.attained_cii, "cii"),
        "required_cii": _publish(context.required_cii, "cii"),
        "ratio_to_required": _publish(ratio, "ratio"),
        "rating": deterministic.rating,
        "risk_level": risk,
        "warnings": sorted(set(warnings)),
        # 가정을 함께 싣는다 — `PRD §3.3` ⑶이 요구한다. 「⑶만 단독으로 크게
        # 표시하지 않는다」를 화면이 지키려면 근거가 응답에 있어야 한다.
        "assumptions": {
            "method": PROJECTION_METHOD,
            "remaining_days": _publish(remaining_days, "distance_nm"),
            "remaining_voyage_count": inputs.plan_voyage_count,
            "planned_distance_nm": _publish(deterministic.planned_distance_nm, "distance_nm"),
            "planned_co2_ton": _publish(
                deterministic.planned_co2_g / Decimal(1_000_000), "fuel_ton"
            ),
            "completed_distance_nm": _publish(deterministic.completed_distance_nm, "distance_nm"),
            "completed_co2_ton": _publish(
                deterministic.completed_co2_g / Decimal(1_000_000), "fuel_ton"
            ),
        },
        # 무엇이 올리는가 (`#1673`). 합은 정확히 ``attained_cii − ytd.attained_cii``다.
        "drivers": _year_end_drivers(
            context,
            inputs,
            deterministic,
            ytd_attained_cii=ytd_attained_cii,
            current_voyage_id=(
                None if in_progress is None or in_progress.voyage is None else in_progress.voyage.id
            ),
            contribution=None if in_progress is None else in_progress.contribution,
            cf_by_fuel=cf_by_fuel or {},
        ),
    }


# ─── 진행 중 항차 → 시뮬레이션 시계 ──────────────────────────────────────────


async def _resolve_progress(session: AsyncSession, *, vessel, voyage, as_of: datetime):
    """``#368`` 시뮬레이션 시계로 진행 중 항차의 누적량을 확정한다.

    속도·일일 소모율은 **항차 계획값을 먼저** 보고 없으면 선박 제원으로 내려간다.
    항차에 계획이 있는데 선박 기본값을 쓰면 그 항차의 계획이 무시되고, 두 값이
    다를 때 화면과 계획서가 어긋난다.
    """
    periods = await cached(
        session,
        ("not_underway_periods", vessel.id, voyage.regulation_year or as_of.year, as_of_key(as_of)),
        lambda: not_underway_repo.list_periods_for_year(
            session,
            vessel_id=vessel.id,
            regulation_year=voyage.regulation_year or as_of.year,
            as_of=as_of,
        ),
    )
    return compute_progress(
        as_of=as_of,
        departure_at=voyage.actual_departure_at or voyage.planned_departure_at,
        arrival_at=voyage.actual_arrival_at,
        # `#649` — 실적이 없으면 예정일에서 자른다. 종전에는 넘기지 않아 상한이
        # 없었고, 예정일을 지난 항차의 누적이 계속 자랐다.
        planned_arrival_at=voyage.planned_arrival_at,
        # `#1321` — 계획 거리에서도 자른다. 종전에는 상한이 **시각 하나**뿐이라
        # 도착 예정일 **안에서도** 계획을 넘었다(시연 시드 186%·359%).
        planned_distance_nm=voyage.planned_distance_nm,
        speed_kn=voyage.planned_speed_kn or vessel.reference_speed_kn,
        daily_foc_ton=vessel.reference_daily_foc_ton,
        # cubic speed model의 기준점 (`TECH_SPEC §4.1`, `#796`). 종전에는 넘기지
        # 않아 **거리는 계획 속도로 늘리면서 연료는 기준 속도의 소모율을 그대로**
        # 곱했다 — 계획 14 kn · 기준 12 kn이면 연료가 1.588배 과소 산출된다.
        reference_speed_kn=vessel.reference_speed_kn,
        not_underway_periods=[
            NotUnderwayWindow(started_at=p.started_at, ended_at=p.ended_at) for p in periods
        ],
    )


#: 유종별 몫. ``((유종, 몫), …)`` — 몫의 합은 1이다.
FuelSplit = tuple[tuple[str, Decimal], ...]


async def _voyage_fuel_split(session: AsyncSession, *, voyage, vessel) -> FuelSplit | None:
    """진행 중 항차의 연료를 유종별로 나눌 몫 (``PRD §3.3.8`` · `#885`).

    ## 왜 몫인가

    시뮬레이션 시계(`#368`)는 ``reference_daily_foc_ton × 경과시간``으로 **총 연료량
    하나**를 낸다. 종전에는 그 총량 전부에 **연료 기록의 첫 유종** CF를 곱했다 — `#867`의
    정렬로 순서는 안정됐으나 **사전순 첫 유종이 대표가 되는 근거는 정본에 없었다.**
    HFO 60 t + 가스오일 40 t 계획이면 소수 유종인 가스오일의 CF(3.206)가 전량에 곱해진다.

    같은 축의 다른 갈래는 이미 유종별이다 — YTD 항해 연료(`#863`)와 not under way(`030`).
    진행분만 하나로 뭉개져 있었다. **계획 연료량 비율로 나눈다.** 입력은 이미 있다.

    ## 종전 동작을 지키는 곳

    - 계획량이 비어 있으면(전부 ``NULL`` — 실적만 기록된 연료 행) **종전대로 첫 유종 하나**(몫 1).
      비율을 만들 근거가 없다. ``chk_fuel_positive``가 0을 막아 합이 0이 되는 길은 ``NULL``뿐이다
    - 연료 기록이 없으면 **선박 기본 연료** 하나
    - 둘 다 없으면 ``None`` — **임의로 ``HFO``를 채우지 않는다.** CF가 달라 CO₂가 틀리고,
      화면은 그 사실을 알 수 없다
    - 단일 유종이면 몫이 1이라 **값이 종전과 같다**(현재 대다수)
    """
    fuel_uses = await cached(
        session,
        ("fuel_uses", voyage.id),
        lambda: voyage_repo.list_fuel_uses(session, voyage.id),
    )
    planned = [(fu.fuel_type, Decimal(str(fu.planned_fuel_ton or 0))) for fu in fuel_uses]
    total = sum((ton for _, ton in planned), Decimal(0))
    if total > 0:
        return tuple((code, ton / total) for code, ton in planned if ton > 0)
    if fuel_uses:
        return ((fuel_uses[0].fuel_type, Decimal(1)),)
    if vessel.default_fuel_type is not None:
        return ((vessel.default_fuel_type, Decimal(1)),)
    return None


def _split_fuel(total_ton: Decimal, split: FuelSplit) -> tuple[tuple[str, Decimal], ...]:
    """총 연료를 몫대로 나눈다. **마지막 몫은 「총량 − 나머지 합」**이다.

    몫마다 곱하면 반올림 찌꺼기로 합이 총량과 어긋날 수 있다 — 누적 연료가 원래보다
    미세하게 늘거나 줄면 같은 화면의 「누적 연료」와 CO₂가 설명되지 않는다.
    """
    parts: list[tuple[str, Decimal]] = []
    assigned = Decimal(0)
    for index, (code, share) in enumerate(split):
        ton = total_ton - assigned if index == len(split) - 1 else total_ton * share
        parts.append((code, ton))
        assigned += ton
    return tuple(parts)


def _display_fuel(split: FuelSplit | None) -> str | None:
    """``current_voyage.fuel_type``에 싣는 유종 — **계획량이 가장 큰 유종**이다.

    필드는 문자열 하나다(`API_SPEC §2.8`). 목록으로 바꾸면 계약이 깨지므로 계산은
    몫으로 하고 표시는 대표 하나로 한다. 몫이 같으면 유종순(`#867`)의 앞이다.
    """
    if not split:
        return None
    return max(split, key=lambda item: item[1])[0]


# ─── 진입점 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InProgressState:
    """진행 중 항차가 YTD에 기여하는 몫과, 기여하지 못한 사유 (#750).

    **YTD의 정의가 이 값에 걸려 있다.** ``PRD §3.3.8``은 진행 중 항차의
    「경과 시간으로부터 산출한 estimate」를 연간 누적에 넣도록 규정한다. 종전에는 이
    계산이 :func:`get_current_cii` 안에만 있어, 같은 YTD를 내는 다른 세 경로
    (``fleet_summary`` · ``cii_history`` · 연간 실적 리포트)가 **인자를 넘기지 않아
    실적 확정분만 집계**했다 — 같은 라벨의 숫자가 화면마다 달랐다.

    그래서 **여기 하나만 둔다.** 네 경로가 각자 조립하면 인자가 다시 갈릴 수 있고,
    그때 화면은 멀쩡한 채 값만 어긋난다.
    """

    voyage: object | None
    progress: object | None
    contribution: InProgressContribution | None
    fuel_code: str | None
    warnings: list[str]
    #: 진행 중 항차가 선언한 규제연도. 항차가 없으면 ``None``이다 (#815).
    regulation_year: int | None = None
    #: 진행 연료를 나눌 유종별 몫 (`#885`). ``fuel_code``는 이 중 표시용 대표 하나다.
    fuel_split: FuelSplit | None = None

    def for_year(self, regulation_year: int) -> InProgressState:
        """조회 연도에 **속하는** 진행분만 남긴다 (#815).

        진행 중 항차 조회에는 연도 조건이 없었고(``find_in_progress``), 기여분은
        무조건 더해졌다. 그래서 ``?year=2024``로 물어도 **2026년에 항해 중인 항차의
        누적분이 2024년 확정 실적에 합산**됐다 — 끝난 해의 실적이 조회할 때마다
        달라졌고, 그 값이 연간 실적 리포트 PDF에도 그대로 실렸다.

        **집계의 나머지는 이미 이 기준을 쓴다.** ``list_annual_inclusions``가
        ``Voyage.regulation_year == regulation_year``로 거른다
        (``db/repositories/voyage.py:224``). 진행분만 다른 기준을 쓰면 분자와 분모가
        서로 다른 해의 항차를 섞는다.

        **기여분만 지우지 않고 상태 전체를 비운다.** ⑵ 항차 구간값과
        ``meta.simulated``도 같은 항차에서 나오므로, 하나만 지우면 화면이 「2024년을
        보는데 지금 뛰는 항차의 구간값이 함께 떠 있는」 상태가 된다. 경고도 마찬가지다 —
        범위 밖 항차에 대한 안내는 그 화면에서 뜻이 없다.

        ⚠️ **연도를 선언하지 않은 항차는 예외다 (`#1336`).** ``regulation_year``가
        ``NULL``인 항차는 `chk_year_policy`(`DB_SCHEMA §2.3`)상 **반드시
        ``EXCLUDE``**이고, `#1085`의 갈래가 이미 그 항차의 ``contribution``과 경고를
        비운 뒤 ``voyage``·``progress``만 남겨 보낸 상태다 — **⑴에 들어갈 것이 아무것도
        없다.** 그런데 ``None != 2026``이 참이라 이 자리에서 **⑵까지 함께 지워졌다**:
        연도를 비워 만든 항차를 진행으로 넘기면 선박은 ``UNDER_WAY``인데 「현재 항차」
        카드가 사라지고 ``meta.simulated``도 내려간다.

        위 문단의 판단(「2024년을 보는데 지금 뛰는 항차의 구간값이 함께 떠 있으면 안
        된다」)은 **다른 해에 속한다고 선언한 항차**에 대한 것이다. 어느 해에도 속하지
        않는 항차는 그 문장이 가리키는 대상이 아니다.
        """
        if self.regulation_year is None or self.regulation_year == regulation_year:
            return self
        return InProgressState(None, None, None, None, [], None)


async def resolve_in_progress_state(
    session: AsyncSession, *, vessel, as_of: datetime
) -> InProgressState:
    """진행 중 항차의 YTD 기여분을 만든다 (``PRD §3.3.8`` · `#750`).

    **거리와 연료가 둘 다 있을 때만 기여분을 만든다.** 한쪽만 넣으면 CII가 한 방향
    으로만 틀리는데, 특히 거리만 넣는 경우가 위험하다 — 분모 ``Dt``만 늘고 분자 ``M``은
    그대로라 **항해할수록 등급이 좋아진다.** ``vessel.reference_daily_foc_ton``은
    nullable이라(``DB_SCHEMA §2.1``) 소모율이 없는 선박에서 시계가 연료를 0으로
    내놓고, 그때 이 상태가 된다.

    넣지 않은 이유는 경고로 싣는다. 값이 안 변하는 것을 화면이 「아직 출항 전」으로
    오해하면 사용자는 없는 제원을 채울 생각을 하지 못한다.
    """
    # 선대 요약이 배치로 이미 읽어 둔 진행 항차를 재활용한다 (#989 ⑵). 캐시가
    # 꺼진 요청(실시간 CII 등)은 종전대로 직접 읽는다.
    voyage = await cached(
        session,
        ("find_in_progress", vessel.id),
        lambda: voyage_repo.find_in_progress(session, vessel.id),
    )
    if voyage is None:
        return InProgressState(None, None, None, None, [], None)

    fuel_split = await _voyage_fuel_split(session, voyage=voyage, vessel=vessel)
    fuel_code = _display_fuel(fuel_split)
    progress = await _resolve_progress(session, vessel=vessel, voyage=voyage, as_of=as_of)

    contribution: InProgressContribution | None = None
    warnings: list[str] = []

    if voyage.annual_inclusion_policy != "INCLUDE_AS_PLAN":
        # ⚠️ **「연간 반영 안 함」 항차는 누적에 넣지 않는다** (`PRD §3.3.8` · `#1085`).
        #
        # `§3.3.8`의 「집계에 넣는 항차의 범위」 표가 `EXCLUDE`를 「넣지 않는다」로 정하는데
        # 진행분만 그 필터를 지나지 않았다. 확정분은 `list_annual_inclusions`가 정책으로
        # 거르고(`db/repositories/voyage.py:224`), 진행분은 `find_in_progress`가 상태로만
        # 골라(`:278-301`) 정책을 보지 않았다 — `PRD §8.1.2`상 `IN_PROGRESS + EXCLUDE`는
        # 합법이므로 데이터 오류로 걸러지지도 않는다.
        #
        # 결과는 **항해 중에는 누적이 늘다가, 완료되는 순간 집계에서 빠져 누적 CII가 한 번에
        # 뛰는 것**이었다(시운전 항차를 `EXCLUDE`로 두고 항해하는 경우).
        #
        # **경고도 함께 비운다.** 위 세 갈래의 경고 문구는 `API_SPEC §1.6`에서 전부
        # 「…진행분이 **누적에 반영되지 않았습니다**. …입력해 주세요」 꼴이다. 사용자가 스스로
        # 반영하지 않기로 둔 항차에 그 문구를 띄우면 **고치면 반영될 것처럼 읽히는 거짓
        # 안내**가 된다(조건부 사실을 무조건으로 적지 않는다). `#815`의 :meth:`for_year`가
        # 「범위 밖 항차에 대한 안내는 그 화면에서 뜻이 없다」로 같은 판단을 이미 내렸다.
        #
        # **`voyage`·`progress`는 남긴다** — ⑵ 항차 구간값(`current_voyage`)은
        # :func:`_voyage_segment`가 이 둘로 만들고 ``contribution``을 쓰지 않는다.
        # `§3.3.8`의 3종 표에서 ⑵는 ⑴과 별개 값이고, 집계 범위 표는 ⑴에만 걸린다.
        # 지금 실제로 뛰고 있는 항차를 화면에서 지울 이유가 없다.
        return InProgressState(
            voyage,
            progress,
            None,
            fuel_code,
            [],
            voyage.regulation_year,
            fuel_split=fuel_split,
        )

    if progress.distance_nm > 0 and progress.fuel_ton > 0 and fuel_split is not None:
        contribution = InProgressContribution(
            distance_nm=progress.distance_nm,
            # 유종별로 나눠 각자의 CF를 곱한다 (`#885`). 종전에는 유종 하나였다.
            fuel_uses=_split_fuel(progress.fuel_ton, fuel_split),
        )
    elif progress.distance_nm > 0 and progress.fuel_ton <= 0:
        warnings.append(WARNING_SIM_NO_FUEL_RATE)
    elif progress.distance_nm > 0 and fuel_split is None:
        warnings.append(WARNING_SIM_NO_FUEL_TYPE)

    # 예정일에서 잘렸다는 사실은 **값이 들어갔든 아니든** 알린다 (`#649`).
    # 위 세 갈래와 배타적이지 않다 — 자르고도 거리·연료가 정상이면 값은 누적에
    # 들어가고, 그때도 「왜 더 늘지 않는가」를 화면이 말해야 한다.
    if progress.past_planned_arrival:
        warnings.append(WARNING_IN_PROGRESS_PAST_ETA)
    # `#1321` — 예정일과 **별개 코드**다. 계획 거리는 예정일보다 먼저 찰 수 있고
    # (감시선 시드는 3.6일 앞선다), 한 코드로 묶으면 화면이 「도착 예정일이
    # 지났습니다」라고 거짓말을 한다.
    if progress.reached_planned_distance:
        warnings.append(WARNING_IN_PROGRESS_PLANNED_DISTANCE_REACHED)

    # 보정을 못 한 사실은 **값이 들어갔을 때만** 알린다 — 진행분이 0이면 보정
    # 여부가 결과에 아무 영향이 없고, 그때 경고를 띄우면 고칠 것이 없는 안내가 된다.
    if progress.speed_uncorrected:
        warnings.append(WARNING_SIM_NO_REFERENCE_SPEED)

    return InProgressState(
        voyage,
        progress,
        contribution,
        fuel_code,
        warnings,
        voyage.regulation_year,
        fuel_split=fuel_split,
    )


async def get_current_cii(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    year: int | None = None,
    as_of: datetime | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """실시간 CII 3종 값 (API_SPEC §2.14).

    :returns: ``(data, meta)``. ``meta``에 ``as_of``·``simulated``가 들어간다 —
        라우트가 그대로 응답 ``meta``에 합친다.
    """
    resolved_as_of = resolve_as_of(as_of)
    regulation_year = year if year is not None else resolved_as_of.year
    _validate_year(regulation_year)

    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None or vessel.is_deleted:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")

    # 진행분 산출은 **한 곳에만 둔다** (`#750`) — 같은 YTD를 내는 네 경로가 각자
    # 조립하면 인자가 갈리고, 그때 화면은 멀쩡한 채 값만 어긋난다.
    #
    # **조회 연도에 속하는 항차만 본다** (`#815`). `?year=<과거>`로 물으면 지금
    # 항해 중인 항차는 그 해의 것이 아니므로 ⑴ 누적·⑵ 구간값·`meta.simulated`
    # 어디에도 들어가지 않는다.
    #
    state = (
        await resolve_in_progress_state(session, vessel=vessel, as_of=resolved_as_of)
    ).for_year(regulation_year)
    voyage = state.voyage
    progress = state.progress
    contribution = state.contribution
    fuel_code = state.fuel_code
    fuel_split = state.fuel_split
    live_warnings: list[str] = [*state.warnings]

    try:
        ytd = await compute_ytd_cii(
            session,
            vessel_id=vessel_id,
            regulation_year=regulation_year,
            as_of=resolved_as_of,
            in_progress=contribution,
        )
    except ValueError as exc:  # pragma: no cover - 방어
        raise CalculationError(str(exc)) from exc

    cf_by_fuel: dict[str, Decimal] = {}
    if fuel_split:
        rows = await param_repo.get_fuel_types_by_codes(session, [c for c, _ in fuel_split])
        cf_by_fuel = {code: Decimal(str(row.cf)) for code, row in rows.items()}

    data: dict[str, object] = {
        "vessel_id": str(vessel.id),
        "vessel_name": vessel.name,
        "regulation_year": regulation_year,
        "transport_capacity_basis": capacity_axis(vessel.ship_type),
        "underway_state": vessel.underway_state,
        "ytd": _ytd_to_dict(ytd),
        "current_voyage": (
            None
            if voyage is None or progress is None
            else _voyage_segment(
                voyage=voyage,
                progress=progress,
                transport_capacity=ytd.transport_capacity,
                cf_by_fuel=cf_by_fuel,
                fuel_code=fuel_code,
                fuel_split=fuel_split,
            )
        ),
        # ⑶은 **잔여 계획 항차**를 근거로 낸다 (`#798`). 진행 중 항차가 없어도,
        # 정박 중이어도 낼 수 있다 — 그때야말로 사용자가 가장 보고 싶어 하는 값이다.
        "year_end_projection": await _project_year_end(
            session,
            vessel_id=vessel_id,
            regulation_year=regulation_year,
            as_of=resolved_as_of,
            # `#1673` — 분해의 출발점(⑴)과 진행 중 항차의 경과분. ⑴과 **같은 값·같은 CF**다.
            ytd_attained_cii=ytd.attained_cii,
            in_progress=state,
            cf_by_fuel=cf_by_fuel,
        ),
        # `API_SPEC §1.6` — 모든 계산 결과에 붙는다. `#353`이 붙인 경고를 함께 싣되
        # 중복은 제거한다.
        "warnings": sorted({WARNING_REFERENCE_ONLY, *ytd.warnings, *live_warnings}),
    }

    meta = {
        "as_of": resolved_as_of.isoformat(),
        # `PRD R-5` 「시뮬레이션 데이터」 배지의 근거. 시계가 만든 값이 하나라도
        # 섞여 있으면 참이다 — 화면이 배지를 조건부로 감출 근거를 스스로 만들지
        # 않게 서버가 판정해 준다.
        "simulated": bool(progress is not None and progress.is_simulated),
    }
    return data, meta
