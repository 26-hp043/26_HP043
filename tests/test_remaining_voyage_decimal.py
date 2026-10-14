"""남은 항차 자료(``RemainingVoyage`` · ``CompletedTotals``)를 Decimal로 나른다 (#2448).

DB 없이 돈다. `#2254`가 유효 CF의 합·곱·나눗셈을 작업 정밀도 안으로 옮긴 뒤에도 서비스 세 자리
(`_inputs_from_snapshot` · `_year_end_drivers` · `_annual_impact`)는 그 값을 ``float``로 내려
엔진에 넘겼고, 결정론 계산이 ``Decimal(str(float))``로 되읽었다. 참값이 전송 자릿수 경계에
**정확히** 놓인 입력에서 ``float``가 참값보다 작은 쪽으로 깎여 여섯째 자리가 1 낮게 나갔다
(`9.133949` ↔ 참값 `9.133950`). `TECH_SPEC §1.1` [ORACLE-S-2 정정] — float 변환은 Monte Carlo
진입점에서만 한다.

세 가지를 잠근다.

1. 고정 입력에서 결정론 값이 **참값의 6자리 절사**다 — 고치기 전 코드에서 실패한다.
2. 계획값을 다시 만드는 함수들(실적 보정 · 민감도 지렛대 · 함대 감속 · 대체 연료)이
   **호출 스레드의 정밀도에 흔들리지 않는다** — Decimal이 결정론 계산에 그대로 들어가므로.
3. Monte Carlo 입력(float64 배열)이 변환 자리를 옮기기 전과 **비트 단위로 같다**.
"""

from __future__ import annotations

import inspect
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from cii_platform.calc import annual_simulation as engine
from cii_platform.calc.annual_simulation import (
    CompletedTotals,
    RemainingVoyage,
    _shift_distance,
    _shift_fuel,
    _shift_speed,
    apply_feedback,
    fuel_cf_alternative_projection,
    mass_weighted_cf,
    project_deterministic,
    simulate_annual,
)
from cii_platform.calc.fleet_reduction import PlannedLeg, apply_slowdown
from cii_platform.calc.rating_engine import DVector
from cii_platform.services import annual_simulation as svc_annual
from cii_platform.services import cii_current, voyage_cii
from cii_platform.services.annual_simulation import _inputs_from_snapshot
from cii_platform.services.cii_current import (
    DRIVER_BASIS_DIFFERENCE,
    DRIVER_CURRENT_VOYAGE,
    DRIVER_REMAINING_PLAN,
)
from cii_platform.services.ytd_cii import InProgressContribution

D_VECTOR = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))
CAPACITY = Decimal(50000)
REQUIRED = Decimal("5.045066")
VESSEL = SimpleNamespace(reference_speed_kn=Decimal(14), reference_daily_foc_ton=Decimal(30))
CF = {"HFO": Decimal("3.114"), "LNG": Decimal("2.750")}


def _truncated_6(value: Fraction) -> str:
    """분수를 소수 6자리로 0 방향 절사한 문자열 — 정수 나눗셈만 쓴다 (`AGENTS §5`)."""
    scaled = value.numerator * 10**6 // value.denominator
    return f"{scaled // 10**6}.{scaled % 10**6:06d}"


def _plan_row(
    voyage_id: str, distance: str, fuels: list[tuple[str, str]], speed: str | None = None
):
    return {
        "voyage_id": voyage_id,
        "kind": "PLAN",
        "planned_distance_nm": distance,
        "actual_distance_nm": None,
        "planned_speed_kn": speed,
        "fuel_uses": [
            {
                "fuel_type": code,
                "planned_fuel_ton": ton,
                "actual_fuel_ton": None,
                "cf_used": str(CF[code]),
            }
            for code, ton in fuels
        ],
    }


def _actual_row(voyage_id: str, distance: str, fuels: list[tuple[str, str]]):
    return {
        "voyage_id": voyage_id,
        "kind": "ACTUAL",
        "planned_distance_nm": distance,
        "actual_distance_nm": distance,
        "planned_speed_kn": None,
        "fuel_uses": [
            {
                "fuel_type": code,
                "planned_fuel_ton": ton,
                "actual_fuel_ton": ton,
                "cf_used": str(CF[code]),
            }
            for code, ton in fuels
        ],
    }


# ─── 1. 고정 입력 — 참값이 전송 자릿수 경계에 정확히 놓인다 ─────────────────────────────
#
# 50,000 DWT 벌크선 · 확정 5,000 nm · HFO 400 t · 잔여 3,000 nm · HFO 100 t + LNG 200 t.
#
#     M = (400×3.114 + 100×3.114 + 200×2.75) × 10⁶ = 2,107,000,000 g
#     W = 50,000 × (5,000 + 3,000)            =   400,000,000
#     M / W = 5.2675                           ← 소수 4자리에서 끝난다
#
# 잔여 항차의 유효 CF는 861.4 / 300 = 2.871333…(비종결)이다. float로 내리면
# 2.87133333333333328…로 참값보다 작아지고, 그 값으로 낸 CII는 5.26749999999999997…이라
# 6자리 절사가 `5.267499`를 낸다. Decimal 그대로면 정확히 5.2675라 `5.267500`이다.

_FIXED_ROWS = [
    _actual_row("done", "5000", [("HFO", "400")]),
    _plan_row("plan", "3000", [("HFO", "100"), ("LNG", "200")]),
]
_FIXED_TRUTH = Fraction(2_107_000_000, 400_000_000)
_FIXED_EXPECTED = "5.267500"


def test_fixed_input_truth_is_on_the_transport_digit_boundary():
    """이 입력이 검사로서 뜻을 가지려면 참값이 6자리 안에서 끝나야 한다."""
    assert Fraction("5.2675") == _FIXED_TRUTH
    assert _truncated_6(_FIXED_TRUTH) == _FIXED_EXPECTED


def test_snapshot_projection_is_the_truncation_of_the_exact_value():
    """⚠️ #2448 — `_inputs_from_snapshot` → `project_deterministic` → `_publish`가 참값의 절사다.

    고치기 전 코드는 유효 CF를 float로 내려 `5.267499`를 냈다.
    """
    completed, remaining, _warnings = _inputs_from_snapshot(_FIXED_ROWS, VESSEL)
    projection = project_deterministic(
        completed=completed,
        remaining=remaining,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
    )
    assert svc_annual._publish(projection.attained_cii, "cii") == _FIXED_EXPECTED
    assert voyage_cii._publish(projection.attained_cii, "attained_cii") == _FIXED_EXPECTED


def test_snapshot_inputs_are_decimal_throughout():
    """조립이 내는 값은 전부 Decimal이다 — 제원·속력까지(`_shift_speed`가 Decimal 연료에 곱한다)."""
    completed, remaining, _warnings = _inputs_from_snapshot(
        [_plan_row("plan", "3000", [("HFO", "100")], speed="13.5"), *_FIXED_ROWS], VESSEL
    )
    assert isinstance(completed.co2_g, Decimal)
    assert isinstance(completed.distance_nm, Decimal)
    assert len(remaining) == 2
    for voyage in remaining:
        for name in ("distance_nm", "fuel_ton", "cf", "reference_speed_kn", "base_daily_foc_ton"):
            assert isinstance(getattr(voyage, name), Decimal), name
    assert remaining[0].speed_kn == Decimal("13.5")
    assert remaining[1].speed_kn is None


def test_year_end_drivers_do_not_invent_a_basis_difference():
    """⚠️ #2448 — `_year_end_drivers`의 경과분 한 줄도 Decimal로 간다.

    ⑴ 올해 누적이 정확히 `5.2675`인데 ⑶의 같은 조립이 `5.267499`를 내면, 분해가 있지도 않은
    `BASIS_DIFFERENCE −0.000001`을 만든다. 고치기 전 코드가 그랬다.
    """
    completed = CompletedTotals(
        co2_g=Decimal(400) * CF["HFO"] * 1_000_000, distance_nm=Decimal(5000)
    )
    context = SimpleNamespace(
        vessel=VESSEL, transport_capacity=CAPACITY, required_cii=REQUIRED, d_vector=D_VECTOR
    )
    inputs = SimpleNamespace(voyages_json=[], completed=completed)
    deterministic = SimpleNamespace(attained_cii=Decimal("5.2675"))
    contribution = InProgressContribution(
        distance_nm=Decimal(3000), fuel_uses=(("HFO", Decimal(100)), ("LNG", Decimal(200)))
    )

    drivers = cii_current._year_end_drivers(
        context,
        inputs,
        deterministic,
        ytd_attained_cii=Decimal("5.2675"),
        current_voyage_id=None,
        contribution=contribution,
        cf_by_fuel=CF,
    )

    # 진행 항차는 있는데 계획 전량(PLAN 행)이 없어 `CURRENT_VOYAGE`는 「경과분 → 확정분만」이다.
    assert [d["key"] for d in drivers] == [DRIVER_CURRENT_VOYAGE, DRIVER_REMAINING_PLAN]
    assert DRIVER_BASIS_DIFFERENCE not in {d["key"] for d in drivers}
    # 확정분만의 CII 4.9824 ↔ 5.2675 — 두 단계가 정확히 상쇄된다.
    assert [d["delta_cii"] for d in drivers] == ["-0.285100", "0.285100"]


@pytest.mark.parametrize(
    "fn",
    [
        svc_annual._inputs_from_snapshot,
        cii_current._year_end_drivers,
        voyage_cii._annual_impact,
    ],
)
def test_service_sites_do_not_convert_to_float(fn):
    """세 자리 어디에도 `float(`가 없다 — 변환 지점은 `simulate_annual` 하나다 (`TECH_SPEC §1.1`).

    `_annual_impact`는 DB가 있어야 끝까지 돌므로 변환 자리를 원문으로 본다.
    """
    assert "float(" not in inspect.getsource(fn), fn.__qualname__


# ─── 2. 계획값을 다시 만드는 함수들이 호출 스레드의 정밀도에 흔들리지 않는다 ─────────────
#
# `RemainingVoyage`가 Decimal을 들면서 이 함수들의 곱이 결정론 계산의 입력이 됐다. 데코레이터가
# 없으면 호출 스레드의 기본 정밀도(28)로 깎인 값이 50자리 계산에 들어간다 — `prec=6`으로 좁혀
# 그 의존을 드러낸다(`tests/test_layer1_context.py`의 `_narrowed`와 같은 방식).

_LONG_FUEL = Decimal("250.123456789")  # 유효숫자 12 — 6자리로 깎이면 250.123이 된다


def _voyage() -> RemainingVoyage:
    return RemainingVoyage(
        distance_nm=Decimal(3000),
        fuel_ton=_LONG_FUEL,
        cf=CF["HFO"],
        speed_kn=Decimal(14),
        reference_speed_kn=Decimal(14),
        base_daily_foc_ton=Decimal(30),
        voyage_id="v-1",
    )


def _narrowed(fn, *args, **kwargs):
    with localcontext(prec=6, rounding=ROUND_HALF_UP):
        return fn(*args, **kwargs)


_LEG = PlannedLeg(
    distance_nm=Decimal(3000), speed_kn=Decimal(14), fuel_ton_by_type={"HFO": _LONG_FUEL}
)

_REBUILDERS = {
    "apply_feedback": (lambda v: apply_feedback([v], Decimal("1.1"))[0], Decimal("275.1358024679")),
    "_shift_fuel": (lambda v: _shift_fuel([v], Decimal("0.90"))[0], Decimal("225.1111111101")),
    "_shift_distance": (
        lambda v: _shift_distance([v], Decimal("1.05"))[0],
        Decimal("262.62962962845"),
    ),
    # (13/14)² 는 비종결이라 기대값을 자릿수로 본다.
    "_shift_speed": (lambda v: _shift_speed([v], Decimal(-1))[0], None),
    "apply_slowdown": (
        lambda v: apply_slowdown([v], [_LEG], Decimal(10)).remaining[0],
        Decimal("202.59999999909"),
    ),
}


@pytest.mark.parametrize("name", sorted(_REBUILDERS))
def test_rebuilders_ignore_the_callers_precision(name):
    rebuild, exact = _REBUILDERS[name]
    default = rebuild(_voyage())
    narrowed = _narrowed(rebuild, _voyage())

    assert narrowed == default, name
    if exact is not None:
        assert default.fuel_ton == exact
    else:
        # 작업 정밀도(50)로 나눈 값이다 — 6자리로 깎였다면 자릿수가 6이다.
        assert len(default.fuel_ton.as_tuple().digits) > 28
    with localcontext(prec=6, rounding=ROUND_HALF_UP):
        clipped = _LONG_FUEL * Decimal("0.90")
    assert clipped != Decimal("225.1111111101"), (
        "6자리로도 같은 값이면 이 검사는 아무것도 잠그지 않는다"
    )


def test_alternative_fuel_lever_ignores_the_callers_precision():
    kwargs = {
        "completed": CompletedTotals(
            co2_g=Decimal(400) * CF["HFO"] * 1_000_000, distance_nm=Decimal(5000)
        ),
        "remaining": [_voyage()],
        "transport_capacity": CAPACITY,
        "required_cii": REQUIRED,
        "d_vector": D_VECTOR,
        "alternative_fuel": "LNG",
        "alternative_cf": CF["LNG"],
    }
    default = fuel_cf_alternative_projection(**kwargs)
    narrowed = _narrowed(fuel_cf_alternative_projection, **kwargs)
    assert narrowed == default
    assert len(default.co2_change_ratio.as_tuple().digits) > 28


# ─── 3. Monte Carlo 입력은 변환 자리를 옮기기 전과 같다 ─────────────────────────────────


def test_monte_carlo_inputs_are_bit_identical_to_the_former_service_side_floats(monkeypatch):
    """엔진이 `float(Decimal)`로 내린 배열이 종전 서비스의 `float(...)`와 비트 단위로 같다.

    표본(`_sample_band`의 ``plan``)과 집계 직전의 ``attained``(`_classify`의 입력)를 가로채,
    종전 변환(`float(Decimal(거리 문자열))` · `float(Σ톤)` · `float(유효 CF)` ·
    `float(확정 누계)`)으로 다시 계산한 배열과 ``np.array_equal``로 견준다.
    """
    rows = [
        _actual_row("done", "5000", [("HFO", "400")]),
        _plan_row("p1", "3000", [("HFO", "100"), ("LNG", "200")]),
        _plan_row("p2", "1234.5", [("HFO", "333.333")]),
    ]
    completed, remaining, _warnings = _inputs_from_snapshot(rows, VESSEL)

    # 종전 서비스가 넘기던 float — 같은 문자열·같은 Decimal에서 같은 식으로 낸다.
    former_distance = np.array(
        [float(Decimal(r["planned_distance_nm"])) for r in rows if r["kind"] == "PLAN"]
    )
    former_fuel, former_cf = [], []
    for row in rows:
        if row["kind"] != "PLAN":
            continue
        ton, cf = mass_weighted_cf(
            (Decimal(u["planned_fuel_ton"]), Decimal(u["cf_used"])) for u in row["fuel_uses"]
        )
        former_fuel.append(float(ton))
        former_cf.append(float(cf))
    former_fuel = np.array(former_fuel)
    former_cf = np.array(former_cf)
    former_completed_co2 = float(Decimal(400) * CF["HFO"] * 1_000_000)
    former_completed_distance = float(Decimal(5000))

    plans: list[np.ndarray] = []
    sampled: list[np.ndarray] = []
    seen: dict[str, np.ndarray] = {}
    real_sample, real_classify = engine._sample_band, engine._classify

    def spy_sample(rng, band, plan, size):
        plans.append(plan)
        out = real_sample(rng, band, plan, size)
        sampled.append(out)
        return out

    def spy_classify(attained, bounds):
        seen["attained"] = attained
        return real_classify(attained, bounds)

    monkeypatch.setattr(engine, "_sample_band", spy_sample)
    monkeypatch.setattr(engine, "_classify", spy_classify)
    simulate_annual(
        completed=completed,
        remaining=remaining,
        transport_capacity=CAPACITY,
        required_cii=REQUIRED,
        d_vector=D_VECTOR,
        target_rating="C",
        seed=2448,
        runs=1000,
    )

    assert np.array_equal(plans[0], former_distance)
    assert np.array_equal(plans[1], former_fuel)
    expected_attained = (
        former_completed_co2 + (sampled[1] * former_cf * engine.GRAMS_PER_TON).sum(axis=1)
    ) / (float(CAPACITY) * (former_completed_distance + sampled[0].sum(axis=1)))
    assert np.array_equal(seen["attained"], expected_attained)
