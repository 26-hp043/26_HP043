"""연간 실행 저장→입력 변경→실제 목록 HTTP와 immutable 결과 검증 (#2304)."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from test_annual_simulation_read_db import _add_voyage
from test_annual_simulation_read_db import session as session
from test_annual_simulation_read_db import vessel_id as vessel_id
from test_scenario_adopt_db import _new_scenario

from cii_platform.api.routes.annual_simulations import router
from cii_platform.db.repositories.calculation_run import mark_annual_needs_recalc
from cii_platform.db.session import get_session
from cii_platform.errors import ValidationError
from cii_platform.services import not_underway as nu
from cii_platform.services import public_record_fill as fill_svc
from cii_platform.services import voyage as voyage_svc
from cii_platform.services.annual_simulation import get_annual_simulation, run_annual_simulation
from cii_platform.services.not_underway_import import import_not_underway_periods
from cii_platform.services.scenario_adopt import adopt_scenario
from cii_platform.services.voyage_import import import_voyages

START = datetime(2026, 1, 2, tzinfo=UTC)
END = datetime(2026, 1, 3, tzinfo=UTC)


async def _period(session, vessel_id):
    return await nu.create_period(
        session,
        vessel_id,
        period_type="DRIFTING",
        started_at=START,
        ended_at=END,
        port_name=None,
        lat=None,
        lon=None,
        distance_nm=Decimal("10"),
        regulation_year=2026,
        voyage_id=None,
        fuel_uses=[{"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": Decimal("2")}],
    )


async def _create_voyage(session, vessel_id):
    return await voyage_svc.create_voyage(
        session,
        vessel_id=vessel_id,
        voyage_no="NEW-2304",
        departure_port_name="A",
        arrival_port_name="B",
        planned_distance_nm=Decimal("100"),
        planned_speed_kn=Decimal("10"),
        regulation_year=2026,
        departure_lat=None,
        departure_lon=None,
        arrival_lat=None,
        arrival_lon=None,
        planned_departure_at=None,
        planned_arrival_at=None,
        notes=None,
        fuel_uses=[{"fuel_type": "HFO", "planned_fuel_ton": Decimal("5"), "source": "USER_INPUT"}],
    )


async def _latest_http(session, vessel_id):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/annual-simulations", params={"vessel_id": str(vessel_id)}
        )
    assert response.status_code == 200
    return response.json()["data"][0]


@pytest.mark.parametrize(
    "action",
    [
        "create",
        "plan",
        "plan_time",
        "transition",
        "actual_distance",
        "actual_fuel",
        "soft_delete",
        "hard_delete",
        "scenario",
        "period_create",
        "period_time",
        "period_distance",
        "period_delete",
        "fuel_add",
        "fuel_delete",
        "csv_voyage",
        "csv_period",
        "public_record",
    ],
)
async def test_saved_run_becomes_stale_on_input_changes(session, vessel_id, action, monkeypatch):
    planned = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="PLAN-2304"
    )
    actual = await _add_voyage(
        session,
        vessel_id,
        policy="INCLUDE_AS_ACTUAL",
        status="COMPLETED"
        if action.startswith("actual_") or action == "public_record"
        else "CONFIRMED",
        no="ACTUAL-2304",
    )
    period = (
        await _period(session, vessel_id)
        if action.startswith("period_") or action.startswith("fuel_")
        else None
    )
    draft = await _create_voyage(session, vessel_id) if action == "hard_delete" else None
    saved = await run_annual_simulation(
        session,
        vessel_id=vessel_id,
        regulation_year=2026,
        target_rating="C",
        simulation_runs=1000,
        random_seed=2304,
    )
    simulation_id = UUID(saved["data"]["simulation_id"])
    assert (await _latest_http(session, vessel_id))["needs_recalc"] is False
    before = await get_annual_simulation(session, simulation_id)
    if action == "create":
        await _create_voyage(session, vessel_id)
    elif action == "plan":
        await voyage_svc.update_voyage(session, planned, planned_distance_nm=Decimal("3001"))
    elif action == "plan_time":
        await voyage_svc.update_voyage(session, planned, planned_arrival_at=END)
    elif action == "transition":
        await voyage_svc.transition_voyage(session, planned, "IN_PROGRESS")
    elif action == "actual_distance":
        await voyage_svc.set_actuals(session, actual, actual_distance_nm=Decimal("3101"))
    elif action == "actual_fuel":
        await voyage_svc.set_actuals(
            session, actual, fuel_uses=[{"fuel_type": "HFO", "actual_fuel_ton": Decimal("261")}]
        )
    elif action == "soft_delete":
        await voyage_svc.delete_voyage(session, actual)
    elif action == "hard_delete":
        await voyage_svc.delete_voyage(session, UUID(draft["id"]))
    elif action == "scenario":
        scenario_id = await _new_scenario(session, vessel_id)
        result = await adopt_scenario(session, scenario_id, target_voyage_id=planned)
        assert result["invalidated_calculation_runs"] == 0
    elif action == "period_create":
        await nu.create_period(
            session,
            vessel_id,
            period_type="DRIFTING",
            started_at=datetime(2026, 2, 1, tzinfo=UTC),
            ended_at=None,
            port_name=None,
            lat=None,
            lon=None,
            distance_nm=Decimal("0"),
            regulation_year=2026,
            voyage_id=None,
            fuel_uses=[],
        )
    elif action == "period_time":
        await nu.update_period(
            session, UUID(period["id"]), ended_at=datetime(2026, 1, 4, tzinfo=UTC)
        )
    elif action == "period_distance":
        await nu.update_period(session, UUID(period["id"]), distance_nm=Decimal("11"))
    elif action == "period_delete":
        await nu.delete_period(session, UUID(period["id"]))
    elif action == "fuel_add":
        await nu.add_fuel_use(
            session,
            UUID(period["id"]),
            consumer_type="OTHER",
            fuel_type="HFO",
            fuel_ton=Decimal("1"),
        )
    elif action == "fuel_delete":
        await nu.delete_fuel_use(session, UUID(period["id"]), UUID(period["fuel_uses"][0]["id"]))
    elif action == "csv_voyage":
        content = (
            b"voyage_no,departure_port_name,arrival_port_name,planned_distance_nm,"
            b"planned_speed_kn,fuel_type,planned_fuel_ton\nCSV-2304,A,B,100,10,HFO,5\n"
        )
        result = await import_voyages(session, vessel_id, content=content)
        assert result["imported_count"] == 1 and result["errors"] == []
    elif action == "csv_period":
        content = (
            b"period_type,started_at,ended_at,distance_nm,fuel_type,fuel_ton,consumer_type\n"
            b"IN_PORT,2026-03-01T00:00:00Z,2026-03-02T00:00:00Z,0,HFO,1,AUX_ENGINE\n"
        )
        result = await import_not_underway_periods(session, vessel_id, content=content)
        assert result["imported_count"] == 1 and result["errors"] == []
    elif action == "public_record":
        # 외부 기록 조회만 대역이다. 원본 항차·연간 실행·낡음 표시와 조회는 실제 DB다.
        async def record(_session, **_fields):
            return SimpleNamespace(
                source="MOF_PORT_MIS",
                port_authority_code="001",
                call_year=2026,
                call_seq="2304",
                fetched_at=END,
            ), END

        monkeypatch.setattr(fill_svc, "_require_record", record)
        await fill_svc.fill_from_public_record(
            session,
            actual,
            field="ARRIVAL",
            record_key={},
            recorded_at=END,
        )
        await session.commit()
    latest = await _latest_http(session, vessel_id)
    assert latest["simulation_id"] == str(simulation_id)
    assert latest["needs_recalc"] is True
    assert await get_annual_simulation(session, simulation_id) == before


@pytest.mark.parametrize(
    "action",
    [
        "same_plan",
        "same_actual",
        "same_fuel",
        "same_period",
        "same_scenario",
        "metadata",
        "rejected",
    ],
)
async def test_no_change_or_rejected_request_keeps_run_current(session, vessel_id, action):
    planned = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="PLAN-2304"
    )
    actual = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="COMPLETED", no="ACTUAL-2304"
    )
    period = await _period(session, vessel_id)
    saved = await run_annual_simulation(
        session,
        vessel_id=vessel_id,
        regulation_year=2026,
        target_rating="C",
        simulation_runs=1000,
        random_seed=2304,
    )
    if action == "same_plan":
        await voyage_svc.update_voyage(session, planned, planned_distance_nm=Decimal("3000"))
    elif action == "same_actual":
        await voyage_svc.set_actuals(session, actual, actual_distance_nm=Decimal("3100"))
    elif action == "same_fuel":
        await voyage_svc.set_actuals(
            session,
            actual,
            fuel_uses=[
                {
                    "fuel_type": "HFO",
                    "actual_fuel_ton": Decimal("260"),
                    "source": "USER_INPUT",
                }
            ],
        )
    elif action == "same_period":
        await nu.update_period(session, UUID(period["id"]), ended_at=END)
    elif action == "same_scenario":
        scenario_id = await _new_scenario(session, vessel_id, distance="3000", fuel="250")
        await session.execute(
            text("UPDATE voyage_scenario SET speed_kn=14 WHERE id=:id"), {"id": scenario_id}
        )
        await adopt_scenario(session, scenario_id, target_voyage_id=planned)
    elif action == "metadata":
        await voyage_svc.update_voyage(session, planned, notes="계산 입력이 아닌 메모")
        await nu.update_period(session, UUID(period["id"]), port_name="계산 입력이 아닌 항구명")
        await voyage_svc.set_actuals(session, actual, actual_arrival_source="USER_INPUT")
    else:
        with pytest.raises(ValidationError):
            await voyage_svc.update_voyage(session, planned, regulation_year=None)
    assert (await _latest_http(session, vessel_id))["needs_recalc"] is False
    assert await get_annual_simulation(session, UUID(saved["data"]["simulation_id"])) == saved


async def test_marker_preserves_other_vessels_types_and_is_monotone(session, vessel_id):
    other_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight) "
            "VALUES (:id, :imo, 'OTHER STALE TEST', 'BULK_CARRIER', 50000)"
        ),
        {"id": other_id, "imo": f"9{other_id.int % 1000000:06d}"},
    )
    expected = {}
    for owner, kind in [
        (vessel_id, "ANNUAL_MONTE_CARLO"),
        (vessel_id, "ANNUAL_MONTE_CARLO"),
        (vessel_id, "VOYAGE_ESTIMATE"),
        (vessel_id, "SCENARIO"),
        (vessel_id, "ANNUAL_DETERMINISTIC"),
        (other_id, "ANNUAL_MONTE_CARLO"),
    ]:
        run_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO calculation_run (id, calculation_type, vessel_id, input_hash, "
                "parameter_hash, model_version, result_json, parameters_used) "
                "VALUES (:id, :kind, :v, :hash, :hash, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"id": run_id, "kind": kind, "v": owner, "hash": "sha256:" + "a" * 64},
        )
        expected[run_id] = int(owner == vessel_id and kind == "ANNUAL_MONTE_CARLO")
    assert await mark_annual_needs_recalc(session, vessel_id) == 2
    assert await mark_annual_needs_recalc(session, vessel_id) == 0
    rows = (
        await session.execute(
            text(
                "SELECT id, needs_recalc, result_json FROM calculation_run "
                "WHERE vessel_id IN (:v, :other)"
            ),
            {"v": vessel_id, "other": other_id},
        )
    ).all()
    assert {UUID(str(row.id)): row.needs_recalc for row in rows} == expected
    assert all(row.result_json in ("{}", {}) for row in rows)
