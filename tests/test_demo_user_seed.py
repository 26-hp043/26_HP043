"""시연 계정 시드의 계약 (#692).

**막으려는 것은 「계정이 없다」가 아니라 「없는 줄 모른다」이다.**

데모 시드는 선박 4척과 항차 11건을 넣으면서 **계정은 하나도 만들지 않았다.** 유일한
계정 ``dev@localhost``는 비밀번호 로그인이 의도적으로 막혀 있어(``auth_dev.py``의
``_STUB_PASSWORD_HASH``) 로그인 화면으로는 들어갈 수 없다. **그 설계는 옳다** — 알려진
이메일로 아무나 들어오는 것을 막는다. 문제는 그 대신 쓸 계정이 없다는 것이었다.

그래서 DB를 다시 만들 때마다 사람이 직접 가입해야 했고, `#691` 이전의 테스트가 계정을
지우고 나면 **들어갈 길이 아예 없었다.**

여기서 고정하는 것은 넷이다.

1. **시드가 계정을 만든다** — 그리고 그 계정으로 실제로 로그인된다
2. **다시 돌려도 늘지 않는다** — 기존 행을 덮지 않는 이 파일의 시드 원칙
3. **``APP_ENV=production``에서는 만들지 않는다** — 고정 비밀번호가 프로덕션에 있으면
   그 값이 알려진 순간 누구나 들어온다
4. **없으면 없다고 말한다** — ``demo_up.sh --check``가 시연 전에 잡는다

케이스: (`TEST_PLAN §14.5` 정의 없음 — 시연 경로 계약)
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.auth.password import MIN_PASSWORD_LENGTH, verify_password
from cii_platform.db.demo_seed import (
    DEMO_USER_DISPLAY_NAME,
    DEMO_USER_EMAIL,
    DEMO_USER_ID,
    DEMO_USER_PASSWORD,
    DEMO_USER_VERIFIED_AT,
    demo_user_missing,
    seed_demo_user,
)

# --- 값 자체 (DB 없이) -----------------------------------------------------------


def test_password_satisfies_the_policy():
    """정책보다 짧으면 **시드가 아니라 해싱 앞의 검사에서** 막힌다.

    그 실패는 「시드가 깨졌다」로 보이지 그 원인을 말해 주지 않는다. 값이 바뀔 때
    여기서 먼저 걸리게 한다.
    """
    assert len(DEMO_USER_PASSWORD) >= MIN_PASSWORD_LENGTH


def test_email_domain_cannot_receive_mail():
    """``.local``을 쓴다 — 실존 도메인이면 시연 중 **실제 주소로 메일이 나간다.**

    이 계정은 가입 확인·비밀번호 재설정 흐름을 타게 될 수 있고, 그 메일이 남의
    주소로 가면 되돌릴 수 없다.
    """
    assert DEMO_USER_EMAIL.endswith(".local")


def test_verified_at_is_filled():
    """인증 시각을 채운다 — 비우면 시연 중 인증 안내가 뜬다.

    이 계정은 **로그인 화면을 통과하기 위한 것**이지 인증 흐름을 보여 주기 위한
    것이 아니다. 인증 메일은 실제 주소로 가입해 확인한다 (`#693`).
    """
    assert DEMO_USER_VERIFIED_AT is not None


# --- 시드 동작 (DB) --------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_account_can_actually_log_in(conn: AsyncConnection):
    """**저장된 해시가 그 비밀번호로 검증된다.**

    행이 들어갔는지만 보면 부족하다 — 해시가 다른 값에서 나왔거나 평문이 그대로
    들어가도 행 수는 같다. 로그인 경로가 실제로 쓰는 :func:`verify_password`로 본다.
    """
    await seed_demo_user(conn)

    row = (
        await conn.execute(
            text(
                "SELECT password_hash, display_name, email_verified_at "
                "FROM app_user WHERE email = :email AND is_deleted = false"
            ),
            {"email": DEMO_USER_EMAIL},
        )
    ).first()

    assert row is not None, "시드가 계정을 만들지 않았다"
    assert verify_password(DEMO_USER_PASSWORD, row.password_hash)
    assert row.display_name == DEMO_USER_DISPLAY_NAME
    assert row.email_verified_at is not None


@pytest.mark.asyncio
async def test_plaintext_password_is_not_stored(conn: AsyncConnection):
    """평문은 저장하지 않는다 (`DB_SCHEMA §2.15`)."""
    await seed_demo_user(conn)

    stored = await conn.scalar(
        text("SELECT password_hash FROM app_user WHERE email = :email"),
        {"email": DEMO_USER_EMAIL},
    )

    assert stored != DEMO_USER_PASSWORD
    assert stored.startswith("$argon2"), stored[:20]


@pytest.mark.asyncio
async def test_reseeding_does_not_add_a_second_row(conn: AsyncConnection):
    """다시 돌려도 늘지 않는다 — ``ON CONFLICT DO NOTHING``.

    시연 중 ``demo_up.sh``를 여러 번 돌리는 것이 정상이다. 그때마다 행이 늘면
    이메일 UNIQUE에 걸려 **시드 전체가 실패한다.**
    """
    await seed_demo_user(conn)
    first = await _count(conn)

    added = await seed_demo_user(conn)

    assert added == 0, "이미 있는데 새로 넣었다고 보고했다"
    assert await _count(conn) == first


@pytest.mark.asyncio
async def test_existing_row_is_not_overwritten(conn: AsyncConnection):
    """사람이 비밀번호를 바꿨으면 **그 변경이 살아남는다.**

    시드가 덮어쓰면 「고쳐 뒀는데 다시 돌아왔다」가 된다 — `#587`이 선박 제원에서
    같은 원칙을 세웠다(``ON CONFLICT DO NOTHING``은 의도된 것이다).
    """
    await seed_demo_user(conn)
    await conn.execute(
        text("UPDATE app_user SET display_name = :name WHERE email = :email"),
        {"name": "사람이 고친 이름", "email": DEMO_USER_EMAIL},
    )

    await seed_demo_user(conn)

    kept = await conn.scalar(
        text("SELECT display_name FROM app_user WHERE email = :email"),
        {"email": DEMO_USER_EMAIL},
    )
    assert kept == "사람이 고친 이름"


@pytest.mark.asyncio
async def test_production_does_not_get_the_account(
    conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
):
    """``APP_ENV=production``에서는 만들지 않는다 — **이 이슈의 보안 조건**이다.

    고정 비밀번호를 가진 계정이 프로덕션에 있으면 그 값이 알려진 순간 누구나
    들어온다. ``dev-login`` 라우트가 프로덕션에서 등록되지 않는 것과 같은 성격이다.
    """
    from cii_platform.db import demo_seed as seed_module

    await conn.execute(
        text("DELETE FROM app_user WHERE email = :email"), {"email": DEMO_USER_EMAIL}
    )

    import cii_platform.config as config_module

    monkeypatch.setattr(config_module, "is_production", lambda: True)

    added = await seed_module.seed_demo_user(conn)

    assert added == 0
    assert await _count(conn) == 0, "프로덕션인데 계정이 만들어졌다"


@pytest.mark.asyncio
async def test_missing_account_is_reported(conn: AsyncConnection):
    """없으면 없다고 말한다 — ``demo_up.sh --check``가 이 판정을 쓴다.

    계정이 사라진 상태는 **오류가 아니라 로그인 실패로만 드러난다.** 시연 도중에
    처음 알면 늦다.
    """
    await conn.execute(
        text("DELETE FROM app_user WHERE email = :email"), {"email": DEMO_USER_EMAIL}
    )
    assert await demo_user_missing(conn) is True

    await seed_demo_user(conn)
    assert await demo_user_missing(conn) is False


@pytest.mark.asyncio
async def test_soft_deleted_account_counts_as_missing(conn: AsyncConnection):
    """``is_deleted``면 없는 것으로 본다.

    이메일 UNIQUE가 ``is_deleted = false``에만 걸려 있어(`DB_SCHEMA §2.15`) 삭제된
    행은 로그인에 쓰이지 않는다. 그것을 「있다」로 세면 **점검이 거짓말을 한다.**
    """
    await seed_demo_user(conn)
    await conn.execute(
        text("UPDATE app_user SET is_deleted = true WHERE email = :email"),
        {"email": DEMO_USER_EMAIL},
    )

    assert await demo_user_missing(conn) is True


@pytest.mark.asyncio
async def test_uuid_is_fixed(conn: AsyncConnection):
    """PK가 고정 상수다.

    ``uuid4()``를 쓰면 시드를 다시 돌릴 때마다 PK가 달라져 ``ON CONFLICT``가 이메일
    UNIQUE에서만 걸린다 — ``auth_dev.py``가 `#308`에서 같은 이유로 고정 UUID를 쓴다.
    """
    await seed_demo_user(conn)

    stored = await conn.scalar(
        text("SELECT id FROM app_user WHERE email = :email"), {"email": DEMO_USER_EMAIL}
    )
    assert str(stored) == DEMO_USER_ID


async def _count(conn: AsyncConnection) -> int:
    return await conn.scalar(
        text("SELECT count(*) FROM app_user WHERE email = :email"),
        {"email": DEMO_USER_EMAIL},
    )
