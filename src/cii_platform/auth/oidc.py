"""구글 OIDC 클라이언트 — discovery · JWKS · id_token 검증 (#274).

구글 Authorization Code + PKCE 플로우를 처리한다. ``client_id``·``client_secret``
은 환경변수에서 읽는다 — **실제 값을 커밋하지 않는다** (API_SPEC §12).

``id_token`` 검증은 **서명을 반드시 확인한다** (이슈 #274 완료 기준: 서명 · ``iss`` ·
``aud`` · ``exp`` · ``nonce`` · ``email_verified`` — 하나라도 빠지면 안 됨).
서명 검증은 PyJWT + cryptography가 담당한다.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

#: 구글 OIDC 설정 — 환경변수에서 읽는다. 실제 값은 .env 또는 배포 환경에서 주입.
GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")

#: 구글 OIDC discovery URL.
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

#: 구글 id_token의 허용 issuer — 계정 도메인이 두 형태로 온다.
GOOGLE_ISSUERS: tuple[str, ...] = ("https://accounts.google.com", "accounts.google.com")

#: 리다이렉트 URI — 배포 환경에서 설정. 기본값은 로컬 개발용.
REDIRECT_URI: str = os.environ.get(
    "OIDC_REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback"
)

#: JWKS 캐시 (프로세스당 1회 조회).
_jwks_cache: dict[str, Any] | None = None
_discovery_cache: dict[str, Any] | None = None


async def get_discovery_document() -> dict[str, Any]:
    """구글 discovery 문서를 가져온다 (캐시)."""
    global _discovery_cache
    if _discovery_cache is not None:
        return _discovery_cache
    async with httpx.AsyncClient() as client:
        resp = await client.get(GOOGLE_DISCOVERY_URL, timeout=10)
        resp.raise_for_status()
        _discovery_cache = resp.json()
    return _discovery_cache


async def get_jwks() -> dict[str, Any]:
    """JWKS (공개키 집합)를 가져온다 (캐시)."""
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    discovery = await get_discovery_document()
    jwks_uri = discovery["jwks_uri"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(jwks_uri, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
    return _jwks_cache


def generate_pkce_pair() -> tuple[str, str]:
    """PKCE code_verifier와 code_challenge를 생성한다.

    반환: ``(code_verifier, code_challenge)``
    code_challenge_method는 S256을 사용한다 (RFC 7636).
    """
    import base64
    import hashlib

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def generate_state() -> str:
    """CSRF 방지용 state 값을 생성한다."""
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    """OIDC nonce — 재생 공격 방지. 로그인 요청마다 생성한다."""
    return secrets.token_urlsafe(16)


def build_auth_url(state: str, code_challenge: str, nonce: str) -> str:
    """구글 인증 화면 URL을 생성한다.

    ``state``에는 호출자가 redirect_to를 이미 합쳐 넣은 값이 온다
    (``"state:redirect_to"`` 형태). ``nonce``는 id_token에 돌아와 검증된다.
    """
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


async def exchange_code(code: str, code_verifier: str) -> dict[str, Any]:
    """Authorization Code를 토큰으로 교환한다."""
    discovery = await get_discovery_document()
    token_endpoint = discovery["token_endpoint"]

    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_endpoint, data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()


async def verify_id_token(
    id_token: str,
    *,
    expected_nonce: str | None = None,
) -> dict[str, Any]:
    """``id_token``을 검증하고 payload를 반환한다.

    검증 항목 (**하나라도 빠지면 안 됨**, 이슈 #274):
    - **서명** — JWKS에서 ``kid``에 해당하는 공개키로 RS256 서명 확인
    - **``iss``** — Google issuer 목록에 속해야 함
    - **``aud``** — 우리 ``GOOGLE_CLIENT_ID``와 일치해야 함
    - **``exp``** — 만료되지 않았어야 함 (PyJWT 기본)
    - **``nonce``** — 로그인 시 발급한 값과 일치해야 함 (재생 공격 방지)
    - **``email_verified``** — true여야 함

    검증 실패는 모두 ``ValueError``로 전파한다 — 라우트가 401로 변환한다.
    """
    # 헤더에서 kid·alg 추출 (서명 검증 전 메타데이터 — 값 자체는 검증하지 않는다).
    try:
        header = pyjwt.get_unverified_header(id_token)
    except pyjwt.PyJWTError as exc:
        # 형식이 깨진 토큰(JWT 구조가 아닌 값)은 여기서 걸린다.
        # 잡지 않으면 DecodeError가 라우트의 ValueError 처리에 안 걸리고
        # catch-all 500으로 새어 나간다 — 401로 거부해야 한다.
        raise ValueError(f"id_token 형식이 올바르지 않습니다: {exc}") from exc
    kid = header.get("kid")
    alg = header.get("alg", "RS256")
    if alg != "RS256":
        raise ValueError(f"지원하지 않는 서명 알고리즘: {alg}")

    # JWKS에서 kid에 해당하는 공개키 찾기.
    jwks = await get_jwks()
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key_data is None:
        raise ValueError("id_token의 kid에 해당하는 공개키를 찾을 수 없습니다.")

    rsa_key = RSAAlgorithm.from_jwk(key_data)

    try:
        payload = pyjwt.decode(
            id_token,
            key=rsa_key,
            algorithms=["RS256"],
            audience=GOOGLE_CLIENT_ID,
            issuer=list(GOOGLE_ISSUERS),
            options={"require": ["sub", "iss", "aud", "exp"]},
        )
    except pyjwt.PyJWTError as exc:
        raise ValueError(f"id_token 검증 실패: {exc}") from exc

    # email_verified 확인 — 이메일이 확인되지 않으면 로그인 거부.
    if not payload.get("email_verified", False):
        raise ValueError("이메일이 확인되지 않은 구글 계정입니다.")

    # nonce 확인 — 로그인 시 발급한 값과 다르면 재생 공격으로 보고 거부.
    if expected_nonce is not None and payload.get("nonce") != expected_nonce:
        raise ValueError("nonce 불일치 — 로그인 요청이 재사용되었습니다.")

    return payload
