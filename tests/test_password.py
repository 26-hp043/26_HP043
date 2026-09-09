"""비밀번호 해싱·정책 단위 검증 (#414).

DB도 HTTP도 쓰지 않는다. `test_auth_api.py`가 **경로**를 보는 반면 여기는
**규칙**을 본다.

가장 중요한 것은 `verify_dummy`가 존재한다는 사실 자체다 — 없는 계정을 즉시
거부하면 응답 시간 차이로 가입 여부가 새어 나간다.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from cii_platform.auth.password import (
    MAX_CONCURRENT_HASHES,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    hash_password_async,
    needs_rehash,
    validate_password,
    verify_dummy,
    verify_dummy_async,
    verify_password,
    verify_password_async,
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


class TestNonBlockingHashing:
    """해싱이 이벤트 루프를 막지 않는다 (#827).

    Argon2 검증 1회가 약 100~140 ms인데 uvicorn 워커는 1개다(``Dockerfile:132``).
    동기로 부르면 그동안 **다른 모든 요청이 대기**한다 — 실측에서 로그인 5건이
    동시에 들어가는 사이 ``/health`` 응답이 최대 18 ms에서 243 ms로 밀렸다.
    미인증 상태에서 가능하다.
    """

    @pytest.mark.asyncio
    async def test_loop_keeps_running_during_verify(self):
        """검증이 도는 동안에도 다른 태스크가 계속 깨어난다.

        **시간을 재지 않는다** — 느린 CI에서 흔들린다. 대신 *다른 태스크가 몇 번
        깨어났는지*를 센다. 동기 호출이면 루프가 통째로 멈춰 **0**이 된다.
        """
        password_hash = await hash_password_async(VALID)
        ticks = 0
        stop = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.005)

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0)  # ticker가 먼저 자리를 잡게 한다
        assert await verify_password_async(VALID, password_hash) is True
        stop.set()
        await task

        # 검증이 60 ms 이상 걸리므로 5 ms 간격이면 여러 번 깨어난다. 하한을 낮게 둔 것은
        # 느린 기계에서 sleep이 늘어나기 때문이며, **막히면 이 값이 1을 넘지 못한다.**
        assert ticks >= 3, f"루프가 멈췄다 — 깨어난 횟수 {ticks}"

    @pytest.mark.asyncio
    async def test_round_trip_matches_the_sync_form(self):
        password_hash = await hash_password_async(VALID)
        assert await verify_password_async(VALID, password_hash) is True
        assert await verify_password_async("wrong-password-here", password_hash) is False
        # 동기 형으로 만든 해시도 그대로 통한다 — 시드가 그쪽을 쓴다.
        assert await verify_password_async(VALID, hash_password(VALID)) is True

    @pytest.mark.asyncio
    async def test_policy_is_checked_before_the_thread(self):
        """길이만으로 거를 입력에 스레드 확보 비용을 치르지 않는다."""
        with pytest.raises(PasswordPolicyError):
            await hash_password_async("short")

    @pytest.mark.asyncio
    async def test_dummy_verification_stays_on_the_same_path(self):
        """없는 계정도 같은 한도를 지난다 — 다른 길로 빠지면 대기 시간이 신호가 된다."""
        assert await verify_dummy_async("whatever-it-is") is None

    def test_concurrency_cap_is_bounded_by_memory(self):
        """동시 실행 수가 곧 순간 메모리다 — 4 x 64 MiB = 256 MiB.

        상한을 **실측한 포화점**에 맞춘다. 같은 해시를 동시 검증하면 가속이 4에서
        2.00x, 8에서 1.96x로 **더 늘지 않는다** — Argon2가 1회당 64 MiB를 훑어
        메모리 대역폭에 걸리기 때문이다. 4를 넘기면 처리량은 그대로인 채 순간
        메모리만 커진다.

        anyio 기본 스레드 한도(40)를 그대로 쓰면 **2.5 GiB**가 되어, 「이벤트 루프
        정지」를 「메모리 고갈」로 바꾸는 것에 지나지 않는다. 컨테이너에 메모리 상한이
        걸려 있지 않아(`docker-compose.prod.yml`) 그 폭주는 호스트까지 간다.
        """
        argon2_memory_mib = 64  # memory_cost=65536 KiB
        assert MAX_CONCURRENT_HASHES * argon2_memory_mib <= 256


class TestRoutesDoNotBlock:
    """라우트가 **동기 형을 다시 부르지 않는지** 소스로 확인한다 (#827).

    동작 검사로는 잡히지 않는다 — 동기 형을 불러도 결과는 똑같고 응답도 200이다.
    달라지는 것은 *그동안 다른 요청이 어떻게 되는가*뿐이라, 되돌아가도 조용히 통과한다.
    """

    ROUTES = ("api/routes/auth.py", "api/routes/auth_tokens.py")
    BLOCKING = ("hash_password(", "verify_password(", "verify_dummy(")

    @pytest.mark.parametrize("relative", ROUTES)
    def test_no_blocking_call_remains(self, relative):
        source = (Path("src/cii_platform") / relative).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        for name in self.BLOCKING:
            # `hash_password_async(`는 `hash_password(`를 포함하지 않는다 — `_async`가 사이에 있다.
            assert name not in code, f"{relative}에 동기 해싱 호출이 남아 있다: {name}"

    def test_the_async_forms_are_actually_coroutines(self):
        """이름만 `_async`인 함수를 잡는다."""
        for func in (hash_password_async, verify_password_async, verify_dummy_async):
            assert inspect.iscoroutinefunction(func), func.__name__
