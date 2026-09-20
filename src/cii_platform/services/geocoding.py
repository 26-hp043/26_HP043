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

## 외부를 기다리는 동안 DB 커넥션을 쥐지 않는다 (`#1364`)

캐시를 보는 SELECT가 트랜잭션을 열고(SQLAlchemy autobegin) **커넥션을 체크아웃한다.**
그 상태로 외부 조회를 기다리면 커넥션이 조회 시간만큼 묶인다 — 제공자가 프로세스에
하나라(`#1335`) 조회가 줄을 서므로 **줄 길이만큼 커넥션이 쌓이고**, 기본 풀(5+10)이 마르면
좌표 조회와 무관한 요청까지 30초 뒤 실패한다(인증 미들웨어도 요청마다 커넥션을 받는다).

그래서 **캐시에서 못 찾은 순간 트랜잭션을 닫고**(커넥션 반납) 바깥으로 나가며, 결과 저장은
새 트랜잭션으로 한다. 그 사이에 다른 요청이 같은 이름을 먼저 저장할 수 있으므로 저장은
`UNIQUE(query)` 충돌을 **정상 경로로** 받아 낸다.

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
from sqlalchemy.exc import IntegrityError

from cii_platform.db.models.port_geocode import PortGeocode
from cii_platform.geocode.nominatim import GeocodeError, GeocodeProvider, GeocodeResult
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

    :raises RuntimeError: **호출자의 잘못**일 때만 — 미커밋 변경을 들고 부른 경우
        (:func:`_release_connection`). 조회 실패는 여기로 오지 않는다.
    """
    # 들어온 시점의 미커밋 변경을 **여기서** 본다 — 캐시 SELECT의 autoflush가 지나가면
    # 대기 객체가 persistent로 옮겨져 뒤에서는 구분할 수 없다 (`#1364`).
    caller_had_pending = bool(session.new or session.dirty or session.deleted)

    found = _sample_match(name)
    if found is not None:
        return found, None

    found = await _cache_match(session, name)
    if found is not None:
        return found, None

    if provider is None:
        return None, REASON_NO_PROVIDER

    await _release_connection(session, caller_had_pending=caller_had_pending)

    try:
        result = await provider.lookup(name)
    except GeocodeError:
        # 바깥이 죽은 것과 「그런 항만이 없다」는 다르다. 화면이 다르게 말해야 한다.
        # 차례를 기다리다 상한을 넘긴 것도 여기로 온다 (`#1364`).
        return None, REASON_LOOKUP_FAILED

    if result is None:
        return None, REASON_NOT_A_PORT

    stored = await _store(session, name=name, result=result)
    if stored is not None:
        return stored, None

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


async def _release_connection(session: AsyncSession, *, caller_had_pending: bool) -> None:
    """외부로 나가기 전에 **트랜잭션을 닫아 커넥션을 풀에 돌려준다** (`#1364`).

    닫는 대상은 캐시를 본 SELECT가 열어 둔 트랜잭션이고, 그 안에 **쓴 것은 없다**.

    **롤백이 아니라 커밋으로 닫는다.** 둘 다 트랜잭션을 끝내 커넥션을 돌려주지만, 세션이
    바깥 트랜잭션에 얹혀 있을 때(테스트 하네스가 그렇다) 롤백은 그 바깥 트랜잭션까지
    끊는다. 아래 가드가 **쓸 것이 없음을 보장**하므로 커밋은 빈 트랜잭션을 닫을 뿐이고,
    이 모듈이 결과 저장에 이미 쓰는 수단과 같다.

    :param caller_had_pending: :func:`lookup_port` **진입 시점**에 세션이 미커밋 변경을
        들고 있었는가. 캐시 SELECT의 autoflush가 지나간 뒤에는 그것을 알 수 없어 미리 잰다.
    :raises RuntimeError: 호출자가 **미커밋 변경을 들고** 들어온 경우. 그대로 닫으면 남의
        작업이 의도치 않게 확정된다 — 지금 호출자는 라우트 하나뿐이고 그런 상태로 들어오지
        않지만, 나중에 항차 저장 흐름 안에서 부르게 되면 **증상 없이 반쪽만 저장된다.**
    """
    if caller_had_pending:
        raise RuntimeError(
            "lookup_port는 외부 조회 전에 트랜잭션을 닫는다 — "
            "미커밋 변경을 들고 부르지 않는다 (#1364)"
        )
    await session.commit()


async def _store(
    session: AsyncSession,
    *,
    name: str,
    result: GeocodeResult,
) -> PortLocation | None:
    """조회 결과를 캐시 표에 넣는다. **새 트랜잭션**이다 (`#1364`).

    커넥션을 놓고 바깥을 다녀오는 사이에 다른 요청이 같은 이름을 먼저 저장할 수 있다 —
    `UNIQUE(query)`가 그것을 막으므로 충돌을 **정상 경로로** 받아, 먼저 저장된 행을 읽어
    돌려준다(``CACHE``). 둘 중 어느 값을 돌려주든 같은 제공자의 같은 질의 결과다.

    충돌이 아니었으면 ``None`` — 호출자가 방금 받은 결과를 ``LOOKUP``으로 돌려준다.
    """
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
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return await _cache_match(session, name)
    return None
