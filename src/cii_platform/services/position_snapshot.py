"""위치 스냅샷 적재 (`#764`).

``PRD §21`` 「AIS 연동 — 위치·항적 **자동** 수집」의 수집 계층이다. 세 출처가 한
표로 들어온다.

============  ==========================================  ==========================
 ``source``    누가 넣나                                   지금 상태
============  ==========================================  ==========================
 ``MANUAL``    ``PATCH /vessels/{id}/position``(사람)      **돈다**
 ``AIS``       :func:`ingest_ais_positions`(배치)          제공자가 붙으면 돈다
 ``SIMULATED`` 시뮬레이션 시계(``TECH_SPEC §5.4.1``)       넣지 않는다 — 아래
============  ==========================================  ==========================

## 시뮬레이션 시계는 스냅샷을 쓰지 않는다

``SIMULATED``를 ``source`` CHECK에 넣어 두었으나 **지금은 아무도 쓰지 않는다.**
시계는 값을 저장하지 않고 **요청 시각에서 파생**하기 때문이다(``#368`` 계약 ⑸ —
「계산 코어는 시각을 모른다」, 파생은 입력 확정 계층이 한다). 파생값을 관측으로
쌓으면 **같은 시각을 두 번 물었을 때 답이 달라지고**, ``as_of`` 재현성 계약이
깨진다. 값이 실제로 저장되는 날이 오면 그때 쓴다 — CHECK를 그때 고치지 않아도
되도록 자리만 비워 둔다.

## 수집은 조회에 섞지 않는다

``API_SPEC §2.6``이 못박아 두었다 — *"조회 경로에서 갱신하지 않는다 … 쓰기를
조회에 섞으면 GET이 트랜잭션을 잡는다."* :func:`ingest_ais_positions`는 **배치에서만**
부른다. 화면이 그리는 동안 외부 조회가 일어나면, 그 실패가 화면 실패가 된다.

## 신선도의 **임계값**은 여기서 정하지 않는다

「몇 분이 지나면 낡은 것인가」는 화면 표기의 문제이고, ``DESIGN_SYSTEM §16`` 항목
14(「AIS 신선도 임계값 표기」)가 **미결**이다. 서버는 :func:`position_age_seconds`로
**경과 시간만** 낸다 — 임계값을 서버가 먼저 정하면 확정 문서와 갈라지고, 갈라진
뒤에는 어느 쪽이 정본인지 판정할 수 없다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.ais.provider import (
    SOURCE_AIS,
    SOURCE_MANUAL,
    AisError,
    state_pair_from,
)
from cii_platform.db.repositories import position_snapshot as snapshot_repo
from cii_platform.db.repositories import vessel as vessel_repo

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.ais.provider import AisProvider
    from cii_platform.db.models.vessel_position_snapshot import VesselPositionSnapshot

_log = logging.getLogger(__name__)


async def record_manual_position(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    lat: Decimal,
    lon: Decimal,
    observed_at: datetime,
) -> bool:
    """사람이 넣은 위치를 스냅샷으로도 남긴다.

    ``vessel.current_lat/lon``은 **덮어쓰는 한 칸**이라 직전 값이 사라진다. 같은
    입력을 여기에도 남겨야 「어디를 지나왔는가」가 생긴다 — AIS가 붙기 전에도
    항적은 쌓인다.

    같은 시각을 두 번 눌러도 한 행이다(저장소가 ``ON CONFLICT DO NOTHING``).
    """
    return await snapshot_repo.insert_snapshot(
        session,
        vessel_id=vessel_id,
        source=SOURCE_MANUAL,
        lat=lat,
        lon=lon,
        observed_at=observed_at,
    )


def position_age_seconds(snapshot: VesselPositionSnapshot, *, at: datetime | None = None) -> float:
    """관측 시각으로부터 흐른 초.

    **``received_at``이 아니라 ``observed_at``으로 잰다.** 수신 시각으로 재면
    「30분 전 위치를 방금 받았다」가 최신으로 읽히고, 그것이 정확히 AIS에서 일어나는
    일이다(지연·재전송).

    임계값 판정은 하지 않는다 — 이 모듈 문서의 「신선도의 임계값」 절 참조.
    """
    now = at or datetime.now(UTC)
    observed = snapshot.observed_at
    if observed.tzinfo is None:
        # DB는 timestamptz라 tz가 붙어 오지만, 다른 경로로 만든 객체를 그대로 받아
        # 비교하다 TypeError로 죽는 일을 막는다.
        observed = observed.replace(tzinfo=UTC)
    return (now - observed).total_seconds()


async def ingest_ais_positions(
    session: AsyncSession,
    *,
    provider: AisProvider,
    at: datetime | None = None,
) -> dict[str, object]:
    """AIS에서 받은 위치를 스냅샷으로 적재하고 선박의 현재 위치를 갱신한다.

    **배치에서만 부른다** (모듈 문서 「수집은 조회에 섞지 않는다」).

    :returns: ``requested``(물어본 선박 수) · ``received``(위치가 온 수) ·
        ``recorded``(새로 쌓인 행 수) · ``unmatched``(우리 선대에 없는 IMO) ·
        ``errors``(조회 실패 메시지).

    ## 위치가 오지 않은 선박은 건드리지 않는다

    AIS는 수신 범위 밖이면 아무것도 주지 않는 것이 정상이다. 그것을 「좌표 없음」으로
    적으면 **마지막으로 알던 위치가 지워진다** — 화면에서 배가 사라진다.

    ## 운항 상태는 코드가 있을 때만 바꾼다

    :func:`state_pair_from`이 옮길 수 있는 코드는 넷뿐이다(0·1·5·8). 나머지는
    ``None``을 돌려주고, 그때는 **기존 상태를 그대로 둔다.** 모르는 것을
    ``NOT_UNDER_WAY``로 적으면 정박하지 않은 배가 정박한 것으로 기록되고
    ``not_underway_period``와 어긋난다.

    ``DRIFTING``·``STS``·``CANAL_TRANSIT``·``DRYDOCK``은 **AIS가 말하지 않는다** —
    사람이 넣는 축으로 남는다.
    """
    now = at or datetime.now(UTC)
    vessels = await vessel_repo.list_all_active(session)
    by_imo = {vessel.imo_number: vessel for vessel in vessels if vessel.imo_number}

    if not by_imo:
        return {
            "requested": 0,
            "received": 0,
            "recorded": 0,
            "unmatched": 0,
            "errors": [],
        }

    try:
        positions = await provider.fetch_positions(imo_numbers=sorted(by_imo))
    except AisError as exc:
        # 수집 실패는 **조용히 넘기지 않는다.** 다만 예외로 배치를 죽이지도 않는다 —
        # 다음 주기가 다시 물으면 되고, 실패 사실은 호출부가 보고해야 한다.
        _log.warning("AIS 위치 조회 실패: %s", exc)
        return {
            "requested": len(by_imo),
            "received": 0,
            "recorded": 0,
            "unmatched": 0,
            "errors": [str(exc)],
        }

    recorded = 0
    unmatched = 0
    for position in positions:
        vessel = by_imo.get(position.imo_number or "")
        if vessel is None:
            # 구독에 남의 배가 섞여 들어올 수 있다 — 세어 두되 저장하지 않는다.
            unmatched += 1
            continue

        if await snapshot_repo.insert_snapshot(
            session,
            vessel_id=vessel.id,
            source=SOURCE_AIS,
            lat=position.lat,
            lon=position.lon,
            observed_at=position.observed_at,
            sog_kn=position.sog_kn,
            cog_deg=position.cog_deg,
            nav_status=position.nav_status,
        ):
            recorded += 1

        # 현재 위치는 **더 새 관측일 때만** 덮는다. 배치가 겹쳐 돌거나 재전송이
        # 섞이면 오래된 관측이 뒤에 도착할 수 있고, 그것을 그대로 쓰면 배가 뒤로 간다.
        if vessel.position_updated_at is None or position.observed_at > vessel.position_updated_at:
            vessel.current_lat = position.lat
            vessel.current_lon = position.lon
            vessel.position_updated_at = position.observed_at
            state = state_pair_from(position.nav_status)
            if state is not None:
                # **두 축을 함께** 적는다 — 026 `chk_vessel_state_pair`가 한쪽만
                # 바뀐 상태를 거부한다.
                vessel.underway_state, vessel.detail_status = state

    await session.commit()
    _log.info(
        "AIS 위치 적재 — 요청 %d · 수신 %d · 신규 %d · 미대조 %d (기준 %s)",
        len(by_imo),
        len(positions),
        recorded,
        unmatched,
        now.isoformat(),
    )
    return {
        "requested": len(by_imo),
        "received": len(positions),
        "recorded": recorded,
        "unmatched": unmatched,
        "errors": [],
    }
