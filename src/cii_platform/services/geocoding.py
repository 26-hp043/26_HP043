"""항만명 → 좌표 (`#768` · `PRD §15.1` MAY · `API_SPEC §3.10`).

`#760`이 샘플 항만 43곳을 넣어 **목록에 있는 항은 이미 좌표가 붙는다.** 남은 것은
**목록 밖 항만**이고, 그것을 사용자가 좌표로 찾아 넣게 하지 않는 것이 이 모듈이다
(`PRD §1 COR-5`가 「개발자도구 기반 수동 좌표 입력」을 결함으로 적었다).

## 세 자리를 순서대로 본다

1. **샘플 목록**(`services/sample_ports.py`) — 원본(NGA WPI)을 옮긴 고정 값이다. 있으면
   외부를 부르지 않는다
2. **캐시 표**(`port_geocode`) — 전에 물어서 얻은 값. 정책이 캐시를 **요구**한다
3. **외부 조회**(Nominatim) — 여기까지 와야 바깥으로 나간다

## 실패가 계산을 막지 않는다

조회가 실패해도 항차는 만들 수 있어야 한다(`PRD §16.2` 오류 격리). 그래서 이 모듈은
예외를 밖으로 내보내지 않고 **「찾았다/못 찾았다 + 이유」**를 돌려준다. 화면은 그 사실을
말하고 사용자는 좌표 없이 진행하거나 직접 넣는다.

## 항만이 아닌 결과는 버린다

「부산」은 도시이기도 하다. 어댑터가 분류로 거르고(`geocode/nominatim.py`), 걸러지지
않으면 **못 찾은 것**으로 다룬다 — 도시 좌표를 항만 좌표로 저장하면 그 뒤의 거리 추정이
조용히 틀린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from cii_platform.db.models.port_geocode import PortGeocode
from cii_platform.geocode.nominatim import GeocodeError, GeocodeProvider
from cii_platform.services.sample_ports import SAMPLE_PORTS

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from sqlalchemy.ext.asyncio import AsyncSession

#: 좌표의 출처. 화면이 「어디서 온 값인가」를 말할 수 있어야 한다.
SOURCE_SAMPLE = "SAMPLE"
SOURCE_CACHE = "CACHE"
SOURCE_LOOKUP = "LOOKUP"

#: 못 찾은 이유. 화면 문구는 이 값으로 고른다 — 서버가 문장을 만들지 않는다.
REASON_NOT_A_PORT = "NOT_A_PORT"
REASON_LOOKUP_FAILED = "LOOKUP_FAILED"
REASON_NO_PROVIDER = "NO_PROVIDER"


@dataclass(frozen=True)
class PortLocation:
    """찾은 좌표 한 건."""

    name: str
    lat: Decimal
    lon: Decimal
    source: str
    display_name: str | None = None


def normalize_query(name: str) -> str:
    """캐시 키. 공백을 접고 대문자로 — 「busan  port」와 「Busan Port」는 같은 질의다."""
    return " ".join(name.split()).upper()


def _sample_match(name: str) -> PortLocation | None:
    """샘플 목록에서 **정확히 같은 이름**을 찾는다.

    부분 일치를 쓰지 않는다 — 「PORT」가 20곳에 걸린다. 목록 화면(`#1005`)이 고른
    이름을 그대로 보내므로 정확 일치로 충분하다.
    """
    key = normalize_query(name)
    for port in SAMPLE_PORTS:
        if normalize_query(port.name) == key or normalize_query(port.name_ko) == key:
            return PortLocation(
                name=port.name,
                lat=Decimal(port.lat),
                lon=Decimal(port.lon),
                source=SOURCE_SAMPLE,
            )
    return None


async def _cache_match(session: AsyncSession, name: str) -> PortLocation | None:
    row = (
        await session.execute(select(PortGeocode).where(PortGeocode.query == normalize_query(name)))
    ).scalar_one_or_none()
    if row is None:
        return None
    return PortLocation(
        name=row.raw_query,
        lat=row.lat,
        lon=row.lon,
        source=SOURCE_CACHE,
        display_name=row.display_name,
    )


async def lookup_port(
    session: AsyncSession,
    *,
    name: str,
    provider: GeocodeProvider | None = None,
) -> tuple[PortLocation | None, str | None]:
    """항만명으로 좌표를 찾는다. ``(찾은 값, 못 찾은 이유)``를 돌려준다.

    **예외를 밖으로 내보내지 않는다** — 조회 실패가 항차 입력을 막지 않는다
    (`PRD §16.2`). 둘 중 하나는 항상 ``None``이다.

    ``provider``가 ``None``이면 외부로 나가지 않는다(샘플·캐시까지만) — 테스트와
    오프라인 환경이 그 상태다.
    """
    found = _sample_match(name)
    if found is not None:
        return found, None

    found = await _cache_match(session, name)
    if found is not None:
        return found, None

    if provider is None:
        return None, REASON_NO_PROVIDER

    try:
        result = await provider.lookup(name)
    except GeocodeError:
        # 바깥이 죽은 것과 「그런 항만이 없다」는 다르다. 화면이 다르게 말해야 한다.
        return None, REASON_LOOKUP_FAILED

    if result is None:
        return None, REASON_NOT_A_PORT

    session.add(
        PortGeocode(
            query=normalize_query(name),
            raw_query=name.strip()[:200],
            display_name=result.display_name[:500],
            lat=result.lat,
            lon=result.lon,
            kind=result.kind,
            source="nominatim",
            fetched_at=datetime.now(UTC),
        )
    )
    await session.commit()

    return (
        PortLocation(
            name=name.strip(),
            lat=result.lat,
            lon=result.lon,
            source=SOURCE_LOOKUP,
            display_name=result.display_name,
        ),
        None,
    )
