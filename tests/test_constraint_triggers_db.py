"""전환에서 사라진 제약을 되살린 트리거의 계약 (#1058 · 마이그레이션 ``a7d3e9b14f26``).

**CUBRID는 CHECK를 검사하지 않는다.** 구문으로 받기만 하고 위반 행을 그대로 넣는다.
그래서 모델에 ``CheckConstraint``를 되돌려 적는 것으로는 **아무것도 막지 못하며**,
검사도 「모델에 제약이 적혀 있는가」를 보면 안 된다 — 적혀 있어도 막지 않기 때문이다.
여기서는 전부 **실제로 DB에 위반을 넣어 보고 거부되는지**만 본다.

고정하는 것은 넷이다.

1. **해시 형식** — ``sha256:`` + 64 hex가 아니면 들어가지 않는다. 형식이 깨진 해시가
   저장되면 그 실행은 **영영 재현 대조를 할 수 없다**(immutable이라 고칠 수도 없다).
2. **불변성** — ``calculation_run``·``simulation_snapshot``의 UPDATE·DELETE 차단.
   단 ``calculation_run``은 ``needs_recalc`` 0 → 1 플립만 통과한다(`024` 계약).
3. **연료 코드 참조** — 없는 코드가 들어가지 않고, 참조 중인 코드는 지워지지 않는다.
   CUBRID의 FK는 **PK만** 가리킬 수 있어 ``fuel_type.code``(별도 UNIQUE)에는 걸 수
   없다 — 그래서 FK가 아니라 트리거다.
4. **열 목록이 스키마를 따라간다** — ``calculation_run``에 열이 늘면 불변성 조건에도
   더해야 한다. 빠뜨리면 **그 열만 조용히 수정 가능해진다.**

케이스: (`TEST_PLAN §14.5` 정의 없음 — CUBRID 제약 대체 계약)
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncConnection


def _load_migration():
    """제약 복원 마이그레이션을 모듈로 읽는다.

    ``alembic/versions``는 패키지가 아니라 일반 import가 안 된다 — 파일 경로로 적재한다
    (`test_seed_migration.py`와 같은 방식). **파일명을 박지 않고 glob으로 찾고, 한 개도
    못 찾으면 실패한다** — 리비전 hex가 바뀌면 박아 둔 이름은 `FileNotFoundError`로 죽고,
    그 죽음은 실패 더미에 묻힌다(`#1058`에서 실제로 겪었다).
    """
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    hits = sorted(versions.glob("*_restore_constraints_as_triggers.py"))
    assert hits, f"제약 복원 마이그레이션을 찾지 못했습니다: {versions}"
    assert len(hits) == 1, f"후보가 둘 이상입니다: {[h.name for h in hits]}"

    spec = importlib.util.spec_from_file_location("migration_constraints", hits[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION = _load_migration()
CALC_RUN_FROZEN_NOT_NULL = _MIGRATION.CALC_RUN_FROZEN_NOT_NULL
CALC_RUN_FROZEN_NULLABLE = _MIGRATION.CALC_RUN_FROZEN_NULLABLE
FUEL_TYPE_REFS = _MIGRATION.FUEL_TYPE_REFS
HASH_TRIGGERS = _MIGRATION.HASH_TRIGGERS
IMMUTABLE_DELETE_TRIGGERS = _MIGRATION.IMMUTABLE_DELETE_TRIGGERS

VALID_HASH = "sha256:" + "0" * 64

#: 마이그레이션이 만드는 트리거 전체.
EXPECTED_TRIGGERS = (
    {name for name, _t, _c in HASH_TRIGGERS}
    | {name for name, _t in IMMUTABLE_DELETE_TRIGGERS}
    | {f"{name}_{event}" for name, _t, _c in FUEL_TYPE_REFS for event in ("ins", "upd")}
    | {"trg_calcrun_immutable_update", "trg_snapshot_immutable_update"}
)


async def _trigger_names(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(text("SELECT name FROM db_trigger"))
    return {row[0] for row in rows}


async def _a_vessel_id(conn: AsyncConnection) -> str:
    """``calculation_run.vessel_id``는 FK다 — 실재하는 선박을 쓴다."""
    vid = await conn.scalar(text("SELECT id FROM vessel"))
    assert vid is not None, "선박이 한 척도 없다 — 이 검사가 헛돈다"
    return str(vid)


async def _insert_run(
    conn: AsyncConnection,
    *,
    input_hash: str = VALID_HASH,
    parameter_hash: str = VALID_HASH,
) -> str:
    run_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO calculation_run "
            "(id, calculation_type, vessel_id, input_hash, parameter_hash, "
            " model_version, result_json, parameters_used, needs_recalc, created_at) "
            "VALUES (:id, :ctype, :vid, :ih, :ph, :mv, :rj, :pu, 0, :ts)"
        ),
        {
            "id": run_id,
            # `chk_calculation_type`의 허용값 넷 중 하나여야 한다. 종전의
            # `"VOYAGE_CII"`는 **그 넷에 없는 값**이었고, CUBRID가 CHECK를 강제하지
            # 않아 들어가고 있었다 — `048`이 그 제약을 트리거로 되살리자 드러났다.
            # `calculation_type`으로서의 `VOYAGE_CII`는 코드 어디에도 없다 (`#1058`).
            "ctype": "VOYAGE_ESTIMATE",
            "vid": await _a_vessel_id(conn),
            "ih": input_hash,
            "ph": parameter_hash,
            "mv": "{}",
            "rj": "{}",
            "pu": "{}",
            "ts": datetime.now(UTC),
        },
    )
    return run_id


# ---------------------------------------------------------------------------
# 0. 트리거가 실재하는가
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_trigger_exists(conn: AsyncConnection):
    """마이그레이션이 적은 트리거가 전부 DB에 있다.

    **비어 있으면 실패한다** — 목록을 훑는 검사는 대상이 0개여도 조용히 통과한다.
    """
    assert EXPECTED_TRIGGERS, "기대 목록이 비었다 — 마이그레이션 상수를 못 읽었다"
    missing = EXPECTED_TRIGGERS - await _trigger_names(conn)
    assert not missing, f"트리거가 없다: {sorted(missing)}"


# ---------------------------------------------------------------------------
# 1. 해시 형식
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not-a-hash", "sha256:" + "0" * 63, "sha256:" + "G" * 64, ""])
async def test_broken_input_hash_is_rejected(conn: AsyncConnection, bad: str):
    """형식이 깨진 ``input_hash``는 들어가지 않는다."""
    with pytest.raises(DatabaseError):
        await _insert_run(conn, input_hash=bad)


@pytest.mark.asyncio
async def test_broken_parameter_hash_is_rejected(conn: AsyncConnection):
    """``parameter_hash``도 같은 형식이다 — 열마다 트리거가 따로 있다."""
    with pytest.raises(DatabaseError):
        await _insert_run(conn, parameter_hash="not-a-hash")


@pytest.mark.asyncio
async def test_valid_hash_passes(conn: AsyncConnection):
    """올바른 해시는 통과한다 — 막기만 하고 통과를 안 보면 「전부 거부」도 통과한다."""
    assert await _insert_run(conn)


# ---------------------------------------------------------------------------
# 2. 불변성
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculation_run_cannot_be_modified(conn: AsyncConnection):
    """결과를 고치지 못한다 — 재현성 계약(`TECH_SPEC §5.4`)의 본체다."""
    run_id = await _insert_run(conn)
    with pytest.raises(DatabaseError):
        await conn.execute(
            text("UPDATE calculation_run SET result_json = '[]' WHERE id = :id"),
            {"id": run_id},
        )


@pytest.mark.asyncio
async def test_calculation_run_cannot_be_deleted(conn: AsyncConnection):
    """지우지 못한다."""
    run_id = await _insert_run(conn)
    with pytest.raises(DatabaseError):
        await conn.execute(text("DELETE FROM calculation_run WHERE id = :id"), {"id": run_id})


@pytest.mark.asyncio
async def test_needs_recalc_flip_is_the_only_allowed_update(conn: AsyncConnection):
    """``needs_recalc`` 0 → 1만 통과한다 (`#283`·`#944`가 서비스에서 하는 그 플립).

    되돌림(1 → 0)과 **다른 열을 함께 바꾸는 것**은 막힌다. 뒤엣것이 핵심이다 —
    플립만 보고 통과시키면 같은 UPDATE에 결과를 실어 보낼 수 있다.
    """
    run_id = await _insert_run(conn)

    await conn.execute(
        text("UPDATE calculation_run SET needs_recalc = 1 WHERE id = :id"), {"id": run_id}
    )
    assert (
        await conn.scalar(
            text("SELECT needs_recalc FROM calculation_run WHERE id = :id"), {"id": run_id}
        )
        == 1
    )

    with pytest.raises(DatabaseError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = 0 WHERE id = :id"), {"id": run_id}
        )


@pytest.mark.asyncio
async def test_needs_recalc_cannot_smuggle_another_column(conn: AsyncConnection):
    """플립과 함께 다른 열을 바꾸면 막힌다."""
    run_id = await _insert_run(conn)
    with pytest.raises(DatabaseError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = 1, result_json = '[]' WHERE id = :id"),
            {"id": run_id},
        )


@pytest.mark.asyncio
async def test_snapshot_is_fully_immutable(conn: AsyncConnection):
    """``simulation_snapshot``은 허용되는 UPDATE가 없다 (`009` 그대로)."""
    snap_id = await conn.scalar(text("SELECT id FROM simulation_snapshot"))
    if snap_id is None:
        pytest.skip("스냅샷이 없다")
    with pytest.raises(DatabaseError):
        await conn.execute(
            text("UPDATE simulation_snapshot SET voyages_json = '[]' WHERE id = :id"),
            {"id": str(snap_id)},
        )


# ---------------------------------------------------------------------------
# 3. 연료 코드 참조
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("table", "column"), [(t, c) for _n, t, c in FUEL_TYPE_REFS])
async def test_unknown_fuel_code_is_rejected(conn: AsyncConnection, table: str, column: str):
    """없는 연료 코드는 들어가지 않는다 — CF를 못 찾아 계산이 조용히 틀린다."""
    with pytest.raises(DatabaseError):
        await conn.execute(text(f"UPDATE {table} SET {column} = 'NO_SUCH_FUEL'"))


@pytest.mark.asyncio
async def test_parent_side_delete_is_deliberately_not_guarded(conn: AsyncConnection):
    """참조 중인 연료를 지우는 것은 **막지 않는다** — 일부러 그렇게 두었다.

    원래 FK는 ``ON DELETE NO ACTION``이라 막았고, 한 번은 트리거로 되살렸다. 그런데
    `db/seed.py`의 재적재가 ``sqlalchemy_cubrid.dml.replace``를 쓰고 **CUBRID의
    ``REPLACE``는 DELETE + INSERT로 구현되어** 그 트리거를 깨운다. 같은 ``code``가 곧바로
    다시 들어가 고아가 생기지 않는데도 재적재 전체가 막혔다(`test_seed_data.py` 7건이
    fixture에서 죽었다). 트리거는 REPLACE의 DELETE와 사람이 친 DELETE를 구분하지 못한다.

    **이 검사는 그 구멍이 열려 있다는 사실을 고정한다.** 나중에 부모 쪽을 막게 되면 이
    검사가 실패하고, 그때 `test_seed_data.py`와 `DB_SCHEMA §7.4`를 함께 봐야 한다.
    """
    code = await conn.scalar(text("SELECT fuel_type FROM voyage_fuel_use"))
    if code is None:
        pytest.skip("참조 중인 연료가 없다")

    await conn.execute(text("DELETE FROM fuel_type WHERE code = :code"), {"code": str(code)})
    remaining = await conn.scalar(
        text("SELECT count(*) FROM fuel_type WHERE code = :code"), {"code": str(code)}
    )
    assert remaining == 0, "부모 쪽이 막혔다 — 막게 되었다면 §7.4와 seed 재적재를 함께 볼 것"


# ---------------------------------------------------------------------------
# 4. 열 목록이 스키마를 따라가는가
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frozen_column_list_matches_the_schema(conn: AsyncConnection):
    """불변성 조건의 열 목록이 실제 스키마와 같다.

    **이 검사가 없으면 열이 늘 때 그 열만 조용히 수정 가능해진다.** PostgreSQL 쪽은
    ``to_jsonb(NEW) - 'needs_recalc'``로 전 열을 자동으로 비교했는데, CUBRID에는 그
    연산이 없어 열거로 옮겼고 **열거는 따라오지 않는다.**
    """
    rows = await conn.execute(
        text("SELECT attr_name FROM db_attribute WHERE class_name = 'calculation_run'")
    )
    actual = {row[0] for row in rows}
    assert actual, "열을 한 개도 읽지 못했다 — 이 검사가 헛돈다"

    listed = set(CALC_RUN_FROZEN_NOT_NULL) | set(CALC_RUN_FROZEN_NULLABLE) | {"needs_recalc"}
    assert listed == actual, (
        "불변성 조건의 열 목록이 스키마와 다르다 — "
        f"빠진 열 {sorted(actual - listed)} · 없는 열 {sorted(listed - actual)}"
    )


@pytest.mark.asyncio
async def test_nullable_split_matches_the_schema(conn: AsyncConnection):
    """NULL 허용 여부도 맞는다 — NOT NULL로 잘못 분류하면 ``=`` 비교가 NULL을 놓친다."""
    rows = await conn.execute(
        text("SELECT attr_name, is_nullable FROM db_attribute WHERE class_name = 'calculation_run'")
    )
    nullable = {row[0] for row in rows if str(row[1]).upper() == "YES"}
    assert set(CALC_RUN_FROZEN_NULLABLE) == nullable - {"needs_recalc"}
