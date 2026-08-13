"""app_user updated_at 트리거 검증 (#317).

022이 추가한 ``trg_app_user_updated``가 DB_SCHEMA §7.2 [M-2]대로 UPDATE 시
``updated_at``을 자동 갱신하는지 확인한다. 020 시절의 회귀(트리거 누락으로
``updated_at``이 영구히 ``created_at``과 같음)를 잠근다.
"""

import asyncio

from sqlalchemy import text


async def _insert_app_user(conn, google_sub: str) -> str:
    row = await conn.execute(
        text("INSERT INTO app_user (google_sub, email) VALUES (:sub, :email) RETURNING id"),
        {"sub": google_sub, "email": f"{google_sub}@example.com"},
    )
    return str(row.scalar_one())


async def _fetch_timestamps(conn, user_id: str) -> tuple:
    row = await conn.execute(
        text("SELECT created_at, updated_at FROM app_user WHERE id = :id"),
        {"id": user_id},
    )
    return row.one()


async def test_app_user_update_touches_updated_at(conn):
    """UPDATE 시 updated_at이 자동 갱신된다 (트리거)."""
    user_id = await _insert_app_user(conn, "trg-test-1")
    created_at, updated_before = await _fetch_timestamps(conn, user_id)
    assert updated_before == created_at  # INSERT 시점에는 같다

    # 트리거가 now()로 갱신하므로 1초 이상 시차를 만든다.
    await asyncio.sleep(1.1)
    await conn.execute(
        text("UPDATE app_user SET display_name = '트리거' WHERE id = :id"),
        {"id": user_id},
    )
    _, updated_after = await _fetch_timestamps(conn, user_id)
    assert updated_after > created_at


async def test_app_user_trigger_exists(conn):
    """trg_app_user_updated 트리거가 app_user에 등록돼 있다."""
    row = await conn.execute(
        text(
            "SELECT count(*) FROM pg_trigger "
            "WHERE tgname = 'trg_app_user_updated' "
            "AND tgrelid = 'app_user'::regclass"
        )
    )
    assert row.scalar_one() == 1
