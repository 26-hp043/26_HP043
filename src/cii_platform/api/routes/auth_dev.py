"""개발 환경 스텁 인증 — ``APP_ENV != production``에서만 등록된다 (#276).

CI와 오프라인 시연에서 외부 IdP(구글) 없이 인증을 통과할 수 있게 한다.
**``APP_ENV=production``에서는 라우트 자체를 등록하지 않는다** — 런타임 조건 분기가
아니라 **기동 시점에** 가른다. 이는 ``config.py``의 ``APP_ENV=production`` 가드와
같은 패턴이다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.auth.session import (
    COOKIE_ATTRIBUTES,
    SESSION_COOKIE_NAME,
    create_session_fields,
)
from cii_platform.config import _ENV
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])

#: 고정 테스트 사용자 — 구글 OIDC 없이 세션을 발급한다.
_STUB_USER_ID = uuid4()
_STUB_GOOGLE_SUB = "stub-dev-user-00000000"
_STUB_EMAIL = "dev@localhost"


@router.post("/dev-login")
async def dev_login(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    """고정 테스트 사용자로 세션을 발급한다 (#276).

    **이 라우트는 ``APP_ENV=production``에서 등록되지 않는다.**
    ``main.py``에서 ``_ENV != "production"``일 때만 ``include_router``한다.
    """
    user = await session.get(AppUser, _STUB_USER_ID)
    if user is None:
        user = AppUser(
            id=_STUB_USER_ID,
            google_sub=_STUB_GOOGLE_SUB,
            email=_STUB_EMAIL,
            display_name="Dev Stub User",
        )
        session.add(user)
        await session.flush()

    fields, session_token, csrf_token = create_session_fields(
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    from cii_platform.db.models.user_session import UserSession

    db_session = UserSession(**fields)
    session.add(db_session)
    await session.commit()

    response = JSONResponse(
        status_code=200,
        content={
            "data": {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
            },
            "meta": {"message": "스텁 인증(dev-login)으로 세션을 발급했습니다."},
        },
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        **COOKIE_ATTRIBUTES,
    )
    response.set_cookie(
        key="csrf",
        value=csrf_token,
        httponly=False,  # CSRF 토큰은 JS에서 읽어 X-CSRF-Token 헤더로 보낸다
        secure=COOKIE_ATTRIBUTES["secure"],
        samesite=COOKIE_ATTRIBUTES["samesite"],
        path=COOKIE_ATTRIBUTES["path"],
    )
    return response


def should_register_dev_auth() -> bool:
    """``APP_ENV=production``이면 False — ``main.py``가 기동 시점에 호출한다."""
    return _ENV != "production"
