"""감사 로그 조회 라우트 (``API_SPEC §16.1`` · `#1241`).

**HTTP만 다룬다** (``TECH_SPEC §16.1``) — 필터 검증과 페이지네이션은
``services.audit``이, 쿼리는 ``db/repositories/audit_log``가 한다.

## 왜 읽는 경로가 필요한가

`#673`이 `PARAMETER_IMPORT`로 **누가·언제·몇 행·어느 판본**을 적재했는지 남기게
했는데, **그 기록에 닿을 방법이 제품 안에 없었다.** 확인하려면 DB 직접 조회뿐이라,
규정 개정 이력을 묻는 질문에 화면으로 답할 수 없었다(`IT-AUDIT-002`).

## 사무직 이상만 본다

감사 로그에는 **사용자 식별자와 IP**가 들어 있다. 현장직에게는 자기 작업과 무관한
남의 활동 기록이고, `PRD §7.10`이 규정 파라미터 관리를 사무직 몫으로 두었으므로
그 이력도 같은 자리에서 본다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

# TYPE_CHECKING 블록에 두면 안 된다 — FastAPI가 의존성 시그니처를 런타임에 해석한다.
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_office
from cii_platform.db.session import get_session
from cii_platform.services import audit as audit_svc

router = APIRouter(tags=["audit"])


@router.get("/audit-logs")
async def list_audit_logs(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _office: Annotated[None, Depends(require_office)],
    action: Annotated[str | None, Query(description="감사 활동 코드 (DB_SCHEMA §2.14)")] = None,
    entity_type: Annotated[str | None, Query(description="대상 종류")] = None,
    user_id: Annotated[str | None, Query(description="행위자")] = None,
    since: Annotated[datetime | None, Query(description="이 시각부터 (포함)")] = None,
    until: Annotated[datetime | None, Query(description="이 시각까지 (포함)")] = None,
    limit: Annotated[int | None, Query(ge=1, description="기본 20 · 최대 100")] = None,
    cursor: Annotated[str | None, Query(description="이전 응답의 meta.next_cursor")] = None,
) -> dict[str, object]:
    """감사 로그를 최신순으로 돌려준다 (``API_SPEC §16.1``).

    ``meta``에 ``next_cursor``·``has_more``가 함께 들어간다 — 「기록이 N건뿐」과
    「아직 다 주지 않았다」가 **다른 모양**이어야 한다(`#1076`·`#1395`가 같은 자리를
    고쳤다).

    ⚠️ **쓰기 경로를 막지 않는다.** ``SELECT``만 하고 잠금을 잡지 않는다 — 조회가
    적재·계산을 방해하면 감사 자체가 부담이 된다(`#1241` 완료 기준 ⑵).
    """
    rows, page = await audit_svc.list_events(
        session,
        limit=limit,
        cursor=cursor,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        since=since,
        until=until,
    )

    state = getattr(request, "state", None)
    return {
        "data": rows,
        "meta": {
            **page,
            "request_id": getattr(state, "request_id", None),
            "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
        },
    }
