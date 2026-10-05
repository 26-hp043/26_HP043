"""시나리오 채택 요청의 경계 — HTTP 수준 (#2091).

``POST /scenarios/{id}/adopt``(``UPDATE_EXISTING_PLAN``)가 항차 생성과 **같은 규칙**을
쓰는지 실제 응답 본문으로 확인한다 (``API_SPEC §5.1``·``§5.2``).

⑴ 출항 예정 시각이 없는 항차의 도착 예정 시각을 지우지 않고, ``updated_fields``도
   그 키를 싣지 않는다.
⑵ 항만명 상한이 항차 생성(200자)과 같다.
⑶ ``base_daily_foc_ton``은 선박 기준 일일 연료와 같은 ``NUMERIC(8,2)`` 범위다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"
_ARRIVAL = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _seed(departure: datetime | None) -> tuple[UUID, UUID, UUID]:
    """선박·계획 항차(도착 예정만 있거나 출항 예정도 있음)·시나리오를 SQL로 넣는다."""
    from cii_platform.db.session import get_sessionmaker

    vessel_id = uuid4()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                "default_fuel_type) VALUES (:id, :imo, 'ADOPT BOUNDARY', 'BULK_CARRIER', "
                "50000, 'HFO')"
            ),
            {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
        )
        voyage_id = UUID(
            await insert_returning_id(
                s,
                "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, "
                " regulation_year, departure_port_name, arrival_port_name, "
                " planned_distance_nm, planned_speed_kn, planned_departure_at, "
                " planned_arrival_at, created_from) "
                "VALUES (:vid, 'PLANNED', 'INCLUDE_AS_PLAN', 2026, 'BUSAN', 'SINGAPORE', "
                " 1000, 12, :dep, :arr, 'MANUAL') RETURNING id",
                {"vid": vessel_id, "dep": departure, "arr": _ARRIVAL},
            )
        )
        await s.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
                "cf_used, source) VALUES (:vid, 'HFO', 80, 3.114, 'USER_INPUT')"
            ),
            {"vid": voyage_id},
        )
        scenario_id = UUID(
            await insert_returning_id(
                s,
                "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, "
                " distance_nm, speed_kn, duration_hours, fuel_ton, cii_value, "
                " estimated_rating, risk_level) "
                "VALUES (:vid, 'SLOW_STEAMING', '감속 운항', 2000, 10.5, 190.5, 120.25, "
                " 5.1, 'C', 'MEDIUM') RETURNING id",
                {"vid": vessel_id},
            )
        )
        await s.commit()
    return vessel_id, voyage_id, scenario_id


async def _arrival_of(voyage_id: UUID):
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        return (
            await s.execute(
                text("SELECT planned_arrival_at FROM voyage WHERE id = :id"), {"id": voyage_id}
            )
        ).scalar_one()


async def _cleanup(vessel_id: UUID) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        for sql in (
            "DELETE FROM voyage_scenario WHERE vessel_id = :v",
            "DELETE FROM calculation_run WHERE vessel_id = :v",
            "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
            "(SELECT id FROM voyage WHERE vessel_id = :v)",
            "DELETE FROM voyage WHERE vessel_id = :v",
            "DELETE FROM vessel WHERE id = :v",
        ):
            await s.execute(text(sql), {"v": vessel_id})
        await s.commit()


async def test_출항_예정이_없는_항차는_도착_예정을_지우지_않고_바꿨다고도_하지_않는다(
    migrated_db, app_fresh_engine
):
    vessel_id, voyage_id, scenario_id = await _seed(None)
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            response = client.post(
                f"/api/v1/scenarios/{scenario_id}/adopt",
                headers=_csrf(client),
                json={"target_voyage_id": str(voyage_id)},
            )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert "planned_arrival_at" not in data["updated_fields"]
        # 나머지 세 값은 실제로 바뀌었으므로 그대로 싣는다.
        assert data["updated_fields"] == [
            "planned_distance_nm",
            "planned_speed_kn",
            "planned_fuel_ton",
        ]
        arrival = await _arrival_of(voyage_id)
        assert arrival is not None
        assert arrival.replace(tzinfo=UTC) == _ARRIVAL
    finally:
        await _cleanup(vessel_id)


async def test_출항_예정이_있는_항차는_도착_예정을_바꾸고_그렇다고_보고한다(
    migrated_db, app_fresh_engine
):
    departure = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    vessel_id, voyage_id, scenario_id = await _seed(departure)
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            response = client.post(
                f"/api/v1/scenarios/{scenario_id}/adopt",
                headers=_csrf(client),
                json={"target_voyage_id": str(voyage_id)},
            )
        assert response.status_code == 200, response.text
        assert "planned_arrival_at" in response.json()["data"]["updated_fields"]
        arrival = await _arrival_of(voyage_id)
        assert arrival.replace(tzinfo=UTC) != _ARRIVAL
    finally:
        await _cleanup(vessel_id)


async def test_채택_요청의_항만명은_항차_생성과_같은_200자까지_받는다(
    migrated_db, app_fresh_engine
):
    vessel_id, voyage_id, scenario_id = await _seed(None)
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            ok = client.post(
                f"/api/v1/scenarios/{scenario_id}/adopt",
                headers=_csrf(client),
                json={
                    "target_voyage_id": str(voyage_id),
                    "departure_port_name": "P" * 150,
                    "arrival_port_name": "Q" * 200,
                },
            )
            assert ok.status_code == 200, ok.text
            over = client.post(
                f"/api/v1/scenarios/{scenario_id}/adopt",
                headers=_csrf(client),
                json={"target_voyage_id": str(voyage_id), "arrival_port_name": "Q" * 201},
            )
            assert over.status_code == 422, over.text
            assert over.json()["error"]["details"][0]["field"] == "arrival_port_name"
    finally:
        await _cleanup(vessel_id)


async def test_비교_요청의_기준_일일_연료는_저장_범위_밖이면_422다(migrated_db, app_fresh_engine):
    from cii_platform.db.demo_seed import VESSEL_ID_BULK

    body = {
        "vessel_id": VESSEL_ID_BULK,
        "regulation_year": 2026,
        "current_speed_kn": 12,
        "fuel_type": "HFO",
        "direct_distance_nm": 1000,
    }
    with TestClient(app, base_url=_BASE) as client:
        assert client.post("/api/v1/auth/dev-login").status_code == 200
        for bad in (1_000_000, 0.001):
            response = client.post(
                "/api/v1/scenarios/compare",
                headers=_csrf(client),
                json={**body, "base_daily_foc_ton": bad},
            )
            assert response.status_code == 422, f"{bad}: {response.text}"
            assert response.json()["error"]["details"][0]["field"] == "base_daily_foc_ton"
