"""app_user updated_at 트리거 검증 (#317).

022이 추가한 ``trg_app_user_updated``가 DB_SCHEMA §7.2 [M-2]대로 UPDATE 시
``updated_at``을 자동 갱신하는지 확인한다. 020 시절의 회귀(트리거 누락으로
``updated_at``이 영구히 ``created_at``과 같음)를 잠근다.
"""

import asyncio

from sqlalchemy import text


async def test_app_user_update_touches_updated_at(migrated_db):
    """UPDATE 시 updated_at이 자동 갱신된다 (트리거).

    ``conn`` fixture는 단일 트랜잭션이라 ``now()``가 트랜잭션 시작 시각으로
    고정돼 트리거 갱신을 관측할 수 없다 — **별도 커밋**으로 검증한다.
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    user_id = None
    try:
        async with sessionmaker() as s:
            row = await s.execute(
                text(
                    "INSERT INTO app_user (google_sub, email) "
                    "VALUES ('trg-live-1', 't1@example.com') RETURNING id, updated_at"
                )
            )
            user_id, updated_before = row.one()
            await s.commit()

        # 트리거는 now()를 새로 찍는다 — 트랜잭션이 달라져야 시차가 생긴다.
        await asyncio.sleep(1.05)

        async with sessionmaker() as s:
            await s.execute(
                text("UPDATE app_user SET display_name = '트리거' WHERE id = :id"),
                {"id": user_id},
            )
            await s.commit()
            after = await s.execute(
                text("SELECT updated_at FROM app_user WHERE id = :id"),
                {"id": user_id},
            )
            updated_after = after.scalar_one()

        assert updated_after > updated_before
    finally:
        async with sessionmaker() as s:
            await s.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": user_id})
            await s.commit()
        await get_engine().dispose()


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
