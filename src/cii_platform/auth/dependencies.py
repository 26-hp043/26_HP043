"""FastAPI 인증 의존성 — 현재 사용자 주입 + CSRF 검증 (#275).

라우트는 이 모듈만 참조한다 (TECH_SPEC §16 계층 규칙).
``auth/session.py``의 세션 로직과 ``db/repositories``를 경유해 DB에 접근한다.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import select

from cii_platform.auth.session import (
    SESSION_COOKIE_NAME,
    hash_token,
    is_valid,
    verify_csrf,
)
from cii_platform.config import should_expose_api_docs, should_expose_dev_auth
from cii_platform.db.models.app_user import AppUser
from cii_platform.db.models.user_session import UserSession
from cii_platform.db.session import get_sessionmaker
from cii_platform.errors import AppError


class AuthenticationError(AppError):
    """세션 없음·만료·무효 (API_SPEC §1.4). HTTP 401."""

    def __init__(self, message: str = "인증이 필요합니다."):
        super().__init__("UNAUTHORIZED", message)


class CsrfError(AppError):
    """CSRF 토큰 누락·불일치 (API_SPEC §1.4). HTTP 403."""

    def __init__(self, message: str = "CSRF 토큰이 올바르지 않습니다."):
        super().__init__("CSRF_ERROR", message)


#: OpenAPI 문서 경로. **프로덕션에서는 공개 경로에 넣지 않는다** (#593).
#:
#: 라우트를 등록하지 않는 것만으로도 404가 되지만, 그것만 하면 **``/docs``만 404이고
#: 나머지 미등록 경로는 401**이 된다 — ``is_public_path()``가 완전일치 허용 목록이라
#: 목록에 없는 경로는 라우팅 전에 401로 끊기기 때문이다. 그 차이 자체가 「여기에
#: 무언가 있다」는 신호가 되므로, 두 곳을 같은 판정으로 묶어 **다른 미등록 경로와
#: 똑같이 401**로 보이게 한다.
_DOCS_PATHS: frozenset[str] = frozenset({"/docs", "/openapi.json", "/redoc"})

#: 개발 환경 스텁 인증 (#276). **프로덕션에서는 라우트 자체가 등록되지 않으므로**
#: 공개 경로에서도 함께 뺀다 (#648).
#:
#: 종전에는 환경과 무관하게 남아 있어, 프로덕션에서 **이 경로만 404**였다 —
#: 목록에 있으면 미들웨어를 통과하고 라우트가 없어 404가 되는데, 다른 미등록 경로는
#: 라우팅 전에 401로 끊긴다. `#593`이 ``/docs``에서 없앤 것과 같은 신호다.
_DEV_AUTH_PATHS: frozenset[str] = frozenset({"/api/v1/auth/dev-login"})

#: 환경과 무관하게 인증이 필요 없는 경로 (API_SPEC §1.2).
#:
#: **전부 ``/api/v1`` prefix를 단다.** 종전에는 접두사 없는 사본 8개
#: (``/health``·``/auth/login`` 등)가 함께 있었는데, ``is_public_path()``의 주석이
#: 스스로 *「실제 요청 경로는 항상 ``/api/v1`` prefix를 달고 나온다」*고 적고 있어
#: **영원히 매치되지 않는 항목**이었다. 허용 목록만 넓히고 아무 일도 하지 않는다 (#648).
_BASE_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/health",
        # 인증 플로우 자체 — 세션 없이 접근해야 한다 (`API_SPEC §1.2`).
        "/api/v1/auth/signup",
        "/api/v1/auth/login",
        # 메일 링크로 진입하므로 세션이 없다 (#408 · `API_SPEC §1.2`).
        "/api/v1/auth/verify-email/request",
        "/api/v1/auth/verify-email/confirm",
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/confirm",
    }
)


def build_public_paths(*, expose_docs: bool, expose_dev_auth: bool) -> frozenset[str]:
    """공개 경로 목록을 만든다 (#593 · #648).

    **환경에 따라 라우트가 등록되지 않는 경로는 목록에서도 뺀다.** 두 판정이 갈리면
    그 경로만 404가 되고, 그 차이가 「여기에 무언가 있다」는 신호가 된다.

    **인자를 받는 이유는 검증 때문이다.** ``PUBLIC_PATHS``는 import 시점에 확정되므로
    나중에 환경변수를 바꿔도 달라지지 않는다 — 순수 함수로 갈라 두면 두 환경의 결과를
    프로세스 하나에서 대조할 수 있다.
    """
    paths = _BASE_PUBLIC_PATHS
    if expose_docs:
        paths |= _DOCS_PATHS
    if expose_dev_auth:
        paths |= _DEV_AUTH_PATHS
    return paths


PUBLIC_PATHS: frozenset[str] = build_public_paths(
    expose_docs=should_expose_api_docs(),
    expose_dev_auth=should_expose_dev_auth(),
)

#: CSRF 검증이 필요 없는 메서드.
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})


def is_public_path(path: str) -> bool:
    """경로가 인증 예외인지 확인한다 — **명시적 목록만** 쓴다 (#308).

    ``startswith("/auth/")`` 같은 접두사 규칙을 쓰지 않는 이유: 실제 요청 경로는
    항상 ``/api/v1`` prefix를 달고 나오므로 접두사가 실효 없었고, 향후 auth 하위에
    보호가 필요한 엔드포인트가 추가될 때 실수로 공개될 위험만 남는다. 공개 경로는
    이 목록에만 추가한다.

    **그 「항상 ``/api/v1``」이 목록에도 적용된다 (#648).** 종전에는 접두사 없는 사본
    8개가 함께 있었는데 같은 이유로 **영원히 매치되지 않았다.** 목록에 있는 경로가
    전부 실제 라우트인지는 ``tests/test_docs_exposure.py``의 불변식 테스트가 본다.
    """
    return path in PUBLIC_PATHS


async def get_current_user(request: Request) -> AppUser:
    """현재 인증된 사용자를 반환한다. 미인증 시 ``AuthenticationError``.

    ``Depends(get_current_user)``로 라우트에 직접 걸 수 있다 (#315) — 세션이
    없으면 ``request.state.session_user`` 캐시 확인 → 쿠키 검증 → DB 조회 순으로
    진행하며, DB 세션은 내부에서 ``get_sessionmaker()``로 만든다(auth_middleware와
    같은 패턴). 같은 요청에서 두 번째 호출은 DB 조회 없이 캐시된 값을 돌려준다.
    """
    cached = getattr(request.state, "session_user", None)
    if cached is not None:
        return cached

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        raise AuthenticationError()

    token_hash = hash_token(token)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        stmt = select(UserSession).where(
            UserSession.session_token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
        result = await session.execute(stmt)
        user_session = result.scalar_one_or_none()

        if user_session is None:
            raise AuthenticationError("세션을 찾을 수 없습니다.")
        if not is_valid(user_session.expires_at, user_session.revoked_at):
            raise AuthenticationError("로그인 세션이 만료되었습니다. 다시 로그인하세요.")

        user_stmt = select(AppUser).where(
            AppUser.id == user_session.user_id,
            AppUser.is_deleted.is_(False),
        )
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if user is None:
            raise AuthenticationError("사용자 계정을 찾을 수 없습니다.")

        request.state.session_user = user
        request.state.session_row = user_session
        return user


def require_csrf(
    request: Request,
) -> None:
    """상태 변경 요청(POST·PATCH·DELETE)에서 CSRF 토큰을 검증한다.

    ``X-CSRF-Token`` 헤더와 세션에 저장된 ``csrf_token_hash``를 비교한다.
    CSRF 토큰 원문은 쿠키로도 전달되지만, **헤더로만** 검증한다 —
    쿠키는 자동으로 전송되므로 공격자가 임의의 값을 넣을 수 있다.

    **fail-closed (#311)** — ``session_row``가 없으면(인증 미들웨어가 배선되지
    않았거나 실행 순서가 어긋난 상태) 요청을 통과시키지 않고 ``AuthenticationError``
    를 낸다. CSRF 가드는 상태를 확신할 수 없을 때 막는 쪽이어야 한다.
    """
    if request.method in SAFE_METHODS:
        return

    user_session = getattr(request.state, "session_row", None)
    if user_session is None:
        raise AuthenticationError()

    csrf_header = request.headers.get("x-csrf-token")
    if csrf_header is None:
        raise CsrfError("CSRF 토큰이 누락되었습니다.")
    if not verify_csrf(csrf_header, user_session.csrf_token_hash):
        raise CsrfError("CSRF 토큰이 올바르지 않습니다.")
