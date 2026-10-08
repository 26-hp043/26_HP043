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
3. **연료 코드 참조** — 없는 코드가 들어가지 않고, 부모 쪽 코드는 개명되지 않는다
   (``068`` · #2260 — 참조 행이 없어도 막는다). 참조 중인 코드의 **삭제**도 부모 트리거로 막는다
   (``069`` · #2308). CUBRID의 FK는 **PK만** 가리킬 수 있어 ``fuel_type.code``(별도 UNIQUE)에는
   걸 수 없다 — 그래서 FK가 아니라 트리거다.
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
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection


def _load_migration(pattern: str = "*_restore_constraints_as_triggers.py"):
    """제약 복원 마이그레이션을 모듈로 읽는다.

    ``alembic/versions``는 패키지가 아니라 일반 import가 안 된다 — 파일 경로로 적재한다
    (`test_seed_migration.py`와 같은 방식). **파일명을 박지 않고 glob으로 찾고, 한 개도
    못 찾으면 실패한다** — 리비전 hex가 바뀌면 박아 둔 이름은 `FileNotFoundError`로 죽고,
    그 죽음은 실패 더미에 묻힌다(`#1058`에서 실제로 겪었다).
    """
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    hits = sorted(versions.glob(pattern))
    assert hits, f"마이그레이션을 찾지 못했습니다({pattern}): {versions}"
    assert len(hits) == 1, f"후보가 둘 이상입니다: {[h.name for h in hits]}"

    spec = importlib.util.spec_from_file_location(f"migration_{hits[0].stem}", hits[0])
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

#: `068`(#2260) — 부모 쪽 연료 코드 개명 거부. `a7d3e9b14f26`과 같은 계약(연료 코드 참조)이라
#: 이 파일이 함께 본다.
_RENAME_MIGRATION = _load_migration("068_*.py")
FUEL_TYPE_RENAME_TRIGGER = _RENAME_MIGRATION.TRIGGER_NAME

VALID_HASH = "sha256:" + "0" * 64

#: 마이그레이션이 만드는 트리거 전체.
EXPECTED_TRIGGERS = (
    {name for name, _t, _c in HASH_TRIGGERS}
    | {name for name, _t in IMMUTABLE_DELETE_TRIGGERS}
    | {f"{name}_{event}" for name, _t, _c in FUEL_TYPE_REFS for event in ("ins", "upd")}
    | {"trg_calcrun_immutable_update", "trg_snapshot_immutable_update"}
    | {FUEL_TYPE_RENAME_TRIGGER}
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


async def _insert_snapshot(
    conn: AsyncConnection,
    *,
    input_hash: str = VALID_HASH,
    parameter_hash: str = VALID_HASH,
) -> str:
    """``simulation_snapshot``에도 해시 열 둘이 있고 트리거가 따로 걸려 있다."""
    snap_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO simulation_snapshot "
            "(id, vessel_id, regulation_year, voyages_json, input_hash, parameter_hash, "
            " created_at) VALUES (:id, :vid, 2026, '[]', :ih, :ph, :ts)"
        ),
        {
            "id": snap_id,
            "vid": await _a_vessel_id(conn),
            "ih": input_hash,
            "ph": parameter_hash,
            "ts": datetime.now(UTC),
        },
    )
    return snap_id


#: 표마다 INSERT 헬퍼 — 네 트리거를 (표, 열)로 돌 때 쓴다.
_INSERTERS = {"calculation_run": _insert_run, "simulation_snapshot": _insert_snapshot}


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
@pytest.mark.parametrize(
    "bad",
    [
        "not-a-hash",
        "sha256:" + "0" * 63,
        "sha256:" + "G" * 64,
        "",
        # 대소문자 — 정본 `[S-7]`의 `~`는 대소문자를 구분하는데 CUBRID `REGEXP`는 기본이
        # 무시라 `066` 전에는 셋 다 통과했다(`#2103`).
        "SHA256:" + "A" * 64,
        "sha256:" + "A" * 64,
        "SHA256:" + "0" * 64,
    ],
)
async def test_broken_input_hash_is_rejected(conn: AsyncConnection, bad: str):
    """형식이 깨진 ``input_hash``는 들어가지 않는다."""
    with pytest.raises(DatabaseError):
        await _insert_run(conn, input_hash=bad)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not-a-hash", "sha256:" + "A" * 64])
async def test_broken_parameter_hash_is_rejected(conn: AsyncConnection, bad: str):
    """``parameter_hash``도 같은 형식이다 — 열마다 트리거가 따로 있다."""
    with pytest.raises(DatabaseError):
        await _insert_run(conn, parameter_hash=bad)


@pytest.mark.asyncio
async def test_valid_hash_passes(conn: AsyncConnection):
    """올바른 해시는 통과한다 — 막기만 하고 통과를 안 보면 「전부 거부」도 통과한다."""
    assert await _insert_run(conn)


@pytest.mark.asyncio
@pytest.mark.parametrize(("table", "column"), [(t, c) for _n, t, c in HASH_TRIGGERS])
async def test_hash_case_is_significant_in_every_trigger(
    conn: AsyncConnection, table: str, column: str
):
    """네 트리거 모두 ``'SHA256:' || REPEAT('A', 64)``를 거부한다 (`#2103` 완료 기준).

    소문자 hex를 바이트 단위로 대조해야 하는 자리다 — ``calc/hash.py``는 소문자만 내므로
    대문자가 들어왔다면 그것은 **다른 곳에서 만든 값**이고, 재현 대조에서 같은 입력이
    다른 키로 갈린다. ``SHA256:``·``A…``가 통과하던 것이 `066`이 ``REGEXP BINARY``로
    바꾼 이유다(`050`·`058`과 같은 방식).
    """
    # `066`은 트리거 이름과 패턴을 사본으로 갖는다 — 원본과 어긋나면 없는 이름을 교체하려다
    # 트리거가 늘어난다(검토 지적). 사본이 원본과 같은지 여기서 잠근다.
    m066 = _load_migration("*_hash_trigger_binary.py")
    assert m066.HASH_TRIGGERS == HASH_TRIGGERS
    assert m066.HASH_PATTERN == _MIGRATION.HASH_PATTERN
    with pytest.raises(DatabaseError):
        await _INSERTERS[table](conn, **{column: "SHA256:" + "A" * 64})


@pytest.mark.asyncio
async def test_lowercase_hash_passes_every_trigger(conn: AsyncConnection):
    """``BINARY``로 좁혀도 소문자 정상 해시는 두 표 모두 통과한다."""
    assert await _insert_run(conn)
    assert await _insert_snapshot(conn)


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
    # 스냅샷을 **이 검사가 넣는다** (`#2143`). 종전에는 있는 행을 집어 쓰고 없으면
    # `pytest.skip`이었다. 데모 시드는 스냅샷을 넣지 않으므로 **앞서 돈 다른 검사가
    # 커밋해 둔 행**이 있을 때만 돌았다 — 전체 실행에서는 돌고 이 파일만 돌리면 건너뛰었다.
    snap_id = await _insert_snapshot(conn)
    with pytest.raises(DatabaseError):
        await conn.execute(
            text("UPDATE simulation_snapshot SET voyages_json = '[1]' WHERE id = :id"),
            {"id": snap_id},
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
@pytest.mark.parametrize("reference", ["vessel", "voyage", "period"])
@pytest.mark.parametrize("deleted", [False, True])
async def test_parent_side_delete_rejects_referenced_code(conn, reference, deleted):
    """세 참조의 활성/삭제 이력을 보존한다. 하나의 참조만 둬 각 갈래를 직접 본다 (#2308)."""
    code = "RF" + uuid.uuid4().hex[:12].upper()
    await conn.execute(
        text(
            "INSERT INTO fuel_type (code, display_name, cf, source_ref) "
            "VALUES (:code, '삭제 참조 검사', 1, 'TEST')"
        ),
        {"code": code},
    )
    vessel_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, default_fuel_type, is_deleted) "
            "VALUES (:id, :imo, 'DELETE REF TEST', 'BULK_CARRIER', :fuel, :deleted)"
        ),
        {
            "id": vessel_id,
            "imo": f"9{vessel_id.int % 1000000:06d}",
            "fuel": code if reference == "vessel" else None,
            "deleted": int(deleted) if reference == "vessel" else 0,
        },
    )
    if reference == "voyage":
        voyage_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO voyage "
                "(id, vessel_id, status, departure_port_name, arrival_port_name, "
                "created_from, is_deleted, planned_distance_nm, planned_speed_kn, "
                "annual_inclusion_policy) "
                "VALUES (:id, :v, 'DRAFT', 'A', 'B', 'MANUAL', :deleted, 10, 10, 'EXCLUDE')"
            ),
            {"id": voyage_id, "v": vessel_id, "deleted": int(deleted)},
        )
        await conn.execute(
            text(
                "INSERT INTO voyage_fuel_use "
                "(voyage_id, fuel_type, planned_fuel_ton, cf_used, source) "
                "VALUES (:id, :code, 1, 1, 'USER_INPUT')"
            ),
            {"id": voyage_id, "code": code},
        )
    elif reference == "period":
        period_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO not_underway_period (id, vessel_id, period_type, started_at, "
                "distance_nm, regulation_year, is_deleted) "
                "VALUES (:id, :v, 'IN_PORT', :start, 0, 2026, :deleted)"
            ),
            {
                "id": period_id,
                "v": vessel_id,
                "start": datetime(2026, 1, 1, tzinfo=UTC),
                "deleted": int(deleted),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO not_underway_fuel_use "
                "(period_id, consumer_type, fuel_type, fuel_ton, cf_used) "
                "VALUES (:id, 'OTHER', :code, 1, 1)"
            ),
            {"id": period_id, "code": code},
        )
    with pytest.raises(IntegrityError) as caught:
        await conn.execute(text("DELETE FROM fuel_type WHERE code=:code"), {"code": code})
    assert "trg_fuel_type_referenced_delete" in str(caught.value).lower()
    # 거부 뒤 실제 부모도 남는다. 초기 고아 여부만 검사하는 가짜 성공을 피한다.
    assert (
        await conn.scalar(text("SELECT count(*) FROM fuel_type WHERE code=:code"), {"code": code})
        == 1
    )


async def test_parent_side_delete_allows_unreferenced_code(conn):
    """이력 참조가 없는 연료는 삭제한다. 부모 DELETE 전부를 막는 검사가 아니다."""
    code = "RF" + uuid.uuid4().hex[:12].upper()
    await conn.execute(
        text(
            "INSERT INTO fuel_type (code, display_name, cf, source_ref) "
            "VALUES (:code, '미참조 검사', 1, 'TEST')"
        ),
        {"code": code},
    )
    await conn.execute(text("DELETE FROM fuel_type WHERE code=:code"), {"code": code})
    assert (
        await conn.scalar(text("SELECT count(*) FROM fuel_type WHERE code=:code"), {"code": code})
        == 0
    )


async def test_parent_delete_trigger_roundtrip_is_idempotent(conn, monkeypatch):
    """현재 격리 DB에서 DOWN/UP을 두 번씩 호출하고 트리거 존재를 복구한다."""
    migration = _load_migration("069_fuel_type_referenced_delete.py")

    def exercise(sync):
        class BoundOp:
            def get_bind(self):
                return sync

            def execute(self, statement):
                return sync.execute(text(statement))

        monkeypatch.setattr(migration, "op", BoundOp())

        def exists():
            return sync.scalar(
                text("SELECT count(*) FROM db_trigger WHERE name=:name"),
                {"name": migration.TRIGGER_NAME},
            )

        try:
            migration.downgrade()
            migration.downgrade()
            assert exists() == 0
            migration.upgrade()
            migration.upgrade()
            assert exists() == 1
        finally:
            migration.upgrade()

    await conn.run_sync(exercise)


async def _referenced_fuel_code(conn: AsyncConnection) -> str:
    """데모 시드가 넣은 연료 실적이 가리키는 코드 — 참조 행이 있는 코드다."""
    code = await conn.scalar(text("SELECT fuel_type FROM voyage_fuel_use"))
    assert code is not None, "voyage_fuel_use가 비었다 — 데모 시드가 연료 실적을 넣지 못했다"
    return str(code)


@pytest.mark.asyncio
async def test_renaming_a_referenced_fuel_code_is_rejected(conn: AsyncConnection):
    """참조 행이 있는 연료 코드의 개명은 막힌다 (`068` · #2260).

    `067`까지는 막히지도 전파되지도 않아 자식 36행이 없는 코드를 가리켰다(실측). FK의
    ``ON UPDATE CASCADE``는 CUBRID가 받지 않고(`a7d3e9b14f26`) 자식 쪽 트리거는 **넣는 쪽만**
    보므로, 부모 쪽 ``BEFORE UPDATE``가 ``code``의 변경 자체를 거부한다.
    """
    code = await _referenced_fuel_code(conn)
    # `cubrid_errors`가 -517 REJECT를 `IntegrityError`로 옮긴다 — 이름에 불변성 표식이 없다.
    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(
            text("UPDATE fuel_type SET code = :renamed WHERE code = :code"),
            {"renamed": f"{code}_RENAMED", "code": code},
        )
    assert FUEL_TYPE_RENAME_TRIGGER in str(excinfo.value), "다른 트리거가 거부했다"


@pytest.mark.asyncio
async def test_updating_other_fuel_type_columns_passes(conn: AsyncConnection):
    """``code``가 그대로인 UPDATE는 통과한다 — `parameter_import._apply_fuel_types`의 경로다.

    개명만 막아야지 CF 개정(제자리 갱신 · `DB_SCHEMA §7.2`)까지 막으면 규제값 적재가 죽는다.
    """
    code = await _referenced_fuel_code(conn)
    before = await conn.scalar(text("SELECT cf FROM fuel_type WHERE code = :code"), {"code": code})
    assert before is not None
    await conn.execute(
        text("UPDATE fuel_type SET cf = cf + 0.000001 WHERE code = :code"), {"code": code}
    )
    after = await conn.scalar(text("SELECT cf FROM fuel_type WHERE code = :code"), {"code": code})
    assert after != before, "cf 갱신이 반영되지 않았다 — 트리거가 개명 아닌 UPDATE까지 막고 있다"


@pytest.mark.asyncio
async def test_renaming_an_unreferenced_fuel_code_is_also_rejected(conn: AsyncConnection):
    """참조 행이 **없는** 코드의 개명도 막힌다 — 조건 없이 막기로 한 결정을 고정한다 (#2260).

    ``code``는 앱 전체가 연료를 부르는 이름이라(적재·seed·CF 조회 · 계산 이력의
    ``parameters_used``) 자식 세 표에 참조가 없어도 바꾸면 이력과 어긋난다. 연료를 바꾸는
    운용은 새 코드 + 옛 코드 ``is_active = 0``이다. 조건부로 바꾸게 되면 이 검사를 함께 바꾼다.
    """
    fresh = f"T{uuid.uuid4().hex[:8].upper()}"
    # `id`는 하이픈 없는 32자 hex다(`UuidText` · `_insert_run`과 같다) — 하이픈이 있는 36자는
    # CHAR(32)에 coerce되지 않아 errno=-494로 선다(실측).
    await conn.execute(
        text(
            "INSERT INTO fuel_type (id, code, display_name, cf, source_ref, version) "
            "VALUES (:id, :code, 'rename probe', 3.114, 'test', 'test')"
        ),
        {"id": uuid.uuid4().hex, "code": fresh},
    )
    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(
            text("UPDATE fuel_type SET code = :renamed WHERE code = :code"),
            {"renamed": f"{fresh}_X", "code": fresh},
        )
    assert FUEL_TYPE_RENAME_TRIGGER in str(excinfo.value), "다른 트리거가 거부했다"


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
