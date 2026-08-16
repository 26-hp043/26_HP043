"""인증 라우트 — signup · login · me · logout (`API_SPEC §1.2`, #414).

## 구글 OIDC를 제거했다

2026-08-16 결정(`PRD §20 O-14`)으로 **제품이 이메일과 비밀번호를 직접 관리**한다.
종전 `/auth/login`(구글 리다이렉트)·`/auth/callback`은 사라졌다.

**세션 계층은 그대로다.** 구글이든 비밀번호든 「자격을 확인한 뒤 세션을 발급한다」는
동일하며, 바뀐 것은 자격을 확인하는 방법 하나다 — `create_session_fields()`·
쿠키 정책·CSRF·감사 로그는 손대지 않았다.

개발 환경에서는 ``auth_dev.py``의 스텁 경로가 별도로 등록된다 (#276).

## 계정 존재 여부를 노출하지 않는다

`API_SPEC §1.2`가 규정한 항목이다. 로그인 실패는 「없는 이메일」과 「비밀번호 불일치」를
**같은 응답·같은 소요시간**으로 낸다 — 구분하면 **가입자 목록을 캐낼 수 있다.**

반면 **회원가입의 이메일 중복은 알린다.** 알리지 않으면 사용자가 가입에 성공했다고
오해한다. 이 비대칭은 `PRD §6.3`이 의도로 명시한 것이다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from cii_platform.api.error_handlers import to_error_response
from cii_platform.api.schemas.auth import LoginRequest, SignupRequest
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import AuthenticationError
from cii_platform.auth.password import (
    PasswordPolicyError,
    hash_password,
    verify_dummy,
    verify_password,
)
from cii_platform.auth.session import (
    COOKIE_ATTRIBUTES,
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_session_fields,
    hash_token,
)
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.models.user_session import UserSession
from cii_platform.db.models.user_token import PURPOSE_EMAIL_VERIFY
from cii_platform.db.session import get_session
from cii_platform.mail import MailDeliveryError, get_mailer
from cii_platform.mail.templates import email_verification
from cii_platform.services import audit as audit_svc
from cii_platform.services.auth_token import issue_token

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: 로그인 실패 문구 — `PRD §6.3` 확정 원문.
#: **「없는 이메일」과 「비밀번호 불일치」에 같은 문구를 쓴다.**
LOGIN_FAILED_MESSAGE = "이메일 또는 비밀번호가 올바르지 않습니다."

#: 회원가입 이메일 중복 문구 — `PRD §6.3` 확정 원문.
EMAIL_TAKEN_MESSAGE = "이미 가입된 이메일입니다. 로그인하거나 비밀번호를 찾아 주세요."


def _client_ip(request: Request) -> str | None:
    """감사 로그용 클라이언트 IP — 미들웨어와 같은 정책으로 뽑는다 (#277).

    rate_limit와 달리 X-Forwarded-For는 신뢰하지 않고 직접 peer만 쓴다 —
    감사 기록의 주체는 정확해야 하고 위조 가능한 헤더에 의존하지 않는다.
    """
    return request.client.host if request.client else None


def _meta(request: Request) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


def _error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    """`API_SPEC §1.3.2` 형식의 오류 응답 — meta(request_id·timestamp)를 채운다."""
    state = getattr(request, "state", None)
    body = to_error_response(
        code,
        message,
        request_id=getattr(state, "request_id", None),
        timestamp=getattr(state, "timestamp", None) or iso_utc_now(),
    )
    return JSONResponse(status_code=status, content=body)


def _normalize_email(email: str) -> str:
    """이메일을 소문자로 통일한다.

    ``User@x.com``과 ``user@x.com``을 다른 계정으로 두면 사용자가 어느 쪽으로
    가입했는지 기억해야 한다. 도메인부는 대소문자를 구분하지 않는 것이 표준이고,
    로컬부도 실무상 구분하지 않는 제공자가 대부분이다.
    """
    return email.strip().lower()


def _user_payload(user: AppUser) -> dict[str, object]:
    """사용자 공개 표현. **``password_hash``를 절대 싣지 않는다.**"""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "email_verified_at": (
            user.email_verified_at.isoformat() if user.email_verified_at else None
        ),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _attach_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    """세션·CSRF 쿠키를 붙인다. 종전 OIDC 콜백과 같은 정책이다."""
    response.set_cookie(key=SESSION_COOKIE_NAME, value=session_token, **COOKIE_ATTRIBUTES)
    # CSRF 토큰은 JS가 읽어 헤더에 실어야 하므로 HttpOnly가 아니다.
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=COOKIE_ATTRIBUTES["secure"],
        samesite=COOKIE_ATTRIBUTES["samesite"],
        path=COOKIE_ATTRIBUTES["path"],
    )


async def _issue_session(
    session: AsyncSession,
    request: Request,
    user: AppUser,
) -> tuple[str, str]:
    """세션 행을 만들고 ``(session_token, csrf_token)``을 돌려준다."""
    fields, session_token, csrf_token = create_session_fields(
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    session.add(UserSession(**fields))
    return session_token, csrf_token


@router.post("/signup", status_code=201)
async def signup(
    request: Request,
    payload: SignupRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """이메일·비밀번호로 가입하고 세션을 발급한다 (`API_SPEC §1.2`).

    **가입 즉시 로그인 상태가 된다.** 이메일 인증 전에도 이용을 허용하기 때문이며
    (`PRD §7.10`), 인증 메일 발송은 `#408`이 이 자리에 붙인다.
    """
    email = _normalize_email(payload.email)

    try:
        password_hash = hash_password(payload.password)
    except PasswordPolicyError as exc:
        return _error_response(request, 422, "VALIDATION_ERROR", str(exc))

    # 중복 확인 — soft delete된 계정은 같은 이메일로 다시 가입할 수 있다.
    existing = await session.execute(
        select(AppUser).where(
            func.lower(AppUser.email) == email,
            AppUser.is_deleted.is_(False),
        )
    )
    if existing.scalar_one_or_none() is not None:
        # 로그인 실패와 달리 **중복은 알린다** — 알리지 않으면 사용자가 가입에
        # 성공했다고 오해한다 (`PRD §6.3` 비대칭 규정).
        return _error_response(request, 409, "CONFLICT", EMAIL_TAKEN_MESSAGE)

    user = AppUser(
        id=uuid4(),
        email=email,
        password_hash=password_hash,
        display_name=payload.display_name,
    )
    session.add(user)
    await session.flush()

    session_token, csrf_token = await _issue_session(session, request, user)
    # 인증 메일 토큰을 같은 트랜잭션에서 발급한다 — 커밋 뒤에 발송한다.
    verify_token = await issue_token(session, user_id=user.id, purpose=PURPOSE_EMAIL_VERIFY)
    await audit_svc.record_login_success(
        session,
        user_id=str(user.id),
        ip_address=_client_ip(request),
        details={"signup": True},
    )
    await session.commit()

    #
    # 메일 발송은 **커밋 뒤**에 한다 (#407 경계).
    #
    # SMTP는 우리 코드 밖에서 깨진다. 그 실패로 가입을 되돌리면 사용자는 계정이
    # 만들어졌는지도 알 수 없다 — 계정은 있고 메일만 실패한 상태가 정상 경로이며,
    # 화면은 재발송 버튼을 준다.
    #
    try:
        await get_mailer().send(
            email_verification(
                to=user.email,
                verify_url=f"{str(request.base_url).rstrip('/')}/verify-email?token={verify_token}",
            )
        )
    except MailDeliveryError:
        _log.warning("가입 확인 메일 발송 실패 — 계정은 생성됨: user_id=%s", user.id)

    response = JSONResponse(
        status_code=201,
        content={"data": _user_payload(user), "meta": _meta(request)},
    )
    _attach_session_cookies(response, session_token, csrf_token)
    return response


@router.post("/login")
async def login(
    request: Request,
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """이메일·비밀번호를 확인하고 세션을 발급한다 (`API_SPEC §1.2`).

    **없는 계정과 비밀번호 불일치를 구분하지 않는다** — 응답도 소요시간도 같다.
    """
    email = _normalize_email(payload.email)

    result = await session.execute(
        select(AppUser).where(
            func.lower(AppUser.email) == email,
            AppUser.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        # 즉시 거부하면 응답 시간 차이로 가입 여부를 알아낼 수 있다.
        # 결과를 쓰지 않는다 — 목적이 시간을 쓰는 것이다.
        verify_dummy(payload.password)
        await audit_svc.record_login_failure(
            session,
            reason="unknown_email",
            ip_address=_client_ip(request),
        )
        await session.commit()
        return _error_response(request, 401, "UNAUTHORIZED", LOGIN_FAILED_MESSAGE)

    if not verify_password(payload.password, user.password_hash):
        await audit_svc.record_login_failure(
            session,
            reason="bad_password",
            ip_address=_client_ip(request),
        )
        await session.commit()
        return _error_response(request, 401, "UNAUTHORIZED", LOGIN_FAILED_MESSAGE)

    session_token, csrf_token = await _issue_session(session, request, user)
    await audit_svc.record_login_success(
        session,
        user_id=str(user.id),
        ip_address=_client_ip(request),
        details={},
    )
    await session.commit()

    response = JSONResponse(content={"data": _user_payload(user), "meta": _meta(request)})
    _attach_session_cookies(response, session_token, csrf_token)
    return response


@router.get("/me")
async def me(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """현재 사용자 정보를 반환한다. **``password_hash``는 미노출.**"""
    user = getattr(request.state, "session_user", None)
    if user is None:
        raise AuthenticationError()

    return {"data": _user_payload(user), "meta": _meta(request)}


@router.post("/logout")
async def logout(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """세션을 즉시 무효화하고 쿠키를 만료시킨다 (#274). 멱등이다.

    ``request.state.session_row``은 **미들웨어 세션에서 로드한 detached 객체**다 —
    속성만 바꿔 라우트 세션으로 commit하면 이 세션에 dirty 객체가 없어 아무것도
    쓰이지 않는다(무효화 누락). 라우트 세션으로 **재조회해** 갱신한다 (#279에서
    발견).
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is not None:
        token_hash = hash_token(token)
        stmt = select(UserSession).where(
            UserSession.session_token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            row.revoked_at = dt.datetime.now(dt.UTC)
            # 실제 무효화가 일어난 경우만 기록한다 — 멱등 재호출은 세션이
            # 이미 없어 기록하지 않는다.
            await audit_svc.record_logout(
                session, user_id=str(row.user_id), ip_address=_client_ip(request)
            )
            await session.commit()

    # 204 No Content — 본문이 없다. JSONResponse는 content 인자가 필수라
    # 쓸 수 없고, 204에 본문을 싣는 것 자체가 규격 위반이다.
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return response
