"""샘플 항만 · 좌표 기반 추정 거리 (API_SPEC §3.8 · §3.9 · #760 · `PRD §15.1` · `§15.2`).

항차 입력 화면이 출발·도착항을 **목록에서 고르면 좌표가 채워지고**, 두 좌표가 있으면
계획 거리를 **좌표 기반 추정 거리**로 채울 수 있게 한다. 둘 다 읽기 전용이다 — 항차를
만들지 않는다. 계산식은 서버 한 곳(`calc/distance.py`)에 두고 화면은 부르기만 한다: 화면에
같은 식을 두면 두 벌이 되어 한쪽만 고쳐진다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, Request

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.services.sample_ports import estimate_distance, list_sample_ports

router = APIRouter(tags=["ports"])


def _meta(request: Request) -> dict[str, object]:
    """API_SPEC §1.3.1 ``meta`` — 다른 라우터와 같은 모양(라우터마다 하나씩 둔다)."""
    state = getattr(request, "state", None)
    return {
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


_Lat = Annotated[Decimal, Query(ge=-90, le=90, description="위도 (VAL-007)")]
_Lon = Annotated[Decimal, Query(ge=-180, le=180, description="경도 (VAL-007)")]


@router.get("/ports/samples")
async def list_sample_ports_route(request: Request) -> dict[str, object]:
    """샘플 항만 목록 (API_SPEC §3.8). 이름·좌표만 — 목록에 없는 항은 자유 입력이다."""
    return {"data": list_sample_ports(), "meta": _meta(request)}


@router.get("/ports/great-circle")
async def estimate_distance_route(
    request: Request,
    from_lat: _Lat,
    from_lon: _Lon,
    to_lat: _Lat,
    to_lon: _Lon,
) -> dict[str, object]:
    """두 좌표의 대권거리 (API_SPEC §3.9). **추정값**이다 — 실제 항로보다 짧다(`PRD §15.2`)."""
    return {
        "data": estimate_distance(from_lat, from_lon, to_lat, to_lon),
        "meta": _meta(request),
    }
