"""활성 키 열 + 유니크 인덱스 — 동시 중복 등록을 계약된 409로 (TEST_PLAN §3.9 · §4.7 · §5.6, #1631).

## 무엇이 문제였나

활성 IMO·이메일의 유일성을 `047`이 **트리거**(`BEFORE INSERT … IF NOT (… NOT EXISTS …)
EXECUTE REJECT`)로 걸어 두었는데, 트리거 안의 `NOT EXISTS`는 일반 `SELECT`와 같은
READ COMMITTED 스냅샷을 본다(`#1796`). 두 요청이 같은 키를 거의 동시에 넣으면 서로의
미커밋 행을 보지 못해 **둘 다 통과**했고, 같은 IMO 행이 조용히 두 개 남았다 — 예외조차
없었다(`#1631` 2026-09-23 실측 · 결과 `['B:ok', 'A:ok']` · 남은 행 2).

## 무엇으로 막는가

`061`이 활성 키 열(`vessel.imo_active` · `app_user.email_active` — 활성이면 원본의 사본,
삭제면 NULL)을 두고 **유니크 인덱스**를 건다. CUBRID 유니크 인덱스는 NULL을 여러 개
허용하므로 삭제된 행이 몇 개든 같은 키를 다시 쓸 수 있고, 활성 행끼리만 유일하다.
값은 앱이 아니라 DB의 `AFTER INSERT/UPDATE` 트리거가 채운다.

## 세 층을 따로 잠근다

1. **DB 층**(`conn` 롤백 세션) — 트리거가 값을 채우고 비우는가 · NULL 다중 허용 · 활성
   중복은 `IntegrityError`이며 `violated_unique_index`가 **인덱스 이름**을 집는가.
2. **경합 층**(세션 둘 · 각자 커밋) — 서비스가 커밋하기 **전에** 두 번째가 끼어들어야
   돌연변이(인덱스 제거 · 예외 변환 제거)가 검출된다. `test_auth_tokens.py`의 두 세션
   교차 틀과 같다.
3. **계약 층** — 경합의 패자가 받는 것이 사전 조회와 **같은 409·같은 문구**인가 ·
   중복이 아닌 무결성 위반은 409로 둔갑하지 않는가.

⚠️ 경합 검사는 `conn` fixture를 쓰지 않는다 — 한 트랜잭션 안에서는 경합이 일어나지 않는다.
"""

from __future__ import annotations

import asyncio
import threading
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.main import app
from cii_platform.api.routes import auth as auth_routes
from cii_platform.api.routes.auth import EMAIL_TAKEN_MESSAGE
from cii_platform.db.cubrid_errors import violated_unique_index
from cii_platform.errors import ConflictError
from cii_platform.services import vessel as vessel_service
from cii_platform.services.vessel import DUPLICATE_IMO_MESSAGE, create_vessel

_BASE = "https://testserver"
PASSWORD = "correct-horse-battery"

#: 데모 시드와 겹치지 않는 IMO — 시드는 `db/demo_seed.py`의 4척뿐이다.
IMO = "9163100"
RACE_IMO = "9163101"
RACE_EMAIL = "race-signup@example.com"


# ─────────────────────────────────────────────────────────────────────────────
# 1. DB 층 — 값은 DB가 채우고, 유일성은 인덱스가 갖는다 (DB-SOFT-003 · 005)
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _insert_vessel(
    session: AsyncSession, *, imo: str, is_deleted: bool = False, imo_active: str | None = None
) -> str:
    """서비스를 지나지 않는 INSERT — 트리거·인덱스만 본다. ``imo_active``는 일부러 넣을 수 있다."""
    vessel_id = uuid4().hex
    await session.execute(
        text(
            "INSERT INTO vessel "
            "(id, imo_number, name, ship_type, deadweight, is_deleted, imo_active) "
            "VALUES (:id, :imo, 'ACTIVE KEY', 'BULK_CARRIER', 50000, :deleted, :active)"
        ),
        {"id": vessel_id, "imo": imo, "deleted": is_deleted, "active": imo_active},
    )
    return vessel_id


async def _vessel_active_key(session: AsyncSession, vessel_id: str) -> str | None:
    row = await session.execute(
        text("SELECT imo_active FROM vessel WHERE id = :id"), {"id": vessel_id}
    )
    return row.scalar_one()


async def _insert_user(session: AsyncSession, *, email: str, is_deleted: bool = False) -> str:
    user_id = uuid4().hex
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, password_hash, is_deleted) "
            "VALUES (:id, :email, 'x', :deleted)"
        ),
        {"id": user_id, "email": email, "deleted": is_deleted},
    )
    return user_id


async def _user_active_key(session: AsyncSession, user_id: str) -> str | None:
    row = await session.execute(
        text("SELECT email_active FROM app_user WHERE id = :id"), {"id": user_id}
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_insert_fills_the_active_key_without_the_app_writing_it(session):
    """DB-SOFT-003 — 앱이 넣지 않아도(NULL) 트리거가 `imo_number`를 복사한다.

    트리거의 자기 갱신이 `updated_at`을 밀지 않는다 — 049의 `ON UPDATE CURRENT_DATETIME`
    열 속성이 그 UPDATE에 반응하면 **방금 만든 행의 수정일이 생성일보다 앞선다.**
    """
    vessel_id = await _insert_vessel(session, imo=IMO)
    assert await _vessel_active_key(session, vessel_id) == IMO

    stamps = (
        await session.execute(
            text("SELECT created_at, updated_at FROM vessel WHERE id = :id"), {"id": vessel_id}
        )
    ).one()
    assert stamps.created_at == stamps.updated_at, (
        f"채움 트리거가 updated_at을 밀었다: {stamps.created_at} → {stamps.updated_at}"
    )


@pytest.mark.asyncio
async def test_soft_delete_clears_the_key_and_restore_refills_it(session):
    """DB-SOFT-003 — 삭제하면 NULL, 되살리면 다시 값. 「자리를 비운다」의 실체다."""
    vessel_id = await _insert_vessel(session, imo=IMO)

    await session.execute(
        text("UPDATE vessel SET is_deleted = 1 WHERE id = :id"), {"id": vessel_id}
    )
    assert await _vessel_active_key(session, vessel_id) is None

    await session.execute(
        text("UPDATE vessel SET is_deleted = 0 WHERE id = :id"), {"id": vessel_id}
    )
    assert await _vessel_active_key(session, vessel_id) == IMO


@pytest.mark.asyncio
async def test_imo_change_moves_the_active_key(session):
    """DB-SOFT-003 — 원본이 바뀌면 활성 키도 따라간다. 옛 키가 남으면 옛 IMO를 영영 못 쓴다."""
    vessel_id = await _insert_vessel(session, imo=IMO)

    await session.execute(
        text("UPDATE vessel SET imo_number = '9163199' WHERE id = :id"), {"id": vessel_id}
    )

    assert await _vessel_active_key(session, vessel_id) == "9163199"


@pytest.mark.asyncio
async def test_a_wrong_explicit_value_is_corrected_by_the_db(session):
    """DB-SOFT-003 — 값의 소유자는 DB다. 앱·시드·수동 SQL이 엉뚱한 값을 넣어도 바로잡는다."""
    vessel_id = await _insert_vessel(session, imo=IMO, imo_active="WRONG")
    assert await _vessel_active_key(session, vessel_id) == IMO


@pytest.mark.asyncio
async def test_many_deleted_rows_share_the_imo_with_one_active_row(session):
    """DB-SOFT-005 — 삭제 행 셋 + 활성 하나. NULL은 유니크 인덱스에서 서로 충돌하지 않는다.

    이 검사가 없으면 「NULL을 하나만 허용하는」 인덱스로 바꿔도 위 검사들이 통과한다 —
    두 번째 삭제에서만 드러난다.
    """
    for _ in range(3):
        await _insert_vessel(session, imo=IMO, is_deleted=True)
    await _insert_vessel(session, imo=IMO)

    count = await session.execute(
        text("SELECT count(*) FROM vessel WHERE imo_number = :imo"), {"imo": IMO}
    )
    assert count.scalar_one() == 4


@pytest.mark.asyncio
async def test_second_active_vessel_with_the_same_imo_names_the_index(session):
    """DB-SOFT-002 보강 — 위반은 `IntegrityError`이고 인덱스 이름이 메시지에 있다.

    이름이 없으면 서비스가 「어느 유니크인가」를 못 가르고, FK·NOT NULL 위반까지 409로
    둔갑시키거나 중복을 500으로 흘린다.
    """
    await _insert_vessel(session, imo=IMO)

    with pytest.raises(IntegrityError) as caught:
        await _insert_vessel(session, imo=IMO)

    assert violated_unique_index(caught.value.orig) == vessel_service.DUPLICATE_IMO_INDEX


@pytest.mark.asyncio
async def test_app_user_email_active_is_filled_and_cleared(session):
    """DB-SOFT-003 — `app_user.email_active`도 같은 구조다."""
    user_id = await _insert_user(session, email="active-key@example.com")
    assert await _user_active_key(session, user_id) == "active-key@example.com"

    await session.execute(
        text("UPDATE app_user SET is_deleted = 1 WHERE id = :id"), {"id": user_id}
    )
    assert await _user_active_key(session, user_id) is None


@pytest.mark.asyncio
async def test_two_active_users_with_the_same_email_are_rejected_but_deleted_ones_are_not(session):
    """DB-SOFT-005 — 탈퇴 계정 둘 + 활성 하나는 되고, 활성 둘은 인덱스 이름과 함께 거부된다."""
    email = "twice@example.com"
    await _insert_user(session, email=email, is_deleted=True)
    await _insert_user(session, email=email, is_deleted=True)
    await _insert_user(session, email=email)

    with pytest.raises(IntegrityError) as caught:
        await _insert_user(session, email=email)

    assert violated_unique_index(caught.value.orig) == auth_routes.EMAIL_TAKEN_INDEX


# ─────────────────────────────────────────────────────────────────────────────
# 2·3. 경합 층 + 계약 층 — 한 요청만 저장, 나머지는 같은 409 (DB-SOFT-004 · AT-AUTH-019)
# ─────────────────────────────────────────────────────────────────────────────


async def _delete_vessel_rows(imo: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM vessel WHERE imo_number = :imo"), {"imo": imo})
        await s.commit()


async def _vessel_count(imo: str) -> int:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = await s.execute(
            text("SELECT count(*) FROM vessel WHERE imo_number = :imo"), {"imo": imo}
        )
        return int(row.scalar_one())


async def _register(session: AsyncSession, name: str) -> dict[str, object] | ConflictError:
    """성공하면 응답 dict, 중복이면 그 예외. 다른 예외는 그대로 올린다."""
    try:
        return await create_vessel(
            session, imo_number=RACE_IMO, name=name, ship_type="BULK_CARRIER", deadweight=50000
        )
    except ConflictError as exc:
        return exc


class TestConcurrentVesselRegistration:
    """DB-SOFT-004 — 같은 IMO를 두 세션이 교차해 등록하면 **정확히 하나만** 남는다.

    첫 세션은 INSERT(flush)를 마친 채 **커밋을 미룬다** — 그 사이 두 번째가 사전 조회
    (남의 미커밋 행은 보이지 않는다)를 지나 INSERT에 이르고, 유니크 인덱스에서 첫
    세션의 커밋까지 기다렸다가 위반으로 떨어진다. 서비스는 그것을 사전 조회와 같은
    409·같은 문구로 바꾼다.

    유니크 인덱스를 빼면 둘 다 성공해 행이 2개(2026-09-23 실측 그대로), 예외 변환을 빼면
    패자가 `IntegrityError`로 새어 이 검사가 실패한다. 교차가 실제로 「flush 뒤 커밋 전」
    에서 났는지는 `vessel_repo.insert` 스파이로 단언한다 — 둘 다 INSERT에 이르러야 한다.
    """

    async def test_two_sessions_leave_one_vessel_and_the_loser_gets_the_same_409(
        self, migrated_db, app_fresh_engine, monkeypatch
    ):
        from cii_platform.db.session import get_sessionmaker

        maker = get_sessionmaker()
        await _delete_vessel_rows(RACE_IMO)
        first_flushed = asyncio.Event()
        second_at_insert = asyncio.Event()
        inserts = {"n": 0}
        real_insert = vessel_service.vessel_repo.insert

        async def counting_insert(session, **fields):
            # 여기 닿았다는 것은 사전 조회를 **지났다**는 뜻이다 — 두 번째가 사전 조회의
            # 409로 끝나면 이 수가 1이라 아래 단언이 잡는다.
            inserts["n"] += 1
            if inserts["n"] == 2:
                second_at_insert.set()
            return await real_insert(session, **fields)

        monkeypatch.setattr(vessel_service.vessel_repo, "insert", counting_insert)
        outcomes: dict[str, object] = {}
        try:

            async def first() -> None:
                async with maker() as s:
                    real_commit = s.commit

                    async def held_commit() -> None:
                        # flush는 끝났다(행 잠금을 쥔 상태). 두 번째가 INSERT에 이를 때까지
                        # 커밋을 미룬다 — 이벤트로 교차를 확정하고, 그 INSERT가 유니크
                        # 인덱스에서 실제로 대기에 들어갈 짧은 틈만 준다.
                        first_flushed.set()
                        await asyncio.wait_for(second_at_insert.wait(), timeout=10)
                        await asyncio.sleep(0.2)
                        await real_commit()

                    s.commit = held_commit  # type: ignore[method-assign]
                    outcomes["first"] = await _register(s, "FIRST")

            async def second() -> None:
                await first_flushed.wait()
                async with maker() as s:
                    outcomes["second"] = await _register(s, "SECOND")

            await asyncio.gather(first(), second())

            # 둘 다 INSERT에 이르렀다 — 경합이 실제로 「flush 뒤 커밋 전」에서 일어났다.
            assert inserts["n"] == 2, inserts
            winners = [v for v in outcomes.values() if isinstance(v, dict)]
            losers = [v for v in outcomes.values() if isinstance(v, ConflictError)]
            assert len(winners) == 1 and len(losers) == 1, outcomes
            assert winners[0]["imo_number"] == RACE_IMO
            # 계약 — 사전 조회가 내는 것과 **같은 문구**. 사용자가 보낸 자기 IMO만 담는다.
            assert losers[0].code == "CONFLICT"
            assert losers[0].message == DUPLICATE_IMO_MESSAGE.format(imo_number=RACE_IMO)
            # 잠금이 없거나 인덱스가 없으면 여기가 2다.
            assert await _vessel_count(RACE_IMO) == 1
        finally:
            await _delete_vessel_rows(RACE_IMO)


@pytest.mark.asyncio
async def test_other_integrity_errors_are_not_disguised_as_duplicates(session, monkeypatch):
    """계약 — 중복이 아닌 무결성 위반은 409로 둔갑하지 않는다 (#1631 완료 기준).

    `insert`가 **다른 인덱스**의 위반을 올리게 흉내 낸다. 서비스가 인덱스 이름을 보지 않고
    `IntegrityError`를 통째로 409로 바꾸면 여기서 `ConflictError`가 나와 실패한다.
    """

    class _Driver(Exception):
        pass

    orig = _Driver(
        "Operation would have caused one or more unique constraint violations. "
        "INDEX idx_some_other_unique(B+tree: 1|1|1) ON CLASS dba.vessel(CLASS_OID: 0|1|1). "
        "(errno=-670, description='Unique constraint violation', sqlstate='23000')"
    )

    async def failing_insert(_session, **_fields):
        raise IntegrityError("INSERT INTO vessel …", {}, orig)

    monkeypatch.setattr(vessel_service.vessel_repo, "insert", failing_insert)

    with pytest.raises(IntegrityError):
        await create_vessel(
            session, imo_number=IMO, name="OTHER", ship_type="BULK_CARRIER", deadweight=50000
        )


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


async def _delete_user_rows(email: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        for table in ("user_token", "user_session"):
            await s.execute(
                text(
                    f"DELETE FROM {table} WHERE user_id IN "
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": email},
            )
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": email})
        await s.commit()


async def _user_count(email: str) -> int:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        row = await s.execute(text("SELECT count(*) FROM app_user WHERE email = :e"), {"e": email})
        return int(row.scalar_one())


class TestConcurrentSignup:
    """AT-AUTH-019 — 같은 이메일로 거의 동시에 가입하면 **한쪽만 201**, 다른 쪽은 409·정본 문구.

    첫 요청은 `flush` 뒤 `_issue_session`에서 **커밋 전에 머문다**(가로챈 자리) — 그 사이
    두 번째 요청이 중복 확인(미커밋 행은 보이지 않는다)을 지나 `flush`에서 유니크
    인덱스에 걸려 첫 요청의 커밋까지 기다렸다가 위반으로 떨어진다. 라우트는 그것을 중복
    확인과 같은 409로 바꾼다. 요청은 스레드 둘에서 보낸다 — TestClient는 동기라 한
    스레드로는 교차가 일어나지 않는다.
    """

    async def test_two_requests_leave_one_account_and_the_loser_gets_409(self, client, monkeypatch):
        await _delete_user_rows(RACE_EMAIL)
        gate = threading.Event()
        original = auth_routes._issue_session
        real_is_initial_admin = auth_routes.is_initial_admin
        calls = {"n": 0, "past_precheck": 0}

        def counting_is_initial_admin(email: str) -> bool:
            # 라우트는 중복 확인을 **지난 뒤** `AppUser(...)`의 역할 인자로 이것을 부른다 —
            # 두 번째 요청이 사전 확인의 409로 끝나면 이 수가 1에 머문다.
            calls["past_precheck"] += 1
            return real_is_initial_admin(email)

        async def held_issue_session(session, request, user):
            calls["n"] += 1
            if calls["n"] == 1:
                # 행 잠금을 쥔 채(flush 뒤 · 커밋 전) 두 번째 요청이 중복 확인을 지날 때까지
                # 머문다. 두 요청이 같은 포털 루프를 쓰므로 블로킹 대기가 아니라 폴링이다.
                gate.set()
                deadline = time.monotonic() + 10
                while calls["past_precheck"] < 2:
                    assert time.monotonic() < deadline, "두 번째 요청이 중복 확인에 이르지 못했다"
                    await asyncio.sleep(0.05)
                await asyncio.sleep(0.2)  # 그 flush가 유니크 인덱스에서 대기에 들어갈 틈
            return await original(session, request, user)

        monkeypatch.setattr(auth_routes, "is_initial_admin", counting_is_initial_admin)
        monkeypatch.setattr(auth_routes, "_issue_session", held_issue_session)

        def post():
            return client.post(
                "/api/v1/auth/signup", json={"email": RACE_EMAIL, "password": PASSWORD}
            )

        def post_after_the_first_flushed():
            assert gate.wait(10), "첫 요청이 flush에 이르지 못했다"
            return post()

        try:
            first, second = await asyncio.gather(
                asyncio.to_thread(post), asyncio.to_thread(post_after_the_first_flushed)
            )
            statuses = sorted([first.status_code, second.status_code])
            assert statuses == [201, 409], (first.text, second.text)
            loser = first if first.status_code == 409 else second
            body = loser.json()["error"]
            assert body["code"] == "CONFLICT"
            # 정본 문구 (PRD §6.3) — 사전 확인 경로와 같은 문장이어야 한다.
            assert body["message"] == EMAIL_TAKEN_MESSAGE
            # 둘 다 중복 확인을 지나 INSERT까지 갔고(경합이 실제로 일어났다), 두 번째는
            # 세션 발급에 이르지 못했다 — 가로챈 자리가 한 번만 불렸다.
            assert calls["past_precheck"] == 2, calls
            assert calls["n"] == 1
            assert await _user_count(RACE_EMAIL) == 1
        finally:
            await _delete_user_rows(RACE_EMAIL)
