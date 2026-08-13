"""항차 hard delete의 계산 이력 참조 검사 — DB 실동작 (#313).

``fk_calculation_run_voyage`` ON DELETE RESTRICT를 서비스가 409로 가리는지
실제 DB에서 검증한다. 참조가 있으면 물리 DELETE가 ``IntegrityError``(→500)가
아니라 409 ``CONFLICT``로 떨어져야 한다.

``conn`` fixture 세션을 TestClient 안에서 쓰면 포털 루프와 fixture 루프가
엔진 연결을 공유해 실패한다 — ``app_fresh_engine``(NullPool) + 커밋 기반이다.
행은 실제 커밋으로 심고(라우트가 다른 연결에서 읽어야 하므로), 종료 시 정리한다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.routes.voyages import router as voyages_router

VALID_HASH = "sha256:" + "b" * 64


async def _insert_vessel(session, imo: str) -> str:
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'DELETE TEST', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_draft_voyage(session, vessel_id: str) -> str:
    row = await session.execute(
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


async def _insert_calculation_run(session, vessel_id: str, voyage_id: str) -> None:
    await session.execute(
        text(
            "INSERT INTO calculation_run "
            "(calculation_type, vessel_id, voyage_id, "
            " input_hash, parameter_hash, model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :voy, :ih, :ih, "
            " '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
        ),
        {"vid": vessel_id, "voy": voyage_id, "ih": VALID_HASH},
    )


def _app() -> FastAPI:
    """get_session override 없음 — 라우트가 패치된(NullPool) 세션팩토리를 쓴다."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(voyages_router, prefix="/api/v1")
    return app


async def _cleanup(session, vessel_id: str) -> None:
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 검증을 마친 테스트
    # 데이터 정리를 위해 잠시 비활성화하고 즉시 복구한다.
    await session.execute(text("ALTER TABLE calculation_run DISABLE TRIGGER trg_calcrun_immutable"))
    await session.execute(
        text("DELETE FROM calculation_run WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    await session.execute(text("ALTER TABLE calculation_run ENABLE TRIGGER trg_calcrun_immutable"))
    await session.execute(text("DELETE FROM voyage WHERE vessel_id = :vid"), {"vid": vessel_id})
    await session.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
    await session.commit()


async def test_hard_delete_with_calc_run_refs_is_409(migrated_db, app_fresh_engine):
    """계산 이력이 참조하는 DRAFT 항차 → 409 (500 아님, #313)."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = voyage_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _insert_vessel(s, "7001111")
            voyage_id = await _insert_draft_voyage(s, vessel_id)
            await _insert_calculation_run(s, vessel_id, voyage_id)
            await s.commit()

        with TestClient(_app()) as client:
            resp = client.delete(f"/api/v1/voyages/{voyage_id}")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"

        async with sessionmaker() as s:
            row = await s.execute(
                text("SELECT count(*) FROM voyage WHERE id = :id"), {"id": voyage_id}
            )
            assert row.scalar_one() == 1
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


async def test_hard_delete_without_refs_is_200(migrated_db, app_fresh_engine):
    """참조 없는 DRAFT 항차 → hard delete 200 (#313)."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = voyage_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _insert_vessel(s, "7002222")
            voyage_id = await _insert_draft_voyage(s, vessel_id)
            await s.commit()

        with TestClient(_app()) as client:
            resp = client.delete(f"/api/v1/voyages/{voyage_id}")

        assert resp.status_code == 200
        assert resp.json()["data"]["hard_delete"] is True

        async with sessionmaker() as s:
            row = await s.execute(
                text("SELECT count(*) FROM voyage WHERE id = :id"), {"id": voyage_id}
            )
            assert row.scalar_one() == 0
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
