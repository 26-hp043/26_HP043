"""공적 기록 대조 규칙 (`#1197` B단계 · ``PRD §17.4.4`` · 결정 G-7).

사용자가 넣은 시각과 공적 재항 기록(``port_call_record``)을 견줘 **6시간을 넘게** 다른 것만
돌려준다. 값을 바꾸지 않고 계산에도 들어가지 않는다(``PRD §17.1``) — 결과는 데이터 점검
화면의 안내뿐이다. DB를 읽지 않는 순수 함수다(``TECH_SPEC §16`` — 판단은 여기, 조회는 서비스).

## 무엇과 무엇을 견주나

=================  ============================  =====================================
대조 칸            사용자가 넣은 값              공적 기록 (그 항구의 항만청)
=================  ============================  =====================================
``DEPARTURE``      항차 ``actual_departure_at``   출발항 기항의 **가장 늦은 출항**
``ARRIVAL``        항차 ``actual_arrival_at``     도착항 기항의 **가장 이른 입항**
``BERTH_START``    정박 구간 ``started_at``       그 항구 기항의 가장 이른 입항
``BERTH_END``      정박 구간 ``ended_at``         그 항구 기항의 가장 늦은 출항
=================  ============================  =====================================

가장 이른 입항 ~ 가장 늦은 출항은 결정 G-7 ①-2 ⓐ다 — 묘박 대기까지 포함한 체류 전체라, 도착을
닻 내린 시각으로 적든 접안 시각으로 적든 같은 뜻이 된다.

## 어느 기항과 견주나 — 가장 가까운 것, 단 48시간 안

같은 항만청의 기록 중 **시각이 가장 가까운 기항**을 고른다. 그 차이가

* **6시간 이하** → 맞다(띄우지 않는다). 6시간 정각도 띄우지 않는다(결정 G-7 ①).
* **6시간 초과 ~ 48시간 이하** → 「공적 기록과 다름」.
* **48시간 초과** → 견줄 기항이 없다 — **대조 불가**로 두고 띄우지 않는다(``PRD §15.1`` 제약
  ⑸ 「기항 자체가 없으면 어긋남이 아니라 대조 불가」). 받아 둔 기간 밖이거나 다른 항구에 댔을
  수 있고, 그것을 「틀렸다」고 단정할 근거가 없다.

48시간은 흔한 실수 가운데 가장 큰 것(날짜 하루 착오 · 24시간)을 잡고도 남는 폭이다. 이 폭을
넓히면 다음 기항을 잘못 짝지어 엉뚱한 시각과 견줄 위험이 커진다 — 시연 대상 두 척은 부산에
V7UJ2 13개월 26회 · D7ZY 8개월 33회 기항했다(`#1197` 09-23 코멘트 §2). 평균 간격이 일주일
안팎이라 48시간 안에 다른 기항이 끼어들 일은 드물다(정황 — 평균이지 최소 간격이 아니다).

항구 이름을 항만청코드로 잇지 못하면(해외 항구 · 모르는 이름) 그 칸은 대조 불가다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from cii_platform.port_calls.authorities import authority_for_port

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: 허용 오차 — 이보다 **크면** 띄운다(결정 G-7 ① · 2026-09-24).
TOLERANCE = timedelta(hours=6)
#: 짝지을 기항을 찾는 폭 — 이보다 멀면 대조 불가(위 docstring).
MATCH_WINDOW = timedelta(hours=48)

FIELD_DEPARTURE = "DEPARTURE"
FIELD_ARRIVAL = "ARRIVAL"
FIELD_BERTH_START = "BERTH_START"
FIELD_BERTH_END = "BERTH_END"
#: 한 항차 안에서 어긋남을 싣는 순서 — 시간 흐름(출항 → 정박 → 도착)이 아니라 칸 종류 순이다.
FIELD_ORDER: tuple[str, ...] = (
    FIELD_DEPARTURE,
    FIELD_ARRIVAL,
    FIELD_BERTH_START,
    FIELD_BERTH_END,
)

_ARRIVAL_SIDE = "arrival"
_DEPARTURE_SIDE = "departure"


@dataclass(frozen=True)
class RecordedCall:
    """대조에 쓰는 공적 기록 한 건 — ``port_call_record``에서 필요한 칸만."""

    port_authority_code: str
    port_authority_name: str | None
    arrival_at: datetime | None
    departure_at: datetime | None
    fetched_at: datetime


@dataclass(frozen=True)
class Mismatch:
    """6시간을 넘게 다른 칸 하나."""

    field: str
    entered_at: datetime
    recorded_at: datetime
    port_authority_code: str
    port_authority_name: str | None
    fetched_at: datetime

    @property
    def difference_minutes(self) -> int:
        """차이(분) — 절댓값 · 분 아래는 버린다(표시용)."""
        return int(abs(self.entered_at - self.recorded_at).total_seconds() // 60)


@dataclass(frozen=True)
class EnteredTime:
    """사용자가 넣은 시각 하나와 그 항구."""

    field: str
    at: datetime | None
    port_name: str | None


def _side(field: str) -> str:
    return _ARRIVAL_SIDE if field in (FIELD_ARRIVAL, FIELD_BERTH_START) else _DEPARTURE_SIDE


def _nearest(
    entered: datetime, authority: str, side: str, records: Iterable[RecordedCall]
) -> tuple[RecordedCall, datetime] | None:
    best: tuple[RecordedCall, datetime] | None = None
    best_gap: timedelta | None = None
    for record in records:
        if record.port_authority_code != authority:
            continue
        recorded = record.arrival_at if side == _ARRIVAL_SIDE else record.departure_at
        if recorded is None:
            continue
        gap = abs(entered - recorded)
        if best_gap is None or gap < best_gap:
            best, best_gap = (record, recorded), gap
    return best


def reconcile(entries: Sequence[EnteredTime], records: Sequence[RecordedCall]) -> list[Mismatch]:
    """넣은 시각들 가운데 공적 기록과 6시간을 넘게 다른 것 — :data:`FIELD_ORDER` 순."""
    mismatches: list[Mismatch] = []
    for entry in entries:
        if entry.at is None:
            continue
        authority = authority_for_port(entry.port_name)
        if authority is None:
            continue  # 항구를 항만청과 잇지 못한다 — 대조 불가
        found = _nearest(entry.at, authority, _side(entry.field), records)
        if found is None:
            continue  # 그 항만청 기록이 없다 — 대조 불가
        record, recorded_at = found
        gap = abs(entry.at - recorded_at)
        if gap > MATCH_WINDOW or gap <= TOLERANCE:
            continue
        mismatches.append(
            Mismatch(
                field=entry.field,
                entered_at=entry.at,
                recorded_at=recorded_at,
                port_authority_code=record.port_authority_code,
                port_authority_name=record.port_authority_name,
                fetched_at=record.fetched_at,
            )
        )
    mismatches.sort(key=lambda item: (FIELD_ORDER.index(item.field), item.entered_at))
    return mismatches
