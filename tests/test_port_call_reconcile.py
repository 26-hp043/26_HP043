"""공적 기록 대조 규칙 (`#1197` · ``PRD §17.4.4`` · 결정 G-7) — DB 없이.

경계가 이 규칙의 전부다. 6시간 **정각은 띄우지 않고** 6시간 1분은 띄운다(결정 G-7 ①).
짝지을 기항이 48시간 밖이면 「틀렸다」가 아니라 **대조 불가**다(``PRD §15.1`` 제약 ⑸).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cii_platform.port_calls.reconcile import (
    FIELD_ARRIVAL,
    FIELD_BERTH_END,
    FIELD_BERTH_START,
    FIELD_DEPARTURE,
    MATCH_WINDOW,
    TOLERANCE,
    EnteredTime,
    RecordedCall,
    reconcile,
)

FETCHED = datetime(2026, 9, 26, tzinfo=UTC)
#: 공적 기록 — 부산 08-08 23:00 입항(묘박) · 08-09 19:00 출항 (결정 G-7 근거표의 예).
ARRIVED = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)
DEPARTED = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
BUSAN = RecordedCall(
    port_authority_code="020",
    port_authority_name="부산",
    arrival_at=ARRIVED,
    departure_at=DEPARTED,
    fetched_at=FETCHED,
)


def _arrival(at: datetime, port: str | None = "BUSAN") -> list[EnteredTime]:
    return [EnteredTime(FIELD_ARRIVAL, at, port)]


def test_exactly_six_hours_is_not_flagged_but_one_minute_more_is():
    assert reconcile(_arrival(ARRIVED + TOLERANCE), [BUSAN]) == []
    [mismatch] = reconcile(_arrival(ARRIVED + TOLERANCE + timedelta(minutes=1)), [BUSAN])
    assert mismatch.field == FIELD_ARRIVAL
    assert mismatch.recorded_at == ARRIVED
    assert mismatch.difference_minutes == 6 * 60 + 1
    assert mismatch.port_authority_name == "부산"
    assert mismatch.fetched_at == FETCHED


def test_earlier_entry_is_flagged_the_same_way():
    """방향은 보지 않는다 — 넣은 값이 12시간 이르면 12시간 늦은 것과 같다(오전·오후 착오)."""
    [mismatch] = reconcile(_arrival(ARRIVED - timedelta(hours=12)), [BUSAN])
    assert mismatch.difference_minutes == 12 * 60


def test_no_call_within_the_window_is_not_a_mismatch():
    """48시간 밖이면 견줄 기항이 없다 — 대조 불가. 48시간 정각까지는 견준다."""
    assert reconcile(_arrival(ARRIVED + MATCH_WINDOW + timedelta(minutes=1)), [BUSAN]) == []
    assert reconcile(_arrival(ARRIVED + MATCH_WINDOW), [BUSAN]) != []


def test_unknown_port_or_other_authority_is_not_compared():
    """항구를 항만청과 잇지 못하거나 그 항만청 기록이 없으면 대조 불가다."""
    late = ARRIVED + timedelta(hours=12)
    assert reconcile(_arrival(late, "SINGAPORE"), [BUSAN]) == []
    assert reconcile(_arrival(late, None), [BUSAN]) == []
    assert reconcile(_arrival(late, "ULSAN"), [BUSAN]) == []
    assert reconcile([EnteredTime(FIELD_ARRIVAL, None, "BUSAN")], [BUSAN]) == []


def test_departure_is_compared_with_the_latest_departure_of_the_call():
    """출항은 출항 쪽과 — 입항 시각과 가까워도 입항과 견주지 않는다."""
    entered = [EnteredTime(FIELD_DEPARTURE, ARRIVED, "BUSAN")]
    [mismatch] = reconcile(entered, [BUSAN])
    assert mismatch.recorded_at == DEPARTED


def test_nearest_call_is_chosen():
    """같은 항만청에 기항이 여럿이면 가장 가까운 기항과 견준다."""
    next_week = RecordedCall("020", "부산", ARRIVED + timedelta(days=7), None, FETCHED)
    assert reconcile(_arrival(ARRIVED + timedelta(days=7, hours=1)), [BUSAN, next_week]) == []


def test_berth_period_uses_both_ends_and_results_come_in_field_order():
    """정박 구간은 시작 ↔ 입항, 끝 ↔ 출항. 결과는 칸 종류 순(출항 · 도착 · 정박 시작 · 끝)."""
    entries = [
        EnteredTime(FIELD_BERTH_END, DEPARTED + timedelta(hours=24), "부산"),
        EnteredTime(FIELD_BERTH_START, ARRIVED + timedelta(hours=7), "부산"),
        EnteredTime(FIELD_ARRIVAL, ARRIVED + timedelta(hours=8), "BUSAN"),
    ]
    fields = [item.field for item in reconcile(entries, [BUSAN])]
    assert fields == [FIELD_ARRIVAL, FIELD_BERTH_START, FIELD_BERTH_END]
