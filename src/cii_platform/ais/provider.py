"""AIS 위치 제공자 계약 (`#764`).

## 무엇을 여기 두나

**바깥에서 받은 위치 한 건의 모양**(:class:`AisPosition`)과 **받아 오는 쪽의 계약**
(:class:`AisProvider`)이다. 저장·중복 판정·운항 상태 반영은
``services/position_snapshot.py``가 맡는다 — ``weather``와 ``services/weather.py``를
가른 것과 같은 이유다.

## 출처 조사 결과 (2026-09-12 · 이슈 코멘트에 전문)

무계약·무하드웨어로 쓸 수 있는 경로가 실제로 있다.

===================  ==========  ==============================================
 출처                 범위        조건
===================  ==========  ==============================================
 aisstream.io         전 지구     무료 · 구독 3 × MMSI 200 = **최대 600척** ·
                                  **SLA 없음 · 끊긴 구간 복구 없음**
 Digitraffic(FI)      핀란드      무료 · CC BY 4.0(출처 표기)
 Kystverket(NO)       노르웨이    무료 · NLOD
 AISHub               전 지구     **자체 AIS 수신기 운영이 조건**
 Datalastic 등        전 지구     월 €199부터
===================  ==========  ==============================================

600척 상한은 이 제품의 선대 상한(``_MAX_FLEET_SIZE = 200``)보다 크므로 규모는
문제가 아니다.

## ⚠️ 붙일 대상이 아직 없다 — 그래서 계약만 먼저 둔다

데모 선박 5척의 IMO는 **합성값**이다(마이그레이션 ``036``이 체크섬만 맞췄다).
실재하지 않는 배라 **어떤 AIS 출처도 이 선박들의 위치를 주지 않는다.** 그러므로
이 모듈은 지금 **아무 데도 연결하지 않는다**:

* 계약(:class:`AisProvider`)과 좌표 모양(:class:`AisPosition`)을 확정하고,
* 항행 상태 코드를 우리 운항 상태로 옮기는 규칙(:func:`underway_state_from`)을 둔다.

실선박 데이터가 들어오면(``#765``) 구현체 하나를 더하는 것으로 끝난다. **반대로
지금 구현체를 만들면, 검증할 방법이 없는 코드가 남는다.**

## 조회 경로에 섞지 않는다

``API_SPEC §2.6``이 못박아 두었다 — *"조회 경로에서 갱신하지 않는다 … 쓰기를
조회에 섞으면 GET이 트랜잭션을 잡는다."* 수집은 **별도 경로**(배치·구독)이며,
:func:`AisProvider.fetch_positions`를 요청 처리 중에 부르지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

#: ``vessel_position_snapshot.source`` (``DB_SCHEMA §2.21``).
SOURCE_MANUAL = "MANUAL"
SOURCE_AIS = "AIS"
SOURCE_SIMULATED = "SIMULATED"

SOURCES = (SOURCE_MANUAL, SOURCE_AIS, SOURCE_SIMULATED)

#: ITU-R M.1371 항행 상태 중 **항해 중**인 코드.
#:
#: 0 = under way using engine · 8 = under way sailing. 둘 다 「이동 중」이며, 나머지는
#: 정박(1 at anchor · 5 moored)·좌초(6)·제한(2~4)·미정의(15) 등이다.
NAV_STATUS_UNDER_WAY = frozenset({0, 8})

#: ``vessel.underway_state`` (``DB_SCHEMA §2.1`` · 026 CHECK).
UNDER_WAY = "UNDER_WAY"
NOT_UNDER_WAY = "NOT_UNDER_WAY"

#: ITU-R M.1371 항행 상태 → ``(underway_state, detail_status)`` **쌍**.
#:
#: 026 ``chk_vessel_state_pair``가 두 축을 **함께** 요구한다 — 한쪽만 적으면 저장이
#: 거부된다. 그래서 매핑도 쌍으로 한다.
#:
#: 여기 없는 코드(2 not under command · 3 restricted manoeuvrability ·
#: 4 constrained by draught · 6 aground · 7 fishing · 9~14 예약 · 15 undefined)는
#: **판정하지 않는다.** 「조종 제한」은 항해 중일 수도 정박 중일 수도 있고, 우리
#: 세부 상태 6종 중 어느 것도 그 뜻을 담지 않는다.
#:
#: ``DRIFTING``·``STS``·``CANAL_TRANSIT``·``DRYDOCK``은 **AIS가 말하지 않는다** —
#: 사람이 넣는 축으로 남는다.
NAV_STATUS_TO_STATE: dict[int, tuple[str, str]] = {
    0: (UNDER_WAY, "SAILING"),  # under way using engine
    1: (NOT_UNDER_WAY, "AT_ANCHOR"),  # at anchor
    5: (NOT_UNDER_WAY, "IN_PORT"),  # moored
    8: (UNDER_WAY, "SAILING"),  # under way sailing
}


class AisError(RuntimeError):
    """AIS 조회 실패. **숨기지 않고 그대로 올린다** — ``weather``의 규약과 같다."""


@dataclass(frozen=True)
class AisPosition:
    """AIS가 준 위치 한 건.

    ORM 모델(:class:`~cii_platform.db.models.vessel_position_snapshot.VesselPositionSnapshot`)과
    이름을 나눈 이유는 **받은 것과 저장한 것을 구분**하기 위해서다 —
    ``WeatherObservation``과 ``WeatherSnapshot``을 가른 것과 같다.

    :param mmsi: AIS의 식별자. **IMO가 아니다** — MMSI는 선적을 바꾸면 달라지므로
        선박 대조는 ``imo_number``로 하고, MMSI는 받은 그대로 남긴다.
    :param observed_at: 배가 그 자리에 있던 시각. **수신 시각이 아니다.**
    """

    mmsi: str
    lat: Decimal
    lon: Decimal
    observed_at: datetime
    imo_number: str | None = None
    sog_kn: Decimal | None = None
    cog_deg: Decimal | None = None
    nav_status: int | None = None


class AisProvider(Protocol):
    """AIS 제공자. 구현체는 **바깥과 말하는 것만** 한다.

    ``imo_numbers``로 묻는 이유는 우리 쪽 식별자가 IMO이기 때문이다(``vessel.imo_number``
    UNIQUE). 제공자가 MMSI로만 받는다면 그 매핑은 **구현체 안에서** 해결한다 —
    호출부가 두 식별자를 함께 들고 다니면 어느 쪽이 정본인지 흐려진다.
    """

    async def fetch_positions(self, *, imo_numbers: list[str]) -> list[AisPosition]:
        """주어진 IMO들의 **가장 최근** 위치를 돌려준다.

        위치가 없는 선박은 **목록에서 빠진다** — 빈 값을 채워 넣지 않는다. AIS는
        수신 범위 밖이면 아무것도 주지 않는 것이 정상이고, 그것을 「좌표 없음」이
        아니라 「행 없음」으로 두어야 마지막 위치가 지워지지 않는다.
        """
        ...


def state_pair_from(nav_status: int | None) -> tuple[str, str] | None:
    """AIS 항행 상태 코드를 ``(underway_state, detail_status)`` 쌍으로 옮긴다.

    **쌍인 이유**는 026 ``chk_vessel_state_pair``가 두 축을 함께 요구하기 때문이다 —
    ``underway_state``만 바꾸면 저장이 거부된다.

    :returns: 옮길 수 있는 코드면 쌍, 아니면 ``None``.

    ``None``일 때는 **기존 상태를 그대로 둔다.** 모르는 것을 ``NOT_UNDER_WAY``로
    적으면 정박하지 않은 배가 정박한 것으로 기록되고, 그 값이
    ``not_underway_period``와 어긋난다.

    ⚠️ **이 함수의 결과를 저장하되 원본 코드도 함께 남긴다**
    (``vessel_position_snapshot.nav_status``) — 매핑 규칙이 바뀌어도 과거 행을 다시
    읽을 수 있어야 한다.
    """
    if nav_status is None:
        return None
    return NAV_STATUS_TO_STATE.get(nav_status)
