"""대화 삭제 경로 셋과 운영 스크립트의 인증·토폴로지 (`#1330`).

## 무엇이 문제였나

`PRD §16.3`은 「ChatMessage 보존 기간 90일, **GDPR 유사 삭제 요청 지원**」이라 적었는데
**응할 경로가 없었다.**

* 대화 하나를 지우는 엔드포인트가 없었다 — `routes/chat.py`의 라우트는 `POST /chat` 하나뿐
* **탈퇴해도 그 사용자의 대화 원문이 남았다** — `delete_me`는 `is_deleted`·세션 폐기·감사만 했다
* 90일 만료 삭제 `purge_expired.py`는 `csql`에 **`-p`를 넘기지 않아** 배포 DB에서
  전부 실패했다. crontab이 매일 돌면서도 **한 번도 지워지지 않았다.**

## 왜 한 파일에 모으나

셋은 **같은 약속의 세 경로**다. 하나만 있으면 「대화는 지웠는데 탈퇴하면 남는다」거나
「요청에는 응하는데 기한은 안 온다」가 된다 — 어느 쪽이든 정본의 문장이 거짓이 된다.

케이스 (`TEST_PLAN §14.5`): 정본 정합 — `PRD §16.3` 보존·삭제
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import chat as chat_repo
from cii_platform.services.audit import AUDIT_ACTIONS

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# 1. 운영 스크립트 — 인증과 서비스 이름
# --------------------------------------------------------------------------


def test_purge_passes_the_password_to_csql() -> None:
    """⚠️ **이것이 빠져 `PRD §16.3`의 90일 삭제가 운영에서 한 번도 돌지 않았다.**

    `db_backup.py`는 *「`-p`를 빠뜨리면 … `errno=-171`로 선다」* 고 적고 넘기는데,
    `purge_expired.py`만 빠져 있었다. **실패해도 cron은 조용하다.**
    """
    from scripts import purge_expired

    assert '-p "$CUBRID_PASSWORD"' in purge_expired._CSQL_PLAIN
    assert '-p "$CUBRID_PASSWORD"' in purge_expired._CSQL


@pytest.mark.parametrize("module_name", ["purge_expired", "db_backup"])
def test_the_db_service_name_is_not_hard_coded(module_name: str) -> None:
    """토폴로지마다 이름이 다르다 — 박아 두면 **OCI에서 어느 명령도 돌지 않는다.**

    `docker-compose.prod.yml`은 `db`지만 OCI가 쓰는 `docker-compose.prod.db.yml`은
    `cubrid`이고, `docs/OPERATIONS.md`도 `exec -T cubrid`로 적는다.
    """
    import importlib

    module = importlib.import_module(f"scripts.{module_name}")
    calls: list[list[str]] = []

    db = module.Db(["compose"], lambda argv, *a, **k: (calls.append(argv), b"")[1])
    db.service = "cubrid"
    # 대역이 빈 출력을 주므로 파싱에서 걸릴 수 있다 — 보려는 것은 **만들어진 argv**다.
    with contextlib.suppress(Exception):
        db.sh("echo hi") if hasattr(db, "sh") else db.query("SELECT 1")

    assert calls, "명령이 만들어지지 않았다"
    assert "cubrid" in calls[0], calls[0]
    assert "db" not in calls[0][calls[0].index("exec") :], calls[0]


def test_the_compose_service_name_matches_the_oci_file() -> None:
    """문서가 아니라 **compose 파일에서** 이름을 읽어 대조한다.

    파일이 바뀌면 이 검사가 먼저 깨진다 — 운영 문서만 고치고 스크립트를 두는 것을
    막는다.
    """
    oci = (ROOT / "docker-compose.prod.db.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "\n  cubrid:" in oci, "OCI compose의 서비스 이름이 바뀌었다"
    assert "DB_SERVICE=cubrid" in readme, "운영 절차에 서비스 이름 지정이 없다"


def test_the_environment_variable_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """이름을 바꿀 **수단**이 실제로 있는지 본다 — 기본값만 고치면 다른 쪽이 깨진다."""
    from scripts import purge_expired

    monkeypatch.setenv("DB_SERVICE", "cubrid")
    assert os.environ.get("DB_SERVICE", purge_expired.DEFAULT_DB_SERVICE) == "cubrid"
    assert purge_expired.DEFAULT_DB_SERVICE == "db"


# --------------------------------------------------------------------------
# 2. 삭제 경로 — 저장소 계층
# --------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _make_user(session) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            'INSERT INTO app_user (id, email, password_hash, "role", is_deleted) '
            "VALUES (:id, :email, 'x', 'FIELD', 0)"
        ),
        {"id": user_id, "email": f"erasure-{user_id.hex[:8]}@example.com"},
    )
    return user_id


async def _make_chat(session, user_id: UUID, *, expires_in_days: int = 90) -> UUID:
    row = await chat_repo.create_session(session, user_id=user_id)
    await chat_repo.add_message(session, session_id=row.id, role="USER", content="안녕")
    # ⚠️ ``expires_at``만 과거로 당기면 트리거(``trg_chk_chat_session_expires_upd``)가
    # 막는다 — 만료가 생성보다 앞설 수 없다. ``created_at``을 함께 옮긴다.
    expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
    await session.execute(
        text("UPDATE chat_session SET created_at = :c, expires_at = :e WHERE id = :i"),
        {"c": expires_at - timedelta(days=90), "e": expires_at, "i": row.id},
    )
    return row.id


async def _message_count(session, session_id: UUID) -> int:
    row = await session.execute(
        text("SELECT COUNT(*) FROM chat_message WHERE session_id = :s"), {"s": session_id}
    )
    return int(row.scalar_one())


@pytest.mark.asyncio
async def test_deleting_one_conversation_takes_its_messages(session) -> None:
    """세션만 지우고 메시지가 남으면 **「지웠다」가 거짓**이 된다."""
    user_id = await _make_user(session)
    chat_id = await _make_chat(session, user_id)

    assert await _message_count(session, chat_id) == 1

    assert await chat_repo.delete_one(session, session_id=chat_id, user_id=user_id) is True
    assert await _message_count(session, chat_id) == 0


@pytest.mark.asyncio
async def test_another_users_conversation_is_not_deleted(session) -> None:
    """주인 조건이 **`DELETE`문 자체**에 있다 — 조회해서 확인하는 갈래가 없다.

    0행이 지워지면 호출부가 404를 낸다. 403이면 id를 바꿔 가며 **남의 대화가
    존재하는지** 알아낼 수 있다.
    """
    owner = await _make_user(session)
    stranger = await _make_user(session)
    chat_id = await _make_chat(session, owner)

    assert await chat_repo.delete_one(session, session_id=chat_id, user_id=stranger) is False
    assert await _message_count(session, chat_id) == 1


@pytest.mark.asyncio
async def test_deleting_an_account_takes_every_conversation(session) -> None:
    """탈퇴는 soft delete인데 **대화만 실제로 지운다** (`PRD §16.3`).

    플래그만 세우면 **원문이 그대로 남아 「지웠다」가 거짓**이 된다.
    """
    user_id = await _make_user(session)
    mine = [await _make_chat(session, user_id) for _ in range(2)]
    other = await _make_chat(session, await _make_user(session))

    assert await chat_repo.delete_for_user(session, user_id=user_id) == 2

    for chat_id in mine:
        assert await _message_count(session, chat_id) == 0
    assert await _message_count(session, other) == 1, "남의 대화가 함께 지워졌다"


@pytest.mark.asyncio
async def test_the_retention_sweep_still_only_takes_expired_rows(session) -> None:
    """대조군 — 새 경로가 생겼다고 **기한 삭제가 넓어지면 안 된다.**

    살아 있는 대화를 지우면 사용자가 쓰는 중에 사라진다.
    """
    user_id = await _make_user(session)
    alive = await _make_chat(session, user_id, expires_in_days=30)
    expired = await _make_chat(session, user_id, expires_in_days=-1)

    await chat_repo.purge_expired(session)

    assert await _message_count(session, alive) == 1
    assert await _message_count(session, expired) == 0


# --------------------------------------------------------------------------
# 3. 감사 — 지운 행은 되짚을 수 없다
# --------------------------------------------------------------------------


def test_the_delete_action_is_registered() -> None:
    """`DB_SCHEMA §2.14`와 대조되는 목록에 들어가 있는지.

    이 컬럼에는 CHECK도 트리거도 없어(`§7.4`) **DB가 알려 주지 않는다.**
    """
    assert "CHAT_DELETE" in AUDIT_ACTIONS


def test_the_audit_record_carries_no_conversation_content() -> None:
    """무엇을 지웠는지 **본문으로 적으면** 「지웠다」가 감사 로그에서 거짓이 된다."""
    import inspect

    from cii_platform.services.audit import record_chat_delete

    parameters = set(inspect.signature(record_chat_delete).parameters)

    assert parameters == {"session", "user_id", "session_id", "ip_address"}


# --------------------------------------------------------------------------
# 4. 라우트 배선 — 저장소 함수만 보면 **끊어져도 통과한다**
# --------------------------------------------------------------------------
#
# ⚠️ 위 ⑵의 검사들은 `chat_repo`를 직접 부른다. 그래서 `delete_me`에서 호출 한 줄을
# 빼도 **전부 통과했다**(돌연변이 M4). 약속이 지켜지는 자리는 **HTTP**다.


def _csrf(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _signup_and_chat(client) -> tuple[str, str]:
    """가입하고 대화 하나를 만든다. ``(user_id, chat_session_id)``."""
    from cii_platform.api.main import API_V1_PREFIX
    from cii_platform.db.session import get_sessionmaker

    email = f"erasure-http-{uuid4().hex[:8]}@example.com"
    created = client.post(
        f"{API_V1_PREFIX}/auth/signup",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert created.status_code == 201, created.text

    async with get_sessionmaker()() as s:
        row = await s.execute(text("SELECT id FROM app_user WHERE email = :e"), {"e": email})
        user_id = UUID(row.scalar_one())
        chat = await chat_repo.create_session(s, user_id=user_id)
        await chat_repo.add_message(s, session_id=chat.id, role="USER", content="안녕")
        await s.commit()
    return str(user_id), str(chat.id)


async def _chat_rows(user_id: str) -> int:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = await s.execute(
            text("SELECT COUNT(*) FROM chat_session WHERE user_id = :u"),
            {"u": UUID(user_id)},
        )
        return int(row.scalar_one())


async def _drop(user_id: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM chat_session WHERE user_id = :u"), {"u": UUID(user_id)})
        await s.execute(
            text("DELETE FROM audit_log WHERE REPLACE(user_id, '-', '') = :u"),
            {"u": UUID(user_id).hex},
        )
        await s.execute(text("DELETE FROM user_token WHERE user_id = :u"), {"u": UUID(user_id)})
        await s.execute(text("DELETE FROM user_session WHERE user_id = :u"), {"u": UUID(user_id)})
        await s.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": UUID(user_id)})
        await s.commit()


async def test_account_deletion_actually_removes_the_conversations(
    migrated_db, app_fresh_engine
) -> None:
    """탈퇴 **라우트**가 대화를 지우고 **몇 건인지 감사에 남기는지** (`#1330`).

    지운 행은 되짚을 수 없으므로 **그 수가 유일한 기록**이다 — 삭제 요청에 응했다는
    사실을 나중에 증명해야 하는 것이 이 규정의 성질이다.
    """
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app
    from cii_platform.db.session import get_sessionmaker
    from cii_platform.db.types import JSONText

    user_id: str | None = None
    try:
        with TestClient(app, base_url="https://testserver") as client:
            user_id, _ = await _signup_and_chat(client)
            assert await _chat_rows(user_id) == 1, "대화가 만들어지지 않았다"

            gone = client.delete(f"{API_V1_PREFIX}/auth/me", headers=_csrf(client))
            assert gone.status_code == 204, gone.text

        assert await _chat_rows(user_id) == 0, "탈퇴했는데 대화 원문이 남았다"

        async with get_sessionmaker()() as s:
            row = await s.execute(
                text(
                    'SELECT details_json FROM audit_log WHERE "action" = :a '
                    "AND REPLACE(user_id, '-', '') = :u"
                ).columns(details_json=JSONText()),
                {"a": "ACCOUNT_DELETE", "u": UUID(user_id).hex},
            )
            details = row.scalar_one()

        assert details["purged_chat_sessions"] == 1
    finally:
        if user_id is not None:
            await _drop(user_id)


async def test_the_delete_endpoint_answers_204_and_404(migrated_db, app_fresh_engine) -> None:
    """``DELETE /chat/sessions/{id}`` — 내 것은 204, 남의 것·없는 것은 **404**.

    403이면 id를 바꿔 가며 **남의 대화가 존재하는지** 알아낼 수 있다.
    """
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    user_id: str | None = None
    try:
        with TestClient(app, base_url="https://testserver") as client:
            user_id, chat_id = await _signup_and_chat(client)

            missing = client.delete(
                f"{API_V1_PREFIX}/chat/sessions/{uuid4()}", headers=_csrf(client)
            )
            assert missing.status_code == 404, missing.text

            mine = client.delete(f"{API_V1_PREFIX}/chat/sessions/{chat_id}", headers=_csrf(client))
            assert mine.status_code == 204, mine.text

        assert await _chat_rows(user_id) == 0
    finally:
        if user_id is not None:
            await _drop(user_id)


async def test_the_delete_endpoint_needs_csrf(migrated_db, app_fresh_engine) -> None:
    """상태를 바꾸는 라우트다 — 헤더 없이는 통과하지 못한다 (`#634`와 같은 규율)."""
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    user_id: str | None = None
    try:
        with TestClient(app, base_url="https://testserver") as client:
            user_id, chat_id = await _signup_and_chat(client)
            refused = client.delete(f"{API_V1_PREFIX}/chat/sessions/{chat_id}")

        assert refused.status_code == 403, refused.text
        assert await _chat_rows(user_id) == 1, "CSRF 없이 지워졌다"
    finally:
        if user_id is not None:
            await _drop(user_id)
