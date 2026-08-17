"""연간 CII 등급 시뮬레이터 — 결정론 예측 + Monte Carlo (PRD §12, #63).

## 이 모듈은 DB를 모른다

``calc`` 계층의 규약대로 **이미 읽어 온 값만** 인자로 받는다(``cii_engine``·
``fuel_estimator``와 같다). 스냅샷 생성·조회는 ``#64``의 몫이다 — 그래야 같은 엔진을
저장된 스냅샷으로도, 손으로 만든 입력으로도 돌릴 수 있다.

## 두 계층이 섞여 있다

===============  ==========  ==========================================
 산출물           정밀도      근거
===============  ==========  ==========================================
 결정론 연말 값    ``Decimal``  표시·저장되는 확정값 (``TECH_SPEC §1``)
 Monte Carlo      ``float64``  5,000회 루프. Decimal은 ~100배 느리다
===============  ==========  ==========================================

``TECH_SPEC §2.1``이 Monte Carlo를 float64로 못박은 이유는 속도만이 아니다 —
삼각분포 역CDF 샘플링(``sqrt(U·(b−a)·(c−a))``)을 Decimal로 하면 **동일 플랫폼 밖에서
bit-exact 재현이 안 된다.**

**등급 경계는 Decimal로 한 번만 구해** float로 내린다. 경계는 시뮬레이션마다 변하지
않는 값(수송능력·연도에 의존)이라 루프 안에서 다시 만들 이유가 없고, Layer 1이
확정한 값을 그대로 쓰는 편이 결정론 결과와 어긋나지 않는다.

## ⚠️ 명세의 미해결 지점 — 속도

``PRD §12.4.1``은 거리·연료·**속도** 셋을 각각 독립 삼각분포로 표본추출하라고 적는다.
그런데 CII는 ``M / (W · Dt)``이고 **속도는 이 식에 들어가지 않는다** — 연료와 거리로만
정해진다. 연료를 독립으로 뽑으면서 속도도 독립으로 뽑으면, 속도가 결과에 아무 영향을
주지 못하거나(현재 식) 같은 변동을 두 번 세게 된다(cubic model로 연결할 경우).

이 모듈은 **거리·연료만 표본추출한다.** 연료 분포의 설명이 「기상·운항 변동」이라
속도 변동을 이미 흡수하고 있다고 본다. 속도는 ``§12.6`` 민감도 분석에서 cubic
model(``fuel_estimator``)을 통해 다룬다 — 그쪽은 연결이 명시돼 있다.

**정본 정정이 필요한 지점이며, 임의로 식을 만들지 않았다.**

## ⚠️ ``simulation_parameter`` 테이블이 없다

``PRD §12.4.1``은 *"분포 기본값은 ``simulation_parameter``로 관리하며 코드
하드코딩하지 않는다"* 고 적는다. 그런데 그 테이블은 **``DB_SCHEMA``에 정의가 없고
실제로 존재하지도 않는다** — PRD가 이름만 부른다.

없는 스키마를 지어내지 않는다. 대신 분포를 **인자로 받고** 기본값을
:data:`DEFAULT_PROFILE`로 둔다. 테이블이 생기면 호출부가 그것을 읽어 넘기면 되고,
이 모듈은 바뀌지 않는다.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np

from cii_platform.calc.precision import layer1_context, validate_layer1_result
from cii_platform.calc.rating_engine import DVector, determine_rating
from cii_platform.calc.rng import RNG_ALGORITHM, create_rng

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 등급 순서 — 확률 누적에 쓴다.
RATINGS: tuple[str, ...] = ("A", "B", "C", "D", "E")

#: ``PRD §12.8`` — 목표 E는 거부한다. D는 경고를 붙이고 진행한다.
TARGET_RATING_REJECTED = "E"
WARNING_TARGET_RATING_D = "TARGET_RATING_D"

#: ``PRD §12.8`` — 잔여 항차 상한. 200 초과는 거부(DoS 방지), 100 초과는 경고.
MAX_REMAINING_VOYAGES = 200
WARN_REMAINING_VOYAGES = 100
WARNING_MANY_VOYAGES = "MANY_REMAINING_VOYAGES"

#: ``PRD §12.2`` — 시뮬레이션 횟수 범위. 초과는 거부가 아니라 상한으로 자른다.
MIN_SIMULATION_RUNS = 1_000
MAX_SIMULATION_RUNS = 10_000
WARNING_RUNS_CLAMPED = "SIMULATION_RUNS_CLAMPED"

#: ``PRD §12.8`` — 누적 실적이 없다. 오류가 아니라 「잔여 계획만으로 예측」 상태다.
WARNING_NO_COMPLETED = "NO_COMPLETED_VOYAGES"

#: ``PRD §12.8`` — 잔여 항차가 없다. 확정 실적만으로 연말 값을 낸다.
WARNING_NO_REMAINING = "NO_REMAINING_VOYAGES"

#: ``PRD §12.8`` — one-at-a-time이라 변수 간 상호작용은 포함되지 않는다.
WARNING_SENSITIVITY_OAT = "SENSITIVITY_ONE_AT_A_TIME"

#: ``PRD §12.4.3`` [ORACLE-C-1] — 확률·분위수는 소수 4자리에서 반올림한다.
PROBABILITY_DIGITS = 4

#: ``PRD §12.4.1`` [ORACLE 삼각분포 가드] — 속도 하한. 계획 1.5kn이면 min이 0.5kn이
#: 되므로 floor를 적용한다.
MIN_SPEED_KN = 1.0

#: 톤 → 그램. ``PRD §3.3.1``의 ``M`` 단위.
GRAMS_PER_TON = 1_000_000


# ─── 입력 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TriangularBand:
    """계획값에 대한 삼각분포 배수 (``PRD §12.4.1``).

    ``mode``가 항상 계획값(배수 1.0)이라 배수로 적는 편이 표와 1:1로 읽힌다.
    """

    min_factor: float
    max_factor: float
    mode_factor: float = 1.0

    def bounds(self, plan: float) -> tuple[float, float, float]:
        """``(left, mode, right)``. **불변식 위반 시 mode를 중심으로 재조정한다.**

        ``PRD §12.4.1`` [ORACLE 삼각분포 가드]가 요구하는 처리다. 파라미터가 잘못
        들어와도 계산을 죽이지 않고 물리적으로 성립하는 범위로 좁힌다 — 시뮬레이션
        하나가 파라미터 오타로 통째로 실패하는 것보다 낫다.
        """
        mode = plan * self.mode_factor
        left = min(plan * self.min_factor, mode)
        right = max(plan * self.max_factor, mode)
        return left, mode, right


@dataclass(frozen=True)
class DistributionProfile:
    """분포 세트 (``PRD §12.2`` ``distribution_profile``)."""

    distance: TriangularBand
    fuel: TriangularBand
    #: 속도 변동 폭(kn). 현재 Monte Carlo에서 쓰지 않는다 — 모듈 docstring 참조.
    #: 민감도 분석(``§12.6``)의 ±1kn이 이 값이다.
    speed_delta_kn: float = 1.0


#: ``PRD §12.4.1`` 기본 분포. **테이블이 생기면 호출부가 대체한다** — 모듈 docstring 참조.
DEFAULT_PROFILE = DistributionProfile(
    distance=TriangularBand(min_factor=0.97, max_factor=1.05),
    fuel=TriangularBand(min_factor=0.90, max_factor=1.15),
)


@dataclass(frozen=True)
class RemainingVoyage:
    """잔여 항차 하나의 계획값.

    ``cf``를 항차마다 받는 이유는 항차별 연료 종류가 다를 수 있기 때문이다
    (``PRD §12.4.1`` — 연료 종류는 MVP에서 고정이지만 항차마다 다를 수 있다).
    """

    distance_nm: float
    fuel_ton: float
    cf: float
    #: 민감도 분석의 속도 지렛대에만 쓴다. 없으면 그 항목을 건너뛴다.
    speed_kn: float | None = None
    reference_speed_kn: float | None = None
    base_daily_foc_ton: float | None = None


@dataclass(frozen=True)
class CompletedTotals:
    """확정·완료 항차의 누계. **변하지 않는다** (``PRD §12.4.1``)."""

    co2_g: float
    distance_nm: float


# ─── 출력 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeterministicProjection:
    """결정론 연말 예측 (``PRD §12.3``). 난수를 쓰지 않는다."""

    attained_cii: Decimal
    rating: str
    boundaries: dict[str, Decimal]
    completed_co2_g: Decimal
    completed_distance_nm: Decimal
    planned_co2_g: Decimal
    planned_distance_nm: Decimal


@dataclass(frozen=True)
class SensitivityEntry:
    """민감도 한 줄 (``PRD §12.6``)."""

    variable: str
    change: str
    attained_cii: Decimal
    rating: str


@dataclass(frozen=True)
class SimulationOutcome:
    """Monte Carlo 집계 (``PRD §12.4.2`` · ``§12.7``)."""

    rating_probabilities: dict[str, Decimal]
    target_success_probability: Decimal
    p10: Decimal
    p50: Decimal
    p90: Decimal
    mean: Decimal
    runs: int
    rng_metadata: dict[str, object]
    warnings: list[str] = field(default_factory=list)


# ─── 결정론 예측 (Layer 1) ───────────────────────────────────────────────────


@layer1_context
def _boundaries_decimal(required_cii: Decimal, d_vector: DVector) -> dict[str, Decimal]:
    """등급 경계 4종. ``determine_rating``이 쓰는 것과 **같은 값**이어야 한다.

    ``attained``에 ``required``를 그대로 넘긴다 — 여기서 필요한 것은 경계값뿐이고
    등급 문자는 버린다. 경계는 ``required × d``라 ``attained``와 무관하다.
    """
    return determine_rating(
        attained_cii=required_cii, required_cii=required_cii, d_vector=d_vector
    ).boundaries


@layer1_context
def project_deterministic(
    *,
    completed: CompletedTotals,
    remaining: Sequence[RemainingVoyage],
    transport_capacity: Decimal,
    required_cii: Decimal,
    d_vector: DVector,
) -> DeterministicProjection:
    """확정 실적 + 잔여 계획으로 연말 값을 낸다 (``PRD §12.3``).

    .. code-block:: text

        projected = (completed_M + planned_M) / (completed_W + planned_W)

    ``W = capacity × distance``이고 capacity가 선박 상수라 분모에서 한 번만 곱한다.

    **난수를 쓰지 않는다.** 같은 입력이면 언제나 같은 값이므로 Monte Carlo와 달리
    ``Decimal``로 계산해 표시·저장값으로 그대로 쓴다.
    """
    if transport_capacity <= 0:
        raise ValueError(f"transport_capacity must be > 0: got {transport_capacity}")
    if required_cii <= 0:
        raise ValueError(f"required_cii must be > 0: got {required_cii}")

    completed_co2 = Decimal(str(completed.co2_g))
    completed_distance = Decimal(str(completed.distance_nm))
    planned_co2 = sum(
        (Decimal(str(v.fuel_ton)) * Decimal(str(v.cf)) * Decimal(GRAMS_PER_TON) for v in remaining),
        Decimal(0),
    )
    planned_distance = sum((Decimal(str(v.distance_nm)) for v in remaining), Decimal(0))

    total_distance = completed_distance + planned_distance
    if total_distance <= 0:
        # `PRD §12.8` — completed_W + planned_W = 0이면 계산 중단.
        raise ValueError("completed_W + planned_W = 0 — 거리가 없어 CII를 낼 수 없습니다.")

    attained = (completed_co2 + planned_co2) / (transport_capacity * total_distance)
    validate_layer1_result(attained, "projected_attained_cii")
    result = determine_rating(attained_cii=attained, required_cii=required_cii, d_vector=d_vector)

    return DeterministicProjection(
        attained_cii=attained,
        rating=result.rating,
        boundaries=result.boundaries,
        completed_co2_g=completed_co2,
        completed_distance_nm=completed_distance,
        planned_co2_g=planned_co2,
        planned_distance_nm=planned_distance,
    )


# ─── Monte Carlo (Layer 2 · float64) ─────────────────────────────────────────


def _classify(attained: np.ndarray, bounds: tuple[float, float, float, float]) -> np.ndarray:
    """attained 배열 → 등급 인덱스 배열.

    경계값과 정확히 같으면 **더 우수한 등급**이다 (``PRD §3.3.6``) — 그래서 `<=`다.
    ``determine_rating``의 비교 순서를 그대로 옮긴 것이며, 어긋나면 결정론 결과와
    Monte Carlo 최빈값이 다른 등급을 가리킬 수 있다.
    """
    superior, lower, upper, inferior = bounds
    # searchsorted 대신 명시적 비교를 쓴다 — 경계 포함 방향(`<=`)이 코드에 드러난다.
    index = np.full(attained.shape, 4, dtype=np.int8)  # 기본 E
    index = np.where(attained <= inferior, 3, index)
    index = np.where(attained <= upper, 2, index)
    index = np.where(attained <= lower, 1, index)
    index = np.where(attained <= superior, 0, index)
    return index


def _round(value: float) -> Decimal:
    """``PRD §12.4.3`` — 확률·분위수는 소수 4자리."""
    return Decimal(str(round(float(value), PROBABILITY_DIGITS)))


def simulate_annual(
    *,
    completed: CompletedTotals,
    remaining: Sequence[RemainingVoyage],
    transport_capacity: Decimal,
    required_cii: Decimal,
    d_vector: DVector,
    target_rating: str,
    seed: int,
    runs: int = 5_000,
    profile: DistributionProfile = DEFAULT_PROFILE,
) -> SimulationOutcome:
    """Monte Carlo로 연말 CII 분포를 낸다 (``PRD §12.4``).

    ## 표본추출은 잔여 항차에만 적용한다

    확정 실적은 이미 일어난 일이라 변하지 않는다 (``PRD §12.4.1``). 이걸 함께
    흔들면 「과거가 달라지는」 분포가 나온다.

    ## 항차별로 뽑고 합친다

    항차마다 독립으로 뽑아야 **항차 수가 많을수록 합계의 상대 변동이 줄어드는**
    실제 성질이 재현된다. 합계에 한 번 곱하면 항차 100건짜리 선박과 1건짜리 선박이
    같은 변동폭을 갖게 된다.

    ``(runs, voyages)`` 배열로 한 번에 뽑는다 — 파이썬 루프로 돌면 5,000회 × 항차 수
    만큼 인터프리터를 오가고, ``PERF-004``(p95 < 3초)를 맞출 수 없다.

    :param seed: ``PRD §12.4.3`` — 동일 seed·동일 입력이면 동일 결과여야 한다.
    :raises ValueError: 목표 등급이 E이거나(``§12.8``) 잔여 항차가 상한을 넘을 때.
    """
    warnings: list[str] = []

    if target_rating == TARGET_RATING_REJECTED:
        raise ValueError("목표 등급 E는 의미 있는 분석이 아닙니다. A~C를 목표로 설정하세요.")
    if target_rating not in RATINGS:
        raise ValueError(f"목표 등급이 올바르지 않습니다: {target_rating}")
    if target_rating == "D":
        warnings.append(WARNING_TARGET_RATING_D)

    if len(remaining) > MAX_REMAINING_VOYAGES:
        raise ValueError(
            f"잔여 항차가 {MAX_REMAINING_VOYAGES}건을 초과했습니다 "
            f"({len(remaining)}건). 계산을 거부합니다."
        )
    if len(remaining) > WARN_REMAINING_VOYAGES:
        warnings.append(WARNING_MANY_VOYAGES)

    if runs > MAX_SIMULATION_RUNS or runs < MIN_SIMULATION_RUNS:
        # 거부가 아니라 자른다 — `PRD §12.8`이 「최대값으로 제한하고 안내」로 적는다.
        runs = min(max(runs, MIN_SIMULATION_RUNS), MAX_SIMULATION_RUNS)
        warnings.append(WARNING_RUNS_CLAMPED)

    if completed.distance_nm <= 0:
        warnings.append(WARNING_NO_COMPLETED)
    if not remaining:
        warnings.append(WARNING_NO_REMAINING)

    # 경계는 Decimal로 한 번만 구해 float로 내린다 — 루프 안에서 변하지 않는 값이다.
    decimal_bounds = _boundaries_decimal(required_cii, d_vector)
    bounds = (
        float(decimal_bounds["superior_boundary"]),
        float(decimal_bounds["lower_boundary"]),
        float(decimal_bounds["upper_boundary"]),
        float(decimal_bounds["inferior_boundary"]),
    )

    capacity = float(transport_capacity)
    rng = create_rng(seed)

    if remaining:
        plan_distance = np.array([v.distance_nm for v in remaining], dtype=np.float64)
        plan_fuel = np.array([v.fuel_ton for v in remaining], dtype=np.float64)
        cf = np.array([v.cf for v in remaining], dtype=np.float64)

        # 계획값이 항차마다 다르므로 bounds도 배열이다.
        size = (runs, len(remaining))
        sampled_distance = _sample_band(rng, profile.distance, plan_distance, size)
        sampled_fuel = _sample_band(rng, profile.fuel, plan_fuel, size)

        planned_co2 = (sampled_fuel * cf * GRAMS_PER_TON).sum(axis=1)
        planned_distance = sampled_distance.sum(axis=1)
    else:
        planned_co2 = np.zeros(runs, dtype=np.float64)
        planned_distance = np.zeros(runs, dtype=np.float64)

    total_distance = completed.distance_nm + planned_distance
    if np.any(total_distance <= 0):
        raise ValueError("completed_W + planned_W = 0 — 거리가 없어 CII를 낼 수 없습니다.")

    attained = (completed.co2_g + planned_co2) / (capacity * total_distance)

    index = _classify(attained, bounds)
    counts = np.bincount(index, minlength=len(RATINGS))
    probabilities = {rating: _round(counts[i] / runs) for i, rating in enumerate(RATINGS)}

    # `PRD §12.5` — 목표가 B면 A·B 합계다. 「목표 등급 **이상**」이 성공이다.
    target_index = RATINGS.index(target_rating)
    success = float(counts[: target_index + 1].sum()) / runs

    return SimulationOutcome(
        rating_probabilities=probabilities,
        target_success_probability=_round(success),
        p10=_round(float(np.percentile(attained, 10))),
        p50=_round(float(np.percentile(attained, 50))),
        p90=_round(float(np.percentile(attained, 90))),
        mean=_round(float(attained.mean())),
        runs=runs,
        rng_metadata=rng_metadata(seed, runs),
        warnings=warnings,
    )


def _sample_band(
    rng: np.random.Generator, band: TriangularBand, plan: np.ndarray, size: tuple[int, int]
) -> np.ndarray:
    """항차별 삼각분포 표본. ``min ≤ mode ≤ max``를 원소마다 보장한다.

    **폭이 0인 항차를 따로 다룬다.** ``numpy.triangular``는 ``left == right``를 거부하는데,
    ``PRD §12.4.1`` 가드가 뒤집힌 파라미터를 재조정하면 그 상태가 실제로 나온다
    (``min_factor=1.5``·``max_factor=0.5``면 셋이 모두 mode로 모인다). 계획값이 0인
    항차도 마찬가지다.

    폭이 0이라는 것은 **변동이 없다**는 뜻이므로 계획값을 그대로 쓴다. 억지로 폭을
    만들면 근거 없는 변동이 결과에 섞인다.
    """
    mode = plan * band.mode_factor
    left = np.minimum(plan * band.min_factor, mode)
    right = np.maximum(plan * band.max_factor, mode)

    degenerate = right <= left
    # 표본추출 자체는 전부에 대해 돌린다 — 항차마다 건너뛰면 뽑는 난수 개수가
    # 입력에 따라 달라져 seed 재현성이 입력 형태에 의존하게 된다.
    safe_left = np.where(degenerate, mode - 1.0, left)
    safe_right = np.where(degenerate, mode + 1.0, right)
    sampled = rng.triangular(safe_left, mode, safe_right, size=size)
    return np.where(degenerate, mode, sampled)


def rng_metadata(seed: int, runs: int) -> dict[str, object]:
    """``PRD §12.4.3`` [ORACLE-C-1] — 재현에 필요한 것을 전부 남긴다.

    ``NEP 19``에 따라 NumPy Generator는 **버전 간 bit-for-bit 호환을 보장하지 않는다.**
    그래서 seed만으로는 부족하고 라이브러리·플랫폼까지 함께 기록해야, 값이 재현되지
    않을 때 「환경이 달라서」인지 「코드가 바뀌어서」인지 가를 수 있다.
    """
    return {
        "seed": seed,
        "generator": RNG_ALGORITHM,
        "num_runs": runs,
        "numpy_version": np.__version__,
        "python_version": platform.python_version(),
        "platform": sys.platform,
        "model_version": f"python-numpy-{np.__version__}-{RNG_ALGORITHM.lower()}",
    }


# ─── 민감도 분석 (PRD §12.6) ─────────────────────────────────────────────────


def _shift_fuel(remaining: Sequence[RemainingVoyage], factor: float):
    return [
        RemainingVoyage(
            distance_nm=v.distance_nm,
            fuel_ton=v.fuel_ton * factor,
            cf=v.cf,
            speed_kn=v.speed_kn,
            reference_speed_kn=v.reference_speed_kn,
            base_daily_foc_ton=v.base_daily_foc_ton,
        )
        for v in remaining
    ]


def _shift_distance(remaining: Sequence[RemainingVoyage], factor: float):
    return [
        RemainingVoyage(
            distance_nm=v.distance_nm * factor,
            # 거리가 늘면 연료도 는다 — 거리만 늘리면 「같은 연료로 더 갔다」가 되어
            # CII가 좋아지는 쪽으로만 틀린다.
            fuel_ton=v.fuel_ton * factor,
            cf=v.cf,
            speed_kn=v.speed_kn,
            reference_speed_kn=v.reference_speed_kn,
            base_daily_foc_ton=v.base_daily_foc_ton,
        )
        for v in remaining
    ]


def _shift_speed(remaining: Sequence[RemainingVoyage], delta_kn: float):
    """속도를 바꾸고 **cubic model로 연료를 다시 낸다** (``TECH_SPEC §4.1``).

    ``fuel ∝ speed² × distance``다(``daily_foc × (v/v_ref)³ × distance/(v·24)``).
    속도만 바꾸고 연료를 그대로 두면 CII가 변하지 않아 이 지렛대가 무의미해진다.

    제원(``reference_speed_kn``·``base_daily_foc_ton``)이 없는 항차는 **건너뛴다** —
    임의 기본값을 넣으면 화면은 깨지지 않고 값만 틀린다.
    """
    shifted = []
    for v in remaining:
        if v.speed_kn is None or v.reference_speed_kn is None or v.base_daily_foc_ton is None:
            shifted.append(v)
            continue
        new_speed = max(v.speed_kn + delta_kn, MIN_SPEED_KN)
        ratio = (new_speed / v.speed_kn) ** 2
        shifted.append(
            RemainingVoyage(
                distance_nm=v.distance_nm,
                fuel_ton=v.fuel_ton * ratio,
                cf=v.cf,
                speed_kn=new_speed,
                reference_speed_kn=v.reference_speed_kn,
                base_daily_foc_ton=v.base_daily_foc_ton,
            )
        )
    return shifted


def analyze_sensitivity(
    *,
    completed: CompletedTotals,
    remaining: Sequence[RemainingVoyage],
    transport_capacity: Decimal,
    required_cii: Decimal,
    d_vector: DVector,
) -> tuple[list[SensitivityEntry], list[str]]:
    """one-at-a-time 민감도 (``PRD §12.6``). SHAP는 쓰지 않는다.

    각 지렛대를 **하나씩만** 움직이고 결정론 예측을 다시 돌린다. Monte Carlo를 다시
    돌리지 않는 이유는, 난수가 섞이면 「이 변수 때문에 바뀐 것」과 「표본이 달라서
    바뀐 것」을 가를 수 없기 때문이다.

    :returns: ``(항목 목록, 경고)``. 경고에 ``SENSITIVITY_ONE_AT_A_TIME``이 항상
        들어간다 — ``§12.8``이 「복합 효과 미포함」 안내를 요구한다.
    """
    levers: list[tuple[str, str, Sequence[RemainingVoyage]]] = [
        ("fuel", "-10%", _shift_fuel(remaining, 0.90)),
        ("fuel", "+10%", _shift_fuel(remaining, 1.10)),
        ("distance", "-5%", _shift_distance(remaining, 0.95)),
        ("distance", "+5%", _shift_distance(remaining, 1.05)),
        ("speed", "-1kn", _shift_speed(remaining, -1.0)),
        ("speed", "+1kn", _shift_speed(remaining, +1.0)),
    ]

    # `§12.6` 「잔여 항차 1개 취소/추가」 — 항차가 있을 때만 성립한다.
    if remaining:
        levers.append(("voyage_count", "-1", list(remaining[:-1])))
        levers.append(("voyage_count", "+1", [*remaining, remaining[-1]]))

    entries: list[SensitivityEntry] = []
    for variable, change, shifted in levers:
        try:
            projection = project_deterministic(
                completed=completed,
                remaining=shifted,
                transport_capacity=transport_capacity,
                required_cii=required_cii,
                d_vector=d_vector,
            )
        except ValueError:
            # 지렛대 하나가 거리를 0으로 만들면(항차 1건에서 -1) 그 줄만 건너뛴다 —
            # 나머지 민감도까지 함께 죽일 이유가 없다.
            continue
        entries.append(
            SensitivityEntry(
                variable=variable,
                change=change,
                attained_cii=projection.attained_cii,
                rating=projection.rating,
            )
        )

    return entries, [WARNING_SENSITIVITY_OAT]
