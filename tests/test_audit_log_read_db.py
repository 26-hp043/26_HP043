"""감사 로그 조회 (`API_SPEC §16.1` · `#1241`).

## 무엇이 문제였나

`audit_log`는 **쌓이기만 하고 읽는 경로가 없었다** — `db/repositories/audit_log.py`에
`insert_event` **하나뿐**이었다. 누가 언제 무엇을 적재했는지 확인하려면 DB 직접
조회뿐이라, 규정 개정 이력을 묻는 질문에 제품 안에서 답할 수 없었다
(`IT-AUDIT-002` · `TEST_PLAN §14.5`).

`#673`이 `PARAMETER_IMPORT`로 **사용자·시각·종류·행 수·판본**을 남기게 해 두었는데,
**그 기록에 닿을 방법이 없었다.**

## 무엇을 단언하는가

「기록이 N건뿐」과 「아직 다 주지 않았다」가 **다른 모양**인가(`#1076`·`#1395`가 같은
자리를 고쳤다), 모르는 `action`이 **빈 목록이 아니라 422**인가(「없다」와 「잘못
물었다」는 다른 답이다), 현장직이 막히는가, 그리고 **조회가 쓰기를 막지 않는가**.

`#1515`가 **행위자**를 더했다 — `user_id`(UUID)만으로는 「누가 올렸나」에 답이 되지
않는다. `actor`가 이름·이메일로 풀리는가, **탈퇴(soft delete) 계정도** 풀리는가,
`app_user`에 없는 행위자는 **`null`**인가(빈 dict나 500이 아니라)를 본다.

케이스 (`TEST_PLAN §14.5`): IT-AUDIT-002 — 변경 경로 기록 열람

⚠️ **이 검사는 자기 행만 본다.** `audit_log`는 세션 seed·다른 검사가 함께 쓰는
표이고 삭제하지 않으므로, 전체 건수를 단언하면 **실행 순서에 따라 깨진다**.
전용 `entity_type`으로 심고 그 필터로만 읽는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from conftest import insert_returning_id
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import audit_log as audit_repo
from cii_platform.errors import ValidationError
from cii_platform.services import audit as audit_svc

#: 이 검사 전용 표식 — 다른 검사의 행과 섞이지 않게 한다.
MARK = "audit-read-probe"

#: 행위자 검사가 만드는 계정의 이메일 접두 — 뒷정리가 이 접두로 지운다.
ACTOR_EMAIL_PREFIX = "audit-actor-"


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def events(session):
    """`PARAMETER_IMPORT` 3건을 **시각을 벌려** 심는다.

    같은 시각이면 커서의 2차 키(`id`)만으로 순서가 갈려 **정렬 단언이 우연에
    기댄다.**
    """
    base = datetime(2026, 3, 1, tzinfo=UTC)
    ids = []
    for index in range(3):
        row_id = uuid4()
        ids.append(row_id)
        await session.execute(
            text(
                'INSERT INTO audit_log (id, "timestamp", user_id, "action", entity_type, '
                "entity_id, details_json, ip_address) VALUES (:id, :ts, :u, :a, :et, :eid, "
                ":d, '10.0.0.1')"
            ),
            {
                "id": row_id,
                "ts": base + timedelta(hours=index),
                "u": "probe-user",
                "a": "PARAMETER_IMPORT",
                "et": MARK,
                "eid": uuid4(),
                "d": f'{{"rows": {index + 1}, "version": "2026.03"}}',
            },
        )
    await session.commit()
    return ids


async def _read(session, **over):
    kwargs = {"entity_type": MARK}
    kwargs.update(over)
    return await audit_svc.list_events(session, **kwargs)


async def _insert_actor(session, *, display_name: str | None, deleted: bool) -> tuple[str, str]:
    """계정 한 명을 심고 ``(id 문자열, 이메일)``을 돌려준다. ``deleted``면 탈퇴 상태."""
    email = f"{ACTOR_EMAIL_PREFIX}{uuid4().hex[:8]}@example.com"
    raw_id = await insert_returning_id(
        session,
        "INSERT INTO app_user (email, password_hash, display_name, is_deleted) "
        "VALUES (:e, 'x', :dn, :del) RETURNING id",
        {"e": email, "dn": display_name, "del": 1 if deleted else 0},
    )
    # 감사 행의 `user_id`는 라우트가 `str(user.id)`로 적는다 — 하이픈 있는 모양이다.
    return str(UUID(raw_id)), email


async def _insert_event_by(session, user_id: str) -> None:
    await session.execute(
        text(
            'INSERT INTO audit_log (id, "timestamp", user_id, "action", entity_type, '
            "details_json, ip_address) VALUES (:id, :ts, :u, 'PARAMETER_IMPORT', :et, "
            "'{}', '10.0.0.1')"
        ),
        {"id": uuid4(), "ts": datetime(2026, 4, 1, tzinfo=UTC), "u": user_id, "et": MARK},
    )


@pytest_asyncio.fixture
async def actors(session):
    """현역 한 명·탈퇴 한 명을 심고 각자의 감사 행을 남긴다."""
    alive_id, alive_email = await _insert_actor(session, display_name="홍길동", deleted=False)
    gone_id, gone_email = await _insert_actor(session, display_name=None, deleted=True)
    await _insert_event_by(session, alive_id)
    await _insert_event_by(session, gone_id)
    await session.commit()
    return {
        "alive": (alive_id, alive_email),
        "gone": (gone_id, gone_email),
    }


@pytest.mark.asyncio
async def test_the_records_can_be_read_at_all(session, events) -> None:
    """**이것이 이 이슈다** — `#673`이 남긴 기록에 닿을 수 있는가."""
    rows, _ = await _read(session)

    assert len(rows) == 3
    assert {row["action"] for row in rows} == {"PARAMETER_IMPORT"}
    assert rows[0]["details"] == {"rows": 3, "version": "2026.03"}
    assert rows[0]["user_id"] == "probe-user"


@pytest.mark.asyncio
async def test_the_newest_comes_first(session, events) -> None:
    """이력은 **최근 것부터** 본다 — 「방금 무엇이 바뀌었나」가 첫 질문이다."""
    rows, _ = await _read(session)

    stamps = [row["timestamp"] for row in rows]
    assert stamps == sorted(stamps, reverse=True)


@pytest.mark.asyncio
async def test_a_partial_page_says_so(session, events) -> None:
    """「기록이 N건뿐」과 「아직 다 주지 않았다」가 **다른 모양**이어야 한다."""
    rows, page = await _read(session, limit=2)

    assert len(rows) == 2
    assert page["has_more"] is True
    assert page["next_cursor"]


@pytest.mark.asyncio
async def test_the_last_page_hands_back_no_cursor(session, events) -> None:
    """커서를 늘 채우면 클라이언트가 **같은 커서를 반복해 무한 루프**에 빠진다."""
    _, page = await _read(session, limit=10)

    assert page["has_more"] is False
    assert page["next_cursor"] is None


@pytest.mark.asyncio
async def test_the_cursor_continues_without_repeating(session, events) -> None:
    """이어 받은 페이지가 **앞 페이지를 다시 주지 않는지** 본다."""
    first, page = await _read(session, limit=2)
    second, _ = await _read(session, limit=2, cursor=page["next_cursor"])

    assert len(second) == 1
    assert {row["id"] for row in first}.isdisjoint({row["id"] for row in second})


@pytest.mark.asyncio
async def test_the_time_range_includes_both_ends(session, events) -> None:
    """「3월 1일까지」를 적은 사용자는 **그날의 사건**을 기대한다."""
    only_first, _ = await _read(
        session,
        since=datetime(2026, 3, 1, tzinfo=UTC),
        until=datetime(2026, 3, 1, tzinfo=UTC),
    )

    assert len(only_first) == 1


@pytest.mark.asyncio
async def test_an_unknown_action_is_refused(session) -> None:
    """빈 목록으로 답하면 사용자는 **「그런 사건이 없다」**로 읽는다.

    「없다」와 「잘못 물었다」는 다른 답이다.
    """
    with pytest.raises(ValidationError):
        await _read(session, action="PARAMETER_IMPORTT")


@pytest.mark.asyncio
async def test_a_broken_cursor_is_refused(session) -> None:
    """URL을 손댄 커서가 **500**이 되면 안 된다."""
    with pytest.raises(ValidationError):
        await _read(session, cursor="not-a-cursor")


@pytest.mark.asyncio
async def test_the_actor_is_resolved_to_a_name_and_an_email(session, actors) -> None:
    """**이것이 `#1515`의 감사 쪽이다** — UUID 옆에 사람이 선다. `user_id`는 그대로 남는다."""
    alive_id, alive_email = actors["alive"]
    rows, _ = await _read(session, user_id=alive_id)

    assert len(rows) == 1
    assert rows[0]["user_id"] == alive_id
    assert rows[0]["actor"] == {"display_name": "홍길동", "email": alive_email}


@pytest.mark.asyncio
async def test_a_deleted_account_still_resolves(session, actors) -> None:
    """탈퇴는 soft delete다.

    감사가 답할 질문은 「그때 누가 했는가」이지 「지금 누가 있는가」가 아니다.
    """
    gone_id, gone_email = actors["gone"]
    rows, _ = await _read(session, user_id=gone_id)

    assert len(rows) == 1
    assert rows[0]["actor"] == {"display_name": None, "email": gone_email}


@pytest.mark.asyncio
async def test_an_unknown_actor_is_null_not_an_error(session, events) -> None:
    """`app_user`에 없는 행위자(`probe-user` 같은 값)는 **`null`**이다 — 빈 dict도 500도 아니다.

    「없음」의 종류가 갈려야 한다: `null`은 「못 찾았다」, `display_name: null`은
    「찾았는데 이름을 안 적었다」다.
    """
    rows, _ = await _read(session)

    assert rows and all(row["actor"] is None for row in rows)
    assert all(row["user_id"] == "probe-user" for row in rows)


def test_the_cursor_round_trips() -> None:
    """인코딩이 값을 잃지 않는지 — 잃으면 다음 페이지가 조용히 어긋난다."""
    original = audit_repo.AuditCursor(datetime(2026, 3, 1, 12, 30, tzinfo=UTC), uuid4())

    assert audit_repo.decode_cursor(audit_repo.encode_cursor(original)) == original


@pytest.mark.asyncio
async def test_reading_does_not_block_writing(session, events) -> None:
    """`#1241` 완료 기준 ⑵ — 조회가 적재·계산을 방해하지 않는다.

    읽는 도중에 같은 표에 쓸 수 있어야 한다. 조회가 잠금을 잡으면 감사 자체가
    부담이 되고, 그러면 **기록을 줄이자는 압력**이 생긴다.
    """
    await _read(session)
    await audit_svc.record_account_delete(
        session, user_id="probe-user", revoked_sessions=1, ip_address="10.0.0.1"
    )
    await session.commit()

    rows, _ = await audit_svc.list_events(session, action="ACCOUNT_DELETE", user_id="probe-user")
    assert rows


async def test_the_route_answers_over_http(migrated_db, app_fresh_engine) -> None:
    """응답 봉투가 실제로 나가는지 (`#433`의 교훈 — 엔진에서 나오는 값이 응답에 안 나간 적이 있다).

    ⚠️ **현장직 403은 여기서 보지 않는다.** `tests/test_roles_db.py`가 `API_SPEC §1.2`
    「사무직 전용 경로」 표를 소스와 대조하며 **표의 모든 경로를 현장직으로 두드린다** —
    이 경로도 그 목록에 넣었다. 역할 하네스를 두 곳에 두면 한쪽만 고쳐진다.
    """
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
        ok = client.get(f"{API_V1_PREFIX}/audit-logs", params={"limit": 5})

    assert ok.status_code == 200, ok.text
    body = ok.json()

    assert isinstance(body["data"], list)
    assert len(body["data"]) <= 5, "limit이 지켜지지 않았다"
    assert "has_more" in body["meta"]
    assert "next_cursor" in body["meta"]


async def test_the_route_refuses_an_unknown_action_over_http(migrated_db, app_fresh_engine) -> None:
    """422다 — 200 + 빈 배열이면 화면이 「없다」고 적는다."""
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
        response = client.get(f"{API_V1_PREFIX}/audit-logs", params={"action": "NOPE"})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def _cleanup() -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM audit_log WHERE entity_type = :m"), {"m": MARK})
        await s.execute(text("DELETE FROM audit_log WHERE user_id = :u"), {"u": "probe-user"})
        await s.execute(
            text("DELETE FROM app_user WHERE email LIKE :p"), {"p": f"{ACTOR_EMAIL_PREFIX}%"}
        )
        await s.commit()


@pytest.fixture(autouse=True, scope="module")
def _module_marker():
    """심은 행을 남기지 않는다 — 다음 실행이 같은 표를 본다."""
    yield
    import asyncio

    with __import__("contextlib").suppress(Exception):
        asyncio.get_event_loop().run_until_complete(_cleanup())
