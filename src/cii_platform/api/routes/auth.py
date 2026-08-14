"""인증 라우트 — login · callback · me · logout (#274, #275).

구글 OIDC Authorization Code + PKCE 플로우를 처리한다.
개발 환경에서는 ``auth_dev.py``의 스텁 경로가 별도로 등록된다 (#276).
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from cii_platform.api.error_handlers import to_error_response
from cii_platform.api.timefmt import iso_utc_now
from cii_platform.auth.dependencies import AuthenticationError
from cii_platform.auth.oidc import (
    build_auth_url,
    exchange_code,
    generate_nonce,
    generate_pkce_pair,
    generate_state,
    verify_id_token,
)
from cii_platform.auth.session import (
    COOKIE_ATTRIBUTES,
    SESSION_COOKIE_NAME,
    create_session_fields,
)
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.models.user_session import UserSession
from cii_platform.db.session import get_session
from cii_platform.services import audit as audit_svc

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """감사 로그용 클라이언트 IP — 미들웨어와 같은 정책으로 뽑는다 (#277).

    rate_limit와 달리 X-Forwarded-For는 신뢰하지 않고 직접 peer만 쓴다 —
    감사 기록의 주체는 정확해야 하고 위조 가능한 헤더에 의존하지 않는다.
    """
    return request.client.host if request.client else None


def _error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    """API_SPEC §1.3.2 형식의 오류 응답 — meta(request_id·timestamp)를 채운다.

    ``request.state``에 미들웨어가 주입한 값을 우선하되, 없으면 같은 포맷의
    헬퍼로 채운다 (``error_handlers``와 같은 정책).
    """
    state = getattr(request, "state", None)
    body = to_error_response(
        code,
        message,
        request_id=getattr(state, "request_id", None),
        timestamp=getattr(state, "timestamp", None) or iso_utc_now(),
    )
    return JSONResponse(status_code=status, content=body)


@router.get("/login")
async def login(
    redirect_to: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """구글 인증 화면으로 302 리다이렉트한다 (#274).

    ``redirect_to``는 앱 내부 경로만 허용한다 — 절대 URL은 거부한다 (open redirect 방어).
    """
    state = generate_state()
    verifier, challenge = generate_pkce_pair()
    nonce = generate_nonce()

    # redirect_to 검증 — 선행 슬래시 + //로 시작하지 않음
    safe_redirect = ""
    if redirect_to and redirect_to.startswith("/") and not redirect_to.startswith("//"):
        safe_redirect = redirect_to

    full_state = f"{state}:{safe_redirect}" if safe_redirect else state
    auth_url = build_auth_url(state=full_state, code_challenge=challenge, nonce=nonce)

    # state·code_verifier·nonce를 임시 저장 — MVP에서는 쿠키에 담는다 (짧은 TTL).
    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key="oidc_state",
        value=state,
        max_age=300,  # 5분
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key="oidc_verifier",
        value=verifier,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key="oidc_nonce",
        value=nonce,
        max_age=300,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/callback", response_model=None)
async def callback(
    request: Request,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,
) -> RedirectResponse | JSONResponse:
    """구글 콜백 — 토큰 교환 → 검증 → 사용자 upsert → 세션 발급 (#274)."""
    if code is None or state is None:
        return _error_response(request, 400, "BAD_REQUEST", "code와 state가 필요합니다.")

    # state 검증
    oidc_state_cookie = request.cookies.get("oidc_state", "")
    verifier = request.cookies.get("oidc_verifier", "")
    nonce_cookie = request.cookies.get("oidc_nonce", "")

    # state에서 원본 state와 redirect_to 분리
    parts = state.split(":", 1)
    raw_state = parts[0]
    redirect_to = parts[1] if len(parts) > 1 else ""

    if raw_state != oidc_state_cookie or not verifier:
        await audit_svc.record_login_failure(
            session, reason="state_mismatch", ip_address=_client_ip(request)
        )
        await session.commit()
        return _error_response(
            request, 401, "UNAUTHORIZED", "state 불일치 — 요청을 다시 시도하세요."
        )

    # 토큰 교환
    try:
        token_response = await exchange_code(code, verifier)
    except Exception as exc:
        # exc 문자열에는 토큰 응답 파편이 섞일 수 있어 details에는 넣지 않는다.
        await audit_svc.record_login_failure(
            session, reason="token_exchange_failed", ip_address=_client_ip(request)
        )
        await session.commit()
        return _error_response(request, 502, "BAD_REQUEST", f"토큰 교환 실패: {exc}")

    id_token = token_response.get("id_token")
    if id_token is None:
        return _error_response(request, 502, "BAD_REQUEST", "id_token이 응답에 없습니다.")

    # id_token 검증 — nonce까지 확인한다 (재생 공격 방지).
    try:
        payload = await verify_id_token(id_token, expected_nonce=nonce_cookie)
    except ValueError as exc:
        await audit_svc.record_login_failure(
            session,
            reason="id_token_verification_failed",
            ip_address=_client_ip(request),
        )
        await session.commit()
        return _error_response(request, 401, "UNAUTHORIZED", f"id_token 검증 실패: {exc}")

    google_sub = payload["sub"]
    email = payload.get("email", "")
    name = payload.get("name", "")

    # 사용자 upsert
    stmt = select(AppUser).where(
        AppUser.google_sub == google_sub,
        AppUser.is_deleted.is_(False),
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = AppUser(
            id=uuid4(),
            google_sub=google_sub,
            email=email,
            display_name=name,
        )
        session.add(user)
        await session.flush()
    else:
        user.email = email
        user.display_name = name or user.display_name

    # 세션 생성

    fields, session_token, csrf_token = create_session_fields(
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db_session = UserSession(**fields)
    session.add(db_session)
    # google_sub는 안정 식별자라 details에 둬도 안전하다 — id_token 원문·세션
    # 토큰은 자격 증명이므로 절대 기록하지 않는다(서비스 레이어 정책).
    await audit_svc.record_login_success(
        session,
        user_id=str(user.id),
        ip_address=_client_ip(request),
        details={"google_sub": google_sub},
    )
    await session.commit()

    # 쿠키 삭제 (oidc_state, oidc_verifier, oidc_nonce)
    is_safe_path = redirect_to.startswith("/") and not redirect_to.startswith("//")
    redirect_path = redirect_to if is_safe_path else "/"
    response = RedirectResponse(url=redirect_path, status_code=302)
    response.delete_cookie("oidc_state", path="/")
    response.delete_cookie("oidc_verifier", path="/")
    response.delete_cookie("oidc_nonce", path="/")

    # 세션 쿠키 설정
    response.set_cookie(key=SESSION_COOKIE_NAME, value=session_token, **COOKIE_ATTRIBUTES)
    response.set_cookie(
        key="csrf",
        value=csrf_token,
        httponly=False,
        secure=COOKIE_ATTRIBUTES["secure"],
        samesite=COOKIE_ATTRIBUTES["samesite"],
        path=COOKIE_ATTRIBUTES["path"],
    )
    return response


@router.get("/me")
async def me(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """현재 사용자 정보를 반환한다 (#274). ``google_sub``는 미노출."""
    user = getattr(request.state, "session_user", None)
    if user is None:
        raise AuthenticationError()

    return {
        "data": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", None),
            "timestamp": getattr(request.state, "timestamp", None) or iso_utc_now(),
        },
    }


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
    import datetime as dt

    from cii_platform.auth.session import hash_token

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
    response.delete_cookie("csrf", path="/")
    return response
