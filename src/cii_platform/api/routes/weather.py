"""기상 스냅샷 조회 (``API_SPEC §9.1`` · `#767`).

## 왜 조회만 여는가

`API_SPEC §9`는 둘을 명세한다 — 조회(`§9.1`)와 **수동 갱신**(`§9.2`). 이 모듈은 **조회만**
연다. `§9.2`는 열지 않으며 그 판단은 `API_SPEC §9.2`가 각주로 적고 있다: 수동 갱신은
**사용자가 외부 API 호출을 직접 일으키는 유일한 경로**이고, 기상은 계산 요청이 필요할 때
알아서 갱신하므로(`services/weather.resolve_with_fallback`) **없어도 제품이 성립한다.**

## 누가 부를 수 있나

로그인한 사용자다. `#591`이 이 절을 유예하며 「누가 부를 수 있는지가 어드민 범위에
걸린다」고 적었는데, **그 전제가 바뀌었다** — `#808`이 「사내 도구 · 로그인 사용자는 같은
데이터를 공유」로 확정해 역할 구분이 없다. 경계는 「로그인했는가」 하나이고, 그것은
`auth_middleware`가 모든 비공개 경로에 이미 걸고 있다.

## 만료된 값도 돌려준다

이 엔드포인트는 「계산에 쓸 값」이 아니라 **「저장된 것이 무엇인가」**를 보여 준다. 계산이
왜 보정 없이 돌았는지 설명하려면 **만료된 값이 거기 있다는 사실 자체**가 답이다. 쓸지
말지는 fallback 체인이 정하고(`PRD §11.6`), 여기서는 `freshness`로 알린다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.db.session import get_session
from cii_platform.errors import NotFoundError
from cii_platform.services.weather import get_snapshot_view

router = APIRouter(tags=["weather"])


def _meta(request: Request) -> dict[str, object]:
    """``API_SPEC §1.3.1`` ``meta`` — 라우터마다 하나씩 둔다(`routes/ports.py`와 같은 모양)."""
    state = getattr(request, "state", None)
    return {
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


_Lat = Annotated[Decimal, Query(ge=-90, le=90, description="위도 (VAL-007)")]
_Lon = Annotated[Decimal, Query(ge=-180, le=180, description="경도 (VAL-007)")]


@router.get("/weather/snapshot")
async def get_weather_snapshot_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    lat: _Lat,
    lon: _Lon,
) -> dict[str, object]:
    """그 좌표 격자에 저장된 가장 최근 기상 스냅샷 (``API_SPEC §9.1``).

    좌표는 **격자로 반올림해** 찾는다(`TECH_SPEC §7.3` 캐시 격자) — 같은 바다를 0.001°
    차이로 물어도 같은 행을 본다.
    """
    view = await get_snapshot_view(session, lat=lat, lon=lon)
    if view is None:
        raise NotFoundError("그 좌표에 저장된 기상 스냅샷이 없습니다.")
    return {"data": view, "meta": _meta(request)}
