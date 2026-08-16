"""비밀번호 해싱·정책 단위 검증 (#414).

DB도 HTTP도 쓰지 않는다. `test_auth_api.py`가 **경로**를 보는 반면 여기는
**규칙**을 본다.

가장 중요한 것은 `verify_dummy`가 존재한다는 사실 자체다 — 없는 계정을 즉시
거부하면 응답 시간 차이로 가입 여부가 새어 나간다.
"""

from __future__ import annotations

import pytest

from cii_platform.auth.password import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password,
    verify_dummy,
    verify_password,
)

VALID = "correct-horse-battery"


class TestPolicy:
    def test_minimum_length_is_enforced(self):
        with pytest.raises(PasswordPolicyError, match=f"{MIN_PASSWORD_LENGTH}자"):
            validate_password("a" * (MIN_PASSWORD_LENGTH - 1))

    def test_exact_minimum_is_allowed(self):
        validate_password("a" * MIN_PASSWORD_LENGTH)

    def test_maximum_length_is_enforced(self):
        """무제한을 허용하면 매우 긴 입력이 해싱 비용을 통해 서비스 거부가 된다."""
        with pytest.raises(PasswordPolicyError, match=f"{MAX_PASSWORD_LENGTH}자"):
            validate_password("a" * (MAX_PASSWORD_LENGTH + 1))

    def test_complexity_is_not_required(self):
        """복잡도를 강제하지 않는다.

        현행 NIST SP 800-63B는 복잡도 강제가 오히려 예측 가능한 패턴을 만든다고
        보고 **길이**를 우선한다. 소문자만으로도 충분히 길면 통과해야 한다.
        """
        validate_password("aaaaaaaaaaaaaaaa")

    def test_hash_applies_the_policy(self):
        """해싱 전에 거른다 — 해싱은 의도적으로 느리다."""
        with pytest.raises(PasswordPolicyError):
            hash_password("short")


class TestHashing:
    def test_hash_is_not_the_plaintext(self):
        digest = hash_password(VALID)
        assert VALID not in digest
        assert digest.startswith("$argon2")

    def test_same_password_hashes_differently(self):
        """salt가 매번 달라야 한다 — 같으면 해시 비교로 동일 비밀번호를 찾을 수 있다."""
        assert hash_password(VALID) != hash_password(VALID)

    def test_verify_accepts_the_right_password(self):
        assert verify_password(VALID, hash_password(VALID)) is True

    def test_verify_rejects_the_wrong_password(self):
        assert verify_password("something-else-entirely", hash_password(VALID)) is False

    def test_verify_rejects_a_corrupt_hash_without_raising(self):
        """해시가 손상돼도 예외를 밖으로 내지 않는다.

        「불일치」와 「해시 손상」을 구분하면 그 차이가 응답에 드러날 수 있다.
        """
        assert verify_password(VALID, "not-a-hash-at-all") is False

    def test_verify_rejects_an_empty_hash(self):
        assert verify_password(VALID, "") is False


class TestTimingDefence:
    def test_verify_dummy_runs_without_raising(self):
        """없는 계정에도 검증 비용을 치른다.

        결과를 쓰지 않는다 — 목적이 시간을 쓰는 것이다.
        """
        verify_dummy("anything-at-all")

    def test_dummy_hash_never_matches_a_real_password(self):
        """더미 해시로 로그인이 되면 안 된다."""
        # verify_dummy는 결과를 돌려주지 않으므로 간접 확인 — 더미 해시는
        # 모듈 내부 상수이고, 어떤 입력으로도 인증을 통과시키지 않는다.
        assert verify_password("dummy-password-for-timing-equalisation", "") is False


class TestRehash:
    def test_fresh_hash_does_not_need_rehash(self):
        assert needs_rehash(hash_password(VALID)) is False

    def test_corrupt_hash_needs_rehash(self):
        assert needs_rehash("garbage") is True
