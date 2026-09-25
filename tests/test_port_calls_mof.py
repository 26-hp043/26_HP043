"""해양수산부 선박운항정보 제공자 — 실제 응답 표본으로 읽기·부르기 (#1197 B단계 ①).

표본은 2026-09-25 실제 호출이다(부산 ``020`` · 2026-08 · 임시 브랜치 워크플로 1회 실행 뒤
브랜치·실행 기록 삭제 — 09-23 ``#1623``과 같은 방식). 공공데이터포털 공개 자료다.

- ``mof_V7UJ2_busan_202608.xml`` — STAR SKIPPER, 기항 2
- ``mof_D7ZY_busan_202608.xml`` — DONGJIN ENDURANCE, 기항 5
  (첫 기항은 묘박지로 들어와 부두에서 나감)
- ``mof_empty_page.xml`` — D7ZY의 마지막 뒤 페이지(``items`` 빔 · ``resultCode 00`` ·
  ``totalCount``는 전체 기항 수 5 그대로)

케이스: (`TEST_PLAN §14.5` 정의 없음 — 외부 제공자 어댑터)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from cii_platform.port_calls.mof_vessel_ops import (
    MofVesselOpsProvider,
    PortCallApiError,
    load_service_key,
    month_windows,
    parse_response,
)
from cii_platform.port_calls.provider import (
    KIND_ARRIVAL,
    REQUEST_FINAL,
    REQUEST_FIRST,
    PortCall,
    PortCallReport,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "port_calls"
_V7UJ2 = (_FIXTURES / "mof_V7UJ2_busan_202608.xml").read_bytes()
_D7ZY = (_FIXTURES / "mof_D7ZY_busan_202608.xml").read_bytes()
_EMPTY = (_FIXTURES / "mof_empty_page.xml").read_bytes()


def _kst(text: str) -> datetime:
    return datetime.fromisoformat(f"{text}+09:00")


# --- 읽기 ------------------------------------------------------------------------


def test_real_response_is_read_into_port_calls():
    calls, total = parse_response(_V7UJ2)
    assert total == 2
    assert [c.call_seq for c in calls] == ["014", "015"]
    first = calls[0]
    assert (first.call_sign, first.port_authority_code, first.call_year) == ("V7UJ2", "020", 2026)
    assert (first.previous_port, first.next_port) == ("JPAXT", "JPAXT")
    assert first.arrival_at == _kst("2026-08-08T14:20:00")
    assert first.departure_at == _kst("2026-08-09T12:20:00")
    assert first.gross_tonnage == Decimal("9520")


def test_anchorage_then_berth_is_one_stay():
    """묘박지로 들어와 부두에서 나간 기항 — 입항·출항 시설이 달라도 한 체류다 (G-7 ⓐ)."""
    calls, total = parse_response(_D7ZY)
    assert total == 5
    first = calls[0]
    facilities = [(r.kind, r.facility_name) for r in first.reports]
    assert facilities == [("ARRIVAL", "남외항 N-3박지"), ("DEPARTURE", "7부두 71선석")]
    assert first.arrival_at == _kst("2026-08-01T06:30:00")
    assert first.departure_at == _kst("2026-08-02T21:45:00")


def test_empty_page_after_the_last_is_normal():
    assert parse_response(_EMPTY) == ([], 5)


def test_error_code_is_raised_without_echoing_the_payload():
    payload = (
        b"<response><header><resultCode>11</resultCode>"
        b"<resultMsg>INVALID_REQUEST_PARAMETER_ERROR</resultMsg></header></response>"
    )
    with pytest.raises(PortCallApiError) as caught:
        parse_response(payload)
    assert caught.value.code == "11"
    with pytest.raises(PortCallApiError) as caught:
        parse_response(b"<html>gateway error serviceKey=SECRET</html")
    assert "SECRET" not in str(caught.value)


# --- 한 기항의 규칙 --------------------------------------------------------------


def _call(*reports: PortCallReport) -> PortCall:
    return PortCall(
        source="T",
        port_authority_code="020",
        call_year=2026,
        call_seq="001",
        call_sign="X",
        reports=reports,
    )


def test_final_report_wins_over_first():
    """``최초``·``최종``이 섞이면 ``최종``만 쓴다 — 정정 전 시각으로 대조하지 않는다 (09-23)."""
    call = _call(
        PortCallReport(KIND_ARRIVAL, REQUEST_FIRST, _kst("2026-08-01T01:00:00")),
        PortCallReport(KIND_ARRIVAL, REQUEST_FINAL, _kst("2026-08-01T05:00:00")),
    )
    assert call.arrival_at == _kst("2026-08-01T05:00:00")
    # 최종이 없으면 있는 것을 쓴다.
    only_first = _call(PortCallReport(KIND_ARRIVAL, REQUEST_FIRST, _kst("2026-08-01T01:00:00")))
    assert only_first.arrival_at == _kst("2026-08-01T01:00:00")
    assert only_first.departure_at is None


def test_gross_tonnage_prefers_grtg_and_skips_zero():
    """내항선은 국제총톤수가 ``0``으로 온다 — ``grtg``를 먼저, 0은 값이 아니다 (09-23)."""
    call = _call(
        PortCallReport(
            KIND_ARRIVAL,
            REQUEST_FINAL,
            _kst("2026-08-01T01:00:00"),
            gross_tonnage=Decimal("4559"),
            international_gross_tonnage=Decimal("0"),
        )
    )
    assert call.gross_tonnage == Decimal("4559")


# --- 부르기 ----------------------------------------------------------------------


def test_month_windows_split_on_calendar_months():
    """1년 범위는 오류(#1623) — 달력 월로 나눈다. 양 끝 포함."""
    assert month_windows(date(2026, 1, 12), date(2026, 3, 5)) == [
        (date(2026, 1, 12), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 5)),
    ]
    assert month_windows(date(2026, 8, 1), date(2026, 8, 1)) == [
        (date(2026, 8, 1), date(2026, 8, 1))
    ]
    with pytest.raises(ValueError):
        month_windows(date(2026, 8, 2), date(2026, 8, 1))


async def test_provider_walks_months_and_stops_when_total_is_reached():
    """월마다 부르고, 모은 수가 ``totalCount``에 닿으면 다음 페이지를 부르지 않는다."""
    asked: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlparse(str(request.url)).query)
        asked.append(query)
        body = _V7UJ2 if query["sde"] == ["20260801"] else _EMPTY
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MofVesselOpsProvider("K" * 64, client)
        calls = await provider.fetch(
            call_sign="V7UJ2",
            port_authority_code="020",
            start=date(2026, 7, 20),
            end=date(2026, 8, 31),
        )

    assert [(q["sde"][0], q["ede"][0], q["pageNo"][0]) for q in asked] == [
        ("20260720", "20260731", "1"),
        ("20260801", "20260831", "1"),
    ]
    assert all(q["clsgn"] == ["V7UJ2"] and q["prtAgCd"] == ["020"] for q in asked)
    assert [c.call_seq for c in calls] == ["014", "015"]


async def test_http_error_does_not_leak_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, content=b"bad gateway")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = MofVesselOpsProvider("SECRETKEY", client)
        with pytest.raises(PortCallApiError) as caught:
            await provider.fetch(
                call_sign="V7UJ2",
                port_authority_code="020",
                start=date(2026, 8, 1),
                end=date(2026, 8, 31),
            )
    assert "SECRETKEY" not in str(caught.value)
    assert caught.value.code == "HTTP 502"


def test_service_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "  abc  ")
    assert load_service_key() == "abc"
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "")
    assert load_service_key() is None
    with pytest.raises(ValueError):
        MofVesselOpsProvider("", httpx.AsyncClient())
