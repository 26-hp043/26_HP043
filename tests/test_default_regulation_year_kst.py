"""연도를 지정하지 않았을 때의 「올해」는 한국 달력의 해다 (`#2131`).

## 이 파일이 지키는 것

서버는 ``as_of``를 UTC로 확정한다. 그 값의 ``.year``를 그대로 읽으면 KST 1월 1일
0시~8시 59분(UTC로는 전년도 12월 31일 15시~23시 59분)에 **전년도가 「올해」**가 된다.
사용자는 KST로 일하므로(``DESIGN_SYSTEM §4.4`` · ``PRD §12.7``) 그 시간대에 대시보드를 열면
새해 집계가 보여야 하고, 한국 달력으로 자르는 내보내기와 같은 해여야 한다.

검사는 **경계 시각** ``2026-01-01T02:00:00+09:00``(= UTC ``2025-12-31T17:00:00Z``)에서
연도를 주지 않은 요청의 기본 연도가 2026인지 본다. 항차·정박 구간의 귀속 연도(UTC 고정,
`#1333`)는 이 파일의 대상이 아니다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.db.demo_seed import VESSEL_ID_BULK
from cii_platform.services import chat_tools
from cii_platform.services.simulation_clock import current_regulation_year, resolve_as_of

KST = timezone(timedelta(hours=9))

#: UTC 달력으로는 2025, 한국 달력으로는 2026인 순간.
KST_NEW_YEAR_EARLY = datetime(2026, 1, 1, 2, 0, tzinfo=KST)


def test_boundary_instant_is_utc_previous_year():
    """전제 — 이 순간을 UTC로 확정하면 `.year`는 전년도다(검사가 의미 있는 입력인지)."""
    assert resolve_as_of(KST_NEW_YEAR_EARLY).year == 2025


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2025, 12, 31, 14, 59, 59, tzinfo=UTC), 2025),
        (datetime(2025, 12, 31, 15, 0, 0, tzinfo=UTC), 2026),
        (KST_NEW_YEAR_EARLY, 2026),
        (datetime(2026, 12, 31, 14, 59, 59, tzinfo=UTC), 2026),
        (datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC), 2027),
    ],
)
def test_current_regulation_year_follows_the_korean_calendar(instant, expected):
    assert current_regulation_year(instant) == expected


def test_current_regulation_year_ignores_the_offset_it_was_given():
    """같은 순간이면 어떤 오프셋으로 표기돼도 같은 해다."""
    instant = datetime(2025, 12, 31, 17, 0, tzinfo=UTC)
    assert current_regulation_year(instant) == current_regulation_year(instant.astimezone(KST))
    assert current_regulation_year(instant.astimezone(timezone(timedelta(hours=-8)))) == 2026


def test_current_regulation_year_does_not_depend_on_host_timezone(monkeypatch):
    """호스트 시간대를 바꿔도 같은 값이다 — 시간대를 코드가 고정한다."""
    import time

    if not hasattr(time, "tzset"):
        pytest.skip("tzset이 없는 플랫폼")
    try:
        for zone in ("UTC", "America/Los_Angeles", "Asia/Seoul"):
            monkeypatch.setenv("TZ", zone)
            time.tzset()
            assert current_regulation_year(KST_NEW_YEAR_EARLY) == 2026
    finally:
        monkeypatch.undo()
        time.tzset()


def test_chat_tool_default_year_uses_the_korean_calendar(monkeypatch):
    """챗봇 도구가 모델이 연도를 말하지 않았을 때 쓰는 「올해」도 같은 해다."""

    class _FrozenNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return KST_NEW_YEAR_EARLY.astimezone(tz) if tz else KST_NEW_YEAR_EARLY

    monkeypatch.setattr(chat_tools, "datetime", _FrozenNow)
    assert chat_tools._regulation_year({}) == 2026


@pytest.mark.parametrize(
    "path",
    [
        f"/vessels/{VESSEL_ID_BULK}/cii/current",
        f"/vessels/{VESSEL_ID_BULK}/cii/ytd-series",
        "/fleet/summary",
        "/fleet/notifications",
    ],
)
def test_http_default_year_is_the_korean_year(migrated_db, app_fresh_engine, path):
    """연도 없는 요청의 응답 `regulation_year`가 UTC가 아니라 한국 달력의 해다."""
    with TestClient(app, base_url="https://testserver") as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        response = client.get(
            f"{API_V1_PREFIX}{path}", params={"as_of": KST_NEW_YEAR_EARLY.isoformat()}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["regulation_year"] == 2026


def test_http_cii_history_default_window_ends_in_the_korean_year(migrated_db, app_fresh_engine):
    """`to`를 주지 않은 연도별 이력의 마지막 해가 한국 달력의 해다 (`cii_history`)."""
    with TestClient(app, base_url="https://testserver") as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        response = client.get(
            f"{API_V1_PREFIX}/vessels/{VESSEL_ID_BULK}/cii-history",
            params={"as_of": KST_NEW_YEAR_EARLY.isoformat()},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["to"] == 2026


def test_http_data_quality_default_year_is_the_korean_year(
    migrated_db, app_fresh_engine, monkeypatch
):
    """데이터 점검은 `as_of`를 받지 않아 서비스가 읽는 시계를 고정한다 (`data_quality`)."""
    from cii_platform.services import data_quality

    frozen = KST_NEW_YEAR_EARLY.astimezone(UTC)
    monkeypatch.setattr(data_quality, "resolve_as_of", lambda _as_of: frozen)
    with TestClient(app, base_url="https://testserver") as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        response = client.get(f"{API_V1_PREFIX}/fleet/data-quality")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["regulation_year"] == 2026


def test_http_annual_report_default_year_is_the_korean_year(migrated_db, app_fresh_engine):
    """연간 리포트의 `year` 미지정은 한국 달력의 해로 만든다 (`report`)."""
    with TestClient(app, base_url="https://testserver") as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        response = client.get(
            f"{API_V1_PREFIX}/vessels/{VESSEL_ID_BULK}/annual-report",
            params={"format": "html", "as_of": KST_NEW_YEAR_EARLY.isoformat()},
        )
        assert response.status_code == 200, response.text
        assert "2026년 누적 (YTD)" in response.text
        assert "2025년 누적 (YTD)" not in response.text


def test_days_to_target_treats_the_previous_korean_year_as_ended():
    """끝난 규제연도 판정이 한국 달력의 해로 한다 (`fleet_summary`).

    UTC 해(2025)로 재면 2025는 아직 올해라 「앞으로 n일」을 계산하러 들어간다.
    """
    from cii_platform.services.fleet_summary import REASON_NOT_THIS_YEAR, compute_days_to_target
    from cii_platform.services.ytd_cii import YtdCiiOutput

    result = compute_days_to_target(
        YtdCiiOutput.__new__(YtdCiiOutput),
        past=None,
        underway_state="UNDER_WAY",
        as_of=KST_NEW_YEAR_EARLY.astimezone(UTC),
        regulation_year=2025,
    )
    assert result.days is None
    assert result.reason == REASON_NOT_THIS_YEAR
