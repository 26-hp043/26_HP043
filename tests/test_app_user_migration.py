"""app_user ``updated_at`` 자동 갱신 검증 (#317).

``DB_SCHEMA §7.2 [M-2]``대로 UPDATE 시 ``updated_at``이 자동 갱신되는지 확인한다.
020 시절의 회귀(갱신 수단 누락으로 ``updated_at``이 영구히 ``created_at``과 같음)를
잠근다 — **CUBRID 전환에서 그 회귀가 실제로 되살아나 있었다**(`#1058`).

## 수단이 트리거에서 열 속성으로 바뀌었다

PostgreSQL에서는 ``022``의 ``trg_app_user_updated`` 트리거였다. CUBRID에서는
트리거로 할 수 없다 — 자기 테이블을 다시 UPDATE해야 해서 **재귀에 걸리고**(실측:
``Maximum … depth``), ``BEFORE``에서 ``UPDATE new SET``으로 값을 바꾸는 것은 컴파일
단계에서 거부된다. ``049``가 MySQL 호환 열 속성
``ON UPDATE CURRENT_DATETIME``으로 옮겼다.

**지키려는 것은 같다** — 「고치면 시각이 바뀐다」. 아래 두 검사는 ⑴ 실제 동작과
⑵ 그 수단이 스키마에 남아 있는가를 각각 본다.
"""

import asyncio
import uuid

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
            # CUBRID에는 `RETURNING`이 없다 — id를 파이썬에서 만들어 넣고 되읽는다
            # (`#1058`). 컬럼은 `CHAR(32)`라 하이픈 없는 hex로 싣는다.
            user_id = uuid.uuid4().hex
            await s.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash) "
                    "VALUES (:id, 't1@example.com', 'x')"
                ),
                {"id": user_id},
            )
            row = await s.execute(
                text("SELECT updated_at FROM app_user WHERE id = :id"), {"id": user_id}
            )
            updated_before = row.scalar_one()
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


async def test_app_user_updated_at_has_the_on_update_attribute(conn):
    """``updated_at``에 자동 갱신 수단이 **스키마에 남아 있다** (`049`).

    위 검사가 동작을 보는 데 반해 이것은 **수단의 존재**를 본다. 둘 다 필요하다 —
    동작 검사는 별도 커밋과 1초 대기가 필요해 무거워서, 수단이 사라진 회귀를
    값싸게 잡을 것이 따로 있어야 한다. `#317`이 잠그려던 회귀가 바로 그것이고,
    CUBRID 전환에서 실제로 되살아났다.

    CUBRID는 열의 기본값·갱신 규칙을 ``db_attr_setdomain_elm``이 아니라
    ``SHOW COLUMNS``의 ``Extra``로 드러낸다 — 실측으로 확인한 자리다.
    """
    rows = (await conn.execute(text("SHOW COLUMNS FROM app_user"))).mappings().all()
    updated_at = next(r for r in rows if r["Field"] == "updated_at")
    assert "on update" in str(updated_at["Extra"]).lower(), (
        f"updated_at에 자동 갱신 수단이 없다: {dict(updated_at)}"
    )
