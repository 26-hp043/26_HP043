"""공개 해상 경로망 위의 바닷길 (`#1300` E-6 ⓕ · `API_SPEC §3.11` · `PRD §5.2`).

`searoute`(Apache-2.0)가 번들한 Eurostat SeaRoute 해상 경로망(EUPL-1.2 — ORNL *Global
Shipping Lane Network, 2000* 기반)에서 두 점 사이의 최단 경로를 찾아 좌표 목록으로 낸다.
선대 대시보드와 항로 비교 지도가 대권선 대신 이 선을 그린다.

## 표시용이다 — 계산 거리는 바꾸지 않는다

CII 계산에 들어가는 거리는 사용자 입력 또는 **대권거리**다(`PRD §15.2` · `TECH_SPEC §5.4`
재현성 계약). 이 모듈이 내는 ``length_nm``은 선의 길이를 캡션·검증에 쓰기 위한 참고값이며
``voyage_scenario.distance_nm``에 들어가지 않는다. 같은 두 점을 두 번 물으면 같은 선이
나온다(경로망·알고리즘이 고정이라 결정론) — 그래도 재현성 해시 재료가 아니다.

## 경계 처리

- **같은 점**은 라이브러리에 묻지 않는다 — ``searoute``는 같은 점도 가까운 노드까지
  갔다 오는 선(≈20nm)을 내는데, 그것은 「항로」가 아니다.
- **날짜변경선**: 라이브러리는 한 구간 안에서는 경도를 ``±180`` 밖으로 이어 준다
  (MapLibre가 허용한다 — 종전 화면의 대권선 보간이 쓰던 것과 같은 표현).
  구간을 이을 때는 다음 구간의 첫 점이 앞 구간의 끝점에 가장 가까운 사본이 되도록
  ``±360``을 더한다 — 그러지 않으면 경유지에서 선이 지구를 한 바퀴 되돌아간다.
- **육지 위의 점**(잘못 넣은 좌표)은 라이브러리가 가장 가까운 경로망 노드로 붙인다.
  오류로 만들지 않는다 — 대권선도 같은 입력을 그렸다.
- **경로가 없으면 선을 내지 않는다.** 라이브러리는 통과 제한(기본 북서항로 금지)으로 막힌
  두 점에 ``UserWarning``을 내고 **두 점을 잇는 직선**을 돌려준다 — 그 직선은 바닷길이
  아니다. 경고를 잡아 :class:`SeaRouteNotFoundError`로 올린다(라우트가 404로 낸다).

## 첫 적재와 동시성

경로망 그래프(노드 ≈ 1만)는 **첫 호출에 메모리에 올린다** — 리눅스 파일시스템 실측
(2026-09-24 · WSL2 · `/tmp`) `import 1.39s + 그래프 0.57s`, 그 뒤 호출은 ms 단위(같은 실측
2ms · ``functools.lru_cache``). 이벤트 루프에서 그대로 돌리면 그동안 모든 요청이 멈추므로
비밀번호 해싱(`auth/password.py`)과 같은 이유로 ``anyio.to_thread``로 보내고, 스레드 수를
:data:`MAX_CONCURRENT_ROUTES`로 제한한다. **첫 적재는 락으로 직렬화한다** — 콜드 상태에서
요청 둘이 동시에 오면 라이브러리의 ``lru_cache``가 비어 있어 둘 다 그래프를 만든다.
앱 기동 시 :func:`warm_up`을 백그라운드로 돌려(`api/main.py` lifespan) 첫 사용자가 그
비용을 치르지 않게 한다 — 실패해도 기동은 계속된다(다음 요청이 다시 적재한다).
"""

from __future__ import annotations

import logging
import threading
import warnings
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

import anyio
import anyio.to_thread

_log = logging.getLogger(__name__)

#: 응답 좌표 자릿수. 경로망 노드 좌표가 소수 6자리이고, 그 이하는 지도에서 구분되지 않는다.
_COORD_PLACES = 6
#: 길이 확정 자릿수 — `calc/distance.py`의 대권거리와 같은 자릿수로 맞춘다.
_LENGTH_QUANTUM = Decimal("0.01")
#: 출처 표기 — 응답 ``source``에 그대로 실린다 (`API_SPEC §3.11`).
SOURCE = "searoute/marnet"
#: 동시에 경로를 찾는 워커 스레드 수 — 비밀번호 해싱(`auth/password.py`)과 같은 관례.
#: 그래프 탐색은 CPU 작업이라 코어 수 이상은 서로를 밀어낼 뿐이다.
MAX_CONCURRENT_ROUTES = 4

_route_limiter = anyio.CapacityLimiter(MAX_CONCURRENT_ROUTES)
#: 첫 적재를 직렬화한다 — 콜드 동시 요청이 그래프를 두 번 만들지 않게.
_load_lock = threading.Lock()


class SeaRouteNotFoundError(ValueError):
    """경로망에서 두 점 사이의 바닷길을 찾지 못했다 — 라이브러리가 직선으로 대신하려 한 경우."""


@dataclass(frozen=True)
class SeaRouteLine:
    """경로망 위의 선 하나. ``coordinates``는 GeoJSON 순서(경도, 위도)다."""

    coordinates: tuple[tuple[float, float], ...]
    length_nm: Decimal
    #: 이은 구간 수 — 경유지가 없으면 1, 하나면 2.
    legs: int


def _key(lat: Decimal, lon: Decimal) -> tuple[float, float]:
    """캐시 키 — 소수 6자리(≈ 0.1m)로 고정해 같은 점이 표기 차이로 두 번 계산되지 않게."""
    return (round(float(lon), _COORD_PLACES), round(float(lat), _COORD_PLACES))


def _ensure_loaded() -> None:
    """경로망·항만 그래프를 한 번만 올린다 — 락 안에서. 이미 올라 있으면 곧바로 돌아온다."""
    # 지연 import — 경로망 데이터를 읽는 비용이 커서 이 함수를 부르는 프로세스만 낸다.
    import searoute

    with _load_lock:
        searoute.setup_M()
        searoute.setup_P()


def warm_up() -> bool:
    """기동 시 백그라운드 적재. 실패해도 예외를 밖으로 내지 않는다 — 기동을 막을 이유가 아니다."""
    try:
        _ensure_loaded()
    except Exception:  # noqa: BLE001 — 어떤 실패든 기동은 계속되고, 다음 요청이 다시 적재한다
        _log.exception("해상 경로망 워밍에 실패했다 — 첫 요청이 다시 적재한다")
        return False
    return True


@lru_cache(maxsize=512)
def _leg(origin: tuple[float, float], destination: tuple[float, float]) -> SeaRouteLine:
    """한 구간 ``(lon, lat) → (lon, lat)``. 경로가 없으면 :class:`SeaRouteNotFoundError`."""
    if origin == destination:
        return SeaRouteLine(coordinates=(origin,), length_nm=Decimal("0.00"), legs=1)
    import searoute

    _ensure_loaded()
    # 경로가 없을 때 라이브러리는 **경고 + 직선**이다(`utils.raise_warn_no_path`). 직선은
    # 바닷길이 아니므로 경고를 잡아 실패로 올린다 — 조용히 육지를 가로지르는 선을 내지 않는다.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        feature = searoute.searoute(
            list(origin),
            list(destination),
            units="naut",
            # 양 끝에 **입력 좌표 그대로**를 붙인다 — 붙이지 않으면 선이 가장 가까운 경로망
            # 노드에서 시작해 마커와 선 끝이 떨어져 보인다.
            append_orig_dest=True,
        )
    if caught:
        raise SeaRouteNotFoundError(
            f"경로망에서 바닷길을 찾지 못했다: {origin} → {destination} — "
            + " / ".join(str(w.message) for w in caught)
        )
    coords = tuple(
        (round(float(lon), _COORD_PLACES), round(float(lat), _COORD_PLACES))
        for lon, lat in feature.geometry["coordinates"]
    )
    length = Decimal(str(feature.properties["length"])).quantize(
        _LENGTH_QUANTUM, rounding=ROUND_HALF_UP
    )
    return SeaRouteLine(coordinates=coords, length_nm=length, legs=1)


def _shift_to_join(prev_lon: float, lon: float) -> float:
    """``lon``의 ``±360`` 사본 중 ``prev_lon``에 가장 가까운 것 — 구간 이음새의 경도 오프셋."""
    best = lon
    for candidate in (lon - 360.0, lon + 360.0):
        if abs(candidate - prev_lon) < abs(best - prev_lon):
            best = candidate
    return best


def sea_route_line(points: list[tuple[Decimal, Decimal]]) -> SeaRouteLine:
    """``(lat, lon)`` 점 둘 이상을 차례로 잇는 바닷길.

    두 점이면 직항, 셋이면 「출발 → 경유지 → 목적항」이다(`PRD §11.3` 우회 경유지).
    각 구간을 따로 구해 이어 붙이고, 이음새에서 겹치는 점 하나를 뺀다.
    """
    if len(points) < 2:
        raise ValueError("경로에는 점이 둘 이상 필요합니다.")
    keys = [_key(lat, lon) for lat, lon in points]
    merged: list[tuple[float, float]] = []
    total = Decimal("0.00")
    for origin, destination in zip(keys[:-1], keys[1:], strict=True):
        leg = _leg(origin, destination)
        total += leg.length_nm
        coords = list(leg.coordinates)
        if merged:
            # 이음새: 앞 구간의 끝과 이 구간의 시작이 같은 점이다 — 경도 사본만 다를 수 있다.
            prev_lon = merged[-1][0]
            offset = _shift_to_join(prev_lon, coords[0][0]) - coords[0][0]
            coords = [(lon + offset, lat) for lon, lat in coords[1:]]
        merged.extend(coords)
    return SeaRouteLine(coordinates=tuple(merged), length_nm=total, legs=len(points) - 1)


async def sea_route_line_async(points: list[tuple[Decimal, Decimal]]) -> SeaRouteLine:
    """:func:`sea_route_line`을 워커 스레드에서 — 그래프 탐색·첫 적재가 루프를 막지 않게."""
    return await anyio.to_thread.run_sync(sea_route_line, points, limiter=_route_limiter)


async def warm_up_async() -> bool:
    """:func:`warm_up`을 워커 스레드에서 — lifespan이 기다리지 않고 띄운다."""
    return await anyio.to_thread.run_sync(warm_up, limiter=_route_limiter)


def serialize_line(line: SeaRouteLine) -> dict[str, object]:
    """`API_SPEC §3.11` 응답 ``data``. 좌표는 지도가 바로 쓰는 float, 길이는 문자열이 아니라
    ``float``다 — `§3.9`(`estimate_distance`)와 같은 자리이며 **표시용 참고값**이지 Layer 1
    계약값이 아니다."""
    return {
        "coordinates": [[lon, lat] for lon, lat in line.coordinates],
        "length_nm": float(line.length_nm),
        "legs": line.legs,
        "source": SOURCE,
    }
