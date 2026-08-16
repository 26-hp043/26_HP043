"""일회용 인증 토큰 서비스 (#408).

이메일 인증과 비밀번호 재설정의 **토큰 발급·검증**을 담당한다. 메일을 실제로
보내는 것은 `#407`의 `mail` 패키지, 화면은 `#415` 소관이다.

## 원문은 한 번만 존재한다

발급 시 만든 원문은 **메일 본문에만** 실린다. DB에는 SHA-256 해시만 남으므로
서버도 나중에 원문을 알 수 없다(`user_session`과 같은 규칙).

## 유효기간이 다른 이유

| 용도 | 기간 |
|---|---|
| 이메일 인증 | 24시간 |
| 비밀번호 재설정 | **1시간** |

재설정이 짧은 것은 **그 토큰이 계정을 통째로 넘기는 힘**을 갖기 때문이다.
메일함이 잠시 노출된 상황에서 창이 짧을수록 피해가 준다.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update

from cii_platform.db.models.user_session import UserSession
from cii_platform.db.models.user_token import (
    PURPOSE_EMAIL_VERIFY,
    PURPOSE_PASSWORD_RESET,
    UserToken,
)

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from sqlalchemy.ext.asyncio import AsyncSession

#: 토큰 원문 바이트 수. `secrets.token_urlsafe`는 이보다 긴 문자열을 만든다.
TOKEN_BYTES = 32

EMAIL_VERIFY_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(hours=1)

_TTL = {
    PURPOSE_EMAIL_VERIFY: EMAIL_VERIFY_TTL,
    PURPOSE_PASSWORD_RESET: PASSWORD_RESET_TTL,
}


class TokenError(Exception):
    """토큰을 쓸 수 없다 — 만료·사용됨·없음.

    **세 경우를 구분하지 않는다.** 「이미 사용된 토큰입니다」와 「없는 토큰입니다」를
    나누면 공격자가 토큰 추측 결과를 좁힐 수 있다. 화면 문구도 하나다
    (`PRD §6.3` — *"링크가 만료되었거나 이미 사용되었습니다"*).
    """


def hash_token(raw: str) -> str:
    """토큰 원문의 SHA-256 hex. `auth.session.hash_token`과 같은 방식이다."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """URL에 실을 수 있는 임의 토큰 원문."""
    return secrets.token_urlsafe(TOKEN_BYTES)


async def issue_token(
    session: AsyncSession,
    *,
    user_id: UUID,
    purpose: str,
    now: datetime | None = None,
) -> str:
    """토큰을 발급하고 **원문을 돌려준다.**

    같은 용도의 기존 미사용 토큰은 **함께 무효화**한다. 재발송을 누를 때마다 유효한
    링크가 늘어나면, 오래된 메일이 유출됐을 때 그 링크가 계속 살아 있다.

    :returns: 메일에 실을 원문. **이 반환값 외에 원문을 얻을 방법은 없다.**
    """
    if purpose not in _TTL:
        raise ValueError(f"알 수 없는 토큰 용도: {purpose}")

    resolved = now or datetime.now(UTC)

    # 같은 용도의 미사용 토큰을 먼저 소진 처리한다.
    await session.execute(
        update(UserToken)
        .where(
            UserToken.user_id == user_id,
            UserToken.purpose == purpose,
            UserToken.used_at.is_(None),
        )
        .values(used_at=resolved)
    )

    raw = generate_token()
    session.add(
        UserToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=resolved + _TTL[purpose],
        )
    )
    return raw


async def consume_token(
    session: AsyncSession,
    *,
    raw: str,
    purpose: str,
    now: datetime | None = None,
) -> UUID:
    """토큰을 검증하고 **사용 처리**한 뒤 소유자 ID를 돌려준다.

    :raises TokenError: 없음·만료·이미 사용됨. **세 경우를 구분하지 않는다.**
    """
    resolved = now or datetime.now(UTC)

    result = await session.execute(
        select(UserToken).where(
            UserToken.token_hash == hash_token(raw),
            UserToken.purpose == purpose,
        )
    )
    token = result.scalar_one_or_none()

    if token is None or token.used_at is not None or token.expires_at <= resolved:
        raise TokenError("링크가 만료되었거나 이미 사용되었습니다.")

    # 사용 표시 — 재사용을 막는다.
    token.used_at = resolved
    return token.user_id


async def revoke_all_sessions(
    session: AsyncSession,
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> int:
    """해당 사용자의 살아 있는 세션을 전부 무효화한다.

    **비밀번호 재설정 성공 시 반드시 호출한다**(`API_SPEC §1.2`). 탈취된 상태에서
    비밀번호만 바꾸면 **공격자 세션이 그대로 살아 있다** — 재설정의 목적이 바로
    그 세션을 끊는 것이다.

    :returns: 무효화한 세션 수.
    """
    resolved = now or datetime.now(UTC)
    result = await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=resolved)
    )
    return result.rowcount or 0
