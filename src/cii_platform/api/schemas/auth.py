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
