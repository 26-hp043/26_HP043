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

## 읽을 수 없는 응답 (`#2113`)

형식이 달라진 항목은 **버리지 않고 그 응답의 실패로 올린다**(:class:`PortCallApiError` · 코드
``FORMAT``). 대상은 기항을 가리키는 키(``etryptYear``·``etryptCo``)와 대조에 쓰는 신고 시각
(``etryptDt``·``tkoffDt``)이다 — 연도가 숫자가 아니거나 빠졌을 때, 차수가 비었을 때, 시각이
ISO 형식이 아니거나 **시간대가 없을 때**. 조용히 버리면 「그 달에 기항이 없다」와 같은 모양이
되고, 빈 차수·시간대 없는 시각을 그대로 받으면 저장 표의 유일 키와 대조의 뺄셈이 깨진다.
문구에는 **필드 이름만** 싣고 값은 싣지 않는다.
"""

from __future__ import annotations

import calendar
import os
import re
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

#: 읽을 수 없는 응답의 코드 — 바깥이 준 ``resultCode``(숫자)와 겹치지 않는다.
CODE_FORMAT = "FORMAT"
#: 바깥이 준 오류 코드·문구 가운데 **그대로 옮겨도 되는 모양**. 코드는 숫자 몇 자리, 문구는
#: ``INVALID_REQUEST_PARAMETER_ERROR``·``SERVICE ERROR`` 같은 대문자 낱말이다. 이 모양이 아닌
#: 문자열은 옮기지 않는다 — 오류 문구는 바깥이 만든 문자열이라 요청 인자(키)를 되비출 수 있고,
#: 수집기는 이 문구를 실패 사유로 로그에 찍는다. 숫자를 뺀 것은 키(영숫자)가 지날 길을 막기
#: 위해서다.
_SAFE_CODE = re.compile(r"\d{1,4}")
_SAFE_MESSAGE = re.compile(r"[A-Z][A-Z_ ]{0,79}")
_WITHHELD = "(문구 생략)"


class PortCallApiError(RuntimeError):
    """``resultCode``가 ``00``이 아니거나, 응답이 XML이 아니거나, 읽을 수 없는 항목이 있다.

    키는 문구에 넣지 않는다. 수집기가 이 문구를 실패 사유로 **그대로** 남기므로, 만드는 쪽이
    바깥에서 온 값을 싣지 않을 책임을 진다.
    """

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


def _report_time(raw_at: str, tag: str) -> datetime:
    """신고 시각 — ``2026-08-08T14:20:00+09:00``처럼 시간대가 붙어 온다(09-23 실측).

    시간대가 없으면 읽지 않는다. 같은 응답의 ``tkoffPrrrnDt``(출항 예정)는 시간대 없는
    ``2026-08-02 18:00:00`` 형식이라, 신고 시각이 그 형식으로 바뀌어도 ``fromisoformat``은
    예외 없이 받는다 — 그대로 저장되면 대조의 뺄셈이 ``TypeError``다(`#2113`).
    """
    try:
        at = datetime.fromisoformat(raw_at)
    except ValueError:
        raise PortCallApiError(CODE_FORMAT, f"{tag}가 ISO 시각이 아니다") from None
    if at.tzinfo is None or at.utcoffset() is None:
        raise PortCallApiError(CODE_FORMAT, f"{tag}에 시간대가 없다")
    return at


def _call_year(item: ET.Element) -> int:
    raw = _text(item, "etryptYear")
    # `isdecimal` — `int()`가 받는 부호·밑줄·공백 표기를 연도로 치지 않는다.
    if raw is None or not (raw.isascii() and raw.isdecimal()) or int(raw) <= 0:
        raise PortCallApiError(CODE_FORMAT, "etryptYear가 연도가 아니다")
    return int(raw)


def _call_seq(item: ET.Element) -> str:
    raw = _text(item, "etryptCo")
    if raw is None:
        # `""`로 받으면 유일 키에서 같은 항만청·연도의 그런 기항이 한 행으로 합쳐진다.
        raise PortCallApiError(CODE_FORMAT, "etryptCo가 비어 있다")
    return raw


def _total_count(root: ET.Element) -> int:
    raw = _text(root, "body/totalCount")
    if raw is None:
        return 0
    if not (raw.isascii() and raw.isdecimal()):
        raise PortCallApiError(CODE_FORMAT, "totalCount가 숫자가 아니다")
    return int(raw)


def _api_error(code: str | None, message: str | None) -> PortCallApiError:
    """바깥이 준 코드·문구로 예외를 만든다 — 알려진 모양만 옮긴다(:data:`_SAFE_MESSAGE`)."""
    safe_code = code if code and _SAFE_CODE.fullmatch(code) else "?"
    if message and not _SAFE_MESSAGE.fullmatch(message):
        message = _WITHHELD
    return PortCallApiError(safe_code, message or "")


def _report(detail: ET.Element) -> PortCallReport | None:
    """신고 한 줄. 입항·출항이 아니거나 시각이 없으면 버린다(대조에 쓸 수 없다)."""
    kind = _KINDS.get(_text(detail, "etryndNm") or "")
    if kind is None:
        return None
    time_tag = "etryptDt" if kind == KIND_ARRIVAL else "tkoffDt"
    raw_at = _text(detail, time_tag)
    if raw_at is None:
        return None
    raw_request = _text(detail, "reqstSeNm") or ""
    return PortCallReport(
        kind=kind,
        request=_REQUESTS.get(raw_request, raw_request),
        at=_report_time(raw_at, time_tag),
        facility_name=_text(detail, "laidupFcltyNm"),
        facility_code=_text(detail, "laidupFcltyCd"),
        gross_tonnage=_decimal(detail, "grtg"),
        international_gross_tonnage=_decimal(detail, "intrlGrtg"),
    )


def parse_response(payload: bytes) -> tuple[list[PortCall], int]:
    """응답 XML → (기항 목록, ``totalCount``).

    ``resultCode``가 ``00``이 아니거나 읽을 수 없는 항목이 있으면 :class:`PortCallApiError`다 —
    이 함수 밖으로 ``ValueError``가 새지 않는다(`#2113`).
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        # 게이트웨이 오류는 XML이 아닌 본문으로 올 수 있다 — 본문은 옮기지 않는다
        # (키가 섞일 수 있다).
        raise PortCallApiError("PARSE", "응답이 XML이 아니다") from exc
    gateway = root if root.tag == "cmmMsgHeader" else root.find("cmmMsgHeader")
    if gateway is not None:
        # 공공데이터포털 게이트웨이가 서비스에 닿기 전에 막은 오류(키 미등록·한도 초과 등)는
        # `<response>`가 아니라 `<OpenAPI_ServiceResponse><cmmMsgHeader>` 봉투로 온다.
        # `returnAuthMsg`가 사유 이름이고 `errMsg`는 늘 `SERVICE ERROR`다.
        raise _api_error(
            _text(gateway, "returnReasonCode"),
            _text(gateway, "returnAuthMsg") or _text(gateway, "errMsg"),
        )
    code = _text(root, "header/resultCode") or ""
    if code != "00":
        raise _api_error(code, _text(root, "header/resultMsg"))
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
                call_year=_call_year(item),
                call_seq=_call_seq(item),
                call_sign=_text(item, "clsgn") or "",
                vessel_name=_text(item, "vsslNm"),
                previous_port=_text(item, "prvsDpmprtNatPrtCd"),
                next_port=_text(item, "nxlnptNatPrtCd"),
                reports=reports,
                raw=ET.tostring(item, encoding="unicode"),
            )
        )
    return calls, _total_count(root)


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
