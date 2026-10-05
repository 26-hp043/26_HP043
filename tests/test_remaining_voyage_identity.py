"""``RemainingVoyage`` 재생성 6곳의 ``voyage_id`` 보존과 ``MIN_SPEED_KN`` 단일 정의 (#2098).

DB 없이 돈다. 재생성이 필드를 하나씩 옮겨 적으면 필드가 늘 때마다 빠진다 — ``voyage_id``가
그렇게 빠졌다(`#1671`).
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from cii_platform.calc import annual_simulation as engine
from cii_platform.calc import fuel_estimator
from cii_platform.calc.annual_simulation import (
    CompletedTotals,
    DistributionProfile,
    RemainingVoyage,
    TriangularBand,
    _shift_distance,
    _shift_fuel,
    _shift_speed,
    apply_feedback,
    fuel_cf_alternative_projection,
    simulate_annual,
)
from cii_platform.calc.fleet_reduction import PlannedLeg, apply_slowdown
from cii_platform.calc.rating_engine import DVector
from cii_platform.services import scenario_compare

D_VECTOR = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))
COMPLETED = CompletedTotals(co2_g=1.0e9, distance_nm=1000.0)


def _voyage(speed: float = 12.0) -> RemainingVoyage:
    return RemainingVoyage(
        distance_nm=500.0,
        fuel_ton=20.0,
        cf=3.114,
        speed_kn=speed,
        reference_speed_kn=14.0,
        base_daily_foc_ton=30.0,
        voyage_id="v-1",
    )


def _leg(speed: str) -> PlannedLeg:
    return PlannedLeg(
        distance_nm=Decimal("500"),
        speed_kn=Decimal(speed),
        fuel_ton_by_type={"HFO": Decimal("20")},
    )


def test_feedback_keeps_voyage_id():
    assert apply_feedback([_voyage()], Decimal("1.1"))[0].voyage_id == "v-1"


def test_shift_fuel_keeps_voyage_id():
    assert _shift_fuel([_voyage()], 1.1)[0].voyage_id == "v-1"


def test_shift_distance_keeps_voyage_id():
    assert _shift_distance([_voyage()], 1.05)[0].voyage_id == "v-1"


def test_shift_speed_keeps_voyage_id():
    assert _shift_speed([_voyage()], 1.0)[0].voyage_id == "v-1"


def test_alternative_fuel_keeps_voyage_id(monkeypatch):
    seen: list[RemainingVoyage] = []
    real = engine.project_deterministic

    def spy(**kwargs):
        seen.extend(kwargs["remaining"])
        return real(**kwargs)

    monkeypatch.setattr(engine, "project_deterministic", spy)
    fuel_cf_alternative_projection(
        completed=COMPLETED,
        remaining=[_voyage()],
        transport_capacity=Decimal("50000"),
        required_cii=Decimal("5.0"),
        d_vector=D_VECTOR,
        alternative_fuel="LNG",
        alternative_cf=Decimal("2.75"),
    )
    assert {v.voyage_id for v in seen} == {"v-1"}


def test_apply_slowdown_keeps_voyage_id():
    result = apply_slowdown([_voyage()], [_leg("12")], Decimal("10"))
    assert result.remaining[0].voyage_id == "v-1"
    assert result.remaining[0].speed_kn != 12.0  # 감속이 실제로 적용됐다


def test_rebuilt_voyage_keeps_every_other_field():
    """바꾸지 않는 필드는 원본 그대로다 — 필드를 옮겨 적다 빠뜨리지 않는다."""
    original = _voyage()
    assert _shift_fuel([original], 1.0)[0] == original


def test_speed_shift_clamps_to_floor():
    """``speed + delta < 1.0``이면 하한 1.0에 붙는다."""
    shifted = _shift_speed([_voyage(speed=1.5)], -1.0)[0]
    assert shifted.speed_kn == engine.MIN_SPEED_KN == 1.0


def test_slowdown_clamps_to_floor():
    """``speed × factor < 1.0``이면 하한에 붙는다."""
    result = apply_slowdown([_voyage(speed=1.5)], [_leg("1.5")], Decimal("50"))
    assert result.remaining[0].speed_kn == 1.0


def test_min_speed_has_one_definition():
    """정의처는 ``fuel_estimator``(Decimal)이고 float 경로는 거기서 파생한다."""
    assert Decimal("1.0") == fuel_estimator.MIN_SPEED_KN
    assert engine.MIN_SPEED_KN == float(fuel_estimator.MIN_SPEED_KN) == 1.0
    assert scenario_compare.MIN_SPEED_KN is fuel_estimator.MIN_SPEED_KN


def test_simulate_annual_never_samples_negative_with_negative_min_factor(monkeypatch):
    """음수 `min_factor`로 ``simulate_annual`` 전체를 돌려도 표본에 음수 거리·연료가 없다."""
    drawn: list[np.ndarray] = []
    real = engine._sample_band

    def spy(*args, **kwargs):
        out = real(*args, **kwargs)
        drawn.append(out)
        return out

    monkeypatch.setattr(engine, "_sample_band", spy)
    profile = DistributionProfile(
        distance=TriangularBand(min_factor=-0.5, max_factor=1.05),
        fuel=TriangularBand(min_factor=-2.0, max_factor=1.15),
    )
    simulate_annual(
        completed=COMPLETED,
        remaining=[_voyage()],
        transport_capacity=Decimal("50000"),
        required_cii=Decimal("5.0"),
        d_vector=D_VECTOR,
        target_rating="C",
        seed=11,
        runs=1000,
        profile=profile,
    )
    assert len(drawn) == 2
    assert all(arr.min() >= 0.0 for arr in drawn)
