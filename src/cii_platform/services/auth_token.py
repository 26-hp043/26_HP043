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

    ## 검사와 사용 표시는 한 문장이어야 한다 (#1079)

    종전에는 `SELECT` → 파이썬에서 `used_at is None` 확인 → `token.used_at = …`
    순서였다. 같은 토큰으로 동시에 온 요청 둘이 **둘 다 `used_at IS NULL`을 읽고**
    통과해, 비밀번호가 나중 요청의 값으로 바뀔 수 있었다. 토큰이 한 번 쓰고 버리는
    증명이라는 전제 자체가 깨지는 자리다.

    그래서 검사 조건을 **`UPDATE`의 `WHERE`에 넣는다.** 조건을 만족하는 행이 정확히
    하나 갱신됐을 때만 성공이고, 판정은 DB의 행 잠금이 한다 — 두 요청이 동시에
    들어와도 뒤엣것의 `WHERE`는 이미 채워진 `used_at` 때문에 0행을 만난다.

    ⚠️ **`RETURNING`을 쓰지 않는다.** CUBRID에 없다(`#1058` 전환). 갱신한 행의
    소유자는 `rowcount`로 성공을 확인한 뒤 따로 읽는다 — 같은 트랜잭션이라 방금 쓴
    값을 그대로 본다. `token_hash`에는 유니크 인덱스가 있어(`idx_user_token_hash`)
    이 조회가 두 행을 만날 수 없다.
    """
    resolved = now or datetime.now(UTC)
    digest = hash_token(raw)

    result = await session.execute(
        update(UserToken)
        .where(
            UserToken.token_hash == digest,
            UserToken.purpose == purpose,
            # 아래 두 줄이 종전의 파이썬 검사를 대신한다 — 여기 있어야 원자적이다.
            UserToken.used_at.is_(None),
            UserToken.expires_at > resolved,
        )
        .values(used_at=resolved)
        .execution_options(synchronize_session=False)
    )

    if (result.rowcount or 0) != 1:
        # 없음·만료·이미 사용됨이 전부 여기로 모인다. **구분하지 않는다**(위 `TokenError`).
        raise TokenError("링크가 만료되었거나 이미 사용되었습니다.")

    owner = await session.execute(select(UserToken.user_id).where(UserToken.token_hash == digest))
    return owner.scalar_one()


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
