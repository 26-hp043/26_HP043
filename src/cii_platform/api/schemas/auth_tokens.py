"""이메일 인증·비밀번호 재설정 요청 스키마 (`API_SPEC §1.2`, #408)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from cii_platform.api.schemas.auth import EMAIL_PATTERN


class VerifyEmailRequest(BaseModel):
    """``POST /api/v1/auth/verify-email/request`` — 인증 메일 재발송."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(pattern=EMAIL_PATTERN, max_length=320)]


class VerifyEmailConfirmRequest(BaseModel):
    """``POST /api/v1/auth/verify-email/confirm`` — 메일 링크의 토큰."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=1, max_length=256)]


class PasswordResetRequest(BaseModel):
    """``POST /api/v1/auth/password-reset/request``."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(pattern=EMAIL_PATTERN, max_length=320)]


class PasswordResetConfirmRequest(BaseModel):
    """``POST /api/v1/auth/password-reset/confirm``.

    길이 정책은 `auth.password.validate_password()`가 소유한다 — 여기서는 빈 값만
    막는다(`SignupRequest`와 같은 근거).
    """

    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=1, max_length=256)]
    password: Annotated[str, Field(min_length=1)]
