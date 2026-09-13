"""함대 감축 계획 서비스 DB 실동작 검증 (`API_SPEC §2.17` · `PRD §12.3.2` · #513).

수식은 ``tests/test_fleet_reduction.py``가 본다. 여기는 ⑴ **연간 등급 관리와 같은 입력으로
조정 전 값을 내는가** ⑵ 저장본이 **저장 시점의 결과 그대로** 남는가 ⑶ HTTP 경로를 본다.

선대 전체를 도는 서비스라 시드된 데모 선박도 섞인다 — 이 파일이 넣은 선박으로 걸러 단언한다.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, ValidationError
from cii_platform.services.annual_simulation import run_annual_simulation
from cii_platform.services.fleet_reduction import (
    evaluate_reduction_plan,
    get_reduction_plan,
    list_reduction_plans,
    save_reduction_plan,
)

YEAR = 2026


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> UUID:
    """확정 1건 + 계획 2건(각 2,880nm · 12kn · HFO 100t). 기준 속력 12kn · 일일 24t."""
    await session.execute(
        text(
            "INSERT INTO regulation_year "
            "(year, z_factor_percent, effective_from, source_ref, version) "
            "SELECT 2026, 11.0, '2026-01-01', 'TEST', '1.0' "
            "WHERE NOT EXISTS (SELECT 1 FROM regulation_year WHERE year = 2026)"
        )
    )
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, gross_tonnage, deadweight, "
            " default_fuel_type, reference_speed_kn, reference_daily_foc_ton) "
            "VALUES (:id, :imo, 'FR TEST', 'BULK_CARRIER', 30000, 50000, 'HFO', 12, 24)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    await _voyage(session, new_id, no="A", actual=True)
    await _voyage(session, new_id, no="B", actual=False)
    await _voyage(session, new_id, no="C", actual=False)
    return new_id


async def _voyage(session, vessel_id: UUID, *, no: str, actual: bool) -> UUID:
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, voyage_no, status, departure_port_name, "
            " arrival_port_name, planned_distance_nm, planned_speed_kn, actual_distance_nm, "
            " annual_inclusion_policy, regulation_year, created_from) "
            "VALUES (:id, :vid, :no, :status, 'Busan', 'Singapore', 2880, 12, :actual, "
            " :policy, 2026, 'MANUAL')"
        ),
        {
            "id": voyage_id,
            "vid": vessel_id,
            "no": no,
            "status": "CONFIRMED" if actual else "PLANNED",
            "policy": "INCLUDE_AS_ACTUAL" if actual else "INCLUDE_AS_PLAN",
            "actual": Decimal(2880) if actual else None,
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            " actual_fuel_ton, cf_used, source) VALUES (:id, 'HFO', 100, :actual, 3.114, "
            " 'USER_INPUT')"
        ),
        {"id": voyage_id, "actual": Decimal(100) if actual else None},
    )
    return voyage_id


def _mine(result: dict, vessel_id: UUID) -> dict:
    return next(row for row in result["vessels"] if row["vessel_id"] == str(vessel_id))


async def _evaluate(session, vessel_id: UUID, percent: str = "10", prices=None) -> dict:
    return await evaluate_reduction_plan(
        session,
        regulation_year=YEAR,
        target="ALL_C_OR_BETTER",
        adjustments=[{"vessel_id": str(vessel_id), "speed_reduction_percent": percent}],
        prices=prices or {},
    )


@pytest.mark.asyncio
async def test_zero_reduction_leaves_every_vessel_as_it_was(session, vessel_id):
    """⚠️ `#513` 완료 기준 — **감속률 0%일 때 전 선박 등급이 그대로다.** 데모 선박까지 전부 본다."""
    result = await _evaluate(session, vessel_id, "0")

    for row in result["vessels"]:
        if row["unavailable_reason"] is None:
            assert row["after"] == row["before"], row["vessel_name"]
    assert result["rating_distribution"]["before"] == result["rating_distribution"]["after"]


@pytest.mark.asyncio
async def test_before_matches_the_annual_grade_screen(session, vessel_id):
    """⚠️ **조정 전 값 = 연간 등급 관리의 결정론 연말 예상.**

    두 화면이 갈리면 어느 쪽이 맞는지부터 따진다.
    """
    annual = await run_annual_simulation(
        session,
        vessel_id=vessel_id,
        regulation_year=YEAR,
        target_rating="C",
        simulation_runs=1000,
        random_seed=12345,
    )
    result = await _evaluate(session, vessel_id, "0")

    before = _mine(result, vessel_id)["before"]
    deterministic = annual["data"]["deterministic"]
    assert Decimal(before["attained_cii"]) == pytest.approx(
        Decimal(deterministic["projected_attained_cii"]), abs=Decimal("1e-4")
    )
    assert before["rating"] == deterministic["projected_rating"]


@pytest.mark.asyncio
async def test_slowing_down_lowers_the_cii_and_adds_days(session, vessel_id):
    """10% 감속: 계획 2건 × (100t → 81t) · 추가 항해일 2 × 1.1111일 = 2.22일."""
    row = _mine(await _evaluate(session, vessel_id, "10"), vessel_id)

    assert Decimal(row["after"]["attained_cii"]) < Decimal(row["before"]["attained_cii"])
    assert row["extra_days"] == "2.22"
    assert row["fuel_saved_ton"] == "38.00"
    assert row["skipped_voyages"] == 0


@pytest.mark.asyncio
async def test_costs_use_the_prices_given_and_leave_missing_ones_empty(session, vessel_id):
    """⚠️ 선박 단가가 없으면 용선료·순손익은 **빈칸**, 연료비는 단가가 있으니 계산된다."""
    result = await _evaluate(session, vessel_id, "10", prices={"fuel_usd_per_ton": {"HFO": "600"}})

    costs = result["costs"]
    assert costs["charter_loss"] is None
    assert costs["net"] is None
    assert costs["fuel_saving"] == "22800.00"  # 38t × 600
    assert str(vessel_id) in costs["missing_charter_rates"]

    priced = await _evaluate(
        session,
        vessel_id,
        "10",
        prices={
            "charter_usd_per_day": {str(vessel_id): "10000"},
            "fuel_usd_per_ton": {"HFO": "600"},
        },
    )
    # 2.2222일 × 10,000 = 22,222.22 · 순손익 = 22,800 − 22,222.22
    assert priced["costs"]["charter_loss"] == "22222.22"
    assert priced["costs"]["net"] == "577.78"


@pytest.mark.asyncio
async def test_an_unknown_vessel_is_rejected(session, vessel_id):
    with pytest.raises(ValidationError):
        await evaluate_reduction_plan(
            session,
            regulation_year=YEAR,
            target="ALL_C_OR_BETTER",
            adjustments=[{"vessel_id": str(uuid4()), "speed_reduction_percent": "10"}],
            prices={},
        )


@pytest.mark.asyncio
async def test_a_saved_plan_keeps_the_result_of_the_moment(session, vessel_id):
    """⚠️ 저장본은 **저장 시점의 결과 그대로**다 — 항차가 바뀐 뒤 다시 계산해 채우지 않는다."""
    saved = await save_reduction_plan(
        session,
        plan_name="9월 감속안",
        regulation_year=YEAR,
        target="ALL_C_OR_BETTER",
        adjustments=[{"vessel_id": str(vessel_id), "speed_reduction_percent": "10"}],
        prices={"fuel_usd_per_ton": {"HFO": "600"}},
        user_id=None,
    )
    kept = _mine(saved["result"], vessel_id)["after"]

    # 계획 항차를 하나 더 넣어 지금 계산하면 값이 달라지는 상태로 만든다.
    await _voyage(session, vessel_id, no="D", actual=False)
    now = _mine(await _evaluate(session, vessel_id, "10"), vessel_id)["after"]
    assert now != kept

    fetched = await get_reduction_plan(session, UUID(saved["plan_id"]))
    assert _mine(fetched["result"], vessel_id)["after"] == kept
    assert fetched["prices"] == {"fuel_usd_per_ton": {"HFO": "600"}}

    listing = await list_reduction_plans(session)
    assert listing[0]["plan_id"] == saved["plan_id"]
    assert "result" not in listing[0]


@pytest.mark.asyncio
async def test_an_unknown_plan_is_not_found(session):
    with pytest.raises(NotFoundError):
        await get_reduction_plan(session, uuid4())


def test_the_routes_answer_over_http(migrated_db, app_fresh_engine):
    """⚠️ 실제 HTTP — 봉투 · 422(감속률 상한 · 모르는 목표) · 저장 201 · 목록 · 단건 · 404."""
    from fastapi.testclient import TestClient

    from cii_platform.api.main import API_V1_PREFIX, app

    with TestClient(app, base_url="https://testserver") as client:
        client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        headers = {"X-CSRF-Token": client.cookies.get("csrf")}
        base = f"{API_V1_PREFIX}/fleet/reduction-plans"
        body = {"regulation_year": YEAR, "target": "ALL_C_OR_BETTER"}

        evaluated = client.post(f"{base}/evaluate", headers=headers, json=body)
        assert evaluated.status_code == 200, evaluated.text
        assert set(evaluated.json()) == {"data", "meta"}
        assert set(evaluated.json()["data"]) == {
            "regulation_year",
            "target",
            "target_met",
            "vessels",
            "rating_distribution",
            "costs",
            "warnings",
        }

        too_much = {
            **body,
            "adjustments": [
                {"vessel_id": "00000000-0000-4000-8000-000000000001", "speed_reduction_percent": 51}
            ],
        }
        assert client.post(f"{base}/evaluate", headers=headers, json=too_much).status_code == 422
        bad_target = {**body, "target": "ALL_A"}
        assert client.post(f"{base}/evaluate", headers=headers, json=bad_target).status_code == 422

        created = client.post(base, headers=headers, json={**body, "plan_name": "HTTP 검사안"})
        assert created.status_code == 201, created.text
        plan_id = created.json()["data"]["plan_id"]

        assert any(p["plan_id"] == plan_id for p in client.get(base).json()["data"])
        assert client.get(f"{base}/{plan_id}").json()["data"]["plan_name"] == "HTTP 검사안"
        assert client.get(f"{base}/{uuid4()}").status_code == 404
