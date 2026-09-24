"""샘플 항만 · 좌표 기반 추정 거리 · 해상 경로망.

(API_SPEC §3.8 · §3.9 · §3.11 · #760 · #1300 · `PRD §15.1` · `§15.2` · `§5.2`)

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
from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.geocode.nominatim import GeocodeProvider
from cii_platform.services.geocoding import lookup_port
from cii_platform.services.sample_ports import estimate_distance, list_sample_ports
from cii_platform.services.sea_route import (
    SeaRouteNotFoundError,
    sea_route_line_async,
    serialize_line,
)

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
_OptLat = Annotated[Decimal | None, Query(ge=-90, le=90, description="경유지 위도 (VAL-007)")]
_OptLon = Annotated[Decimal | None, Query(ge=-180, le=180, description="경유지 경도 (VAL-007)")]


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


@router.get("/ports/sea-route")
async def sea_route_route(
    request: Request,
    from_lat: _Lat,
    from_lon: _Lon,
    to_lat: _Lat,
    to_lon: _Lon,
    via_lat: _OptLat = None,
    via_lon: _OptLon = None,
) -> dict[str, object]:
    """공개 해상 경로망 위의 바닷길 (API_SPEC §3.11 · `#1300`).

    **표시용**이다 — 지도가 대권선 대신 이 선을 그린다. 계산 거리(`§3.9` · `PRD §15.2`)는
    바뀌지 않는다. ``via_*`` 둘을 함께 주면 「출발 → 경유지 → 목적항」을 잇는다(항로 비교의
    우회 경유지). 한쪽만 주면 422다 — 좌표 한 쌍의 반쪽은 위치가 아니다(`§5.1`과 같은 규칙).
    경로망이 두 점을 잇지 못하면 404다.
    """
    if (via_lat is None) != (via_lon is None):
        raise ValidationError(
            "경유지 위도와 경도는 함께 입력해 주세요.",
            field="via_lat" if via_lat is None else "via_lon",
            field_label="경유지 좌표",
        )
    points = [(from_lat, from_lon)]
    if via_lat is not None and via_lon is not None:
        points.append((via_lat, via_lon))
    points.append((to_lat, to_lon))
    try:
        line = await sea_route_line_async(points)
    except SeaRouteNotFoundError as exc:
        # 경로망이 두 점을 잇지 못한다(통과 제한으로 막힌 바다 등) — `§3.10`처럼 404다.
        # 라이브러리가 대신 주는 직선은 바닷길이 아니라 내보내지 않는다.
        raise NotFoundError(
            "공개 해상 경로망에서 두 지점 사이의 바닷길을 찾지 못했습니다. 좌표를 확인해 주세요."
        ) from exc
    return {"data": serialize_line(line), "meta": _meta(request)}


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
    # 제공자는 **프로세스에 하나**다(`main.py`가 `app.state`에 둔다). 요청마다 새로 만들면
    # 어댑터 안의 「초당 1회」 시각이 매번 초기화되어 상한이 한 번도 걸리지 않는다 (`#1335`).
    # 앱이 제공자를 두지 않았으면 바깥으로 나가지 않는다 — 샘플·캐시까지만 본다.
    provider: GeocodeProvider | None = getattr(request.app.state, "geocode_provider", None)
    found, reason = await lookup_port(session, name=name, provider=provider)
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
