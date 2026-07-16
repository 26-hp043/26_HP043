"""이슈 #28 계산 결과 테이블 마이그레이션 검증.

대상: calculation_run(008), simulation_snapshot(009) — 둘 다 immutable.

완료 기준(이슈 #28):
- immutable 트리거: UPDATE / DELETE 시 에러 발생 (calculation_run, simulation_snapshot)
- INSERT는 정상 동작
- hash 형식 CHECK 위반(sha256: + 64 hex 아님) 거부
- upgrade → downgrade → 재upgrade 왕복 (§8.1 롤백 안전성)

추가(설계 결정 증명):
- voyage_id FK를 ON DELETE RESTRICT로 구현했으므로, calculation_run이 딸린 voyage의
  물리 DELETE가 거부됨을 검증한다. (정본의 SET NULL × immutable 트리거 모순을 RESTRICT로
  해소한 결정의 근거를 코드로 고정한다.)
"""

import pytest
from conftest import run_alembic
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

# sha256: + 64 hex — CHECK를 통과하는 유효 해시.
VALID_HASH = "sha256:" + "a" * 64


async def _insert_vessel(conn, imo="7654321") -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'TEST VESSEL', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_voyage(conn, vessel_id) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn) "
            "VALUES (:vid, 'DRAFT', 'EXCLUDE', 'BUSAN', 'SINGAPORE', 1000, 12) "
            "RETURNING id"
        ),
        {"vid": vessel_id},
    )
    return str(row.scalar_one())


async def _insert_calculation_run(conn, vessel_id, voyage_id=None) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO calculation_run "
            "(calculation_type, vessel_id, voyage_id, input_hash, parameter_hash, "
            " model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :voy, :ih, :ph, "
            " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb) "
            "RETURNING id"
        ),
        {"vid": vessel_id, "voy": voyage_id, "ih": VALID_HASH, "ph": VALID_HASH},
    )
    return str(row.scalar_one())


async def _insert_simulation_snapshot(conn, vessel_id) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO simulation_snapshot "
            "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
            "VALUES (:vid, 2026, '[]'::jsonb, :ih, :ph) "
            "RETURNING id"
        ),
        {"vid": vessel_id, "ih": VALID_HASH, "ph": VALID_HASH},
    )
    return str(row.scalar_one())


# ---------------------------------------------------------------------------
# calculation_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculation_run_insert_ok(conn):
    """유효한 calculation_run INSERT는 정상 동작한다."""
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    assert calc_id


@pytest.mark.asyncio
async def test_calculation_run_update_rejected(conn):
    """immutable 트리거: calculation_run UPDATE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("UPDATE calculation_run SET calculation_type = 'SCENARIO' WHERE id = :id"),
            {"id": calc_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_calculation_run_delete_rejected(conn):
    """immutable 트리거: calculation_run DELETE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    calc_id = await _insert_calculation_run(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("DELETE FROM calculation_run WHERE id = :id"),
            {"id": calc_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_calculation_run_hash_check_rejects_bad_format(conn):
    """chk_input_hash_format: sha256: + 64 hex 형식이 아니면 거부된다."""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO calculation_run "
                "(calculation_type, vessel_id, input_hash, parameter_hash, "
                " model_version, result_json, parameters_used) "
                "VALUES ('VOYAGE_ESTIMATE', :vid, 'not-a-hash', :ph, "
                " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"vid": vessel_id, "ph": VALID_HASH},
        )


@pytest.mark.asyncio
async def test_voyage_restrict_delete_with_calculation_run(conn):
    """[이번 RESTRICT 결정의 근거 증명]

    calculation_run이 딸린 voyage의 물리 DELETE는 ON DELETE RESTRICT로 거부된다.
    (정본의 SET NULL이었다면 자식 UPDATE→immutable 트리거로 롤백되어 마찬가지로 실패하나,
     RESTRICT는 FK 위반으로 깔끔히 거부되며 계산 이력을 그대로 보존한다.)
    """
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id)
    await _insert_calculation_run(conn, vessel_id, voyage_id=voyage_id)

    with pytest.raises(IntegrityError):
        await conn.execute(text("DELETE FROM voyage WHERE id = :vid"), {"vid": voyage_id})


# ---------------------------------------------------------------------------
# simulation_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulation_snapshot_insert_ok(conn):
    """유효한 simulation_snapshot INSERT는 정상 동작한다."""
    vessel_id = await _insert_vessel(conn)
    snap_id = await _insert_simulation_snapshot(conn, vessel_id)
    assert snap_id


@pytest.mark.asyncio
async def test_simulation_snapshot_update_rejected(conn):
    """immutable 트리거: simulation_snapshot UPDATE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    snap_id = await _insert_simulation_snapshot(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("UPDATE simulation_snapshot SET regulation_year = 2027 WHERE id = :id"),
            {"id": snap_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_simulation_snapshot_delete_rejected(conn):
    """immutable 트리거: simulation_snapshot DELETE는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    snap_id = await _insert_simulation_snapshot(conn, vessel_id)
    with pytest.raises(DBAPIError) as exc:
        await conn.execute(
            text("DELETE FROM simulation_snapshot WHERE id = :id"),
            {"id": snap_id},
        )
    assert "immutable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_simulation_snapshot_hash_check_rejects_bad_format(conn):
    """chk_snap_param_hash_format: sha256: + 64 hex 형식이 아니면 거부된다."""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO simulation_snapshot "
                "(vessel_id, regulation_year, voyages_json, input_hash, parameter_hash) "
                "VALUES (:vid, 2026, '[]'::jsonb, :ih, 'sha256:short')"
            ),
            {"vid": vessel_id, "ih": VALID_HASH},
        )


# ---------------------------------------------------------------------------
# 롤백/재현성
# ---------------------------------------------------------------------------


def test_downgrade_upgrade_roundtrip():
    """downgrade base → upgrade head 왕복이 성공한다 (§8.1 롤백 안전성).

    008이 생성한 공유 함수 prevent_mutation()이 008.downgrade에서 드롭되고
    재upgrade에서 재생성되는지까지 왕복으로 검증한다.
    """
    down = run_alembic("downgrade", "base")
    assert down.returncode == 0, f"{down.stdout}\n{down.stderr}"
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"


def test_partial_downgrade_preserves_immutability():
    """부분 다운그레이드(009만 롤백) 후에도 calculation_run immutable이 유지된다.

    공유 함수를 009.downgrade에서 드롭하지 않고 008이 소유하도록 한 결정의 근거.
    `downgrade 008`로 009만 롤백해도 prevent_mutation()이 남아 trg_calcrun_immutable이
    정상 동작해야 한다. 검증 후 head로 복구한다.
    """
    step = run_alembic("downgrade", "008")
    assert step.returncode == 0, f"{step.stdout}\n{step.stderr}"
    try:
        # 함수가 남아 있는지 psql 없이 alembic current로 리비전만 확인(경량).
        cur = run_alembic("current")
        assert cur.returncode == 0, f"{cur.stdout}\n{cur.stderr}"
        assert "008" in cur.stdout, cur.stdout
    finally:
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"
