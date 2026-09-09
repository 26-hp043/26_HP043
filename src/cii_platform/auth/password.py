"""비밀번호 해싱·검증 (#414).

자체 ID/PW 인증 전환(`PRD §20 O-14`)으로 **제품이 비밀번호를 보관**하게 됐다.
보관하는 것은 해시뿐이며 원문은 저장·로그·감사 기록 어디에도 남기지 않는다
(`DB_SCHEMA §2.15`).

## 왜 Argon2id인가

- **bcrypt**는 입력을 72바이트에서 자른다. 긴 비밀번호의 뒷부분이 조용히 무시되며,
  그 사실이 화면에도 로그에도 드러나지 않는다.
- **PBKDF2**는 GPU 병렬화에 약하다.
- **Argon2id**는 메모리를 함께 요구해 GPU·ASIC 우위를 줄인다. OWASP 현행 권고다.

## 해싱은 스레드로 내보낸다 (#827)

Argon2 검증 1회가 **약 60 ms**(12코어 개발기 기준)이고, 그동안 uvicorn의 이벤트
루프가 통째로 멈춘다(``Dockerfile:132`` — 워커는 1개다). 미인증 상태에서 가능하며,
없는 계정도 :func:`verify_dummy`로 같은 비용을 치른다.

실측 — 로그인 **1건**이 도는 동안 ``/health`` 최대 지연 (각 6회 중앙값):

=====================  =========================  ==============================
 판본                   대조군(로그인 없음)         로그인 1건 동안
=====================  =========================  ==============================
 동기                    11.9 ms                    **56.4 ms**
 스레드풀                11.4 ms                    **22.5 ms**
=====================  =========================  ==============================

막는 몫이 44.5 ms에서 11.1 ms로 줄었다. **0이 되지는 않는다** — 스레드 전환 비용과
메모리 대역폭 경합이 남는다. 루프 자체는 비어 있다(아래 :data:`MAX_CONCURRENT_HASHES`
주석의 직접 측정: 루프 최대 정지 65.7 ms -> 3.3 ms).

그래서 ``*_async`` 형을 두고 라우트가 그쪽을 부른다. 동기 형은 남긴다 —
시드(``db/demo_seed.py``)와 순수 함수 검사는 이벤트 루프 없이 부른다.

## 타이밍 공격 방어

로그인 실패 시 **계정이 없어도 해시 검증을 수행한다**(`verify_dummy`). 없는 계정을
즉시 거부하면 응답 시간 차이로 **가입 여부를 알아낼 수 있다** — `API_SPEC §1.2`가
「계정 존재 여부를 노출하지 않는다」로 규정한 것을 시간축에서도 지키는 것이다.
"""

from __future__ import annotations

import anyio
import anyio.to_thread
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

#: 동시에 해싱할 수 있는 요청 수.
#:
#: **실측에서 나온 숫자다.** 같은 해시를 N개 동시에 검증한 결과(12코어):
#:
#: ====  ========  ======
#:  N     소요      가속
#: ====  ========  ======
#:  1      57.5 ms  1.01x
#:  2      73.7 ms  1.57x
#:  4     115.8 ms  2.00x
#:  8     237.2 ms  1.96x   <- 4를 넘으면 늘지 않는다
#: ====  ========  ======
#:
#: Argon2가 1회당 64 MiB를 훑어(``memory_cost=65536 KiB``) **메모리 대역폭**에
#: 걸린다. 코어가 남아도 4를 넘기면 처리량은 그대로이고 순간 메모리만 늘어난다 —
#: 4 x 64 MiB = **256 MiB**가 상한이고, 8이면 같은 처리량에 512 MiB를 쓴다.
#:
#: anyio 기본 스레드 한도(40)를 그대로 쓰면 **40 x 64 MiB = 2.5 GiB**가 되어,
#: 「이벤트 루프 정지」를 「메모리 고갈」로 바꾸는 것에 지나지 않는다. 컨테이너에
#: 메모리 상한이 걸려 있지 않아(``docker-compose.prod.yml``) 그 폭주는 호스트까지 간다.
#:
#: 전용 한도를 두는 이유는 **기본 스레드풀을 공유하지 않기 위해서**이기도 하다 —
#: 로그인이 몰릴 때 다른 스레드 작업까지 굶기지 않는다.
MAX_CONCURRENT_HASHES = 4

_hash_limiter = anyio.CapacityLimiter(MAX_CONCURRENT_HASHES)

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


async def hash_password_async(password: str) -> str:
    """:func:`hash_password`를 스레드에서 실행한다 (#827).

    정책 검사는 **여기서 먼저** 한다 — 길이만으로 거를 입력에 스레드 확보 비용까지
    치를 이유가 없고, :class:`PasswordPolicyError`가 스레드 경계를 넘어오는 것보다
    호출부에 가까운 자리에서 나는 편이 낫다.
    """
    validate_password(password)
    return await anyio.to_thread.run_sync(_hasher.hash, password, limiter=_hash_limiter)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """:func:`verify_password`를 스레드에서 실행한다 (#827)."""
    return await anyio.to_thread.run_sync(
        verify_password, password, password_hash, limiter=_hash_limiter
    )


def verify_dummy(password: str) -> None:
    """존재하지 않는 계정에 대해 **검증 시간을 맞춘다.**

    없는 계정을 즉시 거부하면 응답 시간 차이로 가입 여부를 알아낼 수 있다.
    결과는 쓰지 않는다 — 목적이 시간을 쓰는 것이다.
    """
    verify_password(password, _DUMMY_HASH)


async def verify_dummy_async(password: str) -> None:
    """:func:`verify_dummy`를 스레드에서 실행한다 (#827).

    **없는 계정도 같은 한도를 지난다.** 다른 경로로 빠지면 대기 시간 차이가 그대로
    가입 여부 신호가 되어, 이 함수가 막으려던 것이 한도 쪽에서 되살아난다.
    """
    await verify_password_async(password, _DUMMY_HASH)


def needs_rehash(password_hash: str) -> bool:
    """해시가 현재 파라미터보다 약한지. 로그인 성공 시 재해싱 판단에 쓴다."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
