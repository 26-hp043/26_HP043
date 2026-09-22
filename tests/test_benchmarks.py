"""성능 벤치마크 (`TEST_PLAN §6` · `TECH_SPEC §13.2` · #67).

`PRD §16.1`의 p95 목표를 **CI의 pytest 잡 안에서** 검사한다. 별도 잡·별도 의존성
(`pytest-benchmark`)을 두지 않는다 — 목표(1초·3초·5초)와 실측(수 ms~수십 ms) 사이의
여유가 수십 배라, 도구가 주는 정밀도보다 **매 PR마다 돌아 회귀를 잡는 것**이 먼저다.

측정 조건은 `TEST_PLAN §6` `[ORACLE-M-3]` 그대로다 — **warm-up 10회 제외 · 100회 측정 ·
`gc.disable()`**. p95는 100개 표본을 정렬해 95번째 값이다(nearest-rank).

## 무엇을 재는가

계산 **엔진**을 잰다. HTTP·직렬화·인증은 대상이 아니다 — `PRD §16.1`의 항목이 「계산」
이고, 라우트 층 비용은 계산과 무관하게 변한다. 단 `PERF-002`(시나리오 3개 비교)는
서비스가 DB에서 규제값을 읽고 결과를 저장하는 것까지가 「비교」라 서비스를 잰다.

## 임계값은 정본 값 그대로다

`PRD §16.1` 표의 초 단위 값을 옮겨 적었다. 이 파일에서 완화하지 않는다 — 임계값을
코드에서 낮추면 정본이 요구하는 성능이 조용히 달라진다.

케이스: PERF-001 · PERF-002 · PERF-003 · PERF-004 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

import gc
import json
import math
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from fixture_loader import assert_layer1_equal
from sqlalchemy import bindparam, text

from cii_platform.calc.annual_simulation import (
    CompletedTotals,
    RemainingVoyage,
    project_deterministic,
    simulate_annual,
)
from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii, calculate_required_cii
from cii_platform.calc.rating_engine import DVector
from cii_platform.db.demo_seed import VESSEL_ID_BULK
from cii_platform.db.types import UuidText
from cii_platform.services.fleet_summary import get_fleet_summary
from cii_platform.services.scenario_compare import ScenarioCompareInput, compare_scenarios

# ── `TEST_PLAN §6` `[ORACLE-M-3]` 측정 조건 ──────────────────────────────────
WARMUP_RUNS = 10
MEASURED_RUNS = 100

# ── `PRD §16.1` p95 목표 (초) — 정본 값 그대로 ────────────────────────────────
P95_CII_CALCULATION = 1.0
P95_SCENARIO_COMPARE = 5.0
P95_DETERMINISTIC = 1.0
P95_MONTE_CARLO_5000 = 3.0
#: PERF-005 — 선대 상한(200척)에서 대시보드 한 번의 조회. `PRD §16.1` 「초기 페이지 로드」.
P95_FLEET_SUMMARY = 3.0
#: `PRD §5.1`이 정한 선대 상한. 이 규모에서 재는 것이 사무직의 하루와 맞다.
BENCH_FLEET_SIZE = 200

#: `PERF-002`가 만든 행을 되돌리는 문장 (`#1058`).
#:
#: 종전에는 `id = ANY(CAST(:ids AS uuid[]))`였다 — **PostgreSQL 배열**이다. CUBRID에는
#: `uuid[]`도 `ANY(배열)`도 없고, pycubrid는 목록을 한 파라미터로 보내지 못한다.
#:
#:     ProgrammingError: cannot bind a collection (list/tuple/set/frozenset/dict) as a
#:     single parameter; pycubrid does not auto-expand IN (?, ?, ...)
#:
#: `expanding=True`가 실행 시점에 `IN (?, ?, …)`로 펼치고, `UuidText`가 원소마다 저장
#: 형식(`CHAR(32)`)으로 바꾼다 — 대시 형식을 그대로 보내면 **오류 없이 0건**이 지워져
#: 정리가 안 된 채 통과한다(`test_seed_cf_matches_fuel_table`과 같은 자리).
#:
#: 이 자리는 **측정이 끝난 뒤의 `finally`**라 p95 판정에는 들어가지 않는다. 그래서
#: 실패 사유가 「성능 미달」로 보이지 않았다 — 실측 출력은 목표의 27분의 1이었다
#: (`PERF-002 p95=182.82 ms (목표 5000 ms)`).
_DELETE_SCENARIOS = text("DELETE FROM voyage_scenario WHERE id IN :ids").bindparams(
    bindparam("ids", expanding=True, type_=UuidText())
)
_DELETE_RUNS = text("DELETE FROM calculation_run WHERE id IN :ids").bindparams(
    bindparam("ids", expanding=True, type_=UuidText())
)

#: `PRD §13.1` Fixture 1 — 정본값 생성기의 산출물(`TEST_PLAN §1.7`).
_FIXTURE_1 = Path(__file__).parent / "fixtures" / "cii" / "bulk_50000_hfo_2026.json"


def _p95(samples: list[float]) -> float:
    """nearest-rank p95 — 정렬한 표본의 ``ceil(0.95 × n)``번째."""
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _measure(fn: Callable[[], object]) -> float:
    """``fn``을 warm-up 뒤 100회 재고 p95(초)를 낸다. 측정 구간에서 GC를 멈춘다."""
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
    return _p95(samples)


async def _measure_async(fn: Callable[[], Awaitable[object]]) -> float:
    """비동기 판 — ``await`` 왕복까지 측정에 넣는다."""
    for _ in range(WARMUP_RUNS):
        await fn()
    samples: list[float] = []
    gc.collect()
    gc.disable()
    try:
        for _ in range(MEASURED_RUNS):
            started = time.perf_counter()
            await fn()
            samples.append(time.perf_counter() - started)
    finally:
        gc.enable()
    return _p95(samples)


# ── PERF-001 일반 CII 계산 ────────────────────────────────────────────────────


def test_cii_calculation_p95(capsys):
    """PERF-001 — Fixture 1 기반 attained + required 계산이 p95 < 1초.

    워크로드가 **실제 Fixture 1**인지를 먼저 단언한다 — 값이 어긋나면 벤치마크가
    다른 계산을 재고 있는 것이다.
    """
    fixture = json.loads(_FIXTURE_1.read_text(encoding="utf-8"))
    inp, expected = fixture["input"], fixture["expected"]
    fuel_uses = [
        FuelUse(f["fuel_type"], Decimal(str(f["fuel_ton"])), Decimal(str(f["cf"])))
        for f in inp["fuel_uses"]
    ]
    capacity = Decimal(expected["transport_capacity"])
    distance = Decimal(str(inp["distance_nm"]))
    # `PRD §3.3.4` reference line — BULK_CARRIER · DWT < 279,000 · 2026 z=11 (Fixture 1 조건).
    a, c, z = Decimal("4745"), Decimal("0.622"), Decimal("11")

    def workload():
        attained = calculate_attained_cii(fuel_uses, capacity, distance)
        required = calculate_required_cii(a, c, Decimal(expected["reference_capacity"]), z)
        return attained, required

    attained, required = workload()
    # 정본값 30자리와 작업 정밀도 원값의 비교 — `TEST_PLAN §9.1` 규칙(`fixture_loader`).
    assert_layer1_equal(str(attained.attained_cii), expected["attained_cii"])
    assert_layer1_equal(str(required.required_cii), expected["required_cii"])

    p95 = _measure(workload)
    print(f"PERF-001 p95={p95 * 1000:.2f} ms (목표 {P95_CII_CALCULATION * 1000:.0f} ms)")
    assert p95 < P95_CII_CALCULATION


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


def test_deterministic_projection_p95(capsys):
    """PERF-003 — 연간 결정론 계산이 p95 < 1초."""

    def workload():
        return project_deterministic(
            completed=_COMPLETED,
            remaining=_REMAINING,
            transport_capacity=_CAPACITY,
            required_cii=_REQUIRED,
            d_vector=_D_VECTOR,
        )

    p95 = _measure(workload)
    print(f"PERF-003 p95={p95 * 1000:.2f} ms (목표 {P95_DETERMINISTIC * 1000:.0f} ms)")
    assert p95 < P95_DETERMINISTIC


def test_monte_carlo_5000_p95(capsys):
    """PERF-004 — Monte Carlo 5,000회가 p95 < 3초.

    ``runs=5_000``은 `PRD §12.2` 기본값이자 `§16.1`이 목표를 정한 조건이다 — 화면
    체감치(`#67` 08-29 코멘트)는 1,000회 기준이라 이 조건을 잰 적이 없었다.
    """

    def workload():
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

    assert workload().runs == 5_000
    p95 = _measure(workload)
    print(f"PERF-004 p95={p95 * 1000:.2f} ms (목표 {P95_MONTE_CARLO_5000 * 1000:.0f} ms)")
    assert p95 < P95_MONTE_CARLO_5000


# ── PERF-002 기능② 시나리오 3개 비교 ─────────────────────────────────────────


async def test_scenario_compare_p95(migrated_db, app_fresh_engine, capsys):
    """PERF-002 — 샘플 선박 3개 시나리오 비교가 p95 < 5초.

    서비스 경로(규제값 조회 → 계산 → `voyage_scenario` 3행 + `calculation_run` 1행
    저장)를 잰다. 기상은 `NONE`이다 — 외부 조회는 이 목표의 대상이 아니고 CI가
    네트워크를 쓰지 않는다.

    **「캐시 사용 시 < 2초」는 재지 않는다.** 시나리오 비교에는 캐시 층이 없다 —
    `PRD §16.1`의 그 조건은 기상 캐시(`TECH_SPEC §7.3`)를 뜻하는데 여기서는 기상을
    쓰지 않아 성립할 자리가 없다. 있는 척 재면 없는 층을 검증한 것이 된다.

    110회가 남긴 행(시나리오 330 · 계산 이력 110)은 id로 모아 지운다 —
    `calculation_run`은 immutable 트리거를 잠시 끈다(`test_scenario_compare_db.py`와
    같은 패턴).
    """
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    payload = ScenarioCompareInput(
        vessel_id=UUID(VESSEL_ID_BULK),
        regulation_year=2026,
        current_speed_kn=Decimal("14.0"),
        fuel_type="HFO",
        base_daily_foc_ton=Decimal("35.0"),
        direct_distance_nm=Decimal("11000.0"),
        weather_model="NONE",
    )
    scenario_ids: list[str] = []
    run_ids: list[str] = []
    deleted: dict[str, int] = {}

    async def workload():
        async with sessionmaker() as session:
            result = await compare_scenarios(session, payload)
        data = result["data"]
        scenario_ids.extend(s["scenario_id"] for s in data["scenarios"])
        run_ids.append(result["calculation_run_id"])
        return result

    try:
        first = await workload()
        assert [s["scenario_type"] for s in first["data"]["scenarios"]] == [
            "DIRECT",
            "DETOUR",
            "SLOW_STEAMING",
        ]
        p95 = await _measure_async(workload)
        print(f"PERF-002 p95={p95 * 1000:.2f} ms (목표 {P95_SCENARIO_COMPARE * 1000:.0f} ms)")
        assert p95 < P95_SCENARIO_COMPARE
    finally:
        async with sessionmaker() as session:
            scenarios = await session.execute(_DELETE_SCENARIOS, {"ids": scenario_ids})
            await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS INACTIVE"))
            runs = await session.execute(_DELETE_RUNS, {"ids": run_ids})
            await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS ACTIVE"))
            await session.commit()
            deleted["scenarios"] = scenarios.rowcount
            deleted["runs"] = runs.rowcount

    # 정리가 **실제로 지웠는지** 본다. `finally` 밖이라 위에서 이미 실패했으면 여기까지
    # 오지 않는다 — 측정 실패를 정리 실패로 덮지 않는다.
    #
    # 왜 세는가 — 지우지 못해도 `DELETE`는 오류를 내지 않는다. `UuidText`를 빼면 대시
    # 형식이 그대로 나가 **0건이 지워진 채 통과**하고, 이 표에 행이 쌓여 뒤따르는 검사의
    # 수치를 흔든다. 그 구멍을 이 두 줄이 막는다(`#1058`).
    assert deleted["scenarios"] == len(scenario_ids), (
        f"시나리오 {len(scenario_ids)}건 중 {deleted['scenarios']}건만 지워졌다"
    )
    assert deleted["runs"] == len(run_ids), (
        f"계산 실행 {len(run_ids)}건 중 {deleted['runs']}건만 지워졌다"
    )


# ── PERF-005 대시보드 선대 요약 (200척) ──────────────────────────────────────

#: 벤치마크 전용 선박 — 데모 시드와 겹치지 않는 IMO 대역(`98xxxxx`)을 쓴다.
_BENCH_IMO_PREFIX = "98"

_INSERT_BENCH_VESSEL = text(
    "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
    "default_fuel_type, reference_speed_kn, reference_daily_foc_ton) "
    "VALUES (:id, :imo, :name, 'BULK_CARRIER', 50000, 'HFO', 14, 30)"
).bindparams(bindparam("id", type_=UuidText()))

_DELETE_BENCH_VESSELS = text("DELETE FROM vessel WHERE imo_number LIKE :prefix")


async def test_fleet_summary_200_vessels_p95(migrated_db, app_fresh_engine, capsys):
    """PERF-005 — 200척 선대의 대시보드 요약이 p95 < 3초.

    ## 왜 이 자리를 재는가

    `PRD §16.1`의 성능 목표 다섯 중 **초기 페이지 로드만** CI가 판정하지 않고 있었다
    (`#1617`). 나머지 넷은 매 PR마다 여기서 돌고, 하필 판정 밖에 있던 한 행이
    **사용자가 가장 먼저 보는 화면**이다.

    구조 가드(`IT-CACHE-005`)는 N+1 회귀 하나만 잡는다. **척당 계산 비용이 늘어나는
    회귀** — 선박마다 도는 집계가 무거워지는 종류 — 는 시간으로만 드러난다.

    ## 200척인 이유

    `PRD §5.1`이 정한 선대 상한이다. 시연 시드(5척)에서 재면 상한에서 무엇이 되는지
    알 수 없고, 상한을 넘겨 재면 제품이 약속하지 않은 규모를 지키게 된다.

    ## 브라우저는 재지 않는다

    여기서 재는 것은 **서버 응답**이다. 번들 로드·렌더는 이 검사의 대상이 아니며
    그 사실을 `PRD §16.1` 각주가 적는다 — 재지 않는 것을 잰 척하지 않는다.

    ## 뒷정리

    벤치마크 선박은 IMO 대역으로 모아 지운다. 남기면 뒤따르는 검사의 선대 수치가
    흔들린다(`PERF-002`가 시나리오·계산 이력을 지우는 것과 같은 이유).
    """
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    seeded = 0

    async def summary():
        async with sessionmaker() as session:
            return await get_fleet_summary(session, regulation_year=2026, limit=20)

    try:
        async with sessionmaker() as session:
            for index in range(BENCH_FLEET_SIZE):
                await session.execute(
                    _INSERT_BENCH_VESSEL,
                    {
                        "id": uuid4(),
                        "imo": f"{_BENCH_IMO_PREFIX}{index:05d}",
                        "name": f"BENCH {index:03d}",
                    },
                )
            await session.commit()
            seeded = BENCH_FLEET_SIZE

        first = await summary()
        # 200척이 실제로 집계에 들어갔는지 — 빈 선대를 빠르게 재고 통과하지 않는다.
        assert first["summary"]["total"] >= BENCH_FLEET_SIZE

        p95 = await _measure_async(summary)
        print(f"PERF-005 p95={p95 * 1000:.2f} ms (목표 {P95_FLEET_SUMMARY * 1000:.0f} ms)")
        assert p95 < P95_FLEET_SUMMARY
    finally:
        async with sessionmaker() as session:
            removed = await session.execute(
                _DELETE_BENCH_VESSELS, {"prefix": f"{_BENCH_IMO_PREFIX}%"}
            )
            await session.commit()
            deleted = removed.rowcount

    # 정리가 **실제로 지웠는지** 본다 (`PERF-002`와 같은 이유 · `#1058`).
    assert deleted == seeded, f"벤치마크 선박 {seeded}척 중 {deleted}척만 지워졌다"
