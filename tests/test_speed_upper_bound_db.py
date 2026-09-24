"""속력 물리 상한 60 kn — DB 트리거의 계약 (#1269 · 마이그레이션 ``062``).

**막으려는 것은 API를 거치지 않은 행이다.** 서버 스키마(``bounds.SPEED``)가 60을 넘는 요청을
422로 거절해도 시드·복원·수기 SQL로 들어온 ``120`` kn은 연료 모델에서 속력 배율 1,000이
되어 도착 예정 시각과 연간 시뮬레이션까지 흘러간다. CUBRID는 CHECK를 검사하지 않으므로
(``DB_SCHEMA §7.4``) 실제로 위반을 넣어 보고 거부되는지만 본다.

케이스: DB-CHK-023 (`TEST_PLAN §5.1`)

트리거 검사는 ``conn`` fixture의 트랜잭션 안이라 롤백된다 — 행을 남기지 않는다.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection


def _load_migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "062_speed_upper_bound.py"
    spec = importlib.util.spec_from_file_location("migration_062", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION = _load_migration()


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``7``로 시작한다."""
    return f"7{uuid.uuid4().int % 1_000_000:06d}"


async def _insert_vessel(conn: AsyncConnection, reference_speed_kn: str | None) -> str:
    vessel_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, reference_speed_kn) "
            "VALUES (:id, :imo, 'SPEED BOUND TEST', 'BULK_CARRIER', :speed)"
        ),
        {"id": vessel_id, "imo": _imo(), "speed": reference_speed_kn},
    )
    return vessel_id


async def _a_voyage_id(conn: AsyncConnection) -> str:
    """시드 항차 하나 — UPDATE 쪽 트리거를 본다(INSERT는 FK·필수 칸이 많아 선박으로 본다)."""
    voyage_id = await conn.scalar(text("SELECT id FROM voyage"))
    assert voyage_id is not None, "항차가 한 건도 없다 — 이 검사가 헛돈다"
    return str(voyage_id)


async def test_triggers_exist(conn: AsyncConnection):
    """062가 만든 트리거 여덟 개가 DB에 실재한다 — 이름이 바뀌면 downgrade가 엉뚱한 것을 지운다."""
    rows = await conn.execute(text("SELECT name FROM db_trigger"))
    names = {row[0] for row in rows}
    expected = {
        _MIGRATION.trigger_name(check_name, event)
        for check_name, *_ in _MIGRATION.SPEED_COLUMNS
        for event in ("INSERT", "UPDATE")
    }
    assert len(expected) == 8
    assert expected <= names, sorted(expected - names)


@pytest.mark.parametrize("value", ["60", "58.1", "12.5", None])
async def test_vessel_accepts_speed_up_to_60_and_null(conn: AsyncConnection, value):
    """60 정각과 고속선의 실제 속력(58.1)과 「모른다」(NULL)는 들어간다."""
    vessel_id = await _insert_vessel(conn, value)
    stored = await conn.scalar(
        text("SELECT reference_speed_kn FROM vessel WHERE id = :id"), {"id": vessel_id}
    )
    assert (stored is None) == (value is None)


@pytest.mark.parametrize("value", ["60.01", "125", "9999.99"])
async def test_vessel_insert_rejects_speed_above_60(conn: AsyncConnection, value):
    """DB-CHK-023 — API를 거치지 않은 INSERT도 60을 넘으면 거부된다."""
    with pytest.raises(IntegrityError, match="trg_chk_speed_max_ins"):
        await _insert_vessel(conn, value)


@pytest.mark.parametrize(
    ("column", "trigger"),
    [
        ("planned_speed_kn", "trg_chk_speed_max_voyage_upd"),
        ("actual_avg_speed_kn", "trg_chk_actual_speed_max_upd"),
    ],
)
async def test_voyage_update_rejects_speed_above_60(conn: AsyncConnection, column, trigger):
    """항차의 두 속력 칸 — UPDATE 쪽 트리거도 같은 식이다. INSERT만 막으면 수기 UPDATE로 뚫린다."""
    voyage_id = await _a_voyage_id(conn)
    with pytest.raises(IntegrityError, match=trigger):
        await conn.execute(
            text(f"UPDATE voyage SET {column} = 120 WHERE id = :id"), {"id": voyage_id}
        )


async def test_voyage_update_accepts_60(conn: AsyncConnection):
    voyage_id = await _a_voyage_id(conn)
    await conn.execute(
        text("UPDATE voyage SET planned_speed_kn = 60 WHERE id = :id"), {"id": voyage_id}
    )
    stored = await conn.scalar(
        text("SELECT planned_speed_kn FROM voyage WHERE id = :id"), {"id": voyage_id}
    )
    assert float(stored) == 60.0
