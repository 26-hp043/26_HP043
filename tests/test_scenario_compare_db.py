"""기능② DB 실동작 테스트 (#57) — 시나리오 3행·SCENARIO 이력·감사 저장.

계약 테스트(``test_scenario_compare_api.py``)가 저장소를 대역으로 쓰는 반면,
여기는 **실제 INSERT·제약·트리거**를 검증한다 — ``voyage_scenario`` 3행,
``calculation_run`` 1행(``SCENARIO``), ``audit_log`` 1건.

파라미터 시드 상태: 017이 ``fuel_type`` 8행을 넣으므로 HFO는 이미 있다. 나머지
(``regulation_year``·``cii_reference_line``·``cii_rating_boundary``)는 data
migration이 아니라 ``scripts/seed.py`` 경로(#127)이므로 여기서 직접 심는다.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"

IMO = "7200577"

PAYLOAD: dict[str, Any] = {
    "regulation_year": 2026,
    "current_speed_kn": 14.0,
    "fuel_type": "HFO",
    "base_daily_foc_ton": 35.0,
    "direct_distance_nm": 11000.0,
}


async def _seed_parameters(session) -> None:
    await session.execute(
        text(
            "INSERT INTO regulation_year "
            "(year, z_factor_percent, effective_from, source_ref, version) "
            "VALUES (2026, 11.0, '2026-01-01', 'TEST', '1.0')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_reference_line "
            "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
            "VALUES ('BULK_CARRIER', 'all', 'DWT', '4745', 4745, 0.622, 'TEST')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_rating_boundary "
            "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
            "VALUES ('BULK_CARRIER', 'all', 'DWT', 0.86, 0.94, 1.06, 1.18, 'TEST')"
        )
    )


async def _insert_vessel(session) -> str:
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
            "reference_speed_kn) "
            "VALUES (:imo, 'SCENARIO DB TEST', 'BULK_CARRIER', 30000, 50000, 14.0) "
            "RETURNING id"
        ),
        {"imo": IMO},
    )
    return str(row.scalar_one())


async def _cleanup(session, vessel_id: str) -> None:
    # voyage_scenario는 soft delete 대상이지만 테스트 정리는 물리 삭제로 한다.
    await session.execute(
        text("DELETE FROM voyage_scenario WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 잠시 끄고 즉시 복구
    # (test_voyage_delete_db.py와 같은 패턴). audit_log는 _delete_stub_user가
    # 전량 삭제하므로 여기서 건드리지 않는다.
    await session.execute(text("ALTER TABLE calculation_run DISABLE TRIGGER trg_calcrun_immutable"))
    await session.execute(
        text("DELETE FROM calculation_run WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    await session.execute(text("ALTER TABLE calculation_run ENABLE TRIGGER trg_calcrun_immutable"))
    await session.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
    await session.execute(text("DELETE FROM cii_rating_boundary WHERE source_ref = 'TEST'"))
    await session.execute(text("DELETE FROM cii_reference_line WHERE source_ref = 'TEST'"))
    await session.execute(text("DELETE FROM regulation_year WHERE source_ref = 'TEST'"))
    await session.commit()


async def _delete_stub_user() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(text("DELETE FROM audit_log"))
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE google_sub = 'stub-dev-user-00000000')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE google_sub = 'stub-dev-user-00000000'"))
        await s.commit()
    await get_engine().dispose()


async def test_compare_persists_three_scenarios_and_run(migrated_db, app_fresh_engine):
    """응답 200 + voyage_scenario 3행 + calculation_run(SCENARIO) 1행 + 감사 1건."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            await _seed_parameters(s)
            vessel_id = await _insert_vessel(s)
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            # dev-login이 csrf 쿠키(httponly=false)를 심는다 — 헤더로 올려 보낸다.
            csrf = client.cookies.get("csrf")
            resp = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **PAYLOAD},
                headers={"X-CSRF-Token": csrf or ""},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        types = [s["scenario_type"] for s in body["data"]["scenarios"]]
        assert types == ["DIRECT", "DETOUR", "SLOW_STEAMING"]

        # 응답 scenario_id가 실제 저장된 행의 PK와 일치하는지.
        scenario_ids = {s["scenario_id"] for s in body["data"]["scenarios"]}

        async with sessionmaker() as s:
            rows = (
                (
                    await s.execute(
                        text(
                            "SELECT id, scenario_type, cii_value, estimated_rating, "
                            "risk_level, voyage_id, fuel_ton, duration_hours "
                            "FROM voyage_scenario WHERE vessel_id = :vid"
                        ),
                        {"vid": vessel_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == 3
            assert {str(r["id"]) for r in rows} == scenario_ids
            # created_at의 server_default now()는 트랜잭션 시각이라 3행이 같다 —
            # 순서 보장이 없으므로 type을 키로 잡아 비교한다.
            rows_by_type = {r["scenario_type"]: r for r in rows}
            assert set(rows_by_type) == {"DIRECT", "DETOUR", "SLOW_STEAMING"}
            assert all(r["voyage_id"] is None for r in rows)  # 독립 시나리오
            # 계약 테스트 앵커와 같은 값 — 계약(DB 없음) ↔ DB 양쪽이 같은 확정값.
            # fuel_ton은 DB scale이 4(1145.8333), 응답 직렬화는 2자리(1145.83)다.
            direct = rows_by_type["DIRECT"]
            assert round(float(direct["fuel_ton"]), 2) == 1145.83
            assert float(direct["duration_hours"]) == 785.71

            run = (
                await s.execute(
                    text(
                        "SELECT calculation_type, result_json FROM calculation_run "
                        "WHERE vessel_id = :vid"
                    ),
                    {"vid": vessel_id},
                )
            ).fetchone()
            assert run is not None
            assert run.calculation_type == "SCENARIO"
            assert len(run.result_json["scenarios"]) == 3

            audit = (
                await s.execute(
                    text(
                        "SELECT details_json FROM audit_log "
                        "WHERE action = 'CALCULATION_RUN' AND entity_id::text = :rid"
                    ),
                    {"rid": body["calculation_run_id"]},
                )
            ).fetchone()
            assert audit is not None
            assert audit.details_json["calculation_type"] == "SCENARIO"
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


async def test_compare_idempotent_rows_on_repeat(migrated_db, app_fresh_engine):
    """같은 요청을 반복해도 계산 이력·시나리오는 계속 쌓인다(멱등성 없음, #55 규칙)."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            await _seed_parameters(s)
            vessel_id = await _insert_vessel(s)
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            csrf = client.cookies.get("csrf")
            headers = {"X-CSRF-Token": csrf or ""}
            for _ in range(2):
                resp = client.post(
                    "/api/v1/scenarios/compare",
                    json={"vessel_id": vessel_id, **PAYLOAD},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text

        async with sessionmaker() as s:
            count = (
                await s.execute(
                    text("SELECT count(*) FROM voyage_scenario WHERE vessel_id = :vid"),
                    {"vid": vessel_id},
                )
            ).scalar_one()
            assert count == 6  # 요청 2회 × 시나리오 3행 — 계산은 append-only다.
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
