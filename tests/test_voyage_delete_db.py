"""항차 hard delete의 계산 이력 참조 검사 — DB 실동작 (#313).

``fk_calculation_run_voyage`` ON DELETE RESTRICT를 서비스가 409로 가리는지
실제 DB에서 검증한다. 참조가 있으면 물리 DELETE가 ``IntegrityError``(→500)가
아니라 409 ``CONFLICT``로 떨어져야 한다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.routes.voyages import router as voyages_router
from cii_platform.db.session import get_session

VALID_HASH = "sha256:" + "b" * 64


async def _insert_vessel(conn, imo: str) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'DELETE TEST', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_draft_voyage(conn, vessel_id: str) -> str:
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


async def _insert_calculation_run(conn, vessel_id: str, voyage_id: str) -> str:
    row = await conn.execute(
        text(
            "INSERT INTO calculation_run "
            "(calculation_type, vessel_id, voyage_id, "
            " input_hash, parameter_hash, model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :voy, :ih, :ih, 'test', "
            " '{}'::jsonb, '{}'::jsonb) RETURNING id"
        ),
        {"vid": vessel_id, "voy": voyage_id, "ih": VALID_HASH},
    )
    return str(row.scalar_one())


def _app(conn) -> FastAPI:
    async def override_session():
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = override_session
    register_exception_handlers(app)
    app.include_router(voyages_router, prefix="/api/v1")
    return app


async def test_hard_delete_with_calc_run_refs_is_409(conn):
    """계산 이력이 참조하는 DRAFT 항차 → 409 (500 아님, #313)."""
    vessel_id = await _insert_vessel(conn, "7001111")
    voyage_id = await _insert_draft_voyage(conn, vessel_id)
    await _insert_calculation_run(conn, vessel_id, voyage_id)

    with TestClient(_app(conn)) as client:
        resp = client.delete(f"/api/v1/voyages/{voyage_id}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"

    # 항차는 그대로 남는다.
    row = await conn.execute(text("SELECT count(*) FROM voyage WHERE id = :id"), {"id": voyage_id})
    assert row.scalar_one() == 1


async def test_hard_delete_without_refs_is_200(conn):
    """참조 없는 DRAFT 항차 → hard delete 200 (#313)."""
    vessel_id = await _insert_vessel(conn, "7002222")
    voyage_id = await _insert_draft_voyage(conn, vessel_id)

    with TestClient(_app(conn)) as client:
        resp = client.delete(f"/api/v1/voyages/{voyage_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["hard_delete"] is True

    row = await conn.execute(text("SELECT count(*) FROM voyage WHERE id = :id"), {"id": voyage_id})
    assert row.scalar_one() == 0
