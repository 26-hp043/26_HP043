"""해양수산부 선박운항정보 오픈API 제공자 (`#1197` B단계 ① · 결정 2026-09-23).

``https://apis.data.go.kr/1192000/VsslEtrynd5/Info5`` — 「선박입출항신고조회」 하나뿐이다.
요청·응답 규격은 공공데이터포털 활용가이드(``DAT211``)와 09-23 실제 호출로 확인했다
(``#1623`` 코멘트). 테스트 표본은 2026-09-25 실제 응답이다(``tests/fixtures/port_calls``).

## 부르는 법 (실측 · #1623)

* 필수 — 항만청코드 ``prtAgCd``(부산 ``020`` · 울산 ``820`` 등 11개) · 시작일 ``sde`` ·
  종료일 ``ede``(``YYYYMMDD``). 호출부호 ``clsgn``은 선택이지만 늘 준다.
* **한 번에 91일까지는 되고 1년은 ``11 INVALID_REQUEST_PARAMETER_ERROR``다**(상한 미확인) →
  **달력 월 단위로 나눠** 부른다(:func:`month_windows`).
* 응답은 **XML만** · 한 페이지 최대 50건 · 초당 30건 · 개발계정 하루 10,000건.
* ``totalCount``는 **기항 수**다(신고 줄 수가 아니다). 마지막 뒤 페이지는 ``items``가 빈 채
  ``resultCode 00``으로 온다.

키는 ``DATA_GO_KR_SERVICE_KEY``(64자 영숫자 · 인코딩 구분 불필요)다. 키는 로그·예외 문구에
넣지 않는다.
"""

from __future__ import annotations

import calendar
import os
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from cii_platform.port_calls.provider import (
    KIND_ARRIVAL,
    KIND_DEPARTURE,
    REQUEST_FINAL,
    REQUEST_FIRST,
    PortCall,
    PortCallReport,
)

ENDPOINT = "https://apis.data.go.kr/1192000/VsslEtrynd5/Info5"
SOURCE = "MOF_VESSEL_OPS"
#: 한 페이지 최대 건수(가이드).
PAGE_SIZE = 50
#: 한 달 안에서 넘기지 않을 페이지 수 — 한 선박이 한 항만청에 한 달 50회를 넘게 기항할 일은
#: 없다. 응답이 ``totalCount``를 잘못 주어도 무한히 돌지 않게 하는 상한이다.
MAX_PAGES_PER_WINDOW = 10

_KINDS = {"입항": KIND_ARRIVAL, "출항": KIND_DEPARTURE}
_REQUESTS = {"최초": REQUEST_FIRST, "최종": REQUEST_FINAL}


class PortCallApiError(RuntimeError):
    """``resultCode``가 ``00``이 아니거나 응답이 XML이 아니다. 키는 문구에 넣지 않는다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"선박운항정보 API 오류 {code}: {message}")
        self.code = code


def load_service_key() -> str | None:
    """``DATA_GO_KR_SERVICE_KEY`` — 비었으면 ``None``(수집 경로가 꺼진다)."""
    raw = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    return raw or None


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """``start``~``end``를 달력 월 단위 구간으로 나눈다(양 끝 포함).

    1년 범위는 오류이고 91일은 됐다(#1623) — 월 단위면 어느 달이든 31일 이하라 안전하다.
    """
    if end < start:
        raise ValueError(f"종료일({end})이 시작일({start})보다 앞선다")
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        window_end = min(date(cursor.year, cursor.month, last_day), end)
        windows.append((cursor, window_end))
        cursor = date.fromordinal(window_end.toordinal() + 1)
    return windows


def _text(node: ET.Element, tag: str) -> str | None:
    value = node.findtext(tag)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _decimal(node: ET.Element, tag: str) -> Decimal | None:
    raw = _text(node, tag)
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _report(detail: ET.Element) -> PortCallReport | None:
    """신고 한 줄. 입항·출항이 아니거나 시각이 없으면 버린다(대조에 쓸 수 없다)."""
    kind = _KINDS.get(_text(detail, "etryndNm") or "")
    if kind is None:
        return None
    raw_at = _text(detail, "etryptDt" if kind == KIND_ARRIVAL else "tkoffDt")
    if raw_at is None:
        return None
    raw_request = _text(detail, "reqstSeNm") or ""
    return PortCallReport(
        kind=kind,
        request=_REQUESTS.get(raw_request, raw_request),
        # `2026-08-08T14:20:00+09:00` — 시간대가 붙어 온다(09-23 실측).
        at=datetime.fromisoformat(raw_at),
        facility_name=_text(detail, "laidupFcltyNm"),
        facility_code=_text(detail, "laidupFcltyCd"),
        gross_tonnage=_decimal(detail, "grtg"),
        international_gross_tonnage=_decimal(detail, "intrlGrtg"),
    )


def parse_response(payload: bytes) -> tuple[list[PortCall], int]:
    """응답 XML → (기항 목록, ``totalCount``). ``resultCode``가 ``00``이 아니면 예외."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        # 게이트웨이 오류는 XML이 아닌 본문으로 올 수 있다 — 본문은 옮기지 않는다
        # (키가 섞일 수 있다).
        raise PortCallApiError("PARSE", "응답이 XML이 아니다") from exc
    code = _text(root, "header/resultCode") or ""
    if code != "00":
        raise PortCallApiError(code or "?", _text(root, "header/resultMsg") or "")
    calls: list[PortCall] = []
    for item in root.iterfind("body/items/item"):
        reports = tuple(
            report
            for report in (_report(detail) for detail in item.iterfind("details/detail"))
            if report is not None
        )
        calls.append(
            PortCall(
                source=SOURCE,
                port_authority_code=_text(item, "prtAgCd") or "",
                port_authority_name=_text(item, "prtAgNm"),
                call_year=int(_text(item, "etryptYear") or 0),
                call_seq=_text(item, "etryptCo") or "",
                call_sign=_text(item, "clsgn") or "",
                vessel_name=_text(item, "vsslNm"),
                previous_port=_text(item, "prvsDpmprtNatPrtCd"),
                next_port=_text(item, "nxlnptNatPrtCd"),
                reports=reports,
            )
        )
    total = int(_text(root, "body/totalCount") or 0)
    return calls, total


def request_params(
    *, service_key: str, port_authority_code: str, start: date, end: date, call_sign: str, page: int
) -> dict[str, str]:
    """한 페이지의 요청 인자. 날짜 기준은 가이드 기본값(``deGb=I`` · 입항일)이다."""
    return {
        "serviceKey": service_key,
        "prtAgCd": port_authority_code,
        "sde": start.strftime("%Y%m%d"),
        "ede": end.strftime("%Y%m%d"),
        "clsgn": call_sign,
        "numOfRows": str(PAGE_SIZE),
        "pageNo": str(page),
    }


class MofVesselOpsProvider:
    """:class:`~cii_platform.port_calls.provider.PortCallProvider` 구현 — 월 단위 · 페이지 순회."""

    def __init__(self, service_key: str, client: httpx.AsyncClient) -> None:
        if not service_key:
            raise ValueError("DATA_GO_KR_SERVICE_KEY가 비어 있다")
        self._key = service_key
        self._client = client

    async def fetch(
        self, *, call_sign: str, port_authority_code: str, start: date, end: date
    ) -> list[PortCall]:
        seen: dict[tuple[str, int, str], PortCall] = {}
        for window_start, window_end in month_windows(start, end):
            collected = 0
            for page in range(1, MAX_PAGES_PER_WINDOW + 1):
                response = await self._client.get(
                    ENDPOINT,
                    params=request_params(
                        service_key=self._key,
                        port_authority_code=port_authority_code,
                        start=window_start,
                        end=window_end,
                        call_sign=call_sign,
                        page=page,
                    ),
                )
                if response.status_code != 200:
                    # 주소에 키가 실려 있으므로 URL을 문구에 넣지 않는다.
                    raise PortCallApiError(
                        f"HTTP {response.status_code}", "응답 상태가 200이 아니다"
                    )
                calls, total = parse_response(response.content)
                for call in calls:
                    # 월 경계에 걸친 기항이 두 달에 모두 나와도 한 번만 남긴다.
                    seen[(call.port_authority_code, call.call_year, call.call_seq)] = call
                collected += len(calls)
                if not calls or collected >= total:
                    break
        # 입항 시각 순. 입항 신고가 없는 기항(드물다)은 맨 뒤에 차수 순으로 둔다.
        return sorted(seen.values(), key=_call_order)


def _call_order(call: PortCall) -> tuple[bool, float, str]:
    at = call.arrival_at
    return (at is None, at.timestamp() if at else 0.0, call.call_seq)
