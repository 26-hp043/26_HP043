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
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from cii_platform.api.error_handlers import to_error_response
from cii_platform.api.schemas.auth import (
    LoginRequest,
    MeUpdateRequest,
    PasswordChangeRequest,
    RoleUpdateRequest,
    SignupRequest,
    TourLoginRequest,
)
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.backoff import backoff
from cii_platform.auth.dependencies import AuthenticationError, require_admin, require_csrf
from cii_platform.auth.password import (
    PasswordPolicyError,
    hash_password_async,
    validate_password,
    verify_dummy_async,
    verify_password_async,
)
from cii_platform.auth.role_bootstrap import is_initial_admin
from cii_platform.auth.session import (
    COOKIE_ATTRIBUTES,
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_session_fields,
    hash_token,
)
from cii_platform.auth.signup_gate import REJECTED_MESSAGE as SIGNUP_REJECTED_MESSAGE
from cii_platform.auth.signup_gate import load_signup_gate
from cii_platform.auth.tour_gate import REJECTED_MESSAGE as TOUR_REJECTED_MESSAGE
from cii_platform.auth.tour_gate import TOUR_USER_ID as _TOUR_USER_ID
from cii_platform.auth.tour_gate import tour_is_public, verify_tour_code
from cii_platform.config import public_base_url
from cii_platform.db.models.app_user import ROLE_ADMIN, ROLE_FIELD, AppUser
from cii_platform.db.models.user_session import UserSession
from cii_platform.db.models.user_token import PURPOSE_EMAIL_VERIFY
from cii_platform.db.repositories import chat as chat_repo
from cii_platform.db.session import get_session
from cii_platform.errors import NotFoundError
from cii_platform.mail import MailDeliveryError, get_mailer
from cii_platform.mail.templates import email_verification
from cii_platform.services import audit as audit_svc
from cii_platform.services.auth_token import issue_token, revoke_all_sessions

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: 로그인 실패 문구 — `PRD §6.3` 확정 원문.
#: **「없는 이메일」과 「비밀번호 불일치」에 같은 문구를 쓴다.**
LOGIN_FAILED_MESSAGE = "이메일 또는 비밀번호가 올바르지 않습니다."

#: 자격 증명이 틀렸다 — **세션 문제(`UNAUTHORIZED`)와 다른 코드**다 (`API_SPEC §1.4` · #902).
#:
#: 종전에는 로그인 실패와 현재 비밀번호 오입력이 세션 만료와 같은 `UNAUTHORIZED`였다. 정본은
#: 그 코드를 「세션 없음·만료·무효」로 좁혀 정의하고, 봉투가 같아 클라이언트는 문구를
#: 대조하거나(`#878` 전) 세션을 한 번 더 조회해야(`#878`) 두 사유를 갈랐다. 로그인 실패에도
#: 쓰지만 **없는 이메일과 틀린 비밀번호가 같은 코드·같은 문구**라 계정 존재 여부는 여전히
#: 드러나지 않는다(`§1.2`).
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"

#: 비밀번호 변경의 현재 비밀번호 오입력 문구.
CURRENT_PASSWORD_WRONG_MESSAGE = "현재 비밀번호가 올바르지 않습니다."

#: 회원가입 이메일 중복 문구 — `PRD §6.3` 확정 원문.
EMAIL_TAKEN_MESSAGE = "이미 가입된 이메일입니다. 로그인하거나 비밀번호를 찾아 주세요."

#
# 둘러보기 계정 (#1486) — 인터뷰·설문 대상자가 가입 없이 서비스를 보는 자리.
#
# 설계는 ``routes/auth_dev.py``의 스텁 계정을 그대로 따른다. 다른 점은 둘이다 —
# **환경과 무관하게 항상 등록**되고(그쪽은 ``development``·``test``에만 있다),
# 역할이 **관리자**다(그쪽은 사무직).
#

#: 둘러보기 계정의 고정 UUID.
#:
#: **고정 상수여야 한다** (`#308`이 dev-login에서 겪은 것과 같다) — ``uuid4()``를 모듈
#: 로드 시점에 평가하면 서버 재기동마다 PK가 달라져 기존 행을 못 찾고 INSERT를 시도하고,
#: ``email``이 같아 UNIQUE 위반으로 500이 난다.
#: 판정의 단일 출처는 :data:`~cii_platform.auth.tour_gate.TOUR_USER_ID`다 — 중앙 읽기 전용
#: 정책(`auth/tour_policy.py`)이 같은 값을 보며, 두 곳에 각자 적으면 한쪽만 바뀌는 날
#: 정책이 조용히 풀린다. 이름은 이 모듈이 쓰던 것을 유지한다.

_TOUR_EMAIL = "tour@bluelog.local"

_TOUR_DISPLAY_NAME = "둘러보기"

#: 둘러보기 계정의 비밀번호 해시 자리.
#:
#: **로그인에 쓸 수 없는 값을 넣는다.** Argon2 해시 형식이 아니므로 ``verify_password``가
#: 어떤 입력에도 ``False``를 돌려준다 — 이 계정이 ``POST /auth/login``으로도 열리면
#: **그 이메일이 알려진 순간 코드 없이 누구나 관리자가 된다.** 접근 코드를 두는 의미가
#: 사라지는 자리다(`auth_dev._STUB_PASSWORD_HASH`와 같은 판단).
_TOUR_PASSWORD_HASH = "!tour-no-password-login"

#: 둘러보기 계정의 이메일 인증 완료 시각 — **채운다.**
#:
#: 비워 두면 상단에 「이메일 인증이 완료되지 않았습니다」 배너가 계속 뜨고, 「인증 메일
#: 다시 받기」를 눌러도 ``@bluelog.local``이라 닿을 곳이 없다. 이 계정은 인증 흐름을
#: 보이려는 것이 아니라 **로그인 화면을 건너뛰기 위한 것**이다 (`#1293`과 같은 판단).
#:
#: 고정 시각이다 — 호출마다 ``now()``를 넣으면 행이 매번 바뀐다.
_TOUR_VERIFIED_AT = dt.datetime(2026, 9, 21, tzinfo=dt.UTC)

#: 마지막 관리자를 없애려 할 때의 문구 — `PRD §6.3` 확정 원문 (#672 · #1301).
#: 탈퇴(`DELETE /auth/me`)와 강등(`PATCH /auth/users/{id}/role`)이 같은 문구를 쓴다 —
#: 둘 다 「관리자 0명」으로 가는 길이고, 그 상태에서는 아무도 역할을 되돌릴 수 없다.
#:
#: `#1301` 이전에는 이 자리가 「마지막 사무직」이었다. 역할을 바꾸는 권한이 관리자로
#: 넘어가면서 **잠기는 조건도 함께 옮겨졌다** — 사무직이 0명이어도 관리자가 되돌릴 수 있다.
LAST_ADMIN_MESSAGE = (
    "마지막 관리자 계정은 탈퇴하거나 다른 역할로 바꿀 수 없습니다. "
    "다른 계정을 먼저 관리자로 지정해 주세요."
)

#: 없는 계정의 역할을 바꾸려 할 때.
USER_NOT_FOUND_MESSAGE = "계정을 찾을 수 없습니다."


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


def _error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, object]] | None = None,
) -> JSONResponse:
    """`API_SPEC §1.3.2` 형식의 오류 응답 — meta(request_id·timestamp)를 채운다."""
    state = getattr(request, "state", None)
    body = to_error_response(
        code,
        message,
        details=details,
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
        # 현장직·사무직·관리자 (#672 · #1301). 화면이 사이드바·버튼을 이 값으로 가른다 —
        # 서버가 403으로 막는 것과 별개로, 안 되는 것을 되는 것처럼 보이지 않게.
        "role": user.role,
        "email_verified_at": (
            user.email_verified_at.isoformat() if user.email_verified_at else None
        ),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


async def _lock_admin_users(session: AsyncSession) -> int:
    """살아 있는 **사람** 관리자 행을 **잠그고** 센다 (#672 · #1301 · #1486).

    「마지막 관리자」 판정은 세는 것과 바꾸는 것 사이에 다른 요청이 끼면 틀린다 — 관리자 둘이
    동시에 서로를 강등하면 둘 다 「하나 더 있다」를 보고 통과해 0명이 된다. 관리자 행 전부에
    ``FOR UPDATE``를 걸어 그 사이를 닫는다. 행은 몇 개 되지 않는다.

    ## 둘러보기 스텁은 세지 않는다 (#1486)

    그 계정도 ``ADMIN``이라 그냥 세면 **사람 관리자가 한 명뿐일 때도 「둘」로 읽혀** 강등·탈퇴가
    통과한다. 그런데 둘러보기는 ``TOUR_ACCESS_CODE``가 설정돼 있을 때만 들어갈 수 있는
    **런타임 설정**이다 — 인터뷰가 끝나 코드를 비우는 순간 그 관리자는 **닿을 수 없는 행**이
    되고, 계정 관리를 할 사람이 아무도 남지 않는다.

    이 가드가 막으려는 것은 「관리자 행이 0개인 상태」가 아니라 **「역할을 되돌릴 사람이
    없는 상태」**다. 그래서 사람 계정만 센다.
    """
    result = await session.execute(
        select(AppUser)
        .where(
            AppUser.role == ROLE_ADMIN,
            # `.is_(False)`는 `IS 0`을 내는데 CUBRID가 거부한다 — `== 0`으로 쓴다(#1316).
            AppUser.is_deleted == 0,
            AppUser.id != _TOUR_USER_ID,
        )
        .with_for_update()
    )
    return len(result.scalars().all())


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
    """세션 행을 만들고 ``(session_token, csrf_token)``을 돌려준다.

    ## 로그인 시각을 여기서 찍는다 (#1089)

    ``last_login_at``(`DB_SCHEMA §2.14` · `PRD §7.10` — 「마지막 로그인 시각」) 대입이
    **개발용 스텁(`auth_dev.py`)에만** 있어, 운영에서는 로그인을 아무리 해도 늘
    ``null``이었다. 그 값은 ``GET /auth/me`` 응답에 실린다(`API_SPEC §1.2`).

    라우트마다 대입을 흩어 두지 않고 **세션을 발급하는 이 한 곳**에 둔다 — 세션이
    생기는 순간이 곧 로그인한 순간이고, 다음 사람이 새 로그인 경로를 더해도 여기를
    지나므로 빠뜨릴 수 없다.

    **가입도 포함한다.** 가입은 즉시 로그인 상태가 되므로(위 :func:`signup`), 여기서
    찍지 않으면 **로그인해 있는 사용자가 「로그인한 적 없음」으로 보인다** — 「값이
    없다」와 「한 번도 없었다」를 같은 모양으로 그리는 자리가 된다.
    """
    user.last_login_at = dt.datetime.now(dt.UTC)
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

    # 가입 게이트 (#808) — 해싱보다 **먼저** 본다. 거절될 요청에 Argon2 한 번(약 60 ms ·
    # 64 MiB)을 쓰면 게이트가 비용 증폭기가 된다. 거절 문구는 어느 조건에서 떨어졌는지
    # 말하지 않는다(허용 도메인을 하나씩 캐낼 수 없게).
    if not load_signup_gate().allows(email, payload.invite_code):
        return _error_response(request, 422, "VALIDATION_ERROR", SIGNUP_REJECTED_MESSAGE)

    try:
        password_hash = await hash_password_async(payload.password)
    except PasswordPolicyError as exc:
        return _error_response(request, 422, "VALIDATION_ERROR", str(exc))

    # 중복 확인 — soft delete된 계정은 같은 이메일로 다시 가입할 수 있다.
    existing = await session.execute(
        select(AppUser).where(
            func.lower(AppUser.email) == email,
            AppUser.is_deleted == 0,
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
        # 새 계정은 현장직이다. 최초 관리자 목록(`INITIAL_ADMIN_EMAILS`)에 든 이메일만
        # 관리자로 시작한다 — 새 DB에서 관리자 0명이 되지 않게 (#672 · #1301).
        #
        # **가입 화면에서 역할을 고르게 하지 않는다.** 고르게 하면 가입 게이트만 통과한
        # 누구나 스스로 권한을 넓힐 수 있다(자기 신고) — 관리자가 올려 주는 지금 구조가
        # 그것을 막는다. 가입 시 선택은 `production` 전환·가입 게이트와 함께 본다.
        role=ROLE_ADMIN if is_initial_admin(email) else ROLE_FIELD,
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
                # 프론트엔드 라우트다 — API 주소를 그대로 쓰면 링크가 죽는다 (#429).
                verify_url=(
                    f"{public_base_url(str(request.base_url))}/verify-email?token={verify_token}"
                ),
            )
        )
    except MailDeliveryError:
        # `exception`으로 남긴다 — `warning`은 원인 예외(`__cause__`)를 버려, SMTP 비밀번호가
        # 만료돼도 로그에 「실패」만 남고 이유가 없었다 (#819).
        _log.exception("가입 확인 메일 발송 실패 — 계정은 생성됨: user_id=%s", user.id)

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

    # #1203 — 이메일별 실패 백오프. 지연은 계정 존재와 무관하게 이메일 문자열로만
    # 걸린다(존재 비노출). 지연 뒤에도 응답은 종전과 같은 401·같은 문구다.
    await backoff.wait(email)

    result = await session.execute(
        select(AppUser).where(
            func.lower(AppUser.email) == email,
            AppUser.is_deleted == 0,
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        # 즉시 거부하면 응답 시간 차이로 가입 여부를 알아낼 수 있다.
        # 결과를 쓰지 않는다 — 목적이 시간을 쓰는 것이다.
        await verify_dummy_async(payload.password)
        backoff.record_failure(email)
        await audit_svc.record_login_failure(
            session,
            reason="unknown_email",
            ip_address=_client_ip(request),
        )
        await session.commit()
        return _error_response(request, 401, INVALID_CREDENTIALS, LOGIN_FAILED_MESSAGE)

    if not await verify_password_async(payload.password, user.password_hash):
        backoff.record_failure(email)
        await audit_svc.record_login_failure(
            session,
            reason="bad_password",
            ip_address=_client_ip(request),
        )
        await session.commit()
        return _error_response(request, 401, INVALID_CREDENTIALS, LOGIN_FAILED_MESSAGE)

    # 성공은 백오프를 즉시 초기화한다 (#1203) — 다음 실패는 다시 5회 여유부터.
    backoff.record_success(email)

    # 최초 관리자 목록에 든 계정은 로그인할 때마다 관리자로 맞춘다 (#672 · #1301 ·
    # `auth/role_bootstrap.py`). 044 이전에 가입했든 화면에서 강등됐든 — 목록이 「항상
    # 관리자인 사람」이다. 실제로 바뀔 때만 감사 기록을 남긴다.
    if user.role != ROLE_ADMIN and is_initial_admin(email):
        await audit_svc.record_role_change(
            session,
            actor_user_id=str(user.id),
            target_user_id=user.id,
            role_before=user.role,
            role_after=ROLE_ADMIN,
            ip_address=_client_ip(request),
        )
        user.role = ROLE_ADMIN

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


@router.post("/tour-login")
async def tour_login(
    request: Request,
    payload: TourLoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """링크에 실린 접근 코드로 **둘러보기 관리자 세션**을 발급한다 (#1486).

    인터뷰·설문 대상자가 가입 없이 서비스를 보는 자리다. 문은 코드 하나로만 잠기며,
    **코드가 설정되지 않은 배포에서는 항상 거절한다**
    (:func:`~cii_platform.auth.tour_gate.verify_tour_code` — fail-closed).

    ## 왜 ``dev-login``이 아닌가

    그쪽은 ``development``·``test``에서만 **라우트가 등록된다**. 배포는 ``staging``이라
    교수님 링크에서는 401이 난다. 이 라우트는 환경 판정을 보지 않고 항상 등록된다 —
    잠그는 것은 환경이 아니라 코드다.

    ## 거절은 한 가지 모양이다

    「코드가 틀렸다」와 「기능이 꺼져 있다」를 **구분하지 않는다**. 구분하면 기능의 존재가
    새고, 맞히려는 사람에게 「거의 맞았다」는 신호를 준다
    (:data:`~cii_platform.auth.tour_gate.REJECTED_MESSAGE`).
    """
    # 공개 스위치(`TOUR_PUBLIC`)가 켜진 배포에서는 코드 없이도 들어온다 — 로그인 화면의
    # 상시 노출 버튼이 이 경로를 쓴다. **문만 넓어지고 권한은 그대로다**(둘러보기 세션은
    # `auth/tour_policy.py`가 읽기 전용으로 묶는다).
    if not (tour_is_public() or verify_tour_code(payload.code)):
        # 실패도 감사에 남긴다 — 공개 주소의 문이라 시도 자체가 신호다.
        # ⚠️ **코드 원문을 남기지 않는다**(`DB_SCHEMA` — 자격 증명 값은 기록하지 않는다).
        await audit_svc.record_login_failure(
            session,
            reason="tour_code_rejected",
            ip_address=_client_ip(request),
        )
        await session.commit()
        return _error_response(request, 422, "VALIDATION_ERROR", TOUR_REJECTED_MESSAGE)

    user = await session.get(AppUser, _TOUR_USER_ID)
    if user is None:
        # ⚠️ **동시 최초 로그인 경합** (#1495). 인터뷰는 여러 명이 같은 링크를 거의 동시에
        # 누른다. 행이 아직 없을 때 둘이 함께 들어오면 한쪽이 PK·UNIQUE 충돌로 500을 낸다 —
        # 한 번뿐이지만 **하필 처음 여는 순간**이라 눈에 띈다. 넣어 보고 걸리면 되돌려
        # 다시 읽는다(`_insert_ignoring_existing`이 시드에서 쓰는 것과 같은 판단).
        user = AppUser(
            id=_TOUR_USER_ID,
            email=_TOUR_EMAIL,
            password_hash=_TOUR_PASSWORD_HASH,
            display_name=_TOUR_DISPLAY_NAME,
            # 관리자다 — 인터뷰에서 연간 시뮬레이션·리포트·감축 계획을 지나야 하는데
            # 그 셋이 전부 사무직 이상 가드 뒤에 있다. 현장직으로 두면 **서비스의
            # 절반이 잠긴 화면**을 보여 주게 된다.
            role=ROLE_ADMIN,
            email_verified_at=_TOUR_VERIFIED_AT,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            # ⚠️ **동시 최초 로그인 경합** (#1495). 인터뷰는 여러 명이 같은 링크를 거의
            # 동시에 누른다. 행이 아직 없을 때 둘이 함께 들어오면 뒤쪽이 PK·UNIQUE 위반으로
            # 500을 낸다 — 한 번뿐이지만 **하필 처음 여는 순간**이라 눈에 띈다.
            #
            # 되돌리고 다시 읽는다. 이 시점에는 아직 아무것도 쓰지 않았으므로(감사 기록은
            # 아래에서 남긴다) 롤백으로 잃는 것이 없다.
            await session.rollback()
            user = await session.get(AppUser, _TOUR_USER_ID)
            if user is None:  # pragma: no cover - 충돌했는데 행이 없을 수는 없다
                raise

    #
    # 여기부터는 행이 **있다** — 방금 넣었든, 경합으로 남이 넣은 것을 읽었든.
    #
    # 복구를 `else`가 아니라 이 자리에 두는 이유 (#1495): 경합으로 남의 행을 읽은 경우에도
    # 그 행이 강등·탈퇴·해시 변경 상태일 수 있다. `else`에 두면 그 갈래만 건너뛴다.
    #

    # 누군가 화면에서 이 계정을 강등했더라도 되돌린다 — 다음 인터뷰가 조용히
    # 반쪽짜리가 되지 않게. `auth_dev`가 사무직을 되돌리는 것과 같은 자리다.
    if user.role != ROLE_ADMIN:
        user.role = ROLE_ADMIN
    if user.email_verified_at is None:
        user.email_verified_at = _TOUR_VERIFIED_AT
    # **탈퇴 상태도 되돌린다.** 둘러보기 세션은 관리자라 `DELETE /auth/me`를 누를 수
    # 있고, 그러면 이 행에 `is_deleted`가 선다. 그 상태를 그대로 두면 다음 사람이
    # **탈퇴한 계정으로 세션을 받는다** — 로그인 조회는 `is_deleted == 0`으로 거르는데
    # 여기는 PK로 직접 가져오므로 걸러지지 않는다. 지워진 계정이 살아 있는 세션을 갖는
    # 상태가 되어, 화면은 정상인데 다른 경로에서는 없는 사람이 된다.
    if user.is_deleted:
        user.is_deleted = False
    # **비밀번호 해시도 자리표시자로 되돌린다** (#1495).
    #
    # 이 계정은 Argon2 형식이 아닌 값을 넣어 `POST /auth/login`을 막아 둔다. 그런데
    # 비밀번호 재설정이 그 방어를 지울 수 있었다 — 그 경로는 `#1495`에서 막았지만,
    # **막기 전에 이미 바뀐 행**이 배포본에 남아 있을 수 있다. 여기서 되돌리면 그 행도
    # 다음 둘러보기 로그인에 스스로 낫는다.
    if user.password_hash != _TOUR_PASSWORD_HASH:
        user.password_hash = _TOUR_PASSWORD_HASH

    session_token, csrf_token = await _issue_session(session, request, user)
    # 일반 로그인과 **같은 이벤트 스트림**에 남기고 플래그로 가른다 — 둘러보기로 한
    # 조작을 추적할 수 있어야 한다 (`auth_dev`의 ``dev_login`` 플래그와 같은 판단).
    await audit_svc.record_login_success(
        session,
        user_id=str(user.id),
        ip_address=_client_ip(request),
        details={"tour": True},
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


#
# 계정 관리 (#506) — 로그인 상태에서 자기 계정을 다루는 경로.
#
# ## 왜 `request.state.session_user`를 그대로 쓰지 않는가
#
# 미들웨어(`auth/middleware.py:50`)는 **자기 세션**을 열어 사용자를 조회하고
# `request.state`에 넣은 뒤 그 세션을 닫는다. 그래서 그 객체는 **detached**다 —
# 어떤 세션도 관리하지 않는다.
#
# ORM은 「무엇이 바뀌었나」를 세션이 추적했다가 commit 때 UPDATE를 낸다. detached
# 객체의 속성을 바꾸고 라우트 세션으로 commit하면, **그 세션은 이 객체를 모르므로
# 바꿀 것이 없다고 판단하고 아무것도 쓰지 않는다.** 오류도 경고도 없이 200이 나가고
# 화면은 「저장됐습니다」를 보여 주는데 DB는 그대로다.
#
# `#279`가 `logout`에서 정확히 이것을 겪었다. 그래서 아래 세 라우트는 전부
# **라우트 세션으로 `AppUser`를 재조회**한 뒤 갱신한다.
#


async def _reload_user(session: AsyncSession, request: Request) -> AppUser | None:
    """인증된 사용자를 **라우트 세션으로 다시 읽는다** (위 주석 참조).

    미들웨어가 이미 인증을 끝냈으므로 여기서 다시 검증하지 않는다 — 다만 그 사이에
    탈퇴했을 수 있어 `is_deleted`는 다시 본다.
    """
    cached = getattr(request.state, "session_user", None)
    if cached is None:
        return None
    result = await session.execute(
        select(AppUser).where(AppUser.id == cached.id, AppUser.is_deleted == 0)
    )
    return result.scalar_one_or_none()


@router.post("/password-change")
async def change_password(
    request: Request,
    payload: PasswordChangeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    """현재 비밀번호를 확인하고 교체한 뒤 **기존 세션을 전부 무효화**한다.

    `API_SPEC §1.2` · `PRD §5.1`(계정 관리 MUST) · `#506`.

    ## 현재 비밀번호를 왜 다시 받는가

    로그인 상태라도 **세션이 탈취됐을 수 있다.** 확인 없이 바꿀 수 있으면 탈취한
    세션만으로 계정을 통째로 넘길 수 있다.

    ## 본인도 로그아웃된다

    재설정(`password-reset/confirm`)과 같은 규칙이다 — 탈취된 상태에서 비밀번호만
    바꾸면 공격자 세션이 살아 있으므로 **전부 끊는다.** 요청한 본인도 포함이며,
    응답 문구가 그 사실을 알린다(`PRD §6.3`).
    """
    user = await _reload_user(session, request)
    if user is None:
        raise AuthenticationError()

    # 현재 비밀번호가 틀리면 여기서 끝낸다. **새 비밀번호 정책 검사보다 먼저** 본다 —
    # 순서가 반대면 「현재 비밀번호가 틀렸는데 새 비밀번호 규칙만 알려 주는」 응답이 난다.
    if not await verify_password_async(payload.current_password, user.password_hash):
        # 칸을 짚는다 — 화면이 현재 비밀번호 입력칸에 붙인다(#877 `splitSubmitFailure`).
        return _error_response(
            request,
            401,
            INVALID_CREDENTIALS,
            CURRENT_PASSWORD_WRONG_MESSAGE,
            details=[
                {
                    "field": "current_password",
                    "field_label": "현재 비밀번호",
                    "message": CURRENT_PASSWORD_WRONG_MESSAGE,
                }
            ],
        )

    try:
        validate_password(payload.new_password)
        new_hash = await hash_password_async(payload.new_password)
    except PasswordPolicyError as exc:
        return _error_response(request, 422, "VALIDATION_ERROR", str(exc))

    user.password_hash = new_hash
    revoked = await revoke_all_sessions(session, user_id=user.id)
    await audit_svc.record_password_change(
        session,
        user_id=str(user.id),
        revoked_sessions=revoked,
        ip_address=_client_ip(request),
    )
    await session.commit()

    response = JSONResponse(
        content={
            "data": {
                "message": (
                    f"비밀번호가 변경되었습니다. 로그인된 기기 {revoked}대에서 로그아웃되었습니다."
                ),
                "revoked_sessions": revoked,
            },
            "meta": _meta(request),
        }
    )
    # 이 세션도 방금 무효화됐다. 쿠키를 남겨 두면 다음 요청이 401로 떨어지는데,
    # 사용자는 그것을 「오류」로 읽는다. 여기서 정리해 로그인 화면으로 자연히 간다.
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return response


@router.patch("/me")
async def update_me(
    request: Request,
    payload: MeUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    """표시 이름을 바꾼다 (`API_SPEC §1.2`, #506).

    ## `email`은 받지 않는다

    스키마가 `extra="forbid"`라 보내면 422다. 이메일은 로그인 ID이고 새 주소를 잘못
    입력하면 **계정에 접근할 수 없다** — 되돌릴 경로가 없으므로 변경 자체를 두지
    않는다(`PRD §6.3` 각주).

    ## 「보내지 않음」과 「`null`을 보냄」을 구분한다

    `display_name`을 지우는 것은 정당한 조작이다(가입에서도 선택 입력이다). 기본값
    `None`만 보고 판단하면 **둘을 구분할 수 없어 지울 방법이 사라진다.** `PATCH`의
    부분 갱신 규약(`API_SPEC §3.4` 「생략 = 변경 없음 · 명시적 null = 클리어」)을
    그대로 따른다.
    """
    user = await _reload_user(session, request)
    if user is None:
        raise AuthenticationError()

    if "display_name" in payload.model_fields_set:
        raw = payload.display_name
        trimmed = raw.strip() if raw is not None else None
        # 공백만 보낸 것은 지우려는 뜻으로 본다 — 공백뿐인 표시 이름은 화면에서
        # 이름이 없는 것과 구분되지 않는다.
        user.display_name = trimmed or None

    await session.commit()
    await session.refresh(user)
    return JSONResponse(content={"data": _user_payload(user), "meta": _meta(request)})


@router.delete("/me")
async def delete_me(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    """탈퇴 — soft delete 후 세션을 전부 무효화한다 (`API_SPEC §1.2`, #506).

    ## 행을 지우지 않는다 — 단, 대화는 지운다

    `app_user.is_deleted`를 세울 뿐이다. `calculation_run`은 immutable이고
    (`DB_SCHEMA §7.3`) `audit_log`는 보존 대상이라(`§7.1`) **그 사용자가 남긴
    계산·감사 기록은 그대로 남는다.** 규제 대응의 근거가 되는 기록이므로 지우지
    않는 것이 옳고, 탈퇴 확인 문구가 그 사실을 미리 알린다(`PRD §6.3`).

    **대화(`chat_session`·`chat_message`)는 예외다** (`#1330`). `PRD §16.3`이
    「GDPR 유사 삭제 요청 지원」을 적는데 **응할 경로가 없었다** — 탈퇴해도 그
    사용자의 대화 원문이 남았다. 대화는 규제 대응의 근거가 아니고 남겨 둘 이유가
    **보존 정책 90일뿐**인데, 탈퇴는 그 기간을 앞당기는 요청이다.

    ## 같은 이메일로 다시 가입할 수 있다

    `idx_app_user_email`이 `WHERE is_deleted = false`인 **부분 유일 인덱스**라
    (마이그레이션 033) 탈퇴한 계정의 이메일은 다시 쓸 수 있다. **이메일 변경 경로를
    두지 않는 대신 이 길을 연다.**

    ## 멱등이 아니다

    이미 탈퇴한 계정은 미들웨어가 `is_deleted`로 걸러 401을 낸다 — 여기까지 오지
    않는다.
    """
    user = await _reload_user(session, request)
    if user is None:
        raise AuthenticationError()

    # 마지막 관리자는 탈퇴할 수 없다 (#672 · #1301 · `API_SPEC §1.2`). 관리자 0명이 되면
    # 아무도 역할을 되돌릴 수 없다 — `#506`이 연 탈퇴 경로에 조건 하나를 더한다.
    # ⚠️ **둘러보기 스텁은 이 판정의 대상이 아니다** (#1495). 스텁은 계수에서 빠져 있으므로
    # (`_lock_admin_users`), 스텁 자신이 탈퇴할 때 사람 관리자가 한 명뿐이면 계수가 1이 되어
    # 「마지막 관리자라 탈퇴할 수 없다」로 막혔다 — **사실이 아니고**, 노출을 줄이려 스텁을
    # 지우려는 운영자를 막는다. 스텁이 사라져도 사람 관리자는 그대로다.
    if (
        user.role == ROLE_ADMIN
        and user.id != _TOUR_USER_ID
        and await _lock_admin_users(session) <= 1
    ):
        return _error_response(request, 409, "CONFLICT", LAST_ADMIN_MESSAGE)

    user.is_deleted = True
    revoked = await revoke_all_sessions(session, user_id=user.id)
    # `#1330` — 대화 **원문은 지운다.** `PRD §16.3`의 「GDPR 유사 삭제 요청 지원」이
    # 탈퇴에 걸리는 지점이다. 위 「행을 지우지 않는다」는 계산·감사 기록에 대한
    # 것이고, 대화 원문은 그 근거가 아니다 — 남겨 둘 이유가 보존 정책 90일뿐인데
    # 탈퇴는 그 기간을 앞당기는 요청이다.
    purged_chats = await chat_repo.delete_for_user(session, user_id=user.id)
    await audit_svc.record_account_delete(
        session,
        user_id=str(user.id),
        revoked_sessions=revoked,
        purged_chat_sessions=purged_chats,
        ip_address=_client_ip(request),
    )
    await session.commit()

    # 204 — 본문이 없다. 탈퇴한 사용자에게 돌려줄 사용자 정보가 없다.
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return response


#
# 계정 목록·역할 지정 (#672 · #1301) — **관리자만.**
#
# `UIFLOW 2-6` 설정 화면의 「계정 · 역할」 절이 부른다. 목록은 이메일 순이고 탈퇴 계정은
# 빼며, 비밀번호 해시는 `_user_payload`가 싣지 않는다. 역할 지정은 「누가 리포트·연간
# 시뮬레이션·계정 관리를 쓸 수 있나」를 바꾸는 일이라 감사 로그(`ROLE_CHANGE`)에 남는다.
#
# `#1301`이 이 둘을 사무직에서 관리자로 옮겼다 — 종전에는 사무직끼리 서로를 강등할 수
# 있었고 마지막 한 명만 보호됐다. 그래서 **이 파일에는 `require_office`가 걸린 라우트가
# 하나도 남지 않았다**(업무 경로는 vessels·fleet·reports 등 다른 라우터에 있다).
#


@router.get("/users")
async def list_users(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[None, Depends(require_admin)],
) -> dict[str, object]:
    """살아 있는 계정 전부 — **관리자 전용** (`API_SPEC §1.2`, #672 · #1301)."""
    result = await session.execute(
        select(AppUser).where(AppUser.is_deleted == 0).order_by(AppUser.email)
    )
    return {
        "data": [_user_payload(row) for row in result.scalars().all()],
        "meta": _meta(request),
    }


@router.patch("/users/{user_id}/role")
async def update_user_role(
    request: Request,
    user_id: UUID,
    payload: RoleUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
    _admin: Annotated[None, Depends(require_admin)],
) -> Response:
    """계정의 역할을 바꾼다 — **관리자 전용** (`API_SPEC §1.2`, #672 · #1301).

    ## 마지막 관리자는 강등할 수 없다

    자기 자신도 포함이다. 관리자가 둘이면 서로를 바꿀 수 있고, 하나면 그 하나는 다른 역할이
    될 수 없다 — 0명이 되면 아무도 되돌릴 수 없다. 판정은 관리자 행을 잠근 채 한다
    (``_lock_admin_users``).

    ## 같은 값이면 아무것도 쓰지 않는다

    감사 로그에 「OFFICE → OFFICE」가 쌓이면 실제 변경을 찾기 어려워진다. 200과 현재 상태만
    돌려준다.
    """
    actor = await _reload_user(session, request)
    if actor is None:
        raise AuthenticationError()

    result = await session.execute(
        select(AppUser).where(AppUser.id == user_id, AppUser.is_deleted == 0)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise NotFoundError(USER_NOT_FOUND_MESSAGE)

    before = target.role
    if before == payload.role:
        return JSONResponse(content={"data": _user_payload(target), "meta": _meta(request)})

    # 위 탈퇴와 같은 이유로 둘러보기 스텁은 대상이 아니다 (#1495).
    if (
        before == ROLE_ADMIN
        and target.id != _TOUR_USER_ID
        and await _lock_admin_users(session) <= 1
    ):
        return _error_response(request, 409, "CONFLICT", LAST_ADMIN_MESSAGE)

    target.role = payload.role
    await audit_svc.record_role_change(
        session,
        actor_user_id=str(actor.id),
        target_user_id=target.id,
        role_before=before,
        role_after=payload.role,
        ip_address=_client_ip(request),
    )
    await session.commit()
    await session.refresh(target)
    return JSONResponse(content={"data": _user_payload(target), "meta": _meta(request)})


@router.post("/logout")
async def logout(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    """세션을 즉시 무효화하고 쿠키를 만료시킨다 (`API_SPEC §1.2`).

    ``request.state.session_row``은 **미들웨어 세션에서 로드한 detached 객체**다 —
    속성만 바꿔 라우트 세션으로 commit하면 이 세션에 dirty 객체가 없어 아무것도
    쓰이지 않는다(무효화 누락). 라우트 세션으로 **재조회해** 갱신한다 (#279에서
    발견).

    ## CSRF를 검증한다 (#634)

    **세션을 요구하는 상태 변경 라우트 중 이 하나만 예외였다.** 다른 23개는 전부
    ``require_csrf``를 걸고, 검증이 없는 8개는 전부 세션이 없는 공개 인증 경로다.
    예외였던 동안 제3자 사이트가 사용자를 **강제 로그아웃**시킬 수 있었다 —
    데이터가 바뀌지 않아 심각도는 낮지만 규칙의 예외에 사유가 없었다.

    ## 「세션 없어도 204」가 아니다 (#634)

    ``API_SPEC §1.2``가 그렇게 적고 있었으나 **같은 행의 「인증 필요」와 모순**이고,
    그 문구는 `#272`(PR `#297`)에서 사유 없이 들어온 것이다. 세션이 없으면
    ``auth_middleware``가 라우트 앞에서 401로 끊으며, 그것이 「인증 필요」의 뜻이다.
    정본에서 그 문구를 뺐다.

    아래 ``token is not None`` · ``row is not None`` 두 갈래는 그래도 남긴다 —
    미들웨어 통과와 이 조회 사이에 세션이 무효화될 수 있고(동시 로그아웃·비밀번호
    변경), 그때 500을 내는 것보다 204가 옳다.
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
