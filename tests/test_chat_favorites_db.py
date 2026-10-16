"""챗봇 답 즐겨찾기 끝에서 끝까지 (`#2405` · ``API_SPEC §15.9`` · IT-CHAT-089~095).

별은 ``chat_message.favorited_at`` 한 칸이다(``070``). 이 파일이 보는 것은 셋이다 —
⑴ 화면이 별을 달 **번호**가 두 응답(``POST /chat`` · 불러오기)에 실려 나가는가
⑵ 달기·떼기가 멱등이고 **내 것·살아 있는 답**에만 닿는가(그 밖은 모두 같은 404)
⑶ 목록이 최근 순 · 만료 제외 · 질문 짝을 지키고, 대화가 지워지면 별도 함께 사라지는가.

헬퍼(``_login`` · ``_use`` · ``_cleanup``)는 ``test_chat_api_db``의 것을 쓴다 — 같은 개발
계정·같은 정리 순서다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from test_chat_api_db import _BASE, _cleanup, _login, _use

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.auth import tour_gate
from cii_platform.auth.session import CSRF_COOKIE_NAME
from cii_platform.auth.tour_gate import TOUR_USER_ID
from cii_platform.auth.tour_policy import CHAT_BLOCKED_MESSAGE
from cii_platform.db.repositories import chat as chat_repo
from cii_platform.db.session import get_sessionmaker
from cii_platform.llm.provider import FakeProvider, LLMResponse
from cii_platform.services import chat as chat_service

_FAVORITE_KEYS = {
    "session_id",
    "message_id",
    "question",
    "answer",
    "answered_at",
    "expires_at",
    "favorited_at",
}
_MISSING = "00000000-0000-4000-8000-000000000000"


async def _dev_user_id() -> UUID:
    async with get_sessionmaker()() as s:
        value = (
            await s.execute(text("SELECT id FROM app_user WHERE email = 'dev@localhost'"))
        ).scalar_one()
    return UUID(str(value))


async def _new_user() -> UUID:
    user_id = uuid4()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                'INSERT INTO app_user (id, email, password_hash, "role", is_deleted) '
                "VALUES (:id, :email, 'x', 'FIELD', 0)"
            ),
            {"id": user_id, "email": f"fav-{user_id.hex[:8]}@example.com"},
        )
        await s.commit()
    return user_id


async def _drop_user(user_id: UUID) -> None:
    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM chat_session WHERE user_id = :u"), {"u": user_id})
        await s.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": user_id})
        await s.commit()


async def _conversation(
    user_id: UUID,
    turns: list[tuple[str, str]],
    *,
    created: datetime | None = None,
    favorited: dict[int, datetime] | None = None,
) -> tuple[str, list[str]]:
    """대화 하나를 직접 쌓는다 — ``(role, content)`` 순서대로, 1초 간격.

    :returns: ``(session_id, 메시지 번호 목록)``. ``favorited``는 ``{행 순번: 별 단 시각}``.
    """
    start = created or datetime.now(UTC) - timedelta(hours=1)
    async with get_sessionmaker()() as s:
        chat = await chat_repo.create_session(s, user_id=user_id, now=start)
        ids: list[str] = []
        for index, (role, content) in enumerate(turns):
            row = await chat_repo.add_message(
                s,
                session_id=chat.id,
                role=role,
                content=content,
                now=start + timedelta(seconds=index + 1),
            )
            when = (favorited or {}).get(index)
            if when is not None:
                await chat_repo.set_favorited_at(s, row=row, favorited_at=when)
            ids.append(str(row.id))
        await s.commit()
        return str(chat.id), ids


async def _favorited_at(message_id: str) -> object:
    async with get_sessionmaker()() as s:
        return (
            await s.execute(
                text("SELECT favorited_at FROM chat_message WHERE id = :id"),
                {"id": UUID(message_id)},
            )
        ).scalar_one_or_none()


async def test_both_responses_carry_the_saved_answer_number(migrated_db, app_fresh_engine):
    """IT-CHAT-089 — ``POST /chat``과 불러오기(``§15.8``)가 **저장된 답의 번호**를 싣는다.

    화면은 이 번호로 별을 단다. 저장된 답은 문자열, 버린 답은 ``null``이고(저장하지 않아
    가리킬 행이 없다), 불러오기에서는 질문 항목과 폐기 자리 항목도 ``null``이다. 두 응답의
    번호가 **같은 행**을 가리키는지도 본다 — 갈리면 새로고침 뒤 별이 엉뚱한 답에 붙는다.
    """
    _use(
        FakeProvider(
            [
                LLMResponse(text="등급은 화면에서 확인하실 수 있습니다."),
                LLMResponse(text="attained CII는 4.98입니다."),  # 도구 없이 수치 → 폐기
            ]
        )
    )
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            first = client.post(
                "/api/v1/chat", json={"message": "안녕하세요"}, headers=headers
            ).json()["data"]
            assert first["discarded"] is False, first
            assert isinstance(first["message_id"], str)
            assert UUID(first["message_id"])
            second = client.post(
                "/api/v1/chat",
                json={"message": "등급은?", "session_id": first["session_id"]},
                headers=headers,
            ).json()["data"]
            assert second["discarded"] is True, second
            assert second["message_id"] is None

            messages = client.get(f"/api/v1/chat/sessions/{first['session_id']}/messages").json()[
                "data"
            ]["messages"]
            assert [(m["role"], m["discarded"], m["message_id"]) for m in messages] == [
                ("USER", False, None),
                ("ASSISTANT", False, first["message_id"]),
                ("USER", False, None),
                ("ASSISTANT", True, None),
            ]
    finally:
        await _cleanup()


async def test_star_and_unstar_are_idempotent(migrated_db, app_fresh_engine):
    """IT-CHAT-090 — 달기는 **이미 달려 있으면 시각을 바꾸지 않고** 200, 떼기는 없어도 204.

    화면이 두 번 누르거나 재시도해도 결과가 같아야 한다. 다시 달 때 시각이 바뀌면 목록 순서가
    사용자가 누른 적 없는 순간으로 움직인다.
    """
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            user_id = await _dev_user_id()
            session_id, ids = await _conversation(
                user_id, [("USER", "등급은?"), ("ASSISTANT", "C입니다.")]
            )
            path = f"/api/v1/chat/messages/{ids[1]}/favorite"

            first = client.put(path, headers=headers)
            assert first.status_code == 200, first.text
            data = first.json()["data"]
            assert set(data) == {"message_id", "favorited_at"}
            assert data["message_id"] == ids[1]
            assert datetime.fromisoformat(data["favorited_at"]).utcoffset() == timedelta(0)

            again = client.put(path, headers=headers)
            assert again.status_code == 200, again.text
            assert again.json()["data"] == data

            listed = client.get("/api/v1/chat/favorites").json()["data"]["favorites"]
            assert [item["message_id"] for item in listed] == [ids[1]]
            assert listed[0]["session_id"] == session_id
            # 달 때 받은 시각과 목록의 시각이 같다 — 저장 정밀도(밀리초)로 깎아 넣는다.
            assert listed[0]["favorited_at"] == data["favorited_at"]

            for _ in range(2):
                gone = client.delete(path, headers=headers)
                assert gone.status_code == 204, gone.text
                assert gone.content == b""
            assert await _favorited_at(ids[1]) is None
            assert client.get("/api/v1/chat/favorites").json()["data"]["favorites"] == []

            # CSRF 없이는 쓰지 못한다.
            assert client.put(path).status_code == 403
    finally:
        await _cleanup()


async def test_only_my_live_answers_can_be_starred(migrated_db, app_fresh_engine):
    """IT-CHAT-091 — 남의 답 · 만료된 대화의 답 · 질문 행 · 없는 번호는 **모두 같은 404**다.

    갈래마다 다른 코드를 내면 번호를 바꿔 가며 남의 대화가 있는지, 만료됐는지를 알아낼 수
    있다(``§15.4`` · ``§15.6``). 404 뒤에 행이 실제로 바뀌지 않았는지도 본다.
    """
    other = await _new_user()
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            me = await _dev_user_id()
            _, others = await _conversation(
                other, [("USER", "남의 질문"), ("ASSISTANT", "남의 답")]
            )
            _, expired = await _conversation(
                me,
                [("USER", "옛 질문"), ("ASSISTANT", "옛 답")],
                created=datetime.now(UTC) - timedelta(days=chat_repo.RETENTION_DAYS + 1),
            )
            _, mine = await _conversation(me, [("USER", "내 질문"), ("ASSISTANT", "내 답")])

            for message_id in (others[1], expired[1], mine[0], _MISSING):
                path = f"/api/v1/chat/messages/{message_id}/favorite"
                for method in ("PUT", "DELETE"):
                    response = client.request(method, path, headers=headers)
                    assert response.status_code == 404, (message_id, method, response.text)
                    body = response.json()["error"]
                    assert body["code"] == "NOT_FOUND"
                    assert body["message"] == chat_service.FAVORITE_NOT_FOUND_MESSAGE
                    assert "남의 답" not in response.text
                if message_id != _MISSING:
                    assert await _favorited_at(message_id) is None
    finally:
        await _drop_user(other)
        await _cleanup()


async def test_the_list_is_recent_first_mine_only_and_pairs_the_question(
    migrated_db, app_fresh_engine
):
    """IT-CHAT-092 — 목록은 **최근에 단 것부터**, 내 것만, 만료된 대화는 빼고, 질문을 짝짓는다.

    ``question``은 답 **바로 앞 행**이 질문일 때만 채운다 — 앞 행이 답이거나 없으면 ``null``.
    만료 대화의 별은 청소 전까지 행이 남지만, 불러오기가 404를 내므로 목록에 두면 눌러도
    열리지 않는다. 모든 항목이 같은 일곱 키를 갖는다(``#1365`` 키 집합 규약).
    """
    other = await _new_user()
    base = datetime.now(UTC) - timedelta(minutes=30)
    try:
        with TestClient(app, base_url=_BASE) as client:
            _login(client)
            me = await _dev_user_id()
            first_session, first = await _conversation(
                me,
                [("USER", "첫 질문"), ("ASSISTANT", "첫 답"), ("ASSISTANT", "덧붙인 답")],
                favorited={1: base + timedelta(minutes=1), 2: base + timedelta(minutes=3)},
            )
            second_session, second = await _conversation(
                me,
                [("ASSISTANT", "질문 없는 답"), ("USER", "둘째 질문"), ("ASSISTANT", "둘째 답")],
                favorited={0: base + timedelta(minutes=4), 2: base + timedelta(minutes=2)},
            )
            await _conversation(
                me,
                [("USER", "옛 질문"), ("ASSISTANT", "옛 답")],
                created=datetime.now(UTC) - timedelta(days=chat_repo.RETENTION_DAYS + 1),
                favorited={1: base + timedelta(minutes=5)},
            )
            await _conversation(
                other,
                [("USER", "남의 질문"), ("ASSISTANT", "남의 답")],
                favorited={1: base + timedelta(minutes=6)},
            )

            response = client.get("/api/v1/chat/favorites")
            assert response.status_code == 200, response.text
            items = response.json()["data"]["favorites"]
            assert all(set(item) == _FAVORITE_KEYS for item in items), items
            assert [
                (item["session_id"], item["message_id"], item["question"], item["answer"])
                for item in items
            ] == [
                (second_session, second[0], None, "질문 없는 답"),
                (first_session, first[2], None, "덧붙인 답"),
                (second_session, second[2], "둘째 질문", "둘째 답"),
                (first_session, first[1], "첫 질문", "첫 답"),
            ]
            for item in items:
                for key in ("answered_at", "expires_at", "favorited_at"):
                    assert datetime.fromisoformat(item[key]).utcoffset() == timedelta(0)
            stamps = [datetime.fromisoformat(item["favorited_at"]) for item in items]
            assert stamps == sorted(stamps, reverse=True)
            # 지워지는 날은 대화의 보존 기한이다.
            expires = datetime.fromisoformat(items[0]["expires_at"])
            answered = datetime.fromisoformat(items[0]["answered_at"])
            assert timedelta(days=chat_repo.RETENTION_DAYS - 1) < expires - answered
            assert "남의 답" not in response.text
            assert "옛 답" not in response.text
    finally:
        await _drop_user(other)
        await _cleanup()


async def test_the_list_has_no_count_cap(migrated_db, app_fresh_engine):
    """IT-CHAT-093 — 목록은 **건수로 자르지 않는다** — 101건을 달면 101건이 다 온다.

    화면이 이 목록의 번호로 별을 칠한다. 잘라 내면 가장 오래 단 답은 별이 달려 있는데 빈
    별로 보인다. 개수는 90일 보존이 이미 묶는다.
    """
    base = datetime.now(UTC) - timedelta(hours=2)
    count = 101
    try:
        with TestClient(app, base_url=_BASE) as client:
            _login(client)
            me = await _dev_user_id()
            _, ids = await _conversation(
                me,
                [("ASSISTANT", f"답 {n}") for n in range(count)],
                favorited={n: base + timedelta(seconds=n) for n in range(count)},
            )
            items = client.get("/api/v1/chat/favorites").json()["data"]["favorites"]
            assert [item["message_id"] for item in items] == list(reversed(ids))
    finally:
        await _cleanup()


async def test_deleting_the_conversation_takes_the_stars_with_it(migrated_db, app_fresh_engine):
    """IT-CHAT-094 — 대화를 지우면 **별도 함께 사라진다**(결정 2 · ``ON DELETE CASCADE``).

    별을 따로 두면 대화를 지웠는데 목록에 답 본문이 남는다 — 「지웠다」가 거짓이 된다.
    """
    try:
        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)
            me = await _dev_user_id()
            session_id, ids = await _conversation(
                me,
                [("USER", "지울 질문"), ("ASSISTANT", "지울 답")],
                favorited={1: datetime.now(UTC) - timedelta(minutes=1)},
            )
            assert len(client.get("/api/v1/chat/favorites").json()["data"]["favorites"]) == 1

            gone = client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)
            assert gone.status_code == 204, gone.text
            assert client.get("/api/v1/chat/favorites").json()["data"]["favorites"] == []
            assert await _favorited_at(ids[1]) is None
            async with get_sessionmaker()() as s:
                left = (
                    await s.execute(
                        text("SELECT COUNT(*) FROM chat_message WHERE id = :id"),
                        {"id": UUID(ids[1])},
                    )
                ).scalar_one()
            assert left == 0
    finally:
        await _cleanup()


async def test_tour_sees_an_empty_list_and_cannot_star(migrated_db, app_fresh_engine, monkeypatch):
    """IT-CHAT-095 — 둘러보기는 목록이 **늘 비어 있고**, 달기·떼기는 어시스턴트 전용 403이다.

    공유 계정이라 「내 즐겨찾기」가 성립하지 않는다 — 그 계정 소유의 별이 남아 있어도 보이지
    않아야 한다. 쓰기는 ``/chat`` 아래라 정책 미들웨어가 라우트 앞에서 막는다.
    """
    monkeypatch.setenv(tour_gate.ENV_NAME, "harbour-tour-readonly-9x")
    try:
        with TestClient(app, base_url=_BASE) as client:
            entered = client.post(
                f"{API_V1_PREFIX}/auth/tour-login", json={"code": "harbour-tour-readonly-9x"}
            )
            assert entered.status_code == 200, entered.text
            _, ids = await _conversation(
                TOUR_USER_ID,
                [("USER", "둘러보기 질문"), ("ASSISTANT", "둘러보기 답")],
                favorited={1: datetime.now(UTC) - timedelta(minutes=1)},
            )

            listed = client.get(f"{API_V1_PREFIX}/chat/favorites")
            assert listed.status_code == 200, listed.text
            assert listed.json()["data"]["favorites"] == []

            headers = {"X-CSRF-Token": client.cookies[CSRF_COOKIE_NAME]}
            for method in ("PUT", "DELETE"):
                response = client.request(
                    method, f"{API_V1_PREFIX}/chat/messages/{ids[1]}/favorite", headers=headers
                )
                assert response.status_code == 403, response.text
                assert response.json()["error"]["message"] == CHAT_BLOCKED_MESSAGE
            assert await _favorited_at(ids[1]) is not None
    finally:
        async with get_sessionmaker()() as s:
            await s.execute(
                text("DELETE FROM chat_session WHERE user_id = :u"), {"u": TOUR_USER_ID}
            )
            await s.execute(
                text("DELETE FROM user_session WHERE user_id = :u"), {"u": TOUR_USER_ID}
            )
            await s.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": TOUR_USER_ID})
            await s.commit()
        await _cleanup()
