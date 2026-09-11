"""되돌릴 수 없는 downgrade의 해제 조건 — 백업 기록 조회 (#827 · ``DB_SCHEMA §8.1.2``).

``tests/test_migration_guard.py``는 조회 결과를 바꿔 끼워 판단만 본다. 여기서는 **실제
감사 로그에서** 그 시각을 읽는지 확인한다 — 가드가 마이그레이션 안에서 받는 것은 동기
연결이라, 비동기 연결의 ``run_sync``로 같은 모양의 연결을 넘긴다.

백업 스크립트(``scripts/db_backup.py``)가 남기는 행과 **같은 모양**을 넣는다 — 행의 모양이
어긋나면 스크립트는 기록했다고 믿고 가드는 없다고 읽는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from cii_platform.db import migration_guard

pytestmark = pytest.mark.asyncio


async def _insert(conn, action: str, at: datetime) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO audit_log (action, timestamp, details_json) "
            "VALUES (:action, :at, CAST(:details AS jsonb))"
        ),
        {"action": action, "at": at, "details": '{"file": "x.dump"}'},
    )


async def _last(conn) -> datetime | None:
    return await conn.run_sync(migration_guard.last_backup_at)


async def test_reads_the_newest_backup_record(conn):
    # 이 테스트는 트랜잭션 안에서 돈다 — 앞선 실행이 남긴 행이 없다고 가정하지 않고 기준을 잡는다.
    base = datetime(2099, 1, 1, tzinfo=UTC)
    await _insert(conn, migration_guard.BACKUP_ACTION, base - timedelta(hours=5))
    await _insert(conn, migration_guard.BACKUP_ACTION, base)

    assert await _last(conn) == base


async def test_other_actions_are_not_backups(conn):
    before = await _last(conn)
    await _insert(conn, "EXPORT", datetime(2099, 6, 1, tzinfo=UTC))

    assert await _last(conn) == before


async def test_the_guard_unlocks_on_a_real_record(conn, monkeypatch: pytest.MonkeyPatch):
    """조회와 판단을 이어서 — 방금 뜬 백업의 기록 하나로 해제된다."""
    await _insert(conn, migration_guard.BACKUP_ACTION, datetime.now(UTC))
    monkeypatch.setattr(migration_guard, "is_production", lambda: True)
    monkeypatch.setenv(migration_guard.ALLOW_ENV, "037")

    def _check(sync_conn) -> None:
        monkeypatch.setattr(migration_guard, "_migration_bind", lambda: sync_conn)
        migration_guard.guard_irreversible_downgrade("037")

    await conn.run_sync(_check)
