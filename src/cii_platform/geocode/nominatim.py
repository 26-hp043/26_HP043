"""항만명 → 좌표 어댑터 (OpenStreetMap Nominatim · `#768` · `PRD §15.1` MAY).

## 사용 정책이 설계를 정한다

공개 인스턴스의 정책(`PRD §22` 참고문헌 11)을 2026-09-12에 원문으로 확인했다.

=========================  ====================================================
 초당 **1회**               절대 상한. 매일 도는 스크립트는 분당 4회
 **User-Agent 필수**        애플리케이션을 밝힌다. 라이브러리 기본값은 차단 대상
 **캐시 필수**              *"Results must be cached on your side"*
 **자동완성 금지**          입력 중 조회는 정책 위반이다
=========================  ====================================================

그래서 이 어댑터는 **한 번 부르고 끝나는 모양**이다 — 입력 중에 부르지 않고, 사용자가
버튼을 눌러 한 건을 조회한다. 결과 저장은 서비스 계층(`services.geocoding`)이 한다.

## 항만인지 거른다

「부산」은 도시이기도 하다. 정책과 무관하게 **아무 결과나 받으면 엉뚱한 좌표가 항차에
저장된다.** Nominatim의 분류(`class`/`type`)로 거른다 — 항만·정박지·수역만 받는다.
걸러지지 않으면 **좌표 없이 실패**로 돌려준다. 지어내지 않는다.

## CI는 네트워크를 쓰지 않는다

기상 어댑터(`weather/open_meteo.py`)와 같은 규율이다. 프로토콜을 두고 테스트가 갈아
끼운다 — 외부 서비스의 가용성에 결과가 묶이면 실패했을 때 우리 코드가 틀린 것인지 알 수
없다.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx

#: 공개 인스턴스. 자체 호스팅으로 옮기면 이 값만 바꾼다.
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"

#: 정책이 요구하는 식별. **라이브러리 기본값은 차단 대상**이라 제품과 연락처를 밝힌다.
USER_AGENT = "BlueLog-CII/1.0 (+https://github.com/26-hp043/26_HP043)"

#: 정책 상한(초당 1회)을 **코드로 강제**한다. 문서에만 적으면 지켜지지 않는다.
MIN_INTERVAL_SECONDS = 1.0

#: 항만으로 받아들이는 분류. `class:type` 조합이다.
#: - ``harbour``·``port``: 항만 그 자체
#: - ``ferry_terminal``: 여객 부두
#: - ``anchorage``: 정박지
PORT_KINDS = frozenset(
    {
        "harbour",
        "port",
        "ferry_terminal",
        "anchorage",
    }
)


class GeocodeError(RuntimeError):
    """조회가 실패했다. 서비스가 **계산을 막지 않고** 좌표 없이 진행하게 한다."""


@dataclass(frozen=True)
class GeocodeResult:
    """조회 결과 한 건. 좌표와 **무엇으로 판정했는지**를 함께 준다."""

    display_name: str
    lat: Decimal
    lon: Decimal
    kind: str


class GeocodeProvider(Protocol):
    """항만명 → 좌표의 경계. 테스트가 갈아 끼운다 (CI는 네트워크를 쓰지 않는다)."""

    async def lookup(self, name: str) -> GeocodeResult | None: ...


class NominatimProvider:
    """공개 Nominatim 어댑터. **초당 1회**를 프로세스 안에서 강제한다."""

    def __init__(self, client_factory=None) -> None:
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=10.0))
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def _wait_for_slot(self) -> None:
        """직전 호출로부터 1초가 지날 때까지 기다린다.

        **락 안에서 잰다** — 동시에 들어온 두 요청이 각자 「1초 지났다」고 판단하면
        정책을 어긴다. 대기는 요청 하나를 늦출 뿐 계산을 막지 않는다.
        """
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_INTERVAL_SECONDS:
            await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)
        self._last_call = time.monotonic()

    async def lookup(self, name: str) -> GeocodeResult | None:
        """이름 하나를 조회한다. 항만이 아니거나 결과가 없으면 ``None``.

        조회 자체가 실패하면 :class:`GeocodeError` — 「없다」와 「못 물었다」는 다르다.
        """
        params = {
            "q": name,
            "format": "jsonv2",
            "limit": "5",
            "addressdetails": "0",
        }
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "ko,en"}

        async with self._lock:
            await self._wait_for_slot()
            try:
                async with self._client_factory() as client:
                    response = await client.get(NOMINATIM_ENDPOINT, params=params, headers=headers)
                    response.raise_for_status()
                    rows = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise GeocodeError(f"geocoding request failed: {exc}") from exc

        return _first_port(rows)


def _first_port(rows: object) -> GeocodeResult | None:
    """항만 분류인 첫 행. 없으면 ``None`` — **도시 좌표로 대신하지 않는다.**"""
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("type", ""))
        if kind not in PORT_KINDS and str(row.get("class", "")) not in PORT_KINDS:
            continue
        try:
            lat = Decimal(str(row["lat"]))
            lon = Decimal(str(row["lon"]))
        except (KeyError, ArithmeticError, TypeError):
            continue
        return GeocodeResult(
            display_name=str(row.get("display_name", "")),
            lat=lat,
            lon=lon,
            kind=kind or str(row.get("class", "")),
        )
    return None
