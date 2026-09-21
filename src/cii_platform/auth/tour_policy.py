"""둘러보기 세션의 권한 정책 — 읽기 전용 (#1486 후속).

## 왜 중앙에서 막는가

둘러보기 계정은 **관리자**다. 연간 시뮬레이션·리포트·감축 계획이 전부 사무직 이상 가드
뒤에 있어, 현장직으로 두면 서비스의 절반이 잠긴 화면을 보여 주게 되기 때문이다
(`routes/auth.py`의 계정 생성부 주석).

그 권한 그대로 **문을 공개로 열면**(`TOUR_PUBLIC`) 인터넷의 누구나 공유 데모 자료를
고치거나 지울 수 있고, 관리자 전용 조회로 **실제 가입자 이메일**까지 볼 수 있다. 데이터
격리는 범위 밖이므로(`PRD §5.2`) 계정을 방문자마다 따로 만들어도 이 문제는 그대로다 —
막아야 하는 것은 계정 수가 아니라 **쓰기와 민감 조회**다.

## 라우트마다 거는 대신 미들웨어에서 거는 이유

이 저장소의 인증 게이트는 라우트 의존성이 아니라
:func:`~cii_platform.auth.middleware.auth_middleware` **한 곳**이다.
쓰기 라우트 상당수는 ``get_current_user``를 주입받지 않고 미들웨어가 채운
``request.state.session_user``에 기대며, `vessels.py`의 쓰기 라우트는 ``require_csrf``만
달고 있다. 그래서 의존성으로 걸면 **새 라우트가 늘 때마다 빠진다** — 그 누락은 실패가
아니라 **조용한 통과**로 나타난다.

## 무엇을 막는가

| 갈래 | 판정 |
|---|---|
| ``GET`` · ``HEAD`` · ``OPTIONS`` | 통과 — 둘러보기의 목적이 열람이다 |
| 그 밖의 메서드 | **403** — 생성·수정·삭제·계산 실행이 모두 여기 든다 |
| 민감 조회(:data:`DENY_PREFIXES`) | **403** — 메서드와 무관하다. ``GET``이라고 안전한 것이 아니다 |
| ``POST /auth/logout`` | 통과 — 자기 세션 한 줄만 닫는다 |

계산 실행(``POST /calculations/…``)까지 막히는 것은 **의도**다. 열람 범위를 넓혀야 하면
그때 경로를 하나씩 명시 허용하고 비용 한도를 함께 정한다 — 메서드를 통째로 여는 반대
방향은 이 정책이 막으려던 것을 되돌린다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.auth.tour_gate import TOUR_USER_ID

if TYPE_CHECKING:
    from cii_platform.db.models.app_user import AppUser

#: 상태를 바꾸지 않는 메서드. 둘러보기는 이것만 통과한다.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: 메서드와 무관하게 막는 경로.
#:
#: * ``/auth/users`` — 계정 관리 목록. **실제 가입자의 이메일**이 실린다
#: * ``/audit-logs`` — 감사 기록. 이메일·IP·행동 이력이 섞인다
#:
#: 공개 데모에 관리자 세션을 여는 이상, 이 둘은 「읽기」라서 안전한 축에 들지 않는다.
DENY_PREFIXES = ("/api/v1/auth/users", "/api/v1/audit-logs")

#: 안전하지 않은 메서드지만 허용하는 경로 — **자기 세션을 닫는 것**뿐이다.
#:
#: 로그아웃은 세션 한 줄을 폐기한다(계정이 아니라). 막으면 둘러보던 사람이 나가지 못하고,
#: 공유 계정이라 다음 방문자가 남의 세션을 그대로 물려받는다.
ALLOW_UNSAFE_PATHS = ("/api/v1/auth/logout",)

#: 쓰기를 시도했을 때의 문구. **무엇을 해야 하는지**까지 말한다 (`PRD §6.4` 상태 문구).
READ_ONLY_MESSAGE = (
    "둘러보기에서는 자료를 바꿀 수 없습니다. 직접 입력해 보시려면 계정을 만들어 주세요."
)

#: 민감 조회를 시도했을 때의 문구.
DENIED_MESSAGE = "둘러보기에서는 열람할 수 없는 화면입니다."


def is_tour_user(user: AppUser | None) -> bool:
    """이 요청의 주체가 둘러보기 계정인가.

    판정 기준은 **고정 id**다(:data:`~cii_platform.auth.tour_gate.TOUR_USER_ID`).
    이메일로 판정하면 표시명·주소를 바꾸는 날 정책이 조용히 풀린다.
    """
    return user is not None and user.id == TOUR_USER_ID


def tour_denial_reason(method: str, path: str) -> str | None:
    """둘러보기에게 이 요청을 거절할 이유. 허용이면 ``None``.

    순서가 중요하다 — **민감 경로를 먼저 본다.** 메서드부터 보면 ``GET /auth/users``가
    안전 메서드라는 이유로 통과한다.
    """
    if path.startswith(DENY_PREFIXES):
        return DENIED_MESSAGE
    if path in ALLOW_UNSAFE_PATHS:
        return None
    if method.upper() in SAFE_METHODS:
        return None
    return READ_ONLY_MESSAGE
