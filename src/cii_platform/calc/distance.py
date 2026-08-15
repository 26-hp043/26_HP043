"""대권거리(great-circle distance) 계산 — 기능② DIRECT 거리 해석 (#57).

PRD §11.2 DIRECT 생성 방식: "사용자가 입력한 거리 또는 좌표 기반 대권거리".
``direct_distance_nm``가 오면 좌표는 보지 않고, 없으면 현재·목적항 좌표 4개로
대권거리를 잰다.

지구 반경 ``3,440.065`` 해리(평균 지구 반경 6,371 km ÷ 1.852 km/nm)는 상위 문서가
정한 값이 아니라 기하 상수다 — 규제값이 아니므로 AGENTS §2 교차 검증 대상이
아니지만, 단일 소스를 위해 상수로 둔다.

삼각함수는 float로만 계산할 수 있어 이 모듈은 float를 쓴다. 다만 결과는 곧바로
``Decimal``로 확정해 반환하므로, 이 값이 Layer 1 계산에 들어가는 시점에는 이미
결정론적이다. 좌표 → 거리는 기상 보정과 같은 **입력 해석 단계**다 (TECH_SPEC §5.4
— 외부 데이터의 확정 시점 이후 계산은 결정론).
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

#: 평균 지구 반경(해리). 6,371 km ÷ 1.852 km/nm(1해리 국제 표준) → 3,440.065.
EARTH_RADIUS_NM = 3440.065

#: 결과 확정 자릿수 — ``voyage_scenario.distance_nm`` 컬럼이 NUMERIC(12,2)다.
_DISTANCE_QUANTUM = Decimal("0.01")


def great_circle_distance_nm(lat1: Decimal, lon1: Decimal, lat2: Decimal, lon2: Decimal) -> Decimal:
    """두 지점의 대권거리(해리)를 haversine 공식으로 계산한다.

    VAL-007 범위 검증은 스키마가 통과시킨 값만 들어온다는 전제로 여기서 다시 보지
    않는다 — 같은 규칙이 두 곳에 생기면 어느 쪽이 정본인지 알 수 없게 된다.
    """
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlam = math.radians(float(lon2) - float(lon1))

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    nm = EARTH_RADIUS_NM * 2 * math.asin(math.sqrt(a))
    return Decimal(str(nm)).quantize(_DISTANCE_QUANTUM, rounding=ROUND_HALF_UP)
