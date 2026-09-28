"""계산 엔진 벤치마크 (`#790` ⑶ · `#67`) — ``python -m cii_platform.calc.bench``.

`PRD §16.1`의 p95 목표 중 **엔진만 재는 셋**(`PERF-001` · `PERF-003` · `PERF-004`)의
워크로드와 측정 규칙을 이 모듈이 **한 벌만** 갖는다. `tests/test_benchmarks.py`가 CI에서
같은 함수를 불러 판정하고, 운영 서버(app-01)에서는 이 모듈을 직접 실행해 같은 계산을
그 기계에서 잰다.

## 왜 패키지 안에 두는가

운영 이미지는 wheel만 설치한다 — ``tests/``·``scripts/``·pytest가 없다
(``port_calls.collect``와 같은 이유). 그래서 Fixture 1의 입력값도 JSON을 읽지 않고
**이 모듈의 상수**로 둔다. 상수가 fixture 파일과 어긋나지 않는지는
`tests/test_benchmarks.py`의 `PERF-001`이 단언한다.

## `PERF-002`는 여기 없다

시나리오 비교는 서비스 경로라 **DB에 행을 쓴다**(시나리오 3행 + 계산 이력 1행 × 110회).
운영 DB에서 재면 그 행을 만들었다 지워야 하고, 계산 이력은 삭제 금지 트리거를 잠시
꺼야 지워진다 — 벤치마크를 위해 운영 DB의 불변 규칙을 푸는 일이 된다. 그래서 CI 판정만
남긴다. `PERF-005`(200척 선대 요약)도 같은 이유로 뺀다.

## 측정 조건

`TEST_PLAN §6` `[ORACLE-M-3]` 그대로다 — warm-up 10회 제외 · 100회 측정 · 측정 구간
``gc.disable()``. p95는 nearest-rank(정렬한 표본의 ``ceil(0.95 × n)``번째).

목표를 넘으면 종료 코드 1이다.
"""

from __future__ import annotations

import gc
import math
import os
import platform
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from cii_platform.calc.annual_simulation import (
    CompletedTotals,
    RemainingVoyage,
    project_deterministic,
    simulate_annual,
)
from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii, calculate_required_cii
from cii_platform.calc.rating_engine import DVector

# ── `TEST_PLAN §6` `[ORACLE-M-3]` 측정 조건 ──────────────────────────────────
WARMUP_RUNS = 10
MEASURED_RUNS = 100

# ── `PRD §16.1` p95 목표 (초) — 정본 값 그대로 ────────────────────────────────
P95_CII_CALCULATION = 1.0
P95_DETERMINISTIC = 1.0
P95_MONTE_CARLO_5000 = 3.0


def p95(samples: list[float]) -> float:
    """nearest-rank p95 — 정렬한 표본의 ``ceil(0.95 × n)``번째."""
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def measure(fn: Callable[[], object]) -> list[float]:
    """``fn``을 warm-up 뒤 100회 재고 표본(초)을 낸다. 측정 구간에서 GC를 멈춘다."""
    for _ in range(WARMUP_RUNS):
        fn()
    samples: list[float] = []
    gc.collect()
    gc.disable()
    try:
        for _ in range(MEASURED_RUNS):
            started = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - started)
    finally:
        gc.enable()
    return samples


# ── PERF-001 일반 CII 계산 — `PRD §13.1` Fixture 1 ────────────────────────────
#: `tests/fixtures/cii/bulk_50000_hfo_2026.json`의 입력 — 같은지는 테스트가 단언한다.
FIXTURE_1_FUEL_USES = (FuelUse("HFO", Decimal("80.0"), Decimal("3.114")),)
FIXTURE_1_TRANSPORT_CAPACITY = Decimal("50000")
FIXTURE_1_REFERENCE_CAPACITY = Decimal("50000")
FIXTURE_1_DISTANCE_NM = Decimal("1000")
#: `PRD §3.3.4` reference line — BULK_CARRIER · DWT < 279,000 · 2026 z=11 (Fixture 1 조건).
FIXTURE_1_A, FIXTURE_1_C, FIXTURE_1_Z = Decimal("4745"), Decimal("0.622"), Decimal("11")


def cii_calculation_workload():
    """PERF-001 — Fixture 1의 attained + required 계산."""
    attained = calculate_attained_cii(
        list(FIXTURE_1_FUEL_USES), FIXTURE_1_TRANSPORT_CAPACITY, FIXTURE_1_DISTANCE_NM
    )
    required = calculate_required_cii(
        FIXTURE_1_A, FIXTURE_1_C, FIXTURE_1_REFERENCE_CAPACITY, FIXTURE_1_Z
    )
    return attained, required


# ── PERF-003 · PERF-004 기능③ — 단일 선박 · 12개월 항차 ───────────────────────
_CF_HFO = 3.114
_CAPACITY = Decimal("50000")
_REQUIRED = Decimal("5.045066")
#: `PRD §3.3.6` d-vector (BULK_CARRIER).
_D_VECTOR = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))
_SEED = 12345

#: 상반기 6개월은 확정 실적, 하반기 6개월은 잔여 계획 — 「12개월 항차 데이터」.
_COMPLETED = CompletedTotals(co2_g=6 * 250 * _CF_HFO * 1e6, distance_nm=6 * 3000.0)
_REMAINING = [
    RemainingVoyage(
        distance_nm=3000.0,
        fuel_ton=250.0,
        cf=_CF_HFO,
        speed_kn=14.0,
        reference_speed_kn=14.0,
        base_daily_foc_ton=30.0,
    )
    for _ in range(6)
]


def deterministic_workload():
    """PERF-003 — 연간 결정론 계산."""
    return project_deterministic(
        completed=_COMPLETED,
        remaining=_REMAINING,
        transport_capacity=_CAPACITY,
        required_cii=_REQUIRED,
        d_vector=_D_VECTOR,
    )


def monte_carlo_workload():
    """PERF-004 — Monte Carlo 5,000회(`PRD §12.2` 기본값이자 `§16.1`이 목표를 정한 조건)."""
    return simulate_annual(
        completed=_COMPLETED,
        remaining=_REMAINING,
        transport_capacity=_CAPACITY,
        required_cii=_REQUIRED,
        d_vector=_D_VECTOR,
        target_rating="C",
        seed=_SEED,
        runs=5_000,
    )


@dataclass(frozen=True)
class Case:
    case_id: str
    name: str
    workload: Callable[[], object]
    target_s: float


CASES = (
    Case("PERF-001", "일반 CII 계산 (Fixture 1)", cii_calculation_workload, P95_CII_CALCULATION),
    Case("PERF-003", "연간 결정론 계산", deterministic_workload, P95_DETERMINISTIC),
    Case("PERF-004", "Monte Carlo 5,000회", monte_carlo_workload, P95_MONTE_CARLO_5000),
)


def main() -> int:
    print(f"파이썬 {platform.python_version()} · CPU {os.cpu_count()}개 · {platform.platform()}")
    print(f"측정 조건: warm-up {WARMUP_RUNS}회 제외 · {MEASURED_RUNS}회 측정 · gc.disable()")
    print()
    # 머리글은 ASCII로 둔다 — 한글은 폭이 두 칸이라 f-string 채움으로는 값 열과 줄이 어긋난다.
    print(f"{'case':<9} {'p50 ms':>10} {'p95 ms':>10} {'max ms':>10} {'target ms':>9}  판정  내용")
    failed = 0
    for case in CASES:
        samples = sorted(measure(case.workload))
        # p50도 p95와 같은 nearest-rank로 뽑는다. `samples`가 이미 정렬돼 있어
        # p95도 같은 목록에서 바로 읽는다.
        p50 = samples[math.ceil(0.5 * len(samples)) - 1]
        p95_s = samples[math.ceil(0.95 * len(samples)) - 1]
        passed = p95_s < case.target_s
        failed += not passed
        print(
            f"{case.case_id:<9} {p50 * 1000:>10.2f} "
            f"{p95_s * 1000:>10.2f} {samples[-1] * 1000:>10.2f} "
            f"{case.target_s * 1000:>9.0f}  {'통과' if passed else '초과'}  {case.name}"
        )
    # 운영 백엔드 컨테이너는 메모리 상한(512M)을 앱과 나눠 쓴다 — 이 실행이 얼마를 먹었는지 남긴다.
    # `resource`는 Unix 전용이라 여기서 늦게 부른다. 모듈 머리에 두면 Windows에서 이 모듈을
    # 부르는 `tests/test_benchmarks.py`가 수집 단계에서 멈추고 pytest 세션 전체가 중단된다.
    print()
    try:
        import resource
    except ImportError:
        print("이 프로세스의 최대 RSS — 이 플랫폼에서는 잴 수 없다(resource 없음)")
    else:
        peak_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"이 프로세스의 최대 RSS {peak_mib:.0f} MiB")
    print("결과: 전부 목표 이내" if not failed else f"결과: {failed}건 목표 초과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
