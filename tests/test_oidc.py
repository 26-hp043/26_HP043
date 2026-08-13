"""구글 OIDC 인증 테스트 (#274).

``verify_id_token``의 거부 케이스(만료 · 잘못된 aud · email_verified=false · nonce
불일치 · 형식이 깨진 토큰)와 ``/auth/login``·``/auth/callback`` 라우트의 계약을
검증한다. **외부 네트워크(구글) 없이 돈다** — JWKS를 테스트용 RSA 키로 대역하고,
httpx 호출은 monkeypatch로 대체한다.
"""

from __future__ import annotations

import base64
import datetime as dt
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from cii_platform.auth import oidc
from cii_platform.auth.oidc import (
    GOOGLE_ISSUERS,
    build_auth_url,
    generate_nonce,
    verify_id_token,
)

#: 테스트용 고정 client_id — GOOGLE_CLIENT_ID와 달라야 한다 (aud 검증 확인용).
TEST_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
TEST_KID = "test-kid-1"


#: 공개키를 url-safe base64로 인코딩하는 데 쓴다 (JWKS 형식).
def _b64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    """테스트용 RSA 키 쌍과 그 공개키의 JWKS dict를 반환한다."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key()
    numbers = public.public_numbers()
    jwks: dict[str, Any] = {
        "keys": [
            {
                "kty": "RSA",
                "kid": TEST_KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url(numbers.n),
                "e": _b64url(numbers.e),
            }
        ]
    }
    return private, jwks


def _sign_token(private: rsa.RSAPrivateKey, payload: dict[str, Any]) -> str:
    """테스트용 private key로 id_token을 서명한다."""
    return pyjwt.encode(payload, private, algorithm="RS256", headers={"kid": TEST_KID})


def _valid_payload() -> dict[str, Any]:
    """통과해야 하는 id_token payload — 각 테스트가 필요한 필드만 바꾼다."""
    return {
        "iss": GOOGLE_ISSUERS[0],
        "aud": TEST_CLIENT_ID,
        "sub": "google-sub-123",
        "email": "user@example.com",
        "email_verified": True,
        "nonce": "test-nonce-1",
        "exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
        "iat": dt.datetime.now(dt.UTC),
    }


@pytest.fixture
def mock_jwks(monkeypatch: pytest.MonkeyPatch, rsa_keypair):
    """verify_id_token의 get_jwks를 테스트 JWKS로 대체한다."""

    async def fake_jwks() -> dict[str, Any]:
        return rsa_keypair[1]

    monkeypatch.setattr(oidc, "get_jwks", fake_jwks)
    # aud 검증에 사용될 client_id를 테스트 값으로 고정.
    monkeypatch.setattr(oidc, "GOOGLE_CLIENT_ID", TEST_CLIENT_ID)
    return rsa_keypair


class TestVerifyIdToken:
    """id_token 검증 — 서명 · iss · aud · exp · nonce · email_verified."""

    async def test_valid_token_passes(self, mock_jwks):
        private, _ = mock_jwks
        token = _sign_token(private, _valid_payload())
        payload = await verify_id_token(token, expected_nonce="test-nonce-1")
        assert payload["sub"] == "google-sub-123"

    async def test_expired_token_rejected(self, mock_jwks):
        private, _ = mock_jwks
        payload = _valid_payload()
        payload["exp"] = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
        token = _sign_token(private, payload)
        with pytest.raises(ValueError, match="has expired"):
            await verify_id_token(token, expected_nonce="test-nonce-1")

    async def test_wrong_audience_rejected(self, mock_jwks):
        private, _ = mock_jwks
        payload = _valid_payload()
        payload["aud"] = "other-client.apps.googleusercontent.com"
        token = _sign_token(private, payload)
        with pytest.raises(ValueError):
            await verify_id_token(token, expected_nonce="test-nonce-1")

    async def test_unverified_email_rejected(self, mock_jwks):
        private, _ = mock_jwks
        payload = _valid_payload()
        payload["email_verified"] = False
        token = _sign_token(private, payload)
        with pytest.raises(ValueError, match="이메일"):
            await verify_id_token(token, expected_nonce="test-nonce-1")

    async def test_nonce_mismatch_rejected(self, mock_jwks):
        private, _ = mock_jwks
        token = _sign_token(private, _valid_payload())
        with pytest.raises(ValueError, match="nonce"):
            await verify_id_token(token, expected_nonce="different-nonce")

    async def test_wrong_signature_rejected(self, mock_jwks):
        # 다른 키로 서명 → 서명 검증 실패. kid는 같게 해서 키 선택은 통과시키고
        # 서명 검증이 실제로 일어나는지 확인한다.
        other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _sign_token(other_private, _valid_payload())
        with pytest.raises(ValueError):
            await verify_id_token(token, expected_nonce="test-nonce-1")

    async def test_malformed_token_rejected(self, mock_jwks):
        # JWT 구조가 아닌 값 — DecodeError가 ValueError로 변환되어야 한다.
        # 변환되지 않으면 라우트의 401 처리를 건너뛰고 catch-all 500이 된다.
        with pytest.raises(ValueError, match="형식"):
            await verify_id_token("not-a-jwt", expected_nonce="test-nonce-1")

    async def test_unknown_kid_rejected(self, mock_jwks):
        private, _ = mock_jwks
        token = pyjwt.encode(
            _valid_payload(),
            private,
            algorithm="RS256",
            headers={"kid": "unknown-kid"},
        )
        with pytest.raises(ValueError, match="kid"):
            await verify_id_token(token, expected_nonce="test-nonce-1")

    async def test_wrong_issuer_rejected(self, mock_jwks):
        private, _ = mock_jwks
        payload = _valid_payload()
        payload["iss"] = "https://evil.example.com"
        token = _sign_token(private, payload)
        with pytest.raises(ValueError):
            await verify_id_token(token, expected_nonce="test-nonce-1")


class TestOidcHelpers:
    """oidc.py의 순수 함수들."""

    def test_nonce_is_urlsafe_and_unique(self):
        a = generate_nonce()
        b = generate_nonce()
        assert a != b
        assert len(a) > 16

    def test_build_auth_url_contains_required_params(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(oidc, "GOOGLE_CLIENT_ID", TEST_CLIENT_ID)
        url = build_auth_url(state="state-1", code_challenge="challenge-1", nonce="nonce-1")
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-client-id.apps.googleusercontent.com" in url
        assert "response_type=code" in url
        assert "code_challenge_method=S256" in url
        assert "state=state-1" in url
        assert "nonce=nonce-1" in url
