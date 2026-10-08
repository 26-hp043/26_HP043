"""Fixture 3의 파일 기대값을 실제 연간 실행 응답과 대조한다 (#2144)."""

from __future__ import annotations

import json
import platform
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.annual_simulation import run_annual_simulation

_DIR = Path(__file__).parent / "fixtures" / "simulation"


def _read(name):
    return json.loads((_DIR / f"annual_seed_12345_{name}.json").read_text())


def _stable(response):
    """패치 버전·플랫폼은 실행 환경과 대조하고 나머지는 파일에 잠근다."""
    model = dict(response["model_version"])
    assert model.pop("python_version") == platform.python_version()
    mc = dict(response["data"]["monte_carlo"])
    rng = dict(mc["rng_metadata"])
    assert rng.pop("python_version") == platform.python_version()
    assert rng.pop("platform") == platform.platform()
    mc["rng_metadata"] = rng
    return {
        "input_hash": response["input_hash"],
        "parameter_hash": response["parameter_hash"],
        "parameters_used": response["parameters_used"],
        "model_version": model,
        "deterministic": response["data"]["deterministic"],
        "monte_carlo": mc,
    }


@pytest_asyncio.fixture
async def fixture3_session(conn):
    spec = _read("input")["input"]
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        await session.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                "gross_tonnage, default_fuel_type, reference_speed_kn, "
                "reference_daily_foc_ton) VALUES (:id, '9914301', 'FIXTURE 3', "
                ":ship_type, :deadweight, :gross_tonnage, 'HFO', "
                ":reference_speed_kn, :reference_daily_foc_ton)"
            ),
            {
                **{
                    key: spec[key]
                    for key in (
                        "ship_type",
                        "deadweight",
                        "gross_tonnage",
                        "reference_speed_kn",
                        "reference_daily_foc_ton",
                    )
                },
                "id": UUID(spec["vessel_id"]),
            },
        )
        for voyage in spec["voyages"]:
            actual = voyage["annual_inclusion_policy"] == "INCLUDE_AS_ACTUAL"
            await session.execute(
                text(
                    "INSERT INTO voyage (id, vessel_id, voyage_no, status, "
                    "departure_port_name, arrival_port_name, planned_distance_nm, "
                    "planned_speed_kn, actual_distance_nm, annual_inclusion_policy, "
                    "regulation_year, created_from, planned_departure_at, "
                    "planned_arrival_at, actual_departure_at, actual_arrival_at) "
                    "VALUES (:id, :vid, :no, :status, 'Busan', 'Singapore', :distance, "
                    "14, :actual, :policy, :year, 'MANUAL', :departure, :arrival, "
                    ":actual_departure, :actual_arrival)"
                ),
                {
                    "id": UUID(voyage["id"]),
                    "vid": UUID(spec["vessel_id"]),
                    "no": voyage["voyage_no"],
                    "status": voyage["status"],
                    "distance": Decimal(voyage["distance_nm"]),
                    "actual": Decimal(voyage["distance_nm"]) if actual else None,
                    "policy": voyage["annual_inclusion_policy"],
                    "year": spec["regulation_year"],
                    "departure": datetime.fromisoformat(voyage["departure_at"]),
                    "arrival": datetime.fromisoformat(voyage["arrival_at"]),
                    "actual_departure": datetime.fromisoformat(voyage["departure_at"])
                    if actual
                    else None,
                    "actual_arrival": datetime.fromisoformat(voyage["arrival_at"])
                    if actual
                    else None,
                },
            )
            for fuel in voyage["fuel_uses"]:
                await session.execute(
                    text(
                        "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, "
                        "planned_fuel_ton, actual_fuel_ton, cf_used, source) "
                        "VALUES (:id, :fuel, :ton, :actual, 3.114, 'USER_INPUT')"
                    ),
                    {
                        "id": UUID(voyage["id"]),
                        "fuel": fuel["fuel_type"],
                        "ton": Decimal(fuel["fuel_ton"]),
                        "actual": Decimal(fuel["fuel_ton"]) if actual else None,
                    },
                )
        yield session


async def _run(session, seed=None):
    spec = _read("input")["input"]
    return await run_annual_simulation(
        session,
        vessel_id=UUID(spec["vessel_id"]),
        regulation_year=spec["regulation_year"],
        target_rating=spec["target_rating"],
        simulation_runs=spec["simulation_runs"],
        random_seed=spec["random_seed"] if seed is None else seed,
        distribution_profile=spec["distribution_profile"],
        as_of=datetime.fromisoformat(spec["as_of"]),
        commit=False,
    )


@pytest.mark.asyncio
async def test_fixture3_matches_golden_file(fixture3_session):
    """실행마다 만들어지는 식별자 대신 계산값·입력·파라미터 계약을 잠근다."""
    first = _stable(await _run(fixture3_session))
    assert first == _read("expected")["expected"]
    assert _stable(await _run(fixture3_session)) == first


@pytest.mark.asyncio
async def test_fixture3_samples_remaining_voyage(fixture3_session):
    """확정 실적만 있어 seed가 무의미했던 종전 픽스처로 돌아가지 않는다."""
    first = (await _run(fixture3_session))["data"]["monte_carlo"]
    other = (await _run(fixture3_session, 99999))["data"]["monte_carlo"]
    assert Decimal(first["p10"]) < Decimal(first["p50"]) < Decimal(first["p90"])
    assert first["p50"] != other["p50"]
    assert first["mean_cii"] != other["mean_cii"]
    assert np.__version__ == _read("expected")["expected"]["model_version"]["numpy_version"]


def test_fixture3_golden_has_independent_numeric_oracle():
    """제품 sampler·등급 함수 없이 정수·NumPy 원시 연산으로 값을 검산한다."""
    expected = _read("expected")["expected"]
    spec = _read("input")["input"]
    params = expected["parameters_used"]
    actual, plan = spec["voyages"]
    capacity = int(spec["deadweight"])
    cf = Decimal(params["fuel_types"][0]["cf"])
    completed_g = int(Decimal(actual["fuel_uses"][0]["fuel_ton"]) * cf * 1_000_000)
    planned_g = int(Decimal(plan["fuel_uses"][0]["fuel_ton"]) * cf * 1_000_000)
    total_w = capacity * (int(actual["distance_nm"]) + int(plan["distance_nm"]))
    with localcontext() as ctx:
        ctx.prec = 50
        reference = params["reference_line"]
        required = (
            Decimal(reference["a_decimal"])
            * (-Decimal(reference["c"]) * Decimal(capacity).ln()).exp()
            * (1 - Decimal(params["regulation_year"]["z_factor_percent"]) / 100)
        )
        boundaries = [
            float(required * Decimal(params["rating_boundary"][f"d{i}"])) for i in range(1, 5)
        ]
        deterministic = Decimal(completed_g + planned_g) / Decimal(total_w)
    # API_SPEC §1.7 CII 전송은 소수 6자리 절사다.
    from decimal import ROUND_DOWN

    assert (
        str(deterministic.quantize(Decimal("0.000001"), rounding=ROUND_DOWN))
        == (expected["deterministic"]["projected_attained_cii"])
    )
    profiles = {row["variable"]: row for row in params["simulation_profile"]["parameters"]}
    rng = np.random.Generator(np.random.PCG64DXSM(spec["random_seed"]))
    samples = {}
    # 거리 다음 연료, (실행 수, 잔여 항차 수)의 순서도 계약의 일부다.
    for key, value in (
        ("DISTANCE", float(plan["distance_nm"])),
        ("FUEL", float(plan["fuel_uses"][0]["fuel_ton"])),
    ):
        band = profiles[key]
        samples[key] = rng.triangular(
            value * float(band["min"]),
            value * float(band["mode"]),
            value * float(band["max"]),
            size=(spec["simulation_runs"], 1),
        )[:, 0]
    cii = (completed_g + samples["FUEL"] * float(cf) * 1_000_000) / (
        capacity * (int(actual["distance_nm"]) + samples["DISTANCE"])
    )
    categories = np.searchsorted(boundaries, cii, side="left")
    counts = np.bincount(categories, minlength=5)

    def four(value):
        return str(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    mc = expected["monte_carlo"]
    assert {
        rating: four(int(count) / len(cii)) for rating, count in zip("ABCDE", counts, strict=True)
    } == mc["rating_probabilities"]
    target = "ABCDE".index(spec["target_rating"])
    assert four(int(counts[: target + 1].sum()) / len(cii)) == mc["target_success_probability"]
    for name, value in zip(("p10", "p50", "p90"), np.percentile(cii, [10, 50, 90]), strict=True):
        assert four(value) == mc[name]
    assert four(cii.mean()) == mc["mean_cii"]
