"""기상 캐시 신선도의 6시간·24시간 경계 (`API_SPEC §9.1` · `PRD §11.6` · #2144).

## 왜 필요한가

`tests/test_weather_fallback_db.py`는 3시간·10시간·30시간만 넣는다. 세 값 모두 경계에서
멀어, 비교가 `>`에서 `>=`로 바뀌어도 통과한다. 그러면 **정확히 6시간 된 값**에 「오래된
기상 데이터」 경고가 붙고, **정확히 24시간 된 값**은 버려져 보정 없이 계산된다.

## 경계는 정본에서 읽는다

`API_SPEC §9.1`의 신선도 표(`age ≤ 6h` · `6h < age ≤ 24h` · `age > 24h`)를 **기계로 읽어**
그 시각과 그 1초 뒤를 넣는다. 숫자를 여기 다시 적지 않는다.

같은 경계를 쓰는 자리가 둘이다 — 조회 응답의 `freshness_of`와 fallback 체인의
`_fallback_snapshot`. `PRD §11.6` `[#968]`이 뒤쪽을 「6시간 초과 `WEATHER_STALE` ·
24시간 초과 폐기」로 적는다. 둘이 갈리면 「경고는 붙었는데 화면은 신선하다」가 된다.

DB 없이 돈다 — 저장소 조회(`find_last_snapshot`)만 가짜로 바꾼다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from cii_platform.services import weather as weather_service
from cii_platform.services.weather import (
    FRESHNESS_EXPIRED,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    WARNING_WEATHER_STALE,
    _fallback_snapshot,
    freshness_of,
)

API_SPEC = Path(__file__).resolve().parents[1] / "API_SPEC.md"
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
ONE_SECOND = timedelta(seconds=1)


def _documented_limits() -> tuple[int, int]:
    """`API_SPEC §9.1` 신선도 표에서 (FRESH 상한, STALE 상한) 시간을 읽는다."""
    text = API_SPEC.read_text(encoding="utf-8")
    start = text.index("### 9.1 기상 스냅샷 조회")
    block = text[start : text.index("### 9.2", start)]
    fresh = re.search(r"^\| `FRESH` \| age ≤ (\d+)h \|$", block, re.MULTILINE)
    stale = re.search(r"^\| `STALE` \| (\d+)h < age ≤ (\d+)h \|$", block, re.MULTILINE)
    expired = re.search(r"^\| `EXPIRED` \| age > (\d+)h \|$", block, re.MULTILINE)
    assert fresh and stale and expired, "§9.1 신선도 표의 모양이 바뀌었다 — 이 읽기를 고친다"
    # 세 행이 서로 이어진다 — 빈틈이나 겹침이 있으면 경계가 정해지지 않는다.
    assert fresh.group(1) == stale.group(1)
    assert stale.group(2) == expired.group(1)
    return int(stale.group(1)), int(stale.group(2))


FRESH_LIMIT_H, STALE_LIMIT_H = _documented_limits()


def test_the_documented_limits_were_read():
    """표를 못 읽고 0·0으로 도는 일을 막는다."""
    assert 0 < FRESH_LIMIT_H < STALE_LIMIT_H


def _age_hours(age: timedelta) -> float:
    return age.total_seconds() / 3600


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(hours=FRESH_LIMIT_H), FRESHNESS_FRESH),
        (timedelta(hours=FRESH_LIMIT_H) + ONE_SECOND, FRESHNESS_STALE),
        (timedelta(hours=STALE_LIMIT_H), FRESHNESS_STALE),
        (timedelta(hours=STALE_LIMIT_H) + ONE_SECOND, FRESHNESS_EXPIRED),
    ],
    ids=["fresh-limit", "fresh-limit+1s", "stale-limit", "stale-limit+1s"],
)
def test_freshness_changes_only_after_the_limit(age, expected):
    """`age ≤ 6h`는 FRESH, `age ≤ 24h`는 STALE — 두 상한 모두 **포함**이다."""
    assert freshness_of(_age_hours(age)) == expected


@pytest.mark.parametrize(
    ("age", "used", "warnings"),
    [
        (timedelta(hours=FRESH_LIMIT_H), True, []),
        (timedelta(hours=FRESH_LIMIT_H) + ONE_SECOND, True, [WARNING_WEATHER_STALE]),
        (timedelta(hours=STALE_LIMIT_H), True, [WARNING_WEATHER_STALE]),
        (timedelta(hours=STALE_LIMIT_H) + ONE_SECOND, False, []),
    ],
    ids=["fresh-limit", "fresh-limit+1s", "stale-limit", "stale-limit+1s"],
)
async def test_fallback_chain_uses_the_same_limits(monkeypatch, age, used, warnings):
    """fallback 체인도 같은 자리에서 갈린다.

    `PRD §11.6` `[#968]` — 6시간 **초과**면 경고, 24시간 **초과**면 쓰지 않는다.
    """
    snapshot = SimpleNamespace(fetched_at=NOW - age)

    async def find_last_snapshot(session, *, lat_rounded, lon_rounded):
        return snapshot

    monkeypatch.setattr(weather_service.weather_repo, "find_last_snapshot", find_last_snapshot)

    found, got_warnings = await _fallback_snapshot(None, lat=35.0, lon=129.0, now=NOW)

    assert (found is snapshot) is used
    assert (found is None) is not used
    assert got_warnings == warnings
