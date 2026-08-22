"""시뮬레이션 시계 — 시각으로부터 진행 중 항차의 누적량을 확정한다 (#368).

왜 필요한가
-----------
신방향 명세 3은 항해 중 CII가 **실시간으로 변하는 것**을 요구한다. 그런데
``PRD §1 COR-5``가 「MVP는 AIS·IoT를 연동하지 않는다」로 못박고 있어 **값이 저절로
변할 이유가 없다.** 사용자가 다시 입력하기 전까지 화면은 그대로다.

시뮬레이션 시계는 데이터를 받아오는 대신 **서버 시각으로부터 누적량을 계산**한다.
항차에 출항 시각·계획 속도가 있고 선박에 일일 소모율이 있으면 된다::

    출항 2026-08-15 09:00 · 12 kn · 30 t/day
      15:00 조회 → 경과 6h  → 누적 72 nm  · 7.5 t
      21:00 조회 → 경과 12h → 누적 144 nm · 15 t

계층 — 왜 ``calc``가 아니라 ``services``인가
--------------------------------------------
``as_of`` 계약 ⑸: **시뮬레이션 시계는 「입력 확정 계층」에 둔다. Layer 1 계산은
확정된 누적값만 받는다 — 계산 코어는 시각을 모른다.**

시계를 ``calc``에 넣으면 ``TECH_SPEC §1``의 Layer 1 bit-exact 계약(``RK-9`` 불가침)과
부딪힌다. 시계는 **입력을 만들고**, 계산은 **그 입력을 받는다**로 층을 나누면 계산
코어를 건드리지 않는다. 이 모듈의 산출물이 :class:`~cii_platform.services.ytd_cii.
InProgressContribution`이며, ``#353``이 그 주입 지점을 이미 열어 두었다.

이 모듈은 DB에 접근하지 않는다 — 이미 읽어 온 행을 인자로 받는 **순수 함수**다.
그래야 시각 경계 조건을 DB 없이 검증할 수 있다.

재현성
------
``as_of``를 명시적 입력으로 승격시켜 ``TECH_SPEC §5.4`` 1항의 「동일 입력 → 동일
결과」를 그대로 지킨다. 같은 ``as_of``면 몇 번을 호출해도 같은 값이 나온다 —
이 모듈 안에서 ``datetime.now()``를 부르는 곳은 :func:`resolve_as_of` 하나뿐이고,
그 함수는 **확정된 값을 돌려주어** 이후 계산이 전부 그 값 하나에 의존하게 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 하루의 시간(h) — 일일 소모율을 시간당으로 환산할 때 쓴다.
HOURS_PER_DAY = Decimal("24")


def resolve_as_of(as_of: datetime | None) -> datetime:
    """``as_of``를 확정한다 — ``as_of`` 계약 ⑵.

    미지정이면 **서버가 현재 시각을 확정**한다. 호출부는 이 반환값을 응답
    ``meta.as_of``에 그대로 실어야 한다. 그래야 클라이언트가 같은 값으로 다시
    물어 같은 결과를 얻을 수 있다(계약 ⑶).

    tz 없는 값이 들어오면 UTC로 간주한다 — 비교 연산에서 aware/naive가 섞이면
    ``TypeError``가 나고, 그 시점에는 이미 어느 쪽이 의도였는지 알 수 없다.
    """
    if as_of is None:
        return datetime.now(UTC)
    if as_of.tzinfo is None:
        return as_of.replace(tzinfo=UTC)
    return as_of.astimezone(UTC)


@dataclass(frozen=True)
class NotUnderwayWindow:
    """진행량 계산에서 **차감**할 not under way 구간 1건.

    ``ended_at``이 ``None``이면 아직 진행 중인 구간이다 — 이 경우 ``as_of``까지
    이어지는 것으로 본다.
    """

    started_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class VoyageProgress:
    """확정된 진행량 — 이 값이 ``InProgressContribution``으로 넘어간다.

    :param as_of: 실제로 사용한 시각. 응답 ``meta.as_of``에 싣는다.
    :param underway_hours: not under way 구간을 뺀 순수 항해 시간.
    :param distance_nm: 누적 under way 거리.
    :param fuel_ton: 누적 under way 연료.
    :param is_simulated: 시계로 만든 값인지. ``PRD R-5`` 「시뮬레이션 데이터」
        배지의 근거다. 실적이 이미 확정된 항차에서는 ``False``다.
    :param past_planned_arrival: 도착 **실적이 없는데** ``as_of``가 도착 예정일을
        지났는가 (`#649`). 이때 누적은 예정일까지만 세지만, **그 사실이 응답에
        드러나지 않으면 사용자는 값이 왜 멈췄는지 알 수 없다.** 호출부가 이 플래그를
        보고 ``IN_PROGRESS_PAST_ETA`` 경고를 싣는다.
    """

    as_of: datetime
    underway_hours: Decimal
    distance_nm: Decimal
    fuel_ton: Decimal
    is_simulated: bool
    past_planned_arrival: bool = False


def _overlap_hours(
    window_start: datetime,
    window_end: datetime,
    periods: Iterable[NotUnderwayWindow],
    *,
    as_of: datetime,
) -> Decimal:
    """``[window_start, window_end]``와 겹치는 not under way 시간의 합(h).

    구간이 서로 겹치면 그 부분이 두 번 빠진다. ``#376``이 만든
    ``idx_not_underway_period_vessel_started``가 이 조회의 인덱스이며, **구간
    겹침 금지는 ``#370``(입력 경로)의 몫**이다 — 여기서 병합하면 입력이 잘못된
    것을 조용히 덮어 정합성 문제가 화면에서 보이지 않게 된다.
    """
    total = Decimal(0)
    for period in periods:
        start = max(period.started_at, window_start)
        end = min(period.ended_at if period.ended_at is not None else as_of, window_end)
        if end <= start:
            continue
        total += Decimal(str((end - start).total_seconds())) / Decimal("3600")
    return total


def compute_progress(
    *,
    as_of: datetime,
    departure_at: datetime | None,
    arrival_at: datetime | None,
    speed_kn: Decimal | None,
    daily_foc_ton: Decimal | None,
    planned_arrival_at: datetime | None = None,
    not_underway_periods: Iterable[NotUnderwayWindow] = (),
) -> VoyageProgress:
    """진행 중 항차의 누적 거리·연료를 확정한다.

    호출부가 이미 읽어 온 값을 받는다 — 이 함수는 DB를 모른다.

    경계 처리
    ---------
    * **출항 시각이 없으면** 진행량은 0이다. 아직 시작하지 않은 항차이거나
      계획만 있는 항차이며, 임의의 기준 시각을 만들어 내면 그 순간부터 값이
      근거 없이 늘어난다.
    * **``as_of``가 출항 이전이면** 0이다 — 음수 경과 시간을 0으로 자른다.
    * **도착 실적이 있으면** ``min(as_of, arrival_at)``까지만 센다. 도착한 항차의
      누적량이 시간이 지난다고 계속 늘면 안 된다. 이때 ``is_simulated``는
      ``False``다 — 시계가 만든 값이 아니라 실적 구간이다.
    * **도착 실적이 없는데 ``as_of``가 도착 예정일을 지났으면** 예정일까지만 센다
      (`#649`). 종전에는 상한이 없어 **계획을 아무리 넘겨도 거리·연료가 계속
      자랐다** — 출항 90일 뒤면 계획의 7배가 된다. 실사용에서 이 상태는
      「운항이 계속되고 있다」가 아니라 **「도착 실적 입력을 잊었다」**이다.

      ``is_simulated``는 ``True``로 남는다. 잘렸어도 **여전히 시계가 만든 값**이며,
      계획은 실적이 아니므로 「확정됐다」로 읽히게 하지 않는다. 대신
      ``past_planned_arrival``이 서고 호출부가 경고를 싣는다.
    * **속도·일일 소모율이 없으면** 각각 0으로 둔다. ``reference_daily_foc_ton``은
      ``nullable``이며(``DB_SCHEMA §2.1``), 없는 선박에 임의 기본값을 넣으면
      화면이 근거 없는 연료를 표시한다.

    not under way 구간은 **거리에서만 빠지는 것이 아니라 시간에서 빠진다.**
    그래서 정박 중에는 거리도 under way 연료도 늘지 않고, 정박 연료(``#345``
    ``not_underway_fuel_use``)만 별도로 집계된다 — 이것이 「정박이 지속되면 등급이
    나빠진다」가 성립하는 구조다.
    """
    zero = Decimal(0)
    if departure_at is None:
        return VoyageProgress(
            as_of=as_of,
            underway_hours=zero,
            distance_nm=zero,
            fuel_ton=zero,
            is_simulated=False,
        )

    departure_at = resolve_as_of(departure_at)
    window_end = as_of
    is_simulated = True
    past_planned_arrival = False
    if arrival_at is not None:
        arrival_at = resolve_as_of(arrival_at)
        if arrival_at <= as_of:
            # 실적이 확정된 구간이다 — 시계가 값을 만들어 내지 않는다.
            window_end = arrival_at
            is_simulated = False
    elif planned_arrival_at is not None:
        # 실적이 없을 때만 계획을 본다 — 실적이 있으면 그쪽이 사실이다 (`#649`).
        planned_arrival_at = resolve_as_of(planned_arrival_at)
        if planned_arrival_at <= as_of:
            window_end = planned_arrival_at
            past_planned_arrival = True

    if window_end <= departure_at:
        # 예정일이 출항보다 앞서는 등 창이 비면 진행량이 0이다. 그래도 「예정일을
        # 지났다」는 사실은 남긴다 — 값이 0인 이유를 화면이 말할 수 있어야 한다.
        return VoyageProgress(
            as_of=as_of,
            underway_hours=zero,
            distance_nm=zero,
            fuel_ton=zero,
            is_simulated=False,
            past_planned_arrival=past_planned_arrival,
        )

    elapsed_hours = Decimal(str((window_end - departure_at).total_seconds())) / Decimal("3600")
    nuw_hours = _overlap_hours(departure_at, window_end, not_underway_periods, as_of=as_of)
    underway_hours = max(elapsed_hours - nuw_hours, zero)

    distance_nm = (speed_kn or zero) * underway_hours
    fuel_ton = (daily_foc_ton or zero) * underway_hours / HOURS_PER_DAY

    return VoyageProgress(
        as_of=as_of,
        underway_hours=underway_hours,
        distance_nm=distance_nm,
        fuel_ton=fuel_ton,
        is_simulated=is_simulated and underway_hours > zero,
        past_planned_arrival=past_planned_arrival,
    )
