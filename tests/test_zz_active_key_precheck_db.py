"""``061`` 사전 검사를 실제 CUBRID 위에서 — 중복이면 ``047`` 트리거 전에 멈춘다 (`DB-SOFT-007`).

``060``으로 내린 뒤 ``047`` 시절의 경합 결과(같은 IMO의 활성 행 둘)를 만들어 두고
``upgrade head``를 돌린다. 기대는 셋이다 — ⑴ 0이 아닌 종료 코드와 한국어 문구
⑵ **DB가 그대로다**: ``047`` 트리거 4개가 남아 있고 ``imo_active`` 열이 없다 ⑶ 문구에
IMO가 없다(배포 로그는 공개 저장소의 Actions에 남는다). 중복을 지운 뒤 같은 명령이 그대로
지나가는 것까지 본다 — ``docs/OPERATIONS.md`` §3.6.4의 절차가 실제로 이 순서다.

``047`` 트리거는 같은 IMO의 두 번째 INSERT를 **한 세션 안에서는** 막는다(자기 트랜잭션의 행은
``NOT EXISTS``가 본다). 그래서 중복을 만들 때만 ``_ins`` 트리거를 잠시 걷었다가 원문 그대로
되살린다 — 경합으로 만들면 검사가 플래키해진다.

``test_zz_*`` 이름과 ``try/finally`` 복원은 ``test_zz_roundtrip.py``와 같은 이유다 — 전역
스키마를 바꾸므로 마지막에 돌고, 실패해도 head로 돌려놓는다. 개발 DB에서는 돌지 않는다(`#507`).
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import TEST_DATABASE_URL, run_alembic
from db_target import is_disposable, skip_reason
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not is_disposable(TEST_DATABASE_URL),
    reason=skip_reason(TEST_DATABASE_URL),
)

_MIGRATION = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("061_*.py"))

#: 데모 시드(4척)·`test_active_key_unique_db.py`(9163100 · 9163101)와 겹치지 않는 IMO.
DUP_IMO = "9163102"
_INS_TRIGGER = "trg_uq_vessel_imo_active_ins"
_LEGACY_TRIGGERS = {
    "trg_uq_vessel_imo_active_ins",
    "trg_uq_vessel_imo_active_upd",
    "trg_uq_app_user_email_active_ins",
    "trg_uq_app_user_email_active_upd",
}


def _load_061():
    """061 모듈 — ``047`` 트리거 원문(``_legacy_condition``)을 되살릴 때 쓴다."""
    spec = importlib.util.spec_from_file_location("_zz_precheck_061", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(statements: list[str]) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for sql in statements:
                await connection.execute(text(sql))
    finally:
        await engine.dispose()


async def _rows(sql: str) -> list:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(text(sql))).all())
    finally:
        await engine.dispose()


def _vessel_insert(vessel_id: str) -> str:
    return (
        "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, is_deleted) "
        f"VALUES ('{vessel_id}', '{DUP_IMO}', 'PRECHECK DUP', 'BULK_CARRIER', 50000, 0)"
    )


async def _make_duplicates(module) -> tuple[str, str]:
    """``047`` 상태(``060``)에서 같은 IMO의 활성 행 둘 — ``_ins`` 트리거를 잠시 걷고 되살린다."""
    legacy_body = (
        f"BEFORE INSERT ON vessel IF NOT ({module._legacy_condition('vessel', 'imo_number')}) "
        "EXECUTE REJECT"
    )
    first, second = uuid4().hex, uuid4().hex
    await _run(
        [
            f"DROP TRIGGER {_INS_TRIGGER}",
            _vessel_insert(first),
            _vessel_insert(second),
            f"CREATE TRIGGER {_INS_TRIGGER} {legacy_body}",
        ]
    )
    return first, second


async def _legacy_triggers_present() -> set[str]:
    names = {row[0] for row in await _rows("SELECT name FROM db_trigger")}
    return names & _LEGACY_TRIGGERS


async def _active_key_column_exists() -> bool:
    rows = await _rows(
        "SELECT 1 FROM db_attribute WHERE class_name = 'vessel' AND attr_name = 'imo_active'"
    )
    return bool(rows)


def _restore_to_head() -> None:
    restore = run_alembic("upgrade", "head")
    assert restore.returncode == 0, (
        f"restore(upgrade head) 실패: {restore.stdout}\n{restore.stderr}"
    )


def test_duplicates_stop_061_before_the_legacy_triggers_are_dropped():
    """중복이면 사전 검사에서 멈추고 DB는 그대로 — 047 트리거 유지 · 열 없음 · IMO 노출 없음."""
    module = _load_061()
    try:
        down = run_alembic("downgrade", "060")
        assert down.returncode == 0, f"{down.stdout}\n{down.stderr}"
        assert not asyncio.run(_active_key_column_exists()), "060인데 imo_active가 남아 있다"
        assert asyncio.run(_legacy_triggers_present()) == _LEGACY_TRIGGERS

        first, _second = asyncio.run(_make_duplicates(module))
        assert asyncio.run(
            _rows(f"SELECT COUNT(*) FROM vessel WHERE imo_number = '{DUP_IMO}' AND is_deleted = 0")
        ) == [(2,)]

        blocked = run_alembic("upgrade", "head")
        output = f"{blocked.stdout}\n{blocked.stderr}"
        assert blocked.returncode != 0, f"중복이 있는데 061이 지나갔다:\n{output}"
        assert "마이그레이션 061을 적용하지 않았다" in output, output
        assert "vessel.imo_number 1개" in output, output
        assert "OPERATIONS.md §3.6.4" in output, output
        assert DUP_IMO not in output, "문구에 IMO 값이 들어갔다 — 배포 로그는 공개 저장소에 남는다"

        # DB는 그대로다 — 047 트리거가 남아 있고, 열은 만들지 않았다.
        assert asyncio.run(_legacy_triggers_present()) == _LEGACY_TRIGGERS, (
            "멈추기 전에 047 트리거를 걷었다"
        )
        assert not asyncio.run(_active_key_column_exists()), "멈추기 전에 imo_active 열을 만들었다"

        # §3.6.4의 절차 — 한쪽을 소프트 삭제하면 같은 명령이 그대로 지나간다.
        asyncio.run(_run([f"UPDATE vessel SET is_deleted = 1 WHERE id = '{first}'"]))
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"
        assert asyncio.run(_legacy_triggers_present()) == set()
        assert asyncio.run(_active_key_column_exists())
    finally:
        asyncio.run(_run([f"DELETE FROM vessel WHERE imo_number = '{DUP_IMO}'"]))
        _restore_to_head()
