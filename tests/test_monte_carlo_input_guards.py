"""Monte Carlo 진입점의 입력 가드 (#2098).

``simulate_annual``이 ``project_deterministic``과 **같은 가드**를 지나는지 본다. 한쪽에만
있으면 같은 입력에 결정론은 거부하고 Monte Carlo는 음수·``inf`` 분포를 조용히 낸다.

DB 없이 돈다. 문구는 단언하지 않고 두 진입점의 예외가 **같은지**를 단언한다.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from cii_platform.calc import annual_simulation as engine
from cii_platform.calc.annual_simulation import (
    CompletedTotals,
    RemainingVoyage,
    TriangularBand,
    _sample_band,
    project_deterministic,
    simulate_annual,
)
from cii_platform.calc.rating_engine import DVector
from cii_platform.calc.rng import create_rng

D_VECTOR = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))
COMPLETED = CompletedTotals(co2_g=1.0e9, distance_nm=1000.0)
REMAINING = [RemainingVoyage(distance_nm=500.0, fuel_ton=20.0, cf=3.114)]


def _kwargs(capacity: str = "50000", required: str = "5.0") -> dict:
    return {
        "completed": COMPLETED,
        "remaining": REMAINING,
        "transport_capacity": Decimal(capacity),
        "required_cii": Decimal(required),
        "d_vector": D_VECTOR,
    }


def _mc(**kwargs):
    return simulate_annual(**kwargs, target_rating="C", seed=7, runs=1000)


@pytest.mark.parametrize(
    ("capacity", "required"),
    [("0", "5.0"), ("-50000", "5.0"), ("50000", "0"), ("50000", "-1")],
)
def test_same_exception_as_deterministic(capacity, required):
    """같은 입력에 두 진입점이 같은 예외 타입·같은 문구를 낸다."""
    kwargs = _kwargs(capacity, required)
    with pytest.raises(ValueError) as deterministic:
        project_deterministic(**kwargs)
    with pytest.raises(ValueError) as monte_carlo:
        _mc(**kwargs)
    assert type(monte_carlo.value) is type(deterministic.value)
    assert str(monte_carlo.value) == str(deterministic.value)


def test_guard_is_one_shared_function(monkeypatch):
    """가드를 복제하지 않는다 — 두 진입점이 같은 함수를 부른다."""
    calls: list[str] = []
    real = engine._reject_non_positive_capacity_or_required

    def spy(*args):
        calls.append("guard")
        return real(*args)

    monkeypatch.setattr(engine, "_reject_non_positive_capacity_or_required", spy)
    project_deterministic(**_kwargs())
    _mc(**_kwargs())
    assert calls == ["guard", "guard"]


def test_guard_runs_before_any_random_draw(monkeypatch):
    """가드는 난수를 뽑기 전에 돈다 — RNG를 만들기 전에 이미 예외다."""

    def forbidden(seed):  # pragma: no cover - 호출되면 실패
        raise AssertionError("가드보다 먼저 RNG가 만들어졌다")

    monkeypatch.setattr(engine, "create_rng", forbidden)
    with pytest.raises(ValueError, match="transport_capacity"):
        _mc(**_kwargs(capacity="-50000"))


def test_valid_input_result_unchanged_and_reproducible():
    """정상 입력은 같은 seed → 같은 값이다."""
    first = _mc(**_kwargs())
    second = _mc(**_kwargs())
    assert first.rating_probabilities == second.rating_probabilities
    assert (first.p10, first.p50, first.p90, first.mean) == (
        second.p10,
        second.p50,
        second.p90,
        second.mean,
    )


def test_negative_min_factor_never_samples_negative():
    """음수 하한(`min_factor`)이어도 표본에 음수 거리·연료가 없다 (`TECH_SPEC §2.3.1`)."""
    band = TriangularBand(min_factor=-0.5, max_factor=1.15)
    plan = np.array([20.0, 500.0])
    sampled = _sample_band(create_rng(1), band, plan, (5000, 2))
    assert sampled.min() >= 0.0
    left, _, _ = band.bounds(20.0)
    assert left >= 0.0


def test_normal_band_samples_unchanged_by_floor():
    """하한이 양수인 정상 분포는 클램프가 값을 바꾸지 않는다 — 같은 seed에 같은 표본."""
    band = TriangularBand(min_factor=0.90, max_factor=1.15)
    plan = np.array([20.0, 500.0])
    mode = plan
    expected = create_rng(3).triangular(plan * 0.90, mode, plan * 1.15, size=(100, 2))
    got = _sample_band(create_rng(3), band, plan, (100, 2))
    assert np.array_equal(got, expected)
