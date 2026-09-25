"""항차 생성·조회 라우트 (API_SPEC §3.1~§3.3 · §8.2, #53 · #60).

**HTTP 요청/응답만 다룬다** (TECH_SPEC §16.1). 비즈니스 규칙·검증은
``services.voyage``·``services.voyage_import``이 맡는다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.rate_limit import audit_client_ip
from cii_platform.api.schemas.voyage import (
    VoyageActualsRequest,
    VoyageCreateRequest,
    VoyageTransitionRequest,
    VoyageUpdateRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import require_csrf
from cii_platform.db.session import get_session
from cii_platform.errors import ValidationError
from cii_platform.services import audit as audit_svc
from cii_platform.services.not_underway_import import import_not_underway_periods
from cii_platform.services.voyage import (
    create_voyage,
    delete_voyage,
    get_voyage,
    list_voyages,
    set_actuals,
    transition_voyage,
    update_voyage,
)
from cii_platform.services.voyage_import import import_voyages

router = APIRouter(tags=["voyages"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


@router.get("/vessels/{vessel_id}/voyages")
async def list_voyages_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[str | None, Query(description="상태 필터")] = None,
    regulation_year: Annotated[
        int | None, Query(ge=2000, le=2100, description="기준연도 필터")
    ] = None,
    annual_inclusion_policy: Annotated[
        str | None, Query(description="연간 반영 정책 필터 (#1332)")
    ] = None,
    limit: Annotated[int | None, Query(ge=1, description="페이지 크기")] = None,
    cursor: Annotated[str | None, Query(description="페이지네이션 커서")] = None,
) -> dict[str, object]:
    """선박별 항차 목록을 조회한다 (API_SPEC §3.1).

    ``annual_inclusion_policy``는 **`§3.1` 표에는 처음부터 있었는데 여기 선언이 없어
    FastAPI가 조용히 버렸다** (`#1332`) — 문서대로 그 쿼리를 보낸 호출자는 필터가
    걸린 줄 알고 전체 목록을 받았다.
    """
    data, page_meta = await list_voyages(
        session,
        vessel_id,
        limit=limit,
        cursor=cursor,
        status=status,
        regulation_year=regulation_year,
        annual_inclusion_policy=annual_inclusion_policy,
    )
    return {"data": data, "meta": _meta(request, **page_meta)}


@router.get("/voyages/{voyage_id}")
async def get_voyage_route(
    request: Request,
    voyage_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """항차 상세를 조회한다 (API_SPEC §3.2). 없으면 404."""
    return {"data": await get_voyage(session, voyage_id), "meta": _meta(request)}


@router.post("/vessels/{vessel_id}/voyages", status_code=201)
async def create_voyage_route(
    request: Request,
    vessel_id: UUID,
    payload: VoyageCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차를 생성한다 (API_SPEC §3.3). 성공 시 201 Created."""
    data = await create_voyage(
        session,
        vessel_id,
        voyage_no=payload.voyage_no,
        departure_port_name=payload.departure_port_name,
        departure_lat=payload.departure_lat,
        departure_lon=payload.departure_lon,
        arrival_port_name=payload.arrival_port_name,
        arrival_lat=payload.arrival_lat,
        arrival_lon=payload.arrival_lon,
        planned_distance_nm=payload.planned_distance_nm,
        planned_distance_source=payload.planned_distance_source,
        planned_speed_kn=payload.planned_speed_kn,
        planned_departure_at=payload.planned_departure_at,
        planned_arrival_at=payload.planned_arrival_at,
        regulation_year=payload.regulation_year,
        fuel_uses=[
            {
                "fuel_type": fu.fuel_type,
                "planned_fuel_ton": fu.planned_fuel_ton,
                "source": fu.source,
            }
            for fu in payload.fuel_uses
        ],
        notes=payload.notes,
    )
    return {"data": data, "meta": _meta(request)}


@router.patch("/voyages/{voyage_id}")
async def update_voyage_route(
    request: Request,
    voyage_id: UUID,
    payload: VoyageUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차를 수정한다 (API_SPEC §3.4, #54). 없으면 404."""
    # exclude_unset: 생략된 필드는 아예 전달하지 않는다(변경 없음).
    # 명시적 null은 그대로 전달돼 클리어를 뜻한다 (#312).
    update_fields = payload.model_dump(exclude_unset=True)
    data = await update_voyage(session, voyage_id, **update_fields)
    return {"data": data, "meta": _meta(request)}


@router.put("/voyages/{voyage_id}/actuals")
async def set_voyage_actuals_route(
    request: Request,
    voyage_id: UUID,
    payload: VoyageActualsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차 실적을 입력한다 (`API_SPEC §3.6`, #440). 없으면 404.

    **`status`는 바꾸지 않는다** — 전환은 `POST /voyages/{id}/transition`이 한다.
    한 번에 처리하면 `PRD §8.1.1` 전환 가드가 자기 입력을 보고 통과하게 된다.
    """
    fields = payload.model_dump(exclude_unset=True)
    fuel_uses = fields.pop("fuel_uses", None)
    data = await set_actuals(session, voyage_id, fuel_uses=fuel_uses, **fields)
    return {"data": data, "meta": _meta(request)}


@router.post("/voyages/{voyage_id}/transition")
async def transition_voyage_route(
    request: Request,
    voyage_id: UUID,
    payload: VoyageTransitionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차 상태를 전환한다 (API_SPEC §3.5, #54).

    **확정 전환은 감사 로그에 남는다** (`TECH_SPEC §13.1`, #65). 주체(user)와 IP는
    HTTP 개념이라 라우트가 뽑아 넘긴다 — 서비스가 `request`를 알면 계층이 깨진다(§16.1).

    **상태와 감사는 한 번의 커밋으로 확정한다** (`#1625` · `TECH_SPEC §16.3`). 서비스는
    `commit=False`로 flush까지만 하고, 감사 INSERT까지 마친 뒤 여기서 커밋한다 — 종전에는
    서비스가 먼저 커밋해 감사 INSERT가 실패하면 **기록 없는 `CONFIRMED`**가 남았다.
    실패하면 요청 세션이 닫히며 통째로 롤백된다(`db/session.get_session`).
    """
    data = await transition_voyage(
        session,
        voyage_id,
        to_status=payload.to_status,
        annual_inclusion_policy=payload.annual_inclusion_policy,
        commit=False,
    )
    # 서비스가 실어 보낸 「변경 전」 값. 응답에서는 뺀다(`_duration_ms`와 같은 규약).
    from_status = data.pop("_from_status")

    state = getattr(request, "state", None)
    session_user = getattr(state, "session_user", None)
    actor = str(session_user.id) if session_user is not None else None
    client_ip = audit_client_ip(request)

    if data["status"] == "CONFIRMED":
        await audit_svc.record_voyage_confirm(
            session,
            user_id=actor,
            voyage_id=voyage_id,
            from_status=from_status,
            annual_inclusion_policy=data["annual_inclusion_policy"],
            ip_address=client_ip,
        )
    elif from_status == "CONFIRMED":
        # `#1328` — **확정을 되돌리거나 닫는** 두 전환도 기록한다.
        # `PRD §8.1.1`·`API_SPEC §3.5`가 둘 다 「audit log 필수」로 정하는데 코드는
        # 확정만 남겨, **확정된 실적을 되돌려 고친 뒤 다시 확정하면** 로그에 「확정」
        # 두 건만 남고 **누가 언제 되돌렸는지**가 사라졌다.
        #
        # `from_status`로 가르는 이유는 `_TRANSITIONS`상 `CONFIRMED`에서 나가는 길이
        # `COMPLETED`(정정)·`ARCHIVED`(보관) 둘뿐이기 때문이다 — 목적지를 열거하면
        # 전환 표가 늘 때 여기가 조용히 뒤처진다.
        await audit_svc.record_voyage_transition(
            session,
            user_id=actor,
            voyage_id=voyage_id,
            from_status=from_status,
            to_status=data["status"],
            annual_inclusion_policy=data["annual_inclusion_policy"],
            ip_address=client_ip,
        )

    # 기록 대상이 아닌 전환도 여기서 커밋한다 — 서비스가 더는 커밋하지 않는다.
    await session.commit()
    return {"data": data, "meta": _meta(request)}


@router.delete("/voyages/{voyage_id}")
async def delete_voyage_route(
    request: Request,
    voyage_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> dict[str, object]:
    """항차를 삭제한다 (API_SPEC §3.7, #54)."""
    data = await delete_voyage(session, voyage_id)
    return {"data": data, "meta": _meta(request)}


#: ``type`` 값 → 가져오기 함수 (`API_SPEC §8.2` 표 · `#765`).
#:
#: **표를 코드가 갖는다.** 값마다 `if`를 늘리면 새 종류를 더할 때 검증·분기·문서가
#: 따로 놀고, `§8.2` 표에 없는 값이 조용히 통과하는 경로가 생긴다.
_IMPORTERS = {
    "voyages": import_voyages,
    "not_underway_periods": import_not_underway_periods,
}


@router.post("/vessels/{vessel_id}/import")
async def import_voyages_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
    file: Annotated[UploadFile, File(description="CSV 파일 (UTF-8, BOM 허용)")],
    type: Annotated[
        str, Form(description="가져올 자료 종류 — voyages · not_underway_periods")
    ] = "voyages",
    dry_run: Annotated[bool, Query(description="검증만 하고 저장하지 않는다 (#60)")] = False,
) -> dict[str, object]:
    """항차 CSV를 가져온다 (API_SPEC §8.2, #60).

    **vessel-scoped다.** CSV에 선박 식별자가 없고, 있어도 경로와 다르면 무엇을 따를지
    정해야 한다 — 경로 하나로 두면 그 물음 자체가 생기지 않는다.

    ``type``은 폼 필드로 받는다(§8.2 표). 값은 ``voyages``와 ``not_underway_periods``
    둘이며(`#765`), 모르는 값은 **조용히 무시하지 않고** 거부한다 — 무시하면 사용자는
    정박 구간을 올렸다고 믿는데 항차가 들어가거나 아무것도 안 들어간다.
    """
    if type not in _IMPORTERS:
        raise ValidationError(
            f"지원하지 않는 가져오기 종류입니다: {type}",
            field="type",
            field_label="자료 종류",
        )

    content = await file.read()
    data = await _IMPORTERS[type](
        session,
        vessel_id,
        content=content,
        content_type=file.content_type,
        dry_run=dry_run,
    )
    return {"data": data, "meta": _meta(request)}
