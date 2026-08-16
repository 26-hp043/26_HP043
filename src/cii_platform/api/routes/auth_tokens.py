"""이메일 인증·비밀번호 재설정 라우트 (`API_SPEC §1.2`, #408).

`#414`가 만든 가입·로그인 위에, `#407`의 메일 발송을 써서 **일회용 토큰 플로우**를
붙인다.

## 계정 존재 여부를 노출하지 않는다

`POST /auth/password-reset/request`는 **가입 여부와 무관하게 같은 응답**을 낸다.
「가입되지 않은 이메일입니다」를 내면 **가입자 목록을 캐낼 수 있다**
(`API_SPEC §1.2` · `PRD §6.3`).

없는 계정에도 **메일을 보내지 않을 뿐 응답은 같다.** 존재 확인이 목적인 요청에
아무 정보도 주지 않는다.

## 메일 실패로 요청을 되돌리지 않는다

`#407`이 세운 경계다. 토큰은 커밋하고 메일 발송은 그 뒤에 시도한다 — 실패해도
사용자는 재발송을 누를 수 있고, 되돌리면 「토큰도 없고 메일도 없는」 상태가 된다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from cii_platform.api.error_handlers import to_error_response
from cii_platform.api.schemas.auth_tokens import (
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    VerifyEmailConfirmRequest,
    VerifyEmailRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.password import PasswordPolicyError, hash_password
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.models.user_token import (
    PURPOSE_EMAIL_VERIFY,
    PURPOSE_PASSWORD_RESET,
)
from cii_platform.db.session import get_session
from cii_platform.mail import MailDeliveryError, get_mailer
from cii_platform.mail.templates import email_verification, password_reset
from cii_platform.services import audit as audit_svc
from cii_platform.services.auth_token import (
    TokenError,
    consume_token,
    issue_token,
    revoke_all_sessions,
)

router = APIRouter(prefix="/auth", tags=["auth"])

#: 재설정 요청 결과 문구 — `PRD §6.3` 확정 원문.
#: **가입 여부와 무관하게 이 문구 하나만 쓴다.**
RESET_REQUESTED_MESSAGE = (
    "입력하신 주소로 재설정 안내를 보냈습니다. 메일이 오지 않으면 스팸함을 확인해 주세요."
)

#: 토큰 만료·사용됨 문구 — `PRD §6.3` 확정 원문.
TOKEN_INVALID_MESSAGE = "링크가 만료되었거나 이미 사용되었습니다. 다시 요청해 주세요."

#: 메일 발송 실패 안내. 계정·토큰은 만들어졌으므로 재발송을 권한다.
MAIL_FAILED_MESSAGE = "메일이 발송되지 않았습니다. 잠시 후 재발송해 주세요."


def _meta(request: Request) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


def _error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    state = getattr(request, "state", None)
    return JSONResponse(
        status_code=status,
        content=to_error_response(
            code,
            message,
            request_id=getattr(state, "request_id", None),
            timestamp=getattr(state, "timestamp", None) or iso_utc_now(),
        ),
    )


def _ok(request: Request, message: str) -> JSONResponse:
    return JSONResponse(content={"data": {"message": message}, "meta": _meta(request)})


async def _find_active_user(session: AsyncSession, email: str) -> AppUser | None:
    result = await session.execute(
        select(AppUser).where(
            func.lower(AppUser.email) == email.strip().lower(),
            AppUser.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


def _build_url(request: Request, path: str, token: str) -> str:
    """메일에 실을 링크.

    요청의 base URL을 쓴다 — 배포 환경마다 도메인이 다르고, 설정으로 따로 두면
    그 값이 실제 서비스 주소와 어긋났을 때 **링크가 조용히 죽는다.**
    """
    base = str(request.base_url).rstrip("/")
    return f"{base}{path}?token={token}"


@router.post("/verify-email/request")
async def request_email_verification(
    request: Request,
    payload: VerifyEmailRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """인증 메일을 재발송한다.

    가입 직후 자동 발송된 메일이 오지 않았을 때 쓴다. **계정이 없어도 같은 응답**을
    낸다 — 존재 확인 수단이 되면 안 된다.
    """
    user = await _find_active_user(session, payload.email)

    if user is None or user.email_verified_at is not None:
        # 이미 인증됐거나 없는 계정 — 아무것도 하지 않되 응답은 같다.
        return _ok(request, RESET_REQUESTED_MESSAGE)

    raw = await issue_token(session, user_id=user.id, purpose=PURPOSE_EMAIL_VERIFY)
    await session.commit()

    try:
        await get_mailer().send(
            email_verification(
                to=user.email,
                verify_url=_build_url(request, "/verify-email", raw),
            )
        )
    except MailDeliveryError:
        # 토큰은 이미 커밋됐다 — 되돌리지 않는다(#407 경계).
        return _error(request, 502, "INTERNAL_ERROR", MAIL_FAILED_MESSAGE)

    return _ok(request, RESET_REQUESTED_MESSAGE)


@router.post("/verify-email/confirm")
async def confirm_email_verification(
    request: Request,
    payload: VerifyEmailConfirmRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """토큰을 검증하고 `email_verified_at`을 기록한다."""
    try:
        user_id = await consume_token(session, raw=payload.token, purpose=PURPOSE_EMAIL_VERIFY)
    except TokenError:
        await session.rollback()
        return _error(request, 400, "VALIDATION_ERROR", TOKEN_INVALID_MESSAGE)

    user = await session.get(AppUser, user_id)
    if user is None:
        await session.rollback()
        return _error(request, 400, "VALIDATION_ERROR", TOKEN_INVALID_MESSAGE)

    import datetime as dt

    user.email_verified_at = dt.datetime.now(dt.UTC)
    await session.commit()

    return _ok(request, "이메일 인증이 완료되었습니다.")


@router.post("/password-reset/request")
async def request_password_reset(
    request: Request,
    payload: PasswordResetRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """재설정 메일을 보낸다.

    **가입 여부와 무관하게 같은 응답**을 낸다. 「가입되지 않은 이메일입니다」를 내면
    가입자 목록을 캐낼 수 있다.
    """
    user = await _find_active_user(session, payload.email)

    if user is None:
        # 메일을 보내지 않을 뿐 응답은 같다.
        return _ok(request, RESET_REQUESTED_MESSAGE)

    raw = await issue_token(session, user_id=user.id, purpose=PURPOSE_PASSWORD_RESET)
    await session.commit()

    try:
        await get_mailer().send(
            password_reset(
                to=user.email,
                reset_url=_build_url(request, "/password-reset", raw),
            )
        )
    except MailDeliveryError:
        return _error(request, 502, "INTERNAL_ERROR", MAIL_FAILED_MESSAGE)

    return _ok(request, RESET_REQUESTED_MESSAGE)


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    request: Request,
    payload: PasswordResetConfirmRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """토큰을 검증하고 비밀번호를 교체한 뒤 **기존 세션을 전부 무효화**한다."""
    try:
        new_hash = hash_password(payload.password)
    except PasswordPolicyError as exc:
        return _error(request, 422, "VALIDATION_ERROR", str(exc))

    try:
        user_id = await consume_token(session, raw=payload.token, purpose=PURPOSE_PASSWORD_RESET)
    except TokenError:
        await session.rollback()
        return _error(request, 400, "VALIDATION_ERROR", TOKEN_INVALID_MESSAGE)

    user = await session.get(AppUser, user_id)
    if user is None:
        await session.rollback()
        return _error(request, 400, "VALIDATION_ERROR", TOKEN_INVALID_MESSAGE)

    user.password_hash = new_hash

    #
    # 기존 세션 전량 무효화 — `API_SPEC §1.2`.
    #
    # **탈취된 상태에서 비밀번호만 바꾸면 공격자 세션이 그대로 살아 있다.**
    # 재설정의 목적이 바로 그 세션을 끊는 것이다.
    #
    revoked = await revoke_all_sessions(session, user_id=user_id)

    await audit_svc.record_logout(
        session,
        user_id=str(user_id),
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()

    return _ok(
        request,
        f"비밀번호가 변경되었습니다. 로그인된 기기 {revoked}대에서 로그아웃되었습니다.",
    )
