"""데모 시드의 기준일 창이 실제 상대 시각과 어긋나지 않는가 (`#2106`).

## 무엇이 어긋나 있었나

`demo_seed._ANCHOR_MAX`는 가장 늦은 상대 시각이 `+18d`이던 때의 값(12-13)으로 박혀
있었다. `#1052`가 계획 항차를 `+76d`까지 넣었는데 상한은 그대로여서, 2026-10-17부터
`regulation_year: 2026` 항차의 도착 예정이 2027년으로 넘어갔다 — 코드가 바뀌어서가
아니라 날짜가 지나서 어긋나는, `#792`와 같은 부류다.

## 무엇을 잠그는가

* 창의 두 끝이 **실제 `_rel()` 호출의 최소·최대 일수**에서 유도된다 — 상대 일수를
  넓히고 상수를 안 고치면 여기서 걸린다.
* 창의 양 끝에서 모든 상대 시각이 **그 항차·구간의 `regulation_year` 안**에 남는다.
* 창 밖의 날짜는 `_ANCHOR_FALLBACK`으로 떨어진다 — 이슈가 지목한 세 날짜를 그대로 둔다.

DB를 쓰지 않는다 — 시드 모듈의 상수와 자료만 본다.

케이스 (`TEST_PLAN §5.7`): seed 적재 · `#2106`
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cii_platform.db import demo_seed


def _rel_offsets() -> set[timedelta]:
    """`_rel()`이 만든 시각이 기준일에서 떨어진 거리 — 일수 × (시·분 ≤ 1일 미만)."""
    return {
        timedelta(days=days, hours=h, minutes=m)
        for days in demo_seed._REL_DAYS_IN_USE
        for h in range(24)
        for m in range(60)
    }


def _timed_rows() -> list[tuple[str, int, datetime]]:
    """`regulation_year`를 가진 시드 행의 (출처, 규제연도, 시각) 전부."""
    rows: list[tuple[str, int, datetime]] = []
    for name in ("SEED_VOYAGES", "SEED_VOYAGES_WATCH", "SEED_PERIODS"):
        for row in getattr(demo_seed, name):
            year = row["regulation_year"]
            for key, value in row.items():
                if isinstance(value, datetime):
                    rows.append((f"{name}:{row['id']}:{key}", year, value))
    return rows


def test_anchor_window_is_derived_from_the_relative_days_actually_used() -> None:
    """상수가 실제 `_rel()` 호출과 같다 — 호출을 넓히면 상수도 고쳐야 한다."""
    assert demo_seed._REL_DAYS_IN_USE, "시드가 _rel()을 한 번도 쓰지 않았다"
    assert min(demo_seed._REL_DAYS_IN_USE) == demo_seed._EARLIEST_REL_DAYS
    assert max(demo_seed._REL_DAYS_IN_USE) == demo_seed._LATEST_REL_DAYS

    # 창의 양 끝이 **빡빡하다** — 하루만 넘어도 해가 바뀐다.
    latest = timedelta(days=demo_seed._LATEST_REL_DAYS, hours=23, minutes=59)
    assert (demo_seed._ANCHOR_MAX + latest).year == 2026
    assert (demo_seed._ANCHOR_MAX + timedelta(days=1) + latest).year == 2027
    earliest = timedelta(days=demo_seed._EARLIEST_REL_DAYS)
    assert (demo_seed._ANCHOR_MIN + earliest).year == 2026
    assert (demo_seed._ANCHOR_MIN - timedelta(days=1) + earliest).year == 2025


def test_every_relative_time_stays_in_its_regulation_year_at_both_ends() -> None:
    """기준일을 창의 양 끝에 두어도 상대 시각의 연도가 `regulation_year`와 같다.

    상대 시각은 「기준일 + 기록된 오프셋」이므로, 그 거리가 기록된 오프셋과 **정확히**
    같은 값만 상대 시각으로 본다. 절대 날짜가 우연히 같은 거리에 놓이면 검사가 하나
    더 늘 뿐 틀린 실패는 나지 않는다 — 창 안의 오프셋은 양 끝에서도 같은 해에 남는다.
    """
    offsets = _rel_offsets()
    checked = 0
    for where, year, value in _timed_rows():
        delta = value - demo_seed.DEMO_ANCHOR
        if delta not in offsets:
            continue
        checked += 1
        for edge in (demo_seed._ANCHOR_MIN, demo_seed._ANCHOR_MAX):
            assert (edge + delta).year == year, (
                f"{where}: 기준일 {edge:%m-%d}에서 {edge + delta:%Y-%m-%d}이 되어 "
                f"regulation_year {year}을 벗어난다"
            )
    # 진행 중 항차 2건 · 계획 항차 20건 · 관찰선 구간 — 상대 시각이 수십 개여야 한다.
    assert checked >= 40, f"상대 시각을 {checked}개만 찾았다 — 판별이 깨졌는지 확인할 것"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        # 창 안 — 그날 자정이 기준일이다.
        (datetime(2026, 1, 16, 9, 30, tzinfo=UTC), datetime(2026, 1, 16, tzinfo=UTC)),
        (datetime(2026, 10, 6, 13, 0, tzinfo=UTC), datetime(2026, 10, 6, tzinfo=UTC)),
        (datetime(2026, 10, 16, 23, 59, tzinfo=UTC), datetime(2026, 10, 16, tzinfo=UTC)),
        # 창 밖 — 폴백. 이슈가 지목한 세 날짜와 하한 바로 앞.
        (datetime(2026, 1, 15, tzinfo=UTC), demo_seed._ANCHOR_FALLBACK),
        (datetime(2026, 10, 17, tzinfo=UTC), demo_seed._ANCHOR_FALLBACK),
        (datetime(2026, 10, 20, tzinfo=UTC), demo_seed._ANCHOR_FALLBACK),
        (datetime(2026, 12, 14, tzinfo=UTC), demo_seed._ANCHOR_FALLBACK),
        (datetime(2027, 1, 2, tzinfo=UTC), demo_seed._ANCHOR_FALLBACK),
    ],
)
def test_dates_outside_the_window_fall_back_to_the_fixed_anchor(
    today: datetime, expected: datetime
) -> None:
    """상한 뒤의 날짜는 2026년 고정 기준으로 떨어진다 — 조용히 틀리는 대신."""
    assert demo_seed._resolve_anchor(today) == expected


def test_the_fallback_itself_is_inside_the_window() -> None:
    """폴백이 창 밖이면 폴백한 뒤에도 같은 문제가 난다."""
    assert demo_seed._ANCHOR_MIN <= demo_seed._ANCHOR_FALLBACK <= demo_seed._ANCHOR_MAX
