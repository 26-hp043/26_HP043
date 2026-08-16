"""선대 요약 라우트 (`API_SPEC §2.8`).

**HTTP 요청/응답만 다룬다** (`TECH_SPEC §16.1`). 집계·판정은
``services.fleet_summary``가 맡는다.

범위: #350.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

# TYPE_CHECKING 블록에 두면 안 된다. `from __future__ import annotations`로 애노테이션이
# 문자열이 되는데, FastAPI는 의존성 시그니처를 **런타임에** 해석하므로 이름을 찾지 못해
# PydanticUserError로 앱 기동이 실패한다 (vessels.py와 같은 근거).
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.db.session import get_session
from cii_platform.services.fleet_summary import get_fleet_summary

router = APIRouter(tags=["fleet"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    """`API_SPEC §1.3.1` ``meta``. 미들웨어가 주입한 요청 컨텍스트를 옮긴다."""
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/fleet/summary")
async def get_fleet_summary_route(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    regulation_year: Annotated[
        int | None, Query(description="집계 대상 규제연도. 미지정이면 as_of 연도")
    ] = None,
    as_of: Annotated[
        datetime | None,
        Query(description="기준 시각 (ISO 8601 UTC). 미지정이면 서버가 확정"),
    ] = None,
) -> dict[str, object]:
    """대시보드가 한 번의 호출로 선대 전체 현황을 받는다 (#350).

    **선박이 0척인 것은 오류가 아니다.** 아직 등록하지 않은 선사가 정상적으로
    만나는 상태이므로 200에 빈 배열을 돌려준다 — 404로 내면 화면이
    「기능 미구현」과 구분하지 못한다.
    """
    data = await get_fleet_summary(
        session,
        regulation_year=regulation_year,
        as_of=as_of,
    )
    # `as_of` 계약 ⑵ — 실제로 사용한 값을 meta에도 싣는다. 클라이언트가 이 값으로
    # 다시 물어 같은 결과를 얻을 수 있어야 한다.
    return {"data": data, "meta": _meta(request, as_of=data["as_of"])}
