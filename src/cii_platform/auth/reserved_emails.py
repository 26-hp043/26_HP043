"""예약 주소 — 코드가 고정 계정에 쓰는 이메일 (#2109).

둘러보기(``POST /auth/tour-login``)와 개발 스텁(``POST /auth/dev-login``)은 **고정 PK와
고정 이메일**로 계정 한 행을 만든다. 누군가 그 이메일로 먼저 가입하면 활성 이메일의
유니크 인덱스(``uq_app_user_email_active``)가 고정 PK의 INSERT를 막아, 두 경로가 그
배포에서 열리지 않는다.

## 목록은 여기 한 곳이다

가입(거부)과 두 스텁 경로(계정 생성)가 **같은 상수**를 본다. 각자 적으면 한쪽 주소만
바뀌는 날 가입이 옛 주소를 막고 새 주소는 열어 둔다.

## 넣지 않는 것

- **최초 관리자 이메일**(``INITIAL_ADMIN_EMAILS``) — 그 주소는 사람이 가입해야 하는
  주소다. 예약의 뜻(「아무도 가입할 수 없다」)과 반대다.
"""

from __future__ import annotations

#: 둘러보기 계정의 이메일 (`API_SPEC §1.2` 「둘러보기」).
TOUR_EMAIL = "tour@bluelog.local"

#: 개발 스텁 계정의 이메일 (`routes/auth_dev.py`).
DEV_STUB_EMAIL = "dev@localhost"

#: 가입할 수 없는 주소. **정규화(앞뒤 공백 제거·소문자)된 형태**로 적는다.
RESERVED_EMAILS: frozenset[str] = frozenset({TOUR_EMAIL, DEV_STUB_EMAIL})


def is_reserved_email(normalized_email: str) -> bool:
    """예약 주소인가.

    :param normalized_email: **가입이 쓰는 정규화를 이미 지난 값**이다. 여기서 다시
        정규화하지 않는다 — 규칙이 두 벌이 되면 저장되는 값과 비교하는 값이 갈린다.
    """
    return normalized_email in RESERVED_EMAILS
