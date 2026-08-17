"""연간 시뮬레이션 실행 서비스 검증 (API_SPEC §6.1, #64).

계산은 ``#63``이 하고 그 테스트가 따로 있다. 여기서 보는 것은 **조립과 격리**다.

* **스냅샷 격리** — 실행 뒤 원본이 바뀌어도 스냅샷은 그대로여야 한다
  (``TECH_SPEC §11``). 이게 깨지면 재현성 계약이 성립하지 않는다.
* **`annual_inclusion_policy` 필터링** — ``status``로 다시 판정하지 않는다.
* **`parameters_used`에 분포가 실리는가** (``§5.2.1.1`` · `#434`) — 빠지면 분포가
  바뀐 뒤 같은 seed로 돌려도 결과가 달라지는데 해시는 같아진다.
* **재현성** — 같은 seed면 같은 결과.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import ValidationError
from cii_platform.services.annual_simulation import run_annual_simulation

YEAR = 2026
AS_OF = datetime(YEAR, 7, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    await session.execute(
        text(
            "INSERT INTO regulation_year "
            "(year, z_factor_percent, effective_from, source_ref, version) "
            "SELECT 2026, 11.0, '2026-01-01', 'TEST', '1.0' "
            "WHERE NOT EXISTS (SELECT 1 FROM regulation_year WHERE year = 2026)"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_reference_line "
            "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', '4745', 4745, 0.622, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_reference_line WHERE ship_type = 'BULK_CARRIER')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_rating_boundary "
            "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', 0.86, 0.94, 1.06, 1.18, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_rating_boundary WHERE ship_type = 'BULK_CARRIER')"
        )
    )


@pytest_asyncio.fixture
async def vessel_id(session):
    await _seed_parameters(session)
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton) "
            "VALUES (:id, :imo, 'SIM TEST', 'BULK_CARRIER', 50000, 'HFO', 14, 30)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


async def _add_voyage(session, vessel_id, *, policy: str, status: str, fuel: str = "250"):
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_distance_nm, annual_inclusion_policy, regulation_year, created_from) "
            "VALUES (:id, :vid, :status, 'Busan', 'Singapore', 3000, 14, "
            ":actual, :policy, 2026, 'MANUAL')"
        ),
        {
            "id": voyage_id,
            "vid": vessel_id,
            "status": status,
            "policy": policy,
            "actual": Decimal("3000") if policy == "INCLUDE_AS_ACTUAL" else None,
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "actual_fuel_ton, cf_used, source) VALUES (:id, 'HFO', :fuel, :actual, "
            "3.114, 'USER_INPUT')"
        ),
        {
            "id": voyage_id,
            "fuel": Decimal(fuel),
            "actual": Decimal(fuel) if policy == "INCLUDE_AS_ACTUAL" else None,
        },
    )
    return voyage_id


async def _run(session, vessel_id, **over):
    kwargs = {
        "vessel_id": vessel_id,
        "regulation_year": YEAR,
        "target_rating": "C",
        "simulation_runs": 1000,
        "random_seed": 12345,
        "as_of": AS_OF,
    }
    kwargs.update(over)
    return await run_annual_simulation(session, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 조립
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_response_carries_the_four_blocks(session, vessel_id):
    """`API_SPEC §6.1` — 결정론 · Monte Carlo · 민감도 · 스냅샷."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED")

    result = await _run(session, vessel_id)

    for key in ("deterministic", "monte_carlo", "sensitivity_analysis", "snapshot"):
        assert key in result, key
    assert result["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@pytest.mark.asyncio
async def test_policy_decides_actual_versus_plan(session, vessel_id):
    """**`status`로 다시 판정하지 않는다** — 정본은 `annual_inclusion_policy`다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED")
    # EXCLUDE는 어느 쪽에도 들어가지 않는다.
    await _add_voyage(session, vessel_id, policy="EXCLUDE", status="DRAFT")

    result = await _run(session, vessel_id)

    assert result["deterministic"]["completed_voyage_count"] == 1
    assert result["deterministic"]["remaining_voyage_count"] == 1


@pytest.mark.asyncio
async def test_risk_comes_from_probability_not_margin(session, vessel_id):
    """`PRD §9.4.2` — 기능③ 위험도는 **목표 달성 확률** 기반이다.

    기능①·②의 마진 기반 함수를 쓰면 등급마다 `margin_ratio`를 요구해 500이 난다.
    """
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id)

    probability = Decimal(result["monte_carlo"]["target_success_probability"])
    expected = "LOW" if probability >= Decimal("0.8") else result["risk_level"]
    assert result["risk_level"] == expected


# ─────────────────────────────────────────────────────────────────────────────
# 스냅샷 격리 — TECH_SPEC §11
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_records_the_voyages_used(session, vessel_id):
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED")

    result = await _run(session, vessel_id)
    assert result["snapshot"]["voyage_count"] == 2

    stored = await session.scalar(
        text("SELECT jsonb_array_length(voyages_json) FROM simulation_snapshot WHERE id = :id"),
        {"id": result["snapshot"]["snapshot_id"]},
    )
    assert stored == 2


@pytest.mark.asyncio
async def test_snapshot_survives_later_edits(session, vessel_id):
    """**격리의 본체**다 — 원본이 바뀌어도 스냅샷은 그대로여야 한다.

    깨지면 「그때 무슨 데이터로 돌렸나」에 답할 수 없고, 재현성 계약이 성립하지 않는다.
    """
    voyage_id = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED"
    )
    result = await _run(session, vessel_id)

    await session.execute(
        text("UPDATE voyage SET actual_distance_nm = 99999 WHERE id = :id"),
        {"id": voyage_id},
    )

    stored = await session.scalar(
        text(
            "SELECT voyages_json->0->>'actual_distance_nm' FROM simulation_snapshot WHERE id = :id"
        ),
        {"id": result["snapshot"]["snapshot_id"]},
    )
    assert stored is not None and "99999" not in stored


@pytest.mark.asyncio
async def test_snapshot_keeps_the_cf_used(session, vessel_id):
    """CF가 개정되면 원본으로는 재현할 수 없다 — 스냅샷에 함께 남긴다(#378)."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id)

    stored = await session.scalar(
        text(
            "SELECT voyages_json->0->'fuel_uses'->0->>'cf_used' FROM simulation_snapshot "
            "WHERE id = :id"
        ),
        {"id": result["snapshot"]["snapshot_id"]},
    )
    assert stored == "3.114000"


# ─────────────────────────────────────────────────────────────────────────────
# 재현성 — #434 · TECH_SPEC §5.2.1.1
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parameters_used_carries_the_distribution_profile(session, vessel_id):
    """**빠지면 분포가 바뀐 뒤 결과는 달라지는데 해시는 같아진다.**"""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id)

    profile = await session.scalar(
        text("SELECT parameters_used->'simulation_profile' FROM calculation_run WHERE id = :id"),
        {"id": result["calculation_run_id"]},
    )
    assert profile["profile"] == "DEFAULT"
    # 거리·연료·속도 3행이 그대로 실린다.
    assert len(profile["parameters"]) == 3


@pytest.mark.asyncio
async def test_same_seed_reproduces_the_same_result(session, vessel_id):
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED")

    first = await _run(session, vessel_id, random_seed=777)
    second = await _run(session, vessel_id, random_seed=777)

    assert (
        first["monte_carlo"]["rating_probabilities"]
        == second["monte_carlo"]["rating_probabilities"]
    )
    assert first["monte_carlo"]["p50"] == second["monte_carlo"]["p50"]


@pytest.mark.asyncio
async def test_server_generates_a_seed_when_omitted(session, vessel_id):
    """`PRD §12.4.3` 자동 seed — 결과에 실어 「이 seed로 다시 실행」이 가능해야 한다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id, random_seed=None)

    assert result["monte_carlo"]["rng_metadata"]["seed"] > 0


@pytest.mark.asyncio
async def test_calculation_run_is_recorded_with_the_right_type(session, vessel_id):
    """`chk_calculation_type`의 4값 중 하나여야 한다 — 임의 이름은 500이 된다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id)

    kind = await session.scalar(
        text("SELECT calculation_type FROM calculation_run WHERE id = :id"),
        {"id": result["calculation_run_id"]},
    )
    assert kind == "ANNUAL_MONTE_CARLO"


# ─────────────────────────────────────────────────────────────────────────────
# 예외 — PRD §12.8
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_target_rating_e_is_refused(session, vessel_id):
    with pytest.raises(ValidationError, match="목표 등급 E"):
        await _run(session, vessel_id, target_rating="E")


@pytest.mark.asyncio
async def test_unknown_target_rating_is_refused(session, vessel_id):
    with pytest.raises(ValidationError):
        await _run(session, vessel_id, target_rating="Z")


@pytest.mark.asyncio
async def test_sensitivity_always_carries_the_interaction_note(session, vessel_id):
    """`PRD §12.8` — one-at-a-time이라 복합 효과는 포함되지 않는다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED")

    result = await _run(session, vessel_id)
    assert "복합 효과" in result["sensitivity_analysis"]["interaction_note"]


@pytest.mark.asyncio
async def test_no_remaining_plan_is_reported(session, vessel_id):
    """`AC-F3-004` — 확정 실적만으로 산출하되 그 사실을 알린다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id)
    assert "NO_REMAINING_VOYAGES" in result["warnings"]
