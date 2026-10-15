"""세션 관리 — 토큰 생성·해싱·검증 (#275).

세션 토큰 원문은 **DB에 저장하지 않고 SHA-256 해시만 저장한다** (DB_SCHEMA §2.16).
원문은 쿠키로 클라이언트에게만 전달하고, 서버는 해시로 식별한다.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from cii_platform.db.models.user_session import UserSession

if TYPE_CHECKING:
    pass

#: 세션 만료 기간 (일). API_SPEC §1.2 참조.
SESSION_TTL_DAYS = 7

#: CSRF 토큰 길이 (바이트).
CSRF_TOKEN_BYTES = 32

#: 세션 토큰 길이 (바이트).
SESSION_TOKEN_BYTES = 32

#: ``user_session.user_agent`` 칸 길이 — 모델에서 가져와 숫자를 중복하지 않는다 (#2520).
USER_AGENT_MAX_LENGTH: int = UserSession.__table__.c.user_agent.type.length


def _fit_user_agent(user_agent: str | None) -> str | None:
    """칸 길이에 맞춘 User-Agent — **UTF-8 바이트 수**로 센다 (#2520).

    헤더는 latin-1로 풀려 한글 한 글자가 0x80 이상의 글자 셋이 되고, 그 글자는 DB로 갈 때
    UTF-8로 2바이트가 된다. 글자 수로 자르면 255글자가 510바이트가 되어 다시 넘친다.
    """
    if user_agent is None:
        return None
    encoded = user_agent.encode("utf-8")
    if len(encoded) <= USER_AGENT_MAX_LENGTH:
        return user_agent
    return encoded[:USER_AGENT_MAX_LENGTH].decode("utf-8", errors="ignore")


def generate_session_token() -> str:
    """URL-safe 세션 토큰을 생성한다 (32바이트)."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def generate_csrf_token() -> str:
    """CSRF 토큰을 생성한다 (32바이트)."""
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """토큰을 SHA-256 해시로 변환한다 (DB 저장용)."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session_fields(
    user_id: UUID,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[dict[str, object], str, str]:
    """세션 INSERT용 필드 + 원문 토큰 + CSRF 원문을 생성한다.

    반환: ``(db_fields, session_token_plaintext, csrf_token_plaintext)``
    db_fields는 ``user_session`` 테이블에 직접 INSERT 가능하다.
    원문 토큰들은 쿠키/헤더로 클라이언트에 전달하고 **DB에 저장하지 않는다**.
    """
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    expires_at = datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)

    db_fields: dict[str, object] = {
        "id": uuid4(),
        "user_id": user_id,
        "session_token_hash": hash_token(session_token),
        "csrf_token_hash": hash_token(csrf_token),
        "expires_at": expires_at,
        "revoked_at": None,
        # 칸(255)보다 긴 User-Agent는 INSERT가 500이 되므로 저장 전에 자른다 (#2520).
        "user_agent": _fit_user_agent(user_agent),
        "ip_address": ip_address,
    }
    return db_fields, session_token, csrf_token


def is_expired(expires_at: datetime, now: datetime | None = None) -> bool:
    """세션이 만료됐는지 확인한다."""
    check = now or datetime.now(UTC)
    return expires_at <= check


def is_revoked(revoked_at: datetime | None) -> bool:
    """세션이 무효화됐는지 확인한다."""
    return revoked_at is not None


def is_valid(expires_at: datetime, revoked_at: datetime | None) -> bool:
    """세션이 유효한지 (만료·무효 아님) 확인한다."""
    return not is_revoked(revoked_at) and not is_expired(expires_at)


def verify_csrf(provided: str, stored_hash: str) -> bool:
    """CSRF 토큰이 저장된 해시와 일치하는지 확인한다 (constant-time)."""
    return secrets.compare_digest(hash_token(provided), stored_hash)


#: 쿠키 이름 — API_SPEC §1.2.
SESSION_COOKIE_NAME = "sid"
CSRF_COOKIE_NAME = "csrf"

#: 쿠키 속성 — API_SPEC §1.2 (HttpOnly · Secure · SameSite=Lax).
COOKIE_ATTRIBUTES = {
    "httponly": True,
    "secure": True,
    "samesite": "lax",
    "path": "/",
}
