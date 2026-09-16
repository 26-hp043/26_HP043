"""calculation_run needs_recalc 가드 트리거 실동작 검증 (#283, 마이그레이션 024).

024가 세운 규칙을 DB에서 직접 검증한다:

1. ``needs_recalc`` false→true 플립은 **허용** (다른 컬럼 불변 시)
2. result_json 등 다른 컬럼 UPDATE는 **여전히 거부** (immutable 유지)
3. true→false 되돌림은 **거부** (표시는 누적 전용)
4. DELETE는 **여전히 거부** (계산 이력 보존)
5. ``mark_needs_recalc`` 저장소 함수가 1번 경로로 동작
6. 🔴 **nullable 열이 NULL↔값으로 바뀌는 것도 거부** (`051` · `#1058`)

calculation_run INSERT 시 needs_recalc는 기본 false — 024의 server_default.

## 6번이 왜 새로 생겼나

CUBRID 전환 뒤 2번이 **nullable 열에서 뚫려 있었다.** 트리거 조건이
``new.c = obj.c OR (둘 다 NULL)``이라 한쪽만 NULL이면 식이 NULL이 되고,
``IF NOT (NULL)``은 거부하지 않는다. 그래서 ``duration_ms``·``warnings_json``이 NULL인
실행(= 갓 저장된 실행의 흔한 모양)은 **플립과 함께 값을 채워 넣을 수 있었다.**
``051``이 NULL 갈래를 명시해 막았고, 아래 표가 그것을 고정한다.
"""

from __future__ import annotations

import pytest
from conftest import insert_returning_id
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

VALID_HASH = "sha256:" + "d" * 64


async def _insert_vessel(conn, imo: str) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO vessel (imo_number, name, ship_type) "
        "VALUES (:imo, 'RECALC TEST', 'BULK_CARRIER') RETURNING id",
        {"imo": imo},
    )


async def _insert_calculation_run(conn, vessel_id: str) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO calculation_run "
        "(calculation_type, vessel_id, input_hash, parameter_hash, "
        " model_version, result_json, parameters_used) "
        "VALUES ('VOYAGE_ESTIMATE', :vid, :ih, :ih, "
        "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb) RETURNING id",
        {"vid": vessel_id, "ih": VALID_HASH},
    )


async def test_needs_recalc_flip_allowed(conn):
    """플립(false→true, 단일 컬럼)은 가드가 통과시킨다 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300101")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    await conn.execute(
        text("UPDATE calculation_run SET needs_recalc = true WHERE id = :id"),
        {"id": calc_id},
    )
    row = await conn.execute(
        text("SELECT needs_recalc FROM calculation_run WHERE id = :id"), {"id": calc_id}
    )
    # CUBRID에 BOOLEAN이 없다 — `sa.Boolean()`이 SMALLINT로 내려가 **1**이 온다
    # (`a7d3e9b14f26`이 `needs_recalc`에서 같은 것을 확인했다 · `#1058`).
    # `is True`로 보면 여기서 선다.
    assert row.scalar_one() == 1


async def test_other_column_update_still_rejected(conn):
    """result_json 변경 UPDATE는 여전히 거부 — immutable 유지 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300202")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("UPDATE calculation_run SET duration_ms = 1 WHERE id = :id"),
            {"id": calc_id},
        )
    assert "immutable" in str(exc.value).lower()


async def test_flip_with_other_column_change_rejected(conn):
    """플립 + 다른 컬럼 동시 변경도 거부 — 플립만 통과 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300303")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = true, duration_ms = 1 WHERE id = :id"),
            {"id": calc_id},
        )


async def test_rollback_flip_rejected(conn):
    """true→false 되돌림은 거부 — 표시는 누적 전용 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300404")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    await conn.execute(
        text("UPDATE calculation_run SET needs_recalc = true WHERE id = :id"),
        {"id": calc_id},
    )
    with pytest.raises(DBAPIError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = false WHERE id = :id"),
            {"id": calc_id},
        )


async def test_delete_still_rejected(conn):
    """DELETE는 종전처럼 거부 — 계산 이력 보존 (#283)."""
    vessel_id = await _insert_vessel(conn, "7300505")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError):
        await conn.execute(text("DELETE FROM calculation_run WHERE id = :id"), {"id": calc_id})


async def test_mark_needs_recalc_repository_flips_only_matching(conn):
    """저장소 함수 — 대상 선박의 미표시 행만 true로 (#283).

    ``conn`` fixture는 함수 단일 트랜잭션이라 트리거 위반이 나면 이후 명령이
    전부 abort된다 — 위반 케이스와 성공 케이스를 한 테스트에 섞지 않는다
    (test_db_hardening_023과 같은 교훈).
    """
    from cii_platform.db.repositories.calculation_run import mark_needs_recalc

    class _SyncExecuteAdapter:
        """conn(run_sync 호환)을 AsyncSession.execute처럼 노출한다."""

        def __init__(self, connection):
            self._conn = connection

        async def execute(self, stmt, params=None):
            return await self._conn.execute(stmt, params or {})

    vessel_id = await _insert_vessel(conn, "7300606")
    other_vessel_id = await _insert_vessel(conn, "7300707")
    await _insert_calculation_run(conn, vessel_id)
    await _insert_calculation_run(conn, vessel_id)
    await _insert_calculation_run(conn, other_vessel_id)

    marked = await mark_needs_recalc(_SyncExecuteAdapter(conn), vessel_id)
    assert marked == 2

    row = await conn.execute(
        text("SELECT count(*) FROM calculation_run WHERE vessel_id = :vid AND needs_recalc = true"),
        {"vid": vessel_id},
    )
    assert row.scalar_one() == 2
    other = await conn.execute(
        text("SELECT count(*) FROM calculation_run WHERE vessel_id = :vid AND needs_recalc = true"),
        {"vid": other_vessel_id},
    )
    assert other.scalar_one() == 0


# ---------------------------------------------------------------------------
# 6. 🔴 nullable 열의 NULL ↔ 값 변경 (`051`)
# ---------------------------------------------------------------------------


async def _insert_run_with_duration(conn, vessel_id: str, duration_ms: int) -> str:
    """``duration_ms``에 값이 있는 실행. NULL → 값 / 값 → NULL 양방향을 보려면 둘 다 필요하다."""
    return await insert_returning_id(
        conn,
        "INSERT INTO calculation_run "
        "(calculation_type, vessel_id, input_hash, parameter_hash, "
        " model_version, result_json, parameters_used, duration_ms) "
        "VALUES ('VOYAGE_ESTIMATE', :vid, :ih, :ih, "
        "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, :dur) RETURNING id",
        {"vid": vessel_id, "ih": VALID_HASH, "dur": duration_ms},
    )


async def test_flip_with_a_null_column_filled_in_is_rejected(conn):
    """🔴 NULL이던 ``duration_ms``를 플립과 함께 채우는 것은 거부된다 (`051`).

    **전환 뒤 이것이 통과하고 있었다.** 갓 저장된 실행은 ``duration_ms``가 NULL인 경우가
    많아 현실에서 가장 흔한 모양이 막히지 않았다.
    """
    vessel_id = await _insert_vessel(conn, "7310101")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = 1, duration_ms = 1 WHERE id = :id"),
            {"id": calc_id},
        )


async def test_flip_with_a_value_column_nulled_out_is_rejected(conn):
    """🔴 반대 방향 — 값이 있던 열을 플립과 함께 NULL로 만드는 것도 거부된다 (`051`)."""
    vessel_id = await _insert_vessel(conn, "7310202")
    calc_id = await _insert_run_with_duration(conn, vessel_id, 42)

    with pytest.raises(DBAPIError):
        await conn.execute(
            text("UPDATE calculation_run SET needs_recalc = 1, duration_ms = NULL WHERE id = :id"),
            {"id": calc_id},
        )


async def test_flip_with_warnings_filled_in_is_rejected(conn):
    """🔴 ``warnings_json``도 같다 — 저장된 실행의 경고를 사후에 넣을 수 없다 (`051`).

    이쪽이 사용자에게 더 직접 보인다. 화면·리포트가 그 실행에 붙여 보여 주는 값이라,
    나중에 넣거나 지울 수 있으면 「그때 무슨 경고가 있었나」가 사실이 아니게 된다.
    """
    vessel_id = await _insert_vessel(conn, "7310303")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    with pytest.raises(DBAPIError):
        await conn.execute(
            text(
                "UPDATE calculation_run SET needs_recalc = 1, "
                "warnings_json = '[\"WARNING_X\"]' WHERE id = :id"
            ),
            {"id": calc_id},
        )


async def test_the_flip_still_passes_when_a_null_column_stays_null(conn):
    """대칭 — 막는 조건이 **정상 플립까지 막지 않는다.**

    이 검사가 없으면 `051`의 조건이 평가 불가가 되어 전부 거부되는 상태를 통과시킨다.
    실제로 그런 판을 한 번 만들었다 — ``<=>``(NULL-safe 등호)는 ``SELECT``에서는 되지만
    **트리거 조건에서는 평가되지 않는다**(``Cannot evaluate 'new.id<=>obj.id'``, errno=-527).
    """
    vessel_id = await _insert_vessel(conn, "7310404")
    calc_id = await _insert_calculation_run(conn, vessel_id)

    await conn.execute(
        text("UPDATE calculation_run SET needs_recalc = 1 WHERE id = :id"), {"id": calc_id}
    )
    row = await conn.execute(
        text("SELECT needs_recalc, duration_ms FROM calculation_run WHERE id = :id"),
        {"id": calc_id},
    )
    assert tuple(row.one()) == (1, None)


async def test_the_flip_still_passes_when_a_value_column_keeps_its_value(conn):
    """대칭 — 값이 **그대로인** nullable 열이 있어도 플립은 통과한다 (`051`).

    NULL 갈래를 적으면서 `값 = 값` 갈래를 빠뜨리면 여기서 걸린다.
    """
    vessel_id = await _insert_vessel(conn, "7310505")
    calc_id = await _insert_run_with_duration(conn, vessel_id, 7)

    await conn.execute(
        text("UPDATE calculation_run SET needs_recalc = 1, duration_ms = 7 WHERE id = :id"),
        {"id": calc_id},
    )
    row = await conn.execute(
        text("SELECT needs_recalc, duration_ms FROM calculation_run WHERE id = :id"),
        {"id": calc_id},
    )
    assert tuple(row.one()) == (1, 7)
