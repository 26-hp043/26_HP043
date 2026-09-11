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

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.calc.capacity import resolve_transport_capacity
from cii_platform.calc.rating_engine import NEXT_WORSE_BOUNDARY_KEY
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import AppError, ParameterError, ValidationError
from cii_platform.services.cii_current import resolve_in_progress_state
from cii_platform.services.cii_history import list_cii_history
from cii_platform.services.pagination import normalize_limit
from cii_platform.services.simulation_clock import resolve_as_of
from cii_platform.services.ytd_cii import YtdCiiOutput, compute_ytd_cii

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.db.models.vessel import Vessel

#: 표시 자릿수 — `DESIGN_SYSTEM §4.2`. 화면이 아니라 여기서 문자열로 확정한다.
#: `API_SPEC §1.7`이 수치를 문자열로 직렬화하도록 규정하므로 float으로 되돌리지 않는다.
_CII_DIGITS = 4

#: 「D등급 진입까지 n일」 판정 대상 등급. C 이상에서만 의미가 있다.
_TARGET_RATING = "D"

#: 등급 악화 순서. 값이 클수록 나쁘다.
_RATING_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}

#: ``vessels[]`` 정렬 키 (#772). 종전에는 화면(``fleetRules.sortVessels``)이 가졌다.
FLEET_SORT_KEYS: tuple[str, ...] = ("risk", "name", "grade")
DEFAULT_FLEET_SORT = "risk"
#: `API_SPEC §1.5` — 목록 조회 공통 기본·상한.
_DEFAULT_PAGE = 20
_MAX_PAGE = 100

#: 값을 낼 수 없는 사유 (#419). ``data_available=False``인 선박이 **왜** 그런지 구분한다.
#:
#: 「실적 없음」과 「제원 미비」는 사용자가 할 일이 완전히 다르다 — 전자는 항차를
#: 등록해야 하고 후자는 선박 제원을 입력해야 한다. 둘을 같은 빈칸으로 그리면 화면이
#: 무엇을 하라고 말할 수 없다.
UNAVAILABLE_NO_DATA = "NO_DATA"
#: 선박 제원으로 capacity를 정할 수 없다 — DWT·GT가 비었거나, 0 이하이거나,
#: ``ship_type``이 `PRD §3.4.3`의 13종에 없다. **셋 다 사용자가 선박 정보에서
#: 고친다.** ``DB_SCHEMA §2.1``에서 제원이 nullable이고 ``PRD §20 O-11``이 수동 입력
#: 경로를 열어 두어 **실제로 발생한다.**
UNAVAILABLE_MISSING_SPEC = "MISSING_SPEC"
#: 해당 **선종**의 기준선·등급 경계가 없다. 연도 파라미터 부재는 선대 공통이라
#: 여기서 잡지 않는다 — 아래 ``get_fleet_summary`` 주석 참조.
UNAVAILABLE_NO_PARAMETERS = "NO_PARAMETERS"
#: 위 어느 것으로도 설명되지 않는 실패. **사용자가 할 수 있는 것이 없다.**
#:
#: 이 사유를 따로 두는 이유가 있다. 예외가 났다는 사실만으로 「제원 미비」라고 적으면
#: 제원이 멀쩡한 선박에 제원을 입력하라고 시키게 된다 — 사용자가 해도 아무것도
#: 바뀌지 않고, 이 이슈가 없애려던 **위장**이 방향만 바꿔 되살아난다.
UNAVAILABLE_CALCULATION_ERROR = "CALCULATION_ERROR"


@dataclass(frozen=True)
class DaysToTarget:
    """「D등급 진입까지 n일」 산정 결과.

    ``days``가 ``None``이면 ``reason``이 왜인지 말한다. **숫자를 못 낸 것과 0일인
    것은 다르므로** 둘을 같은 자리에 넣지 않는다.
    """

    days: int | None
    reason: str | None


#: D **진입** 경계가 들어 있는 :attr:`RatingResult.boundaries` 키 (#814).
#:
#: 종전에는 ``"d"`` 리터럴이었다. **``determine_rating``은 그런 키를 만들지 않는다** —
#: 넷뿐이고 전부 ``*_boundary`` 형태다(``superior``·``lower``·``upper``·``inferior``).
#: 그래서 ``boundary``가 **언제나 ``None``**이었고, `#431`이 만든 산식 33줄이 한 줄도
#: 실행되지 않은 채 사유는 늘 ``NO_DATA``였다. 대시보드의 「D등급 진입까지 n일」은
#: 항상 빈칸이었다.
#:
#: 리터럴을 다시 쓰지 않고 :data:`NEXT_WORSE_BOUNDARY_KEY`에서 파생시킨다 —
#: **C를 벗어나는 지점이 곧 D 진입점**이고, 그 대응표는 등급 판정에 쓴 부등식과 짝을
#: 이루는 정본이다(``attained <= upper``로 C가 된다). 리터럴을 두면 경계 정의가
#: 바뀔 때 이 파일만 옛 값을 가리킨다.
_D_ENTRY_BOUNDARY_KEY = NEXT_WORSE_BOUNDARY_KEY["C"]

#: ``DaysToTarget.reason`` 값 — 이슈 #350이 명시한 경계 4종.
REASON_ALREADY_AT_OR_BELOW = "ALREADY_AT_OR_BELOW"
REASON_NOT_THIS_YEAR = "NOT_THIS_YEAR"
REASON_NOT_UNDER_WAY = "NOT_UNDER_WAY"
REASON_NO_DATA = "NO_DATA"

#: 최근 구간에 항해 실적이 없어 소비율을 낼 수 없다 (#431).
REASON_NO_RECENT_DATA = "NO_RECENT_DATA"

#: 최근 운항 강도가 경계보다 효율적이라 이대로면 진입하지 않는다 (#431).
#: **0일이 아니라 「해당 없음」이다** — 숫자를 만들면 「곧 진입한다」로 읽힌다.
REASON_NOT_WORSENING = "NOT_WORSENING"

#: 최근 실적을 재는 창 (일). ``#350``이 제시한 3안 중 「최근 N일 평균」을 쓴다.
#:
#: **30일로 정한 근거.** 항차 하나가 보통 1~3주라, 이보다 짧으면 항차 한 건의
#: 유불리가 그대로 기울기가 되어 값이 요동친다. 이보다 길면 운항 패턴이 바뀐 것을
#: 늦게 알아채는데, 이 값의 쓰임이 **사전 경고**라 늦은 경고는 의미가 없다.
RECENT_WINDOW_DAYS = 30


def _publish(value: Decimal | None, digits: int) -> str | None:
    """Layer 1 값을 표시 문자열로.

    ``float``으로 되돌리지 않는다 — `API_SPEC §1.7`이 문자열 직렬화로 지킨 정밀도가
    그 순간 사라진다.
    """
    if value is None:
        return None
    return f"{value:.{digits}f}"


def _spec_number(value: Decimal | None) -> float | None:
    """선박 제원을 JSON number로 (`#653`).

    ``_publish``를 쓰지 않는다 — 그쪽은 `API_SPEC §1.7`의 **Layer 1 문자열 직렬화**이고,
    ``gross_tonnage``는 계산 결과가 아니라 입력 제원이라 `§2.1` 예시가 ``25000.0``처럼
    숫자로 적는다. `services/vessel.py`의 ``_number``와 같은 규칙이다.
    """
    return None if value is None else float(value)


def compute_days_to_target(
    ytd: YtdCiiOutput,
    *,
    past: YtdCiiOutput | None,
    window_days: int = RECENT_WINDOW_DAYS,
    underway_state: str | None,
    as_of: datetime,
) -> DaysToTarget:
    """D등급 진입까지 남은 일수 (#350 · 산식 정정 #431).

    ## 산식

    경계 ``B``, 수송능력 ``W``, 누적 배출 ``M``(g)·누적 거리 ``Dt``, 하루치 증가분
    ``m``·``d``일 때 ``(M + m·t) / (W·(Dt + d·t)) = B``를 ``t``에 대해 푼다.

    ``A ≡ M / W = attained × Dt``로 두면 ``W``가 약분돼 사라진다::

        t = N · (B·Dt_now − A_now) / ((A_now − A_past) − B·(Dt_now − Dt_past))

    ``W``를 식에서 없애는 편이 안전하다 — 선종별 축(DWT/GT)이 갈리는 값이라
    한 번 더 곱하는 자리마다 틀릴 여지가 생긴다.

    ## 왜 두 시점이 필요한가

    ``m``·``d``를 **YTD 평균**으로 두면 ``m / (W·d) = attained``가 되어 분모가 정확히
    0이 된다 — 정의상 영원히 경계에 닿지 않는다. ``attained_cii``는 누적 분자/분모의
    **비**라서 일정한 강도로 운항하면 **평평하지 커지지 않기** 때문이다.

    의미 있는 ``n일``은 **최근 강도가 YTD 평균보다 나쁠 때만** 존재한다. 그래서
    ``as_of``와 ``as_of − window_days`` 두 시점의 누적값을 차분해 최근 강도를 낸다.

    (종전 구현은 ``attained``가 연초 0에서 선형 성장한다고 가정했고, 그 결과
    **경계까지의 여유와 무관하게 언제나 경과일수**를 냈다 — ``#431``.)

    ## 정박 중에는 계산하지 않는다

    ``#350``이 경계 케이스로 지목한 항목이다. not under way 구간은 거리가 늘지 않고
    연료만 는다(``PRD §3.3`` · ``MEPC.412(84)`` §4.2). 그래서 정박 중에는 CII가 단조
    악화하고, n일이 하루가 다르게 짧아졌다가 **출항하는 순간 되돌아간다.** 평활화
    규칙을 발명하는 대신 사유로 표기한다.

    :param past: ``as_of − window_days`` 시점의 누적. ``None``이면 그 시점이 연초
        이전이라는 뜻이므로 **연초(누적 0)** 로 본다.
    """
    if not ytd.data_available or ytd.attained_cii is None or ytd.rating is None:
        return DaysToTarget(None, REASON_NO_DATA)

    if _RATING_ORDER.get(ytd.rating, 0) >= _RATING_ORDER[_TARGET_RATING]:
        # 이미 D 이하 — 「진입까지 n일」이 정의되지 않는다.
        return DaysToTarget(None, REASON_ALREADY_AT_OR_BELOW)

    if underway_state == "NOT_UNDER_WAY":
        return DaysToTarget(None, REASON_NOT_UNDER_WAY)

    boundary = ytd.boundaries.get(_D_ENTRY_BOUNDARY_KEY) if ytd.boundaries else None
    distance_now = ytd.total_distance_nm
    if boundary is None or distance_now is None or distance_now <= 0:
        return DaysToTarget(None, REASON_NO_DATA)

    # A = attained × Dt (= M / W). 누적 배출을 수송능력으로 나눈 값이다.
    area_now = ytd.attained_cii * distance_now

    if past is not None and past.data_available and past.attained_cii is not None:
        distance_past = past.total_distance_nm or Decimal(0)
        area_past = past.attained_cii * distance_past
    else:
        # 창의 시작이 연초 이전이면 누적은 0이다. 이 경우 최근 강도가 곧 YTD 평균이라
        # 아래 분모가 0 이하로 떨어져 NOT_WORSENING이 된다 — 연초 몇 주 동안은
        # 「아직 판단할 수 없다」가 정직한 답이다.
        distance_past = Decimal(0)
        area_past = Decimal(0)

    delta_distance = distance_now - distance_past
    delta_area = area_now - area_past
    if delta_distance <= 0:
        # 창 안에 항해가 없었다 — 소비율을 낼 근거가 없다.
        return DaysToTarget(None, REASON_NO_RECENT_DATA)

    # 분모 = ΔA − B·ΔD = ΔD·(최근 강도 − B). 0 이하면 최근 운항이 경계보다
    # 효율적이라는 뜻이므로 이대로면 진입하지 않는다.
    denominator = delta_area - boundary * delta_distance
    if denominator <= 0:
        return DaysToTarget(None, REASON_NOT_WORSENING)

    numerator = boundary * distance_now - area_now
    if numerator <= 0:  # pragma: no cover - 등급 판정에서 이미 걸러진다
        return DaysToTarget(None, REASON_ALREADY_AT_OR_BELOW)

    days = int(Decimal(window_days) * numerator / denominator)

    if days > _days_left_in_year(as_of):
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


def _unavailable_ytd(year: int) -> YtdCiiOutput:
    """계산할 수 없는 선박의 자리를 채운다 (#419).

    ``compute_ytd_cii``가 예외를 던진 경우에도 **선대 표에는 그 선박의 행이 있어야
    한다** — 목록에서 빠지면 사용자는 선박이 사라진 줄 안다.

    ``transport_capacity``에 0을, ``capacity_axis``에 빈 문자열을 넣는다. **둘 다
    「모른다」는 뜻이며 값을 지어내지 않기 위한 것**이다 — 축을 임의로 ``DWT``로 적으면
    미지원 선종에 없는 사실을 만들어 낸다. 이 행은 ``data_available=False``라 선대
    응답이 두 값을 싣지 않으므로 화면에 새어 나가지도 않는다.
    """
    return YtdCiiOutput(
        data_available=False,
        regulation_year=year,
        capacity_axis="",
        transport_capacity=Decimal(0),
    )


def _spec_gap(vessel: Vessel) -> str | None:
    """실패가 **이 선박 자신의 제원으로 설명되는가** (#419).

    ``ValidationError``가 났다는 사실만으로는 「제원 미비」라고 말할 수 없다. 같은
    예외가 이력 조회 창 규칙 위반이나 파라미터 seed 손상 같은 **선박과 무관한 이유**로도
    나오기 때문이다. 그것을 「제원을 입력하세요」로 안내하면 **사용자가 해도 아무것도
    바뀌지 않는다.**

    그래서 예외의 종류가 아니라 선박을 직접 본다. 판정에는 계산 엔진이 쓰는 함수를
    그대로 부른다 — 기준을 여기에 다시 적으면 두 벌로 갈라진다.

    :returns: 제원으로 설명되면 :data:`UNAVAILABLE_MISSING_SPEC`, 아니면 ``None``.
    """
    try:
        resolve_transport_capacity(vessel)
    except ValueError:
        # DWT·GT 부재 · 0 이하 · 미지원 선종. **셋 다 선박 정보에서 고친다.**
        return UNAVAILABLE_MISSING_SPEC
    return None


@dataclass(frozen=True)
class _Derived:
    """한 척에서 계산으로 얻는 것 전부."""

    ytd: YtdCiiOutput
    prior: list[str | None]
    past: YtdCiiOutput | None
    unavailable_reason: str | None


async def _derive_vessel(
    session: AsyncSession,
    vessel: Vessel,
    *,
    year: int,
    resolved: datetime,
) -> _Derived:
    """한 척의 파생값을 구한다 — **실패는 그 값 하나만 무력화한다** (#419).

    ## 세 호출을 따로 잡는다

    이 선박을 계산하는 경로가 셋이다 — 현재 시점(``compute_ytd_cii``), 직전 2개 연도
    (``_prior_confirmed_ratings`` → ``list_cii_history``, 안에서 **연도마다** 같은 계산을
    부르므로 선박당 최대 4회), 최근 구간 시작점(#431).

    **셋을 한 울타리에 넣으면 안 된다.** 첫 호출이 성공해도 뒤가 던지면 이미 나온
    ``ytd``까지 버려져, **제원이 멀쩡하고 등급까지 나온 선박이 「제원 미비」로 표시된다.**
    뒤의 둘은 다른 연도를 보고 이력 조회 창 규칙이라는 **또 다른 검증**을 통과해야 하므로
    앞과 실패 조건이 같지 않다.

    그래서 ``ytd``만 사유를 만들고, 나머지 둘의 실패는 **그 파생값만** 비운다.

    ## 왜 계산 쪽을 고치지 않는가

    ``compute_ytd_cii``가 제원 부족에 예외를 던지는 것 자체는 옳다 — **단건 조회(선박
    상세)에서는 무엇을 채워야 하는지 알려 줘야** 하기 때문이다. 「한 척의 실패가 전체
    실패가 아니다」를 아는 것은 선대를 도는 이쪽이므로, 판단도 여기서 한다.
    """
    # 진행 중 항차 기여분을 넣는다 (`PRD §3.3.8`, `#750`).
    #
    # 종전에는 `as_of`만 넘기고 `in_progress`를 넘기지 않아 **실적 확정분만** 집계했다.
    # 같은 선박을 두고 대시보드는 8.980을, 실시간 CII 화면은 7.028을 냈다 — 이 모듈
    # docstring이 막겠다고 선언한 바로 그 실패다. 수식을 다시 구현하지는 않았고,
    # **인자가 갈려** 같은 결과가 났다.
    #
    # 대시보드의 위험 배너·등급 분포·정렬·`days_to_d`가 전부 이 값 위에서 돌므로
    # (`PRD §3.3.7`), 정의가 다르면 **규제 트리거 판정이 갈릴 수 있다.**
    #
    # **조회 연도에 속하는 항차만 넣는다** (`#815`). `#750`은 「올해를 볼 때만」이라는
    # 약한 기준을 썼는데, 그것은 진행 중 항차가 늘 올해 것이라는 가정에 기댄다.
    # 집계의 나머지는 `Voyage.regulation_year == regulation_year`로 거르므로
    # (`db/repositories/voyage.py:224`) 진행분도 같은 기준을 쓴다.
    #
    # 진행분 조회 실패가 선박 전체를 무효로 만들지 않게 `AppError`를 잡는다 — 이
    # 함수가 통째로 지키려는 원칙(「한 척의 실패가 선대 전체의 실패가 아니다」)이
    # 진행분에도 그대로 적용된다.
    try:
        in_progress = (
            (await resolve_in_progress_state(session, vessel=vessel, as_of=resolved))
            .for_year(year)
            .contribution
        )
    except AppError:
        in_progress = None

    try:
        ytd = await compute_ytd_cii(
            session,
            vessel_id=vessel.id,
            regulation_year=year,
            as_of=resolved,
            in_progress=in_progress,
        )
    except ParameterError:
        # 호출부가 연도를 먼저 확인하므로, 여기 남는 것은 선종별 기준선·등급 경계다.
        return _Derived(_unavailable_ytd(year), [], None, UNAVAILABLE_NO_PARAMETERS)
    except ValidationError:
        # **예외의 종류로 사유를 단정하지 않는다.** 선박을 직접 보고 판정한다 —
        # `_spec_gap` 참조.
        return _Derived(
            _unavailable_ytd(year), [], None, _spec_gap(vessel) or UNAVAILABLE_CALCULATION_ERROR
        )
    except AppError:
        # `CalculationError`(엔진 가드) · `NotFoundError`(목록 조회와 개별 조회 사이의
        # 소프트 삭제 경합) 등. 드물지만 **잡지 않으면 선대 전체가 그 하나에 실패한다** —
        # 이 이슈가 없애려던 바로 그 실패 모드다.
        return _Derived(_unavailable_ytd(year), [], None, UNAVAILABLE_CALCULATION_ERROR)

    #
    # 아래 둘은 **이미 나온 ``ytd``를 무효로 만들지 않는다.**
    #
    try:
        prior = await _prior_confirmed_ratings(
            session,
            vessel_id=vessel.id,
            current_year=year,
            as_of=resolved,
        )
    except AppError:
        # 이력을 못 읽으면 「직전 등급을 모른다」로 둔다. `PRD §3.3.7`의 D 3년 연속
        # 판정은 확정 등급이 없는 해를 이미 D로 치지 않으므로(`모르는 것을 나쁜 쪽으로
        # 단정하지 않는다`) 빈 목록이 그 규칙과 같은 뜻이다.
        prior = []

    #
    # 최근 강도를 재려면 **두 시점**이 필요하다 (#431). 선박당 집계가 한 번 더
    # 늘어나지만, 한 시점만으로는 분모가 정의상 0이 되어 값을 낼 수 없다.
    #
    window_start = resolved - timedelta(days=RECENT_WINDOW_DAYS)
    past = None
    if window_start.year >= year:
        # #864 — 기준선에도 **그 시점의 진행분**이 들어가야 한다. 현재값에는 진행
        # 중 항차의 연초부터 누적이 들어 있으므로 기준선에 빠지면 그 전체가 30일
        # 창의 증가분으로 계상되어 「D등급까지 n일」이 실제보다 몇 배 짧아진다.
        try:
            baseline_in_progress = (
                (await resolve_in_progress_state(session, vessel=vessel, as_of=window_start))
                .for_year(year)
                .contribution
            )
        except AppError:
            # 진행분을 못 재면 기준선을 확정분만으로 둔다 — n일이 과대 짧아질 수
            # 있으나 선박 요약 전체를 무효로 하지는 않는다(#431의 창 미제외 경로와
            # 같은 태도다).
            baseline_in_progress = None
        try:
            past = await compute_ytd_cii(
                session,
                vessel_id=vessel.id,
                regulation_year=year,
                as_of=window_start,
                in_progress=baseline_in_progress,
            )
        except AppError:
            # 최근 구간을 못 재면 「n일」만 사유로 비운다. 올해 누적값은 그대로 쓴다.
            past = None

    return _Derived(
        ytd,
        prior,
        past,
        None if ytd.data_available else UNAVAILABLE_NO_DATA,
    )


async def get_fleet_summary(
    session: AsyncSession,
    *,
    regulation_year: int | None = None,
    as_of: datetime | None = None,
    sort: str = DEFAULT_FLEET_SORT,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, object]:
    """선대 전체 현황을 한 번에 반환한다 (`API_SPEC §2.8`).

    :param regulation_year: 집계 대상 규제연도. 미지정이면 ``as_of`` 연도.
    :param as_of: 기준 시각(``as_of`` 계약 ⑵). 미지정이면 서버가 확정하며,
        응답에 **실제 사용한 값을 반드시 싣는다** — 클라이언트가 같은 값으로 다시
        물어 같은 결과를 얻을 수 있어야 한다(계약 ⑶). **다음 페이지를 물을 때도 첫
        페이지의 ``as_of``를 그대로 싣는다** — 시각이 바뀌면 순서가 바뀌어 페이지 사이에
        선박이 빠지거나 겹친다.
    :param sort: ``vessels[]`` 정렬 — ``risk``(기본) · ``name`` · ``grade`` (#772).
    :param limit: ``vessels[]`` 페이지 크기(`§1.5` — 기본 20, 최대 100).
    :param cursor: 이전 응답의 ``next_cursor``.

    ## 무엇을 자르고 무엇을 자르지 않는가 (#772 · 2026-09-11 결정 3-⑤)

    **``summary``·``actions``는 선대 전체다. ``vessels[]``만 페이지로 자른다.** 위험 선박
    배너·등급 분포는 「이 페이지의 위험 선박 수」가 되는 순간 뜻을 잃는다(`PRD §6.2 SCR-001`).
    그래서 페이지와 무관하게 **전 선박을 계산**한다 — 페이지네이션이 계산량을 줄이지는
    않고, 줄이는 것은 응답 크기다.

    **정렬은 서버가 한다.** 페이지로 자르면 화면이 전체를 정렬할 수 없다 — 1쪽의 위험
    선박 뒤에 2쪽의 더 위험한 선박이 올 수 있다.

    ⚠️ **종전에는 200척에서 조용히 잘렸다** — ``list_active(limit=200)[:200]``이라 201번째
    선박부터 ``summary.total``에도 배너에도 없었다(`#772` 실측: 등록 201척 → total 200).
    이제 자르지 않는다.
    """
    resolved = resolve_as_of(as_of)
    year = regulation_year if regulation_year is not None else resolved.year
    if sort not in FLEET_SORT_KEYS:
        raise ValidationError(
            f"sort는 {' · '.join(FLEET_SORT_KEYS)} 중 하나여야 합니다: {sort}",
            field="sort",
            field_label="정렬",
        )
    page_size = normalize_limit(limit, default=_DEFAULT_PAGE, maximum=_MAX_PAGE)
    offset = _decode_fleet_cursor(cursor, sort) if cursor else 0

    # 선박 목록은 한 번에 가져온다. 여기서 개별 조회를 돌면 그 자체가 N+1이다.
    vessels = await vessel_repo.list_all_active(session)

    #
    # 연도 파라미터는 **선대 공통**이라 루프 밖에서 한 번 확인한다 (#419).
    #
    # 루프 안에서 잡으면 「전 선박이 파라미터 없음」으로 표시되어, 실제 원인(그 해의
    # 규정 seed가 없다)이 선박 문제로 위장된다. `API_SPEC §2.8`도 이 경우를
    # **409 PARAMETER_ERROR**로 규정한다 — 요청 전체가 실패하는 것이 맞다.
    #
    # 이 확인을 먼저 하면, 루프 안에서 남는 ParameterError는 **선종별**(기준선·등급
    # 경계) 뿐이라 선박 단위로 다룰 수 있다.
    #
    # **선박이 0척이면 묻지 않는다.** 아직 아무것도 등록하지 않은 선사가 정상적으로
    # 만나는 상태이고(`API_SPEC §2.8`), 그 화면에 파라미터 오류를 띄우면 사용자는
    # 「기능이 고장났다」로 읽는다. 계산할 대상이 없으므로 파라미터도 필요 없다.
    #
    if vessels and await param_repo.get_regulation_year(session, year) is None:
        raise ParameterError(f"해당 연도의 규정 파라미터가 없습니다. (기준연도 {year})")

    rows: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []

    for vessel in vessels:
        derived = await _derive_vessel(session, vessel, year=year, resolved=resolved)
        ytd = derived.ytd
        unavailable_reason = derived.unavailable_reason
        reasons = evaluate_risk_reasons(ytd_rating=ytd.rating, prior_ratings=derived.prior)
        days = compute_days_to_target(
            ytd,
            past=derived.past,
            underway_state=vessel.underway_state,
            as_of=resolved,
        )

        rows.append(
            {
                "vessel_id": str(vessel.id),
                "name": vessel.name,
                "ship_type": vessel.ship_type,
                "imo_number": vessel.imo_number,
                "underway_state": vessel.underway_state,
                "detail_status": vessel.detail_status,
                # CII 적용 대상 표시 (#653). 화면이 GT로 다시 판정하지 않도록
                # **서버 판정(`is_cii_applicable_hint`)을 그대로** 싣고, 「미해당」과
                # 「GT가 없어 판정 불가」를 가를 수 있게 `gross_tonnage`를 함께 낸다.
                # 두 필드 모두 `API_SPEC §2.1` 선박 객체의 기존 어휘라 새 용어가 없다.
                "is_cii_applicable_hint": vessel.is_cii_applicable_hint,
                "gross_tonnage": _spec_number(vessel.gross_tonnage),
                "current_lat": _publish(vessel.current_lat, 6),
                "current_lon": _publish(vessel.current_lon, 6),
                "position_updated_at": (
                    vessel.position_updated_at.isoformat()
                    if vessel.position_updated_at is not None
                    else None
                ),
                "data_available": ytd.data_available,
                "ytd_attained_cii": _publish(ytd.attained_cii, _CII_DIGITS),
                "ytd_required_cii": _publish(ytd.required_cii, _CII_DIGITS),
                "ytd_rating": ytd.rating,
                "risk_level": ytd.risk_level,
                "risk_reasons": reasons,
                "days_to_d": days.days,
                "days_to_d_reason": days.reason,
                # `data_available=False`인 선박이 **왜** 그런지 (#419).
                "unavailable_reason": unavailable_reason,
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

    ordered = sort_fleet_rows(rows, sort)
    page = ordered[offset : offset + page_size]
    has_more = offset + page_size < len(ordered)
    return {
        "as_of": resolved.isoformat(),
        "regulation_year": year,
        # 선대 전체 — 페이지와 무관하다(위 docstring).
        "summary": _aggregate_counts(rows),
        "vessels": page,
        "actions": actions,
        # 라우트가 `meta`로 옮긴다(`§1.5`). `data`에 남기지 않는다.
        "_page": {
            "next_cursor": _encode_fleet_cursor(offset + page_size, sort) if has_more else None,
            "has_more": has_more,
        },
    }


def _rating_rank(row: dict[str, object]) -> int:
    """나쁜 등급이 큰 값. **등급이 없는 선박(실적 없음)은 가장 뒤**(-1).

    나쁜 등급으로 오해되면 안 된다 — 실적이 없는 것이지 나쁜 것이 아니다.
    """
    rating = row["ytd_rating"]
    return _RATING_ORDER[rating] if isinstance(rating, str) and rating in _RATING_ORDER else -1


def _name_key(row: dict[str, object]) -> str:
    """이름순 — 대소문자를 가르지 않는다(화면의 ``localeCompare`` 기본과 같은 방향)."""
    return str(row["name"]).casefold()


def sort_fleet_rows(rows: list[dict[str, object]], sort: str) -> list[dict[str, object]]:
    """``vessels[]`` 정렬 (#772 — 종전 ``frontend/.../fleetRules.sortVessels``를 옮겼다).

    * ``risk`` (기본) — ⑴ 규제 트리거 선박 먼저 ⑵ YTD 등급이 나쁜 순 ⑶ 이름. 이 화면의 목적이
      「위험 선박 식별」이라 기본이다(`PRD §2.3`) — 이름순이 기본이면 위험 선박이 아래로 숨는다
    * ``grade`` — 등급이 나쁜 순, 같으면 이름
    * ``name`` — 이름

    **마지막 키는 늘 ``vessel_id``다.** 동명·동급 선박의 순서가 요청마다 바뀌면 페이지 사이에
    선박이 겹치거나 빠진다.
    """
    if sort == "name":
        key = lambda r: (_name_key(r), str(r["vessel_id"]))  # noqa: E731
    elif sort == "grade":
        key = lambda r: (-_rating_rank(r), _name_key(r), str(r["vessel_id"]))  # noqa: E731
    else:
        key = lambda r: (  # noqa: E731
            0 if r["risk_reasons"] else 1,
            -_rating_rank(r),
            _name_key(r),
            str(r["vessel_id"]),
        )
    return sorted(rows, key=key)


def _encode_fleet_cursor(offset: int, sort: str) -> str:
    """불투명 커서 — 다음 페이지의 시작 위치와 **그 순서를 만든 정렬 키**를 담는다."""
    return base64.urlsafe_b64encode(json.dumps({"o": offset, "s": sort}).encode()).decode("ascii")


def _decode_fleet_cursor(token: str, sort: str) -> int:
    """커서를 되돌린다. 깨졌거나 **다른 정렬의 커서**면 422다.

    정렬을 바꾸고 옛 커서로 물으면 다른 순서의 n번째부터가 나와 선박이 겹치거나 빠진다 —
    조용히 받아 주지 않는다.
    """
    try:
        payload = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
        offset, cursor_sort = int(payload["o"]), str(payload["s"])
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ValidationError(
            "cursor 형식이 올바르지 않습니다.", field="cursor", field_label="커서"
        ) from None
    if offset < 0 or cursor_sort != sort:
        raise ValidationError(
            "cursor가 이 정렬의 것이 아닙니다. 첫 페이지부터 다시 불러오세요.",
            field="cursor",
            field_label="커서",
        )
    return offset


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
    }
