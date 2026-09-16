"""이슈 #345 not under way 테이블 마이그레이션 검증.

완료 기준(이슈 #345):
- ``alembic upgrade head`` 후 두 테이블 생성 (conftest migrated_db fixture로 보장)
- ``period_type``·``consumer_type``에 허용값 외 INSERT가 거부됨
- ``not_underway_period`` 삭제 시 자식 행이 CASCADE 삭제됨
- ``test_orm_schema_sync`` 통과 (모델 등록으로 자동 검증)

추가:
- FK RESTRICT: 정박 기록이 있는 vessel 물리 삭제 거부
- FK SET NULL: 항차 삭제 시 voyage_id만 NULL로
- 인덱스 존재 — partial(vessel_id, regulation_year)·period_id 자식 인덱스
- updated_at 트리거 갱신 (§7.2)

(downgrade/upgrade 왕복은 전역 스키마를 변형하므로 test_zz_roundtrip.py가 담당.)
"""

import asyncio
import uuid

import pytest
from conftest import insert_returning_id, uuid_hex
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _insert_vessel(conn, imo="1234567") -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO vessel (imo_number, name, ship_type) "
        "VALUES (:imo, 'TEST VESSEL', 'BULK_CARRIER') RETURNING id",
        {"imo": imo},
    )


async def _insert_voyage(conn, vessel_id) -> str:
    return await insert_returning_id(
        conn,
        "INSERT INTO voyage "
        "(vessel_id, status, annual_inclusion_policy, regulation_year, "
        " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn) "
        "VALUES (:vid, 'DRAFT', 'EXCLUDE', NULL, 'BUSAN', 'SINGAPORE', 1000, 12) "
        "RETURNING id",
        {"vid": vessel_id},
    )


async def _insert_period(
    conn,
    vessel_id,
    *,
    period_type="AT_ANCHOR",
    started_at="DATETIMETZ'2026-01-10 00:00:00 +00:00'",
    ended_at="DATETIMETZ'2026-01-12 00:00:00 +00:00'",
    voyage_id=None,
) -> str:
    # 시각은 CUBRID DATETIMETZ 리터럴이다 — PostgreSQL의 `'…T…+00'::timestamptz`는
    # CUBRID가 `Invalid or missing timezone`으로 거부한다 (#1058, 실측).
    voyage_expr = f"'{uuid_hex(voyage_id)}'" if voyage_id is not None else "NULL"
    return await insert_returning_id(
        conn,
        "INSERT INTO not_underway_period "
        "(vessel_id, regulation_year, period_type, started_at, ended_at, voyage_id) "
        f"VALUES ('{uuid_hex(vessel_id)}', 2026, :ptype, {started_at}, {ended_at}, "
        f"{voyage_expr}) "
        "RETURNING id",
        {"ptype": period_type},
    )


async def _insert_fuel(
    conn,
    period_id,
    *,
    consumer_type="AUX_ENGINE",
    fuel_type="HFO",
    fuel_ton=12.5,
    cf_used=3.114,
):
    # 030 (#378) — cf_used는 NOT NULL. 기본값은 017 seed의 HFO CF와 같다.
    await conn.execute(
        text(
            "INSERT INTO not_underway_fuel_use "
            "(period_id, consumer_type, fuel_type, fuel_ton, cf_used) "
            "VALUES (:pid, :ctype, :ftype, :ton, :cf)"
        ),
        {
            "pid": period_id,
            "ctype": consumer_type,
            "ftype": fuel_type,
            "ton": fuel_ton,
            "cf": cf_used,
        },
    )


@pytest.mark.asyncio
async def test_period_insert_ok_with_voyage_context(conn):
    """정상 INSERT — 항차 맥락 참조·종료 시각 NULL(진행 중 정박)도 허용."""
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id)
    period_id = await _insert_period(
        conn, vessel_id, period_type="IN_PORT", ended_at="NULL", voyage_id=voyage_id
    )

    row = await conn.execute(
        text(
            "SELECT vessel_id, regulation_year, period_type, ended_at, voyage_id "
            "FROM not_underway_period WHERE id = :pid"
        ),
        {"pid": period_id},
    )
    result = row.one()
    assert str(result.vessel_id) == vessel_id
    assert result.regulation_year == 2026
    assert result.period_type == "IN_PORT"
    assert result.ended_at is None
    assert str(result.voyage_id) == voyage_id


@pytest.mark.asyncio
async def test_period_type_rejects_unknown_value(conn):
    """period_type 허용값 6종 밖은 chk_not_underway_period_type으로 거부."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _insert_period(conn, vessel_id, period_type="SAILING")


@pytest.mark.asyncio
async def test_consumer_type_rejects_unknown_value(conn):
    """consumer_type 허용값 4종 밖은 chk_not_underway_consumer_type으로 거부."""
    vessel_id = await _insert_vessel(conn)
    period_id = await _insert_period(conn, vessel_id)

    with pytest.raises(IntegrityError):
        await _insert_fuel(conn, period_id, consumer_type="CARGO_HEATING")


@pytest.mark.asyncio
async def test_period_time_order_rejects_ended_before_started(conn):
    """ended_at ≤ started_at은 chk_not_underway_period_time_order로 거부."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _insert_period(
            conn,
            vessel_id,
            started_at="DATETIMETZ'2026-01-12 00:00:00 +00:00'",
            ended_at="DATETIMETZ'2026-01-10 00:00:00 +00:00'",
        )


@pytest.mark.asyncio
async def test_fuel_ton_rejects_non_positive(conn):
    """fuel_ton ≤ 0은 chk_not_underway_fuel_positive로 거부."""
    vessel_id = await _insert_vessel(conn)
    period_id = await _insert_period(conn, vessel_id)

    with pytest.raises(IntegrityError):
        await _insert_fuel(conn, period_id, fuel_ton=0)


@pytest.mark.asyncio
async def test_fuel_type_rejects_unknown_code(conn):
    """fuel_type FK — 존재하지 않는 코드는 거부 (§7.1 [S-1]).

    참조하는 'HFO'는 017이 적재한 seed 행이다 (#83).
    """
    vessel_id = await _insert_vessel(conn)
    period_id = await _insert_period(conn, vessel_id)

    with pytest.raises(IntegrityError):
        await _insert_fuel(conn, period_id, fuel_type="NO_SUCH_FUEL")


@pytest.mark.asyncio
async def test_period_rejects_vessel_physical_delete(conn):
    """정박 기록이 있는 선박의 물리 삭제는 RESTRICT로 거부된다."""
    vessel_id = await _insert_vessel(conn)
    await _insert_period(conn, vessel_id)

    with pytest.raises(IntegrityError):
        await conn.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})


@pytest.mark.asyncio
async def test_voyage_delete_sets_period_voyage_null(conn):
    """항차 삭제 시 정박 기록은 남고 voyage_id만 NULL이 된다 (맥락 참조)."""
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id)
    period_id = await _insert_period(conn, vessel_id, voyage_id=voyage_id)

    await conn.execute(text("DELETE FROM voyage WHERE id = :vid"), {"vid": voyage_id})

    row = await conn.execute(
        text("SELECT voyage_id FROM not_underway_period WHERE id = :pid"),
        {"pid": period_id},
    )
    assert row.scalar_one() is None


@pytest.mark.asyncio
async def test_period_delete_cascades_fuel_rows(conn):
    """구간 삭제 시 not_underway_fuel_use 자식 행이 CASCADE로 함께 삭제된다."""
    vessel_id = await _insert_vessel(conn)
    period_id = await _insert_period(conn, vessel_id)
    await _insert_fuel(conn, period_id, consumer_type="MAIN_ENGINE", fuel_ton=3.2)
    await _insert_fuel(conn, period_id, consumer_type="AUX_ENGINE", fuel_ton=1.1)

    await conn.execute(text("DELETE FROM not_underway_period WHERE id = :pid"), {"pid": period_id})

    count = await conn.scalar(
        text("SELECT count(*) FROM not_underway_fuel_use WHERE period_id = :pid"),
        {"pid": period_id},
    )
    assert count == 0


@pytest.mark.asyncio
async def test_expected_indexes_present(conn):
    """인덱스 구성 — #345(025)의 partial 인덱스 + #376(029)의 3종.

    029는 UNIQUE의 선행열이 ``period_id``로 같아 완전히 중복되는
    ``idx_not_underway_fuel_use_period``를 제거했다(``voyage_fuel_use`` 선례).
    """
    # CUBRID 카탈로그 — `db_index`(이름·UNIQUE·filter_expression) ⋈ `db_index_key`(키 열).
    # PostgreSQL `pg_indexes.indexdef` 한 줄이 여기서는 세 조각으로 갈라진다 (#1058).
    rows = await conn.execute(
        text(
            "SELECT i.index_name, i.is_unique, i.filter_expression, k.key_attr_name "
            "FROM db_index i JOIN db_index_key k "
            "  ON k.class_name = i.class_name AND k.index_name = i.index_name "
            "WHERE i.class_name IN ('not_underway_period', 'not_underway_fuel_use') "
            "ORDER BY i.index_name, k.key_order"
        )
    )
    defs: dict[str, dict] = {}
    for r in rows:
        entry = defs.setdefault(
            r.index_name,
            {"unique": r.is_unique == "YES", "filter": r.filter_expression, "cols": []},
        )
        entry["cols"].append(r.key_attr_name)

    vessel_year = defs.get("idx_not_underway_period_vessel_year")
    assert vessel_year is not None, f"partial 인덱스 없음: {defs}"
    assert "vessel_id" in vessel_year["cols"]
    assert "regulation_year" in vessel_year["cols"]
    # soft delete 호환 — 활성 행만 인덱싱 (vessel의 idx_vessel_imo 패턴).
    # PostgreSQL의 `WHERE is_deleted = false`는 CUBRID filtered index의 filter_expression이다.
    assert vessel_year["filter"] is not None and "is_deleted" in vessel_year["filter"], (
        f"활성 행만 거르는 filter가 없음: {vessel_year}"
    )

    # --- 029 (#376) ---------------------------------------------------------
    # (1) 정합성 — 구간+소비원+연료 UNIQUE.
    fuel_unique = defs.get("idx_not_underway_fuel_use_unique")
    assert fuel_unique is not None, f"UNIQUE 인덱스 없음: {defs}"
    assert fuel_unique["unique"], f"UNIQUE가 아님: {fuel_unique}"
    for col in ("period_id", "consumer_type", "fuel_type"):
        assert col in fuel_unique["cols"], f"{col}이 UNIQUE 키에 없음: {fuel_unique}"

    # 중복 인덱스는 029가 제거했다 — 되살아나면 쓰기마다 두 번 갱신된다.
    assert "idx_not_underway_fuel_use_period" not in defs, (
        f"029가 제거한 중복 인덱스가 남아 있음: {defs}"
    )

    # (2) #368 구간 겹침 조회 — started_at이 인덱스에 들어간다.
    vessel_started = defs.get("idx_not_underway_period_vessel_started")
    assert vessel_started is not None, f"(vessel_id, started_at) 인덱스 없음: {defs}"
    assert "vessel_id" in vessel_started["cols"]
    assert "started_at" in vessel_started["cols"]
    assert vessel_started["filter"] is not None and "is_deleted" in vessel_started["filter"], (
        f"활성 행만 거르는 filter가 없음: {vessel_started}"
    )

    # (3) voyage FK 자식 인덱스 — SET NULL 확인 경로. partial이면 안 된다.
    voyage_child = defs.get("idx_not_underway_period_voyage")
    assert voyage_child is not None, f"voyage_id 자식 인덱스 없음: {defs}"
    assert "voyage_id" in voyage_child["cols"]
    assert voyage_child["filter"] is None, (
        f"FK 확인은 삭제된 행도 봐야 하므로 partial이면 안 된다: {voyage_child}"
    )


@pytest.mark.asyncio
async def test_fuel_use_rejects_duplicate_consumer_fuel(conn):
    """같은 구간+소비원+연료 중복 삽입을 거부한다 (#376 · §2.3 [S-2] 패턴).

    중복이 들어가면 ``sum_fuel_by_type``(#353)이 그대로 합산해 분자 ``M``이 부풀고
    등급이 실제보다 나쁘게 나온다.
    """
    vessel_id = await _insert_vessel(conn, imo="9376001")
    period_id = await _insert_period(conn, vessel_id)
    await _insert_fuel(conn, period_id, consumer_type="AUX_ENGINE", fuel_type="HFO")

    with pytest.raises(IntegrityError):
        await _insert_fuel(conn, period_id, consumer_type="AUX_ENGINE", fuel_type="HFO")


@pytest.mark.asyncio
async def test_fuel_use_allows_same_fuel_for_other_consumer(conn):
    """소비원이 다르면 같은 연료를 허용한다 — UNIQUE 키가 3열인 이유.

    MEPC.385(81) DCS 보고 단위가 「구간 × 소비원 × 연료」이므로, 한 구간에서
    보조엔진과 보일러가 같은 유종을 쓰는 것은 정상 기록이다.
    """
    vessel_id = await _insert_vessel(conn, imo="9376002")
    period_id = await _insert_period(conn, vessel_id)
    await _insert_fuel(conn, period_id, consumer_type="AUX_ENGINE", fuel_type="HFO")
    await _insert_fuel(conn, period_id, consumer_type="OIL_FIRED_BOILER", fuel_type="HFO")

    count = await conn.scalar(
        text("SELECT count(*) FROM not_underway_fuel_use WHERE period_id = :pid"),
        {"pid": period_id},
    )
    assert count == 2


async def test_period_update_touches_updated_at(migrated_db):
    """UPDATE 시 updated_at이 자동 갱신된다 (trg_not_underway_period_updated, §7.2).

    ``conn`` fixture는 단일 트랜잭션이라 ``now()``가 트랜잭션 시작 시각으로
    고정돼 트리거 갱신을 관측할 수 없다 — 별도 커밋으로 검증한다
    (test_app_user_migration의 #317 패턴).
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    period_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await insert_returning_id(
                s,
                "INSERT INTO vessel (imo_number, name, ship_type) "
                "VALUES ('7654321', 'TRG VESSEL', 'BULK_CARRIER') RETURNING id",
                {},
            )
            # CUBRID에는 RETURNING이 없고 앱 엔진은 id를 자동으로 붙이지 않는다 —
            # id를 여기서 만들어 넣고 updated_at은 되읽는다 (#1058).
            period_id = uuid.uuid4().hex
            await s.execute(
                text(
                    "INSERT INTO not_underway_period "
                    "(id, vessel_id, regulation_year, period_type, started_at, port_name) "
                    "VALUES (:pid, :vid, 2026, 'AT_ANCHOR', "
                    "DATETIMETZ'2026-01-10 00:00:00 +00:00', 'BUSAN')"
                ),
                {"pid": period_id, "vid": vessel_id},
            )
            before = await s.execute(
                text("SELECT updated_at FROM not_underway_period WHERE id = :pid"),
                {"pid": period_id},
            )
            updated_before = before.scalar_one()
            await s.commit()

        # 트리거는 now()를 새로 찍는다 — 트랜잭션이 달라져야 시차가 생긴다.
        await asyncio.sleep(1.05)

        async with sessionmaker() as s:
            await s.execute(
                text("UPDATE not_underway_period SET port_name = 'SINGAPORE' WHERE id = :pid"),
                {"pid": period_id},
            )
            await s.commit()
            after = await s.execute(
                text("SELECT updated_at FROM not_underway_period WHERE id = :pid"),
                {"pid": period_id},
            )
            updated_after = after.scalar_one()

        assert updated_after > updated_before
    finally:
        async with sessionmaker() as s:
            await s.execute(
                text("DELETE FROM not_underway_period WHERE id = :pid"),
                {"pid": period_id},
            )
            await s.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
            await s.commit()
        await get_engine().dispose()


@pytest.mark.asyncio
async def test_fuel_use_requires_cf_snapshot(conn):
    """``cf_used``는 NOT NULL이다 (#378 · 030).

    NULL을 허용하면 집계마다 「snapshot 있음/없음」 분기가 생기고, 그 분기가 곧
    030이 없앤 이중 CF 경로다.
    """
    vessel_id = await _insert_vessel(conn, imo="9378001")
    period_id = await _insert_period(conn, vessel_id)

    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO not_underway_fuel_use "
                "(period_id, consumer_type, fuel_type, fuel_ton) "
                "VALUES (:pid, 'AUX_ENGINE', 'HFO', 1.0)"
            ),
            {"pid": period_id},
        )


@pytest.mark.asyncio
async def test_fuel_use_rejects_non_positive_cf(conn):
    """``cf_used <= 0``은 chk_nufu_cf_used_positive로 거부된다 (#96 chk_cf_positive 선례)."""
    vessel_id = await _insert_vessel(conn, imo="9378002")
    period_id = await _insert_period(conn, vessel_id)

    with pytest.raises(IntegrityError):
        await _insert_fuel(conn, period_id, cf_used=0)
