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
from cii_platform.db.models.app_user import OFFICE_OR_ABOVE, ROLE_ADMIN, AppUser
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


#: 역할 거부 문구 — 사무직 권한이 필요한 경로 (`API_SPEC §1.4` · `PRD §6.3` 확정 원문).
#:
#: `#1301`이 「사무직 계정만」을 **「사무직 권한이 있는 계정만」**으로 고쳤다. 관리자도
#: 이 경로를 지나므로(상위집합) 종전 문구는 **사실과 달랐다** — 관리자가 막힌 줄 알고
#: 읽을 문구가 아니라, 권한이 모자란 현장직이 읽을 문구다.
OFFICE_ONLY_MESSAGE = "이 작업은 사무직 권한이 있는 계정만 할 수 있습니다."

#: 관리자 전용 거부 문구 (#1301 · `PRD §6.3` 확정 원문).
#:
#: **같은 `FORBIDDEN_ROLE` 코드에 문구만 다르다.** 코드를 또 가르지 않는 이유는 화면이
#: 할 일이 같기 때문이다 — 안내하고 끝낸다. 반면 문구가 같으면 사무직이 계정 관리에서
#: 막혔을 때 「사무직 계정만 할 수 있습니다」를 읽게 되어, **자기가 사무직인데** 그 말을
#: 듣는 상태가 된다.
ADMIN_ONLY_MESSAGE = "이 작업은 관리자 권한이 있는 계정만 할 수 있습니다."


class RoleForbiddenError(AppError):
    """역할이 허용하지 않는 작업 (API_SPEC §1.4). HTTP 403 · ``FORBIDDEN_ROLE`` (#672).

    CSRF와 **같은 403이지만 코드가 다르다.** 한 status가 두 원인을 가리키면 화면이 갈라 쓸 수
    없다 — CSRF는 토큰을 다시 실어 재시도할 일이고, 역할은 안내하고 끝낼 일이다.
    """

    def __init__(self, message: str = OFFICE_ONLY_MESSAGE):
        super().__init__("FORBIDDEN_ROLE", message)


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
        # 둘러보기 — 인터뷰·설문 대상자가 가입 없이 들어오는 문 (#1486). **환경과
        # 무관하게 항상 등록되고 접근 코드로만 잠긴다.** 그래서 `build_public_paths()`의
        # 인자를 늘리지 않고 여기(기본 목록)에 둔다 — 인자는 「환경에 따라 등록이 갈리는
        # 경로」를 위한 것이고, 판정이 갈리면 그 경로만 404가 되어 존재가 드러난다.
        "/api/v1/auth/tour-login",
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


#: 세션 실패 문구 — 미들웨어와 의존성이 **같은 한 벌**을 쓴다 (#1050).
SESSION_NOT_FOUND_MESSAGE = "세션을 찾을 수 없습니다."
SESSION_EXPIRED_MESSAGE = "로그인 세션이 만료되었습니다. 다시 로그인하세요."
USER_NOT_FOUND_MESSAGE = "사용자 계정을 찾을 수 없습니다."


async def resolve_session(request: Request) -> AppUser:
    """쿠키 → 토큰 해시 → 세션 행 → 만료·폐기 판정 → 사용자 조회 — **세션 검증의 유일한 한 벌**
    (#1050).

    ## 왜 한 곳인가

    종전에는 이 다섯 단계가 ``auth_middleware``와 ``get_current_user``에 **두 벌** 있었고,
    미들웨어가 모든 비공개 경로에서 먼저 돌아 ``request.state.session_user``를 채우므로 의존성
    쪽 본문은 **운영에서 한 번도 실행되지 않았다**(`#955` 커버리지 하한이 드러낸 공백). 갈려도
    증상이 없다가, 미들웨어 배선이 바뀌는 날 갈린 쪽이 판정을 맡는다. 지금은 미들웨어도
    의존성도 이 함수를 부른다.

    결과는 ``request.state``에 캐시한다 — 같은 요청에서 두 번째 호출은 DB를 다시 읽지 않는다.
    DB 세션은 내부에서 ``get_sessionmaker()``로 만든다(미들웨어에는 의존성 주입이 없다).

    :raises AuthenticationError: 쿠키 없음 · 세션 없음 · 만료 · 폐기 · 삭제된 계정. 문구는
        분기마다 다르고(`API_SPEC §1.4` ``UNAUTHORIZED``), 미들웨어는 그 문구를 그대로 401
        응답에 싣는다.
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
            raise AuthenticationError(SESSION_NOT_FOUND_MESSAGE)
        if not is_valid(user_session.expires_at, user_session.revoked_at):
            raise AuthenticationError(SESSION_EXPIRED_MESSAGE)

        user_stmt = select(AppUser).where(
            AppUser.id == user_session.user_id,
            AppUser.is_deleted == 0,
        )
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if user is None:
            raise AuthenticationError(USER_NOT_FOUND_MESSAGE)

        request.state.session_user = user
        request.state.session_row = user_session
        return user


async def get_current_user(request: Request) -> AppUser:
    """현재 인증된 사용자를 반환한다. 미인증 시 ``AuthenticationError``.

    ``Depends(get_current_user)``로 라우트에 직접 걸 수 있다 (#315). 판정은
    :func:`resolve_session` 한 벌이다 (#1050) — 비공개 경로에서는 미들웨어가 이미 채운 캐시를
    돌려주고, 공개 경로에 걸면 여기서 쿠키를 읽어 같은 규칙으로 판정한다.
    """
    return await resolve_session(request)


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


def require_office(request: Request) -> None:
    """사무직 **이상**만 지나가는 라우트에 건다 (#672 · #1301 · `API_SPEC §1.2` 역할 표).

    ``Depends(require_office)``로 ``require_csrf`` 옆에 둔다. 미들웨어가 채운
    ``request.state.session_user``의 ``role``만 본다 — DB를 다시 읽지 않는다.

    **관리자도 통과한다** (#1301). ``ADMIN``은 ``OFFICE``의 상위집합이라 업무 경로를 함께
    쓴다 — 판정을 :data:`~cii_platform.db.models.app_user.OFFICE_OR_ABOVE` 하나로 두는 것은
    ``role == ROLE_OFFICE`` 비교가 흩어지면 **한 곳을 빠뜨려도 조용히** 통과하거나 막히기
    때문이다. 이름을 ``require_office``로 두는 것은 정본의 표 이름(「사무직 전용 경로」)과
    ``tests/test_roles_db.py``의 소스 대조가 이 이름을 쓰기 때문이다.

    **fail-closed** — 사용자가 없으면(배선 어김) 통과시키지 않고 ``AuthenticationError``다.
    ``require_csrf``가 ``session_row``에 대해 같은 판단을 한다(#311).

    어느 라우트에 걸리는가는 ``API_SPEC §1.2``의 역할 표가 정하고,
    ``tests/test_roles_db.py``가 소스와 대조한다 — 한쪽만 바뀌면 거기서 걸린다.
    """
    user = getattr(request.state, "session_user", None)
    if user is None:
        raise AuthenticationError()
    if getattr(user, "role", None) not in OFFICE_OR_ABOVE:
        raise RoleForbiddenError()


def require_admin(request: Request) -> None:
    """관리자만 지나가는 라우트에 건다 (#1301 · `API_SPEC §1.2` 「관리자 전용 경로」).

    지금 걸리는 곳은 **계정 관리 둘**이다 — ``GET /auth/users`` · ``PATCH
    /auth/users/{id}/role``.

    ## 왜 사무직에서 떼어냈나

    종전에는 사무직이 전 계정의 역할을 바꿀 수 있었고, 그래서 **사무직끼리 서로를 강등할 수
    있었다**(마지막 한 명만 `409`로 보호됐다). 계정을 건드리는 권한을 한 곳으로 모으면 그
    경로가 사라진다. 업무 권한(제원·시뮬레이션·리포트·감축 계획)은 사무직에 그대로 남는다.

    :func:`require_office`와 **같은 fail-closed** 규율이고 같은 ``FORBIDDEN_ROLE`` 코드를
    쓴다. 문구만 다르다(:data:`ADMIN_ONLY_MESSAGE`) — 사무직이 여기서 막혔을 때 「사무직
    계정만 할 수 있습니다」를 읽으면 **자기가 사무직인데** 그 말을 듣는 상태가 된다.
    """
    user = getattr(request.state, "session_user", None)
    if user is None:
        raise AuthenticationError()
    if getattr(user, "role", None) != ROLE_ADMIN:
        raise RoleForbiddenError(ADMIN_ONLY_MESSAGE)
