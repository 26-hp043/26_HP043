"""재항(寄港) 기록 제공자 계약 (`#1197` B단계 ①).

## 무엇을 여기 두나

**공적 기록 한 건의 모양**(:class:`PortCall`)과 **받아 오는 쪽의 계약**
(:class:`PortCallProvider`)이다.
저장·대조(허용 오차 6시간 · 결정 G-7)·데이터 점검 표시는 뒤따르는 단계가 맡는다 —
``ais/provider.py``가 계약만 먼저 둔 것과 같은 나눔이다.

09-22 결정이 계약을 「**재항 기록을 주는 것**」으로 정했고, 09-23 결정이 첫 구현을
해양수산부 선박운항정보 오픈API(``mof_vessel_ops.py``)로 바꿨다. 선박관제정보 CSV·울산항만공사
API는 같은 계약의 구현체를 더하는 것으로 붙는다.

## 한 기항 = 신고 여러 줄

공적 기록은 기항 하나에 **입항·출항 신고가 따로** 있고, 신고를 고치면 ``최초``와 ``최종``이
함께 남는다(09-23 실측). 묘박지로 들어와 부두에서 나가면 입항과 출항의 계선 시설이 다르다
(D7ZY 2026-08-01 · 「남외항 N-3박지」 → 「7부두 71선석」). 그래서 신고를 그대로 담고, 대조가
쓰는 두 시각은 :attr:`PortCall.arrival_at`·:attr:`PortCall.departure_at`이 **규칙으로** 뽑는다.

## 값을 바꾸지 않는다

이 모듈은 우리 항차·정박 구간을 읽지도 쓰지도 않는다. 사용자가 넣은 값은 공적 기록과
달라도 그대로 두고 알리기만 한다(``PRD §17.1``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

#: 신고 종류.
KIND_ARRIVAL = "ARRIVAL"
KIND_DEPARTURE = "DEPARTURE"

#: 신고 구분 — 원문 ``reqstSeNm``의 ``최초``·``최종``. 그 밖의 값은 원문 그대로 둔다.
REQUEST_FIRST = "FIRST"
REQUEST_FINAL = "FINAL"


@dataclass(frozen=True)
class PortCallReport:
    """입항 또는 출항 신고 한 줄."""

    kind: str
    request: str
    at: datetime
    facility_name: str | None = None
    facility_code: str | None = None
    #: 총톤수(``grtg``) · 국제총톤수(``intrlGrtg``). 내항선은 국제총톤수가 ``0``으로 온다.
    gross_tonnage: Decimal | None = None
    international_gross_tonnage: Decimal | None = None


@dataclass(frozen=True)
class PortCall:
    """공적 기록의 기항 한 번.

    ``source``·``port_authority_code``·``call_year``·``call_seq``가 기항 하나를 가리킨다 —
    원문의 ``etryptYear``·``etryptCo``(항만청 안의 연도별 입항 차수)다.
    """

    source: str
    port_authority_code: str
    call_year: int
    call_seq: str
    call_sign: str
    vessel_name: str | None = None
    port_authority_name: str | None = None
    #: 전출항지 · 차항지 (UN/LOCODE 5자리).
    previous_port: str | None = None
    next_port: str | None = None
    reports: tuple[PortCallReport, ...] = field(default_factory=tuple)
    #: 제공자가 준 **원문 그대로**(해수부 API는 ``<item>`` XML 한 덩어리). 저장 표가 보관한다
    #: — 파싱 규칙을 고쳐도 원문에서 다시 읽을 수 있게(``PRD §15.1`` ``[#1197]`` 「원본 그대로
    #: 보관」). 같은 기항인지 가리는 데는 쓰지 않는다.
    raw: str | None = field(default=None, compare=False, repr=False)

    def _reports_of(self, kind: str) -> list[PortCallReport]:
        """그 종류의 신고 — ``최종``이 하나라도 있으면 ``최종``만 쓴다(09-23 · ``최초`` 혼재)."""
        of_kind = [r for r in self.reports if r.kind == kind]
        finals = [r for r in of_kind if r.request == REQUEST_FINAL]
        return finals or of_kind

    @property
    def arrival_at(self) -> datetime | None:
        """이 기항의 **가장 이른** 입항 — 결정 G-7 ①-2 ⓐ(묘박 대기까지 포함한 체류 전체)."""
        times = [r.at for r in self._reports_of(KIND_ARRIVAL)]
        return min(times) if times else None

    @property
    def departure_at(self) -> datetime | None:
        """이 기항의 **가장 늦은** 출항 — 결정 G-7 ①-2 ⓐ."""
        times = [r.at for r in self._reports_of(KIND_DEPARTURE)]
        return max(times) if times else None

    @property
    def gross_tonnage(self) -> Decimal | None:
        """GT — ``grtg``를 먼저 본다(내항선은 ``intrlGrtg``가 ``0`` · 09-23 실측)."""
        for report in self._reports_of(KIND_ARRIVAL) + self._reports_of(KIND_DEPARTURE):
            for value in (report.gross_tonnage, report.international_gross_tonnage):
                if value is not None and value > 0:
                    return value
        return None


class PortCallProvider(Protocol):
    """재항 기록을 주는 쪽.

    **조회 경로에서 부르지 않는다** — 수집은 별도 경로(CLI·배치)다. 바깥 서비스의 지연이
    화면 응답에 섞이지 않게 한다(``ais/provider.py``와 같은 규칙).
    """

    async def fetch(
        self, *, call_sign: str, port_authority_code: str, start: date, end: date
    ) -> list[PortCall]:
        """한 선박(호출부호)의 한 항만청 기록을 ``start``~``end``(입항일 기준 · 양 끝 포함)로."""
        ...
