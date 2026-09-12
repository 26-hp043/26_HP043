"""샘플 항만 · 좌표 기반 추정 거리 (API_SPEC §3.8 · §3.9 · #760 · `PRD §15.1` · `§15.2`).

항차 입력 화면이 출발·도착항을 **목록에서 고르면 좌표가 채워지고**, 두 좌표가 있으면
계획 거리를 **좌표 기반 추정 거리**로 채울 수 있게 한다. 둘 다 읽기 전용이다 — 항차를
만들지 않는다. 계산식은 서버 한 곳(`calc/distance.py`)에 두고 화면은 부르기만 한다: 화면에
같은 식을 두면 두 벌이 되어 한쪽만 고쳐진다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.db.session import get_session
from cii_platform.errors import NotFoundError
from cii_platform.services.geocoding import lookup_port
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


#: 못 찾은 이유 → 화면에 나갈 한국어 문구 (`API_SPEC §3.10`).
#:
#: **서버가 문장을 만든다.** 화면 세 곳(항차 추가 · 항로 비교 · 계획 저장)이 각자 쓰면
#: 같은 상황에 다른 말이 나온다 (`#877`·`#900`이 같은 이유로 서버로 모았다).
_LOOKUP_FAILURE_MESSAGES = {
    "NOT_A_PORT": (
        "그 이름으로 항만을 찾지 못했습니다. 이름을 바꿔 보시거나 좌표를 직접 입력해 주세요."
    ),
    "LOOKUP_FAILED": (
        "항만 좌표 조회에 실패했습니다. 잠시 뒤 다시 시도하거나 좌표를 직접 입력해 주세요."
    ),
    "NO_PROVIDER": "항만 좌표 조회를 쓸 수 없는 환경입니다. 좌표를 직접 입력해 주세요.",
}


@router.get("/ports/lookup")
async def lookup_port_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str, Query(min_length=2, max_length=200, description="항만명")],
) -> dict[str, object]:
    """항만명으로 좌표를 찾는다 (`API_SPEC §3.10` · `#768`).

    **입력 중에 부르지 않는다.** 사용자가 「좌표 찾기」를 눌렀을 때 한 번 호출하는
    자리다 — 공개 Nominatim 사용 정책이 **자동완성을 금지**한다.

    샘플 목록 → 캐시 → 외부 조회 순으로 보고, 못 찾으면 404다. 실패해도 항차 입력은
    막히지 않는다(`PRD §16.2`) — 화면이 문구를 보여 주고 사용자가 직접 넣는다.
    """
    from cii_platform.geocode.nominatim import NominatimProvider

    found, reason = await lookup_port(session, name=name, provider=NominatimProvider())
    if found is None:
        raise NotFoundError(_LOOKUP_FAILURE_MESSAGES[reason or "NOT_A_PORT"])
    return {
        "data": {
            "name": found.name,
            "lat": float(found.lat),
            "lon": float(found.lon),
            "source": found.source,
            "display_name": found.display_name,
        },
        "meta": _meta(request),
    }
