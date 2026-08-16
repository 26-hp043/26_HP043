"""비밀번호 해싱·검증 (#414).

자체 ID/PW 인증 전환(`PRD §20 O-14`)으로 **제품이 비밀번호를 보관**하게 됐다.
보관하는 것은 해시뿐이며 원문은 저장·로그·감사 기록 어디에도 남기지 않는다
(`DB_SCHEMA §2.15`).

## 왜 Argon2id인가

- **bcrypt**는 입력을 72바이트에서 자른다. 긴 비밀번호의 뒷부분이 조용히 무시되며,
  그 사실이 화면에도 로그에도 드러나지 않는다.
- **PBKDF2**는 GPU 병렬화에 약하다.
- **Argon2id**는 메모리를 함께 요구해 GPU·ASIC 우위를 줄인다. OWASP 현행 권고다.

## 타이밍 공격 방어

로그인 실패 시 **계정이 없어도 해시 검증을 수행한다**(`verify_dummy`). 없는 계정을
즉시 거부하면 응답 시간 차이로 **가입 여부를 알아낼 수 있다** — `API_SPEC §1.2`가
「계정 존재 여부를 노출하지 않는다」로 규정한 것을 시간축에서도 지키는 것이다.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

#: 비밀번호 최소 길이.
#:
#: 복잡도 규칙(대문자·특수문자 강제)을 두지 않는 것은 의도다 — 현행 NIST SP 800-63B는
#: 복잡도 강제가 오히려 예측 가능한 패턴(`Password1!`)을 만든다고 보고 **길이**를
#: 우선한다. 짧고 복잡한 것보다 길고 단순한 편이 낫다.
MIN_PASSWORD_LENGTH = 10

#: 최대 길이. Argon2는 bcrypt와 달리 자르지 않으나, 무제한을 허용하면 매우 긴 입력이
#: 해싱 비용을 통해 서비스 거부 수단이 된다.
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher()

#: 존재하지 않는 계정에 대해 검증 시간을 맞추기 위한 더미 해시.
#: 모듈 로드 시 한 번 만든다 — 매 요청 생성하면 그 자체가 비용이다.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalisation")


class PasswordPolicyError(ValueError):
    """비밀번호가 정책을 만족하지 않는다."""


def validate_password(password: str) -> None:
    """정책 검사. 위반이면 :class:`PasswordPolicyError`.

    **해싱 전에 호출한다.** 해싱은 의도적으로 느리므로, 길이만으로 거를 수 있는
    입력에 그 비용을 치를 이유가 없다.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"비밀번호는 {MAX_PASSWORD_LENGTH}자를 넘을 수 없습니다.")


def hash_password(password: str) -> str:
    """비밀번호를 해시한다. 정책 검사를 함께 수행한다."""
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """해시와 일치하는지 확인한다.

    예외를 밖으로 내지 않고 ``bool``로 좁힌다 — 호출부가 「불일치」와 「해시 손상」을
    구분해 다룰 이유가 없고, 구분하면 그 차이가 응답에 드러날 수 있다.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:  # noqa: BLE001 — 검증 실패는 어떤 이유든 로그인 거부다
        return False


def verify_dummy(password: str) -> None:
    """존재하지 않는 계정에 대해 **검증 시간을 맞춘다.**

    없는 계정을 즉시 거부하면 응답 시간 차이로 가입 여부를 알아낼 수 있다.
    결과는 쓰지 않는다 — 목적이 시간을 쓰는 것이다.
    """
    verify_password(password, _DUMMY_HASH)


def needs_rehash(password_hash: str) -> bool:
    """해시가 현재 파라미터보다 약한지. 로그인 성공 시 재해싱 판단에 쓴다."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
