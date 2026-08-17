"""선대 요약 서비스 — ``GET /fleet/summary`` (#350).

대시보드(`UIFLOW v2.0` 2-4 · `PRD §6.2 SCR-001`)가 **한 번의 호출로** 선대 전체
현황을 받도록 모아 준다.

## 계산을 다시 짜지 않는다

선박별 YTD 누적 CII·등급·위험도는 ``services.ytd_cii.compute_ytd_cii``(#353)가
이미 산출한다. 대시보드 전용 배치 쿼리로 같은 수식을 다시 구현하면 **선박 상세
화면과 대시보드가 서로 다른 값을 내면서 화면은 멀쩡해 보인다.** 값이 틀려도
깨지지 않으므로 발견이 늦다 — 이 저장소가 반복해서 겪은 실패 유형이다.

그래서 계산은 그대로 재사용하고, 이 모듈은 **모으고 판정하고 표기하는 일**만 한다.

## 두 가지 위험 개념을 함께 내린다

| 필드 | 근거 | 성격 |
|---|---|---|
| ``risk_level`` | `PRD §9.4.1` | 표시용 4단계 (LOW·MEDIUM·HIGH·CRITICAL) |
| ``risk_reasons`` | `PRD §3.3.7` | **규제 트리거** — 시정조치계획 의무 발생 여부 |

둘은 다른 것을 본다. ``risk_level``은 「지금 여유가 얼마나 있나」이고,
``risk_reasons``는 「MARPOL Reg 28.7에 걸렸나」다. C등급이어도 여유가 없으면
``HIGH``지만 규제 의무는 없고, D등급 3년차는 여유와 무관하게 의무가 생긴다.

**하나로 합치면 조치 목록에 무슨 사유인지 쓸 수 없다.**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import CalculationError, ValidationError
from cii_platform.services.cii_history import list_cii_history
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import YtdCiiOutput, compute_ytd_cii

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from sqlalchemy.ext.asyncio import AsyncSession

#: 표시 자릿수 — `DESIGN_SYSTEM §4.2`. 화면이 아니라 여기서 문자열로 확정한다.
#: `API_SPEC §1.7`이 수치를 문자열로 직렬화하도록 규정하므로 float으로 되돌리지 않는다.
_CII_DIGITS = 4

#: 「D등급 진입까지 n일」 판정 대상 등급. C 이상에서만 의미가 있다.
_TARGET_RATING = "D"

#: 등급 악화 순서. 값이 클수록 나쁘다.
_RATING_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


@dataclass(frozen=True)
class DaysToTarget:
    """「D등급 진입까지 n일」 산정 결과.

    ``days``가 ``None``이면 ``reason``이 왜인지 말한다. **숫자를 못 낸 것과 0일인
    것은 다르므로** 둘을 같은 자리에 넣지 않는다.
    """

    days: int | None
    reason: str | None


#: ``DaysToTarget.reason`` 값 — 이슈 #350이 명시한 경계 4종.
REASON_ALREADY_AT_OR_BELOW = "ALREADY_AT_OR_BELOW"
REASON_NOT_THIS_YEAR = "NOT_THIS_YEAR"
REASON_NOT_UNDER_WAY = "NOT_UNDER_WAY"
REASON_NO_DATA = "NO_DATA"

#: ``unavailable_reason`` 값 (#419) — ``data_available=false``인 **이유**.
#: 「실적 없음」과 「제원 미비」는 사용자가 할 일이 다르다(항차 등록 vs 제원 입력).
REASON_MISSING_SPECS = "MISSING_SPECS"
REASON_CALCULATION_FAILED = "CALCULATION_FAILED"


def _publish(value: Decimal | None, digits: int) -> str | None:
    """Layer 1 값을 표시 문자열로.

    ``float``으로 되돌리지 않는다 — `API_SPEC §1.7`이 문자열 직렬화로 지킨 정밀도가
    그 순간 사라진다.
    """
    if value is None:
        return None
    return f"{value:.{digits}f}"


def compute_days_to_target(
    ytd: YtdCiiOutput,
    *,
    underway_state: str | None,
    as_of: datetime,
) -> DaysToTarget:
    """D등급 진입까지 남은 일수.

    ## 정박 중에는 계산하지 않는다

    이슈 #350이 경계 케이스로 지목한 항목이다. not under way 구간은 **거리가 늘지
    않고 연료만 는다**(`PRD §3.3` · `MEPC.412(84)` §4.2). 그래서 정박 중에는 CII가
    단조 악화하고, n일이 하루가 다르게 짧아졌다가 **출항하는 순간 되돌아간다.**

    평활화 규칙을 발명하는 대신 ``NOT_UNDER_WAY``로 표기한다. 요동치는 숫자를
    보여 주는 것보다 「지금은 산정하지 않는다」가 정직하다.

    ## 소비율 가정

    이슈가 제시한 3안 중 **「최근 실적 평균」의 변형**을 쓴다 — 누적 실적에서
    **under way 구간만** 뽑아 하루치 악화 속도를 낸다. 정박 구간을 섞으면 위 문제가
    산정식 안으로 들어온다.
    """
    if not ytd.data_available or ytd.attained_cii is None or ytd.rating is None:
        return DaysToTarget(None, REASON_NO_DATA)

    if _RATING_ORDER.get(ytd.rating, 0) >= _RATING_ORDER[_TARGET_RATING]:
        # 이미 D 이하 — 「진입까지 n일」이 정의되지 않는다.
        return DaysToTarget(None, REASON_ALREADY_AT_OR_BELOW)

    if underway_state == "NOT_UNDER_WAY":
        return DaysToTarget(None, REASON_NOT_UNDER_WAY)

    boundary = ytd.boundaries.get("d") if ytd.boundaries else None
    if boundary is None or ytd.underway_distance_nm is None:
        return DaysToTarget(None, REASON_NO_DATA)

    elapsed_days = as_of.timetuple().tm_yday
    if elapsed_days <= 0 or ytd.underway_distance_nm <= 0:
        return DaysToTarget(None, REASON_NO_DATA)

    # 하루치 악화 속도 = (현재 attained − 연초 0 기준) / 경과일.
    # attained_cii는 누적 분자/분모의 비이므로 선형 외삽이 정확하지는 않다.
    # 다만 「대략 며칠 남았나」를 알리는 사전 경고이고, 정확한 예측은
    # 연간 시뮬레이터(#63·#64)가 Monte Carlo로 담당한다.
    daily_rate = (boundary - ytd.attained_cii) / Decimal(elapsed_days)
    if daily_rate <= 0:
        return DaysToTarget(None, REASON_ALREADY_AT_OR_BELOW)

    remaining = (boundary - ytd.attained_cii) / daily_rate
    days = int(remaining)

    days_left_this_year = _days_left_in_year(as_of)
    if days > days_left_this_year:
        return DaysToTarget(None, REASON_NOT_THIS_YEAR)

    return DaysToTarget(max(days, 0), None)


def _days_left_in_year(as_of: datetime) -> int:
    """올해 남은 일수. 규제연도는 역년(calendar year)이다 (`PRD §3.2`)."""
    year_end = datetime(as_of.year, 12, 31, 23, 59, 59, tzinfo=as_of.tzinfo)
    return max((year_end - as_of).days, 0)


async def _prior_confirmed_ratings(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    current_year: int,
    as_of: datetime,
) -> list[str | None]:
    """직전 2개 규제연도의 확정 등급 — 오래된 연도부터.

    `PRD §3.3.7`의 「D등급 3년 연속」 판정에 필요하다. 확정 등급은 연말 DCS 보고·검증
    이후에 정해지므로 **올해는 포함하지 않는다.**
    """
    history = await list_cii_history(
        session,
        vessel_id=vessel_id,
        from_year=current_year - 2,
        to_year=current_year - 1,
        as_of=as_of,
    )
    years = history.get("years", [])
    return [row.get("rating") if row.get("data_available") else None for row in years]


def evaluate_risk_reasons(
    *,
    ytd_rating: str | None,
    prior_ratings: list[str | None],
) -> list[str]:
    """`PRD §3.3.7` 「경고 배너 판정 기준」을 그대로 옮긴다.

    > 1. 올해 YTD 등급이 **E**
    > 2. 직전 2개 규제연도의 확정 등급이 연속 **D**이고, 올해 YTD 등급도 **D**

    **연말 예상 등급이 아니라 YTD 등급이 기준인 것이 핵심이다.** 예상 등급은 Monte
    Carlo 종속이라 같은 화면을 두 번 열면 값이 달라질 수 있어, 정본이 그 기준을 후속
    이슈로 연기했다.
    """
    if ytd_rating is None:
        return []

    reasons: list[str] = []
    if ytd_rating == "E":
        reasons.append("E_THIS_YEAR")
    elif ytd_rating == "D" and len(prior_ratings) == 2 and all(r == "D" for r in prior_ratings):
        reasons.append("D_THIRD_YEAR")
    return reasons


#: ``risk_reasons`` → 조치 목록 문구. 규제 용어는 `PRD §3.3.7`을 따른다.
_ACTION_TEXT = {
    "E_THIS_YEAR": "E등급 1년차 — SEEMP Part III 시정조치계획 대상",
    "D_THIRD_YEAR": "D등급 3년 연속 — SEEMP Part III 시정조치계획 대상",
}
_ACTION_SEVERITY = {"E_THIS_YEAR": "critical", "D_THIRD_YEAR": "warning"}


async def get_fleet_summary(
    session: AsyncSession,
    *,
    regulation_year: int | None = None,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """선대 전체 현황을 한 번에 반환한다 (`API_SPEC §2.8`).

    :param regulation_year: 집계 대상 규제연도. 미지정이면 ``as_of`` 연도.
    :param as_of: 기준 시각(``as_of`` 계약 ⑵). 미지정이면 서버가 확정하며,
        응답에 **실제 사용한 값을 반드시 싣는다** — 클라이언트가 같은 값으로 다시
        물어 같은 결과를 얻을 수 있어야 한다(계약 ⑶).
    """
    resolved = resolve_as_of(as_of)
    year = regulation_year if regulation_year is not None else resolved.year

    # 선박 목록은 한 번에 가져온다. 여기서 개별 조회를 돌면 그 자체가 N+1이다.
    # ``list_active``는 「다음 페이지 있음」 판정용으로 ``limit + 1``건을 준다 —
    # 초과분을 잘라내는 것은 호출부 몫이다.
    vessels = (await vessel_repo.list_active(session, limit=_MAX_FLEET_SIZE))[:_MAX_FLEET_SIZE]

    rows: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []

    for vessel in vessels:
        # #419 — 한 척의 계산 실패가 선대 전체를 무너뜨리지 않는다. 제원 미비는
        # 오류가 아니라 **상태**다(`data_available=False`와 같은 계열, #353 계약).
        # 단건 조회(선박 상세)는 예외로 「제원을 입력하세요」를 안내하지만, 목록
        # 화면은 그 선박만 사유를 달고 내려간다. ParameterError는 잡지 않는다 —
        # 규제 파라미터 미적재는 서버 배포 문제라 조용히 사라지면 안 된다.
        ytd: YtdCiiOutput | None = None
        unavailable_reason: str | None = None
        try:
            ytd = await compute_ytd_cii(
                session,
                vessel_id=vessel.id,
                regulation_year=year,
                as_of=resolved,
            )
        except ValidationError as exc:
            # field=vessel_id — 제원(DWT/GT) 미비. 그 외의 ValidationError(예: 알
            # 수 없는 연료 코드)은 제원 문제가 아니다 — 「제원을 입력하세요」 안내가
            # 사용자를 엉뚱한 곳으로 보내므로 CALCULATION_FAILED로 분류한다.
            unavailable_reason = (
                REASON_MISSING_SPECS if exc.field == "vessel_id" else REASON_CALCULATION_FAILED
            )
        except CalculationError:
            unavailable_reason = REASON_CALCULATION_FAILED

        base = {
            "vessel_id": str(vessel.id),
            "name": vessel.name,
            "ship_type": vessel.ship_type,
            "imo_number": vessel.imo_number,
            "underway_state": vessel.underway_state,
            "detail_status": vessel.detail_status,
            "current_lat": _publish(vessel.current_lat, 6),
            "current_lon": _publish(vessel.current_lon, 6),
            "position_updated_at": (
                vessel.position_updated_at.isoformat()
                if vessel.position_updated_at is not None
                else None
            ),
        }

        if ytd is None:
            # 계산 자체가 안 된 선박 — 위험 판정 재료도 없다(risk_reasons=[]).
            rows.append(
                {
                    **base,
                    "data_available": False,
                    "unavailable_reason": unavailable_reason,
                    "ytd_attained_cii": None,
                    "ytd_required_cii": None,
                    "ytd_rating": None,
                    "risk_level": None,
                    "risk_reasons": [],
                    "days_to_d": None,
                    "days_to_d_reason": REASON_NO_DATA,
                }
            )
            continue

        prior = await _prior_confirmed_ratings(
            session,
            vessel_id=vessel.id,
            current_year=year,
            as_of=resolved,
        )
        reasons = evaluate_risk_reasons(ytd_rating=ytd.rating, prior_ratings=prior)
        days = compute_days_to_target(
            ytd,
            underway_state=vessel.underway_state,
            as_of=resolved,
        )

        rows.append(
            {
                **base,
                "data_available": ytd.data_available,
                # 「실적 없음」과 「제원 미비」는 사용자가 할 일이 다르다 (#419).
                "unavailable_reason": None if ytd.data_available else REASON_NO_DATA,
                "ytd_attained_cii": _publish(ytd.attained_cii, _CII_DIGITS),
                "ytd_required_cii": _publish(ytd.required_cii, _CII_DIGITS),
                "ytd_rating": ytd.rating,
                "risk_level": ytd.risk_level,
                "risk_reasons": reasons,
                "days_to_d": days.days,
                "days_to_d_reason": days.reason,
            }
        )

        for reason in reasons:
            actions.append(
                {
                    "vessel_id": str(vessel.id),
                    "vessel_name": vessel.name,
                    "severity": _ACTION_SEVERITY[reason],
                    "reason": reason,
                    "message": _ACTION_TEXT[reason],
                }
            )

    return {
        "as_of": resolved.isoformat(),
        "regulation_year": year,
        "summary": _aggregate_counts(rows),
        "vessels": rows,
        "actions": actions,
    }


#: 한 번에 집계하는 최대 선박 수. 중소선사 대상이라 실무상 충분하며,
#: 넘어가면 페이지네이션이 필요하다는 신호다(후속 이슈).
_MAX_FLEET_SIZE = 200


def _aggregate_counts(rows: list[dict[str, object]]) -> dict[str, object]:
    """KPI 집계.

    **화면이 다시 세지 않게 여기서 확정한다.** 화면과 서버가 각자 세면 필터·정렬이
    붙었을 때 서로 달라지고, 그 차이는 눈으로 발견되지 않는다.
    """
    under_way = sum(1 for r in rows if r["underway_state"] == "UNDER_WAY")
    not_under_way = sum(1 for r in rows if r["underway_state"] == "NOT_UNDER_WAY")

    distribution: dict[str, int] = {k: 0 for k in _RATING_ORDER}
    for row in rows:
        rating = row["ytd_rating"]
        if isinstance(rating, str) and rating in distribution:
            distribution[rating] += 1

    return {
        "total": len(rows),
        "under_way": under_way,
        "not_under_way": not_under_way,
        # 상태 미기록 선박이 있으면 위 둘의 합이 total과 다르다. 화면이 그 차이를
        # 「알 수 없음」으로 표시할 수 있도록 굳이 채워 넣지 않는다.
        "unknown_state": len(rows) - under_way - not_under_way,
        "rating_distribution": distribution,
        "at_risk": sum(1 for r in rows if r["risk_reasons"]),
        "no_data": sum(1 for r in rows if not r["data_available"]),
        # #419 — no_data의 내역. 「실적 없음」(항차를 등록하세요)과 「제원 미비」
        # (DWT/GT를 입력하세요)는 사용자의 다음 행동이 다르므로 나눠서 센다.
        "missing_specs": sum(
            1 for r in rows if r.get("unavailable_reason") == REASON_MISSING_SPECS
        ),
    }
