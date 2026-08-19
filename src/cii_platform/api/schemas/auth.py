"""인증 요청 스키마 (`API_SPEC §1.2`, #414).

요청만 Pydantic으로 정의한다. 응답은 라우트가 직접 조립한다 — 인증 응답은 사용자
모델의 일부만 노출하므로(비밀번호 해시 제외) 모델을 그대로 내보내면 안 된다.

## 비밀번호 길이 검증을 여기 두지 않는다

형식만 여기서 보고, **길이 정책은 `auth.password.validate_password()`가 소유**한다.
두 곳에 두면 한쪽만 바뀌었을 때 어긋나고, 정책 위반 메시지도 갈린다.

## 이메일 형식을 `EmailStr`로 보지 않는다

`EmailStr`은 `email-validator` 의존성을 요구한다. 대신 **DB의
`chk_app_user_email_format` CHECK 제약과 같은 정규식**을 쓴다 — 두 곳이 같은
규칙을 보면 API를 통과한 값이 DB에서 거부되는 일이 없다. `VesselCreateRequest`가
IMO 번호에 대해 *"형식은 여기서, DB CHK 제약과 이중 방어"* 라고 적은 것과 같은
방식이다.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

#: DB `chk_app_user_email_format`과 같은 규칙.
#: PostgreSQL의 `[^@[:space:]]`가 Python에서는 `[^@\s]`다.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


class SignupRequest(BaseModel):
    """``POST /api/v1/auth/signup``.

    ``extra="forbid"``인 이유: 오타 필드가 조용히 무시되면 사용자가 의도하지 않은
    값으로 계정이 만들어진다(`VesselCreateRequest`와 같은 근거).
    """

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(pattern=EMAIL_PATTERN, max_length=320)]
    #: 길이 정책은 `auth.password`가 본다. 여기서는 빈 값만 막는다.
    password: Annotated[str, Field(min_length=1)]
    display_name: Annotated[str | None, Field(default=None, max_length=100)]


class LoginRequest(BaseModel):
    """``POST /api/v1/auth/login``."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(pattern=EMAIL_PATTERN, max_length=320)]
    password: Annotated[str, Field(min_length=1)]


class PasswordChangeRequest(BaseModel):
    """``POST /api/v1/auth/password-change`` (`API_SPEC §1.2`, #506).

    **현재 비밀번호를 함께 받는다.** 로그인 상태라도 세션이 탈취됐을 수 있으므로,
    비밀번호를 바꾸려면 그 비밀번호를 아는 사람임을 한 번 더 확인한다 — 확인 없이
    바꿀 수 있으면 **탈취한 세션만으로 계정을 통째로 넘길 수 있다.**
    """

    model_config = ConfigDict(extra="forbid")

    #: 길이 정책은 검사하지 않는다 — 기존 비밀번호는 옛 정책으로 만들어졌을 수 있다.
    current_password: Annotated[str, Field(min_length=1)]
    #: 새 비밀번호의 길이 정책은 `auth.password.validate_password`가 본다.
    new_password: Annotated[str, Field(min_length=1)]


class MeUpdateRequest(BaseModel):
    """``PATCH /api/v1/auth/me`` (`API_SPEC §1.2`, #506).

    ## ``email``을 받지 않는다

    `extra="forbid"`라 `email`을 보내면 **422로 거부**된다. 이메일은 로그인 ID이자
    `idx_app_user_email`의 키이고, 새 주소를 잘못 입력하면 **계정에 접근할 수 없다** —
    비밀번호 재설정 메일도 그 주소로 간다. 주소를 바꾸려면 탈퇴 후 재가입한다
    (`PRD §6.3` · `API_SPEC §1.2`).

    ## ``display_name``에 ``null``을 보낼 수 있다

    표시 이름을 지우는 것은 정당한 조작이다(가입 시에도 선택 입력이다). 그래서
    「보내지 않음」(변경 없음)과 「`null`을 보냄」(지움)을 구분해야 하며, 그 구분은
    `model_fields_set`으로 한다 — 라우트 참조.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str | None, Field(default=None, max_length=100)]
