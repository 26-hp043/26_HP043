"""연간 시뮬레이션 실행 서비스 검증 (API_SPEC §6.1, #64).

계산은 ``#63``이 하고 그 테스트가 따로 있다. 여기서 보는 것은 **조립과 격리**다.

* **스냅샷 격리** — 실행 뒤 원본이 바뀌어도 스냅샷은 그대로여야 한다
  (``TECH_SPEC §11``). 이게 깨지면 재현성 계약이 성립하지 않는다.
* **`annual_inclusion_policy` 필터링** — ``status``로 다시 판정하지 않는다.
* **`parameters_used`에 분포가 실리는가** (``§5.2.1.1`` · `#434`) — 빠지면 분포가
  바뀐 뒤 같은 seed로 돌려도 결과가 달라지는데 해시는 같아진다.
* **재현성** — 같은 seed면 같은 결과.

케이스 (`TEST_PLAN §14.5`):
    IT-SNAP-001 · IT-SNAP-002 · IT-SNAP-003 · IT-SNAP-004
    AT-AS-001 · AT-AS-003 · AT-AS-004 · AT-AS-005
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import ValidationError
from cii_platform.services.annual_simulation import (
    _inputs_from_snapshot,
    run_annual_simulation,
)
from cii_platform.services.voyage_cii import DISCLAIMER

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


async def _add_plan_voyage(session, vessel_id, *, fuels: list[tuple[str, str, str]]):
    """계획 항차 1건 + 연료 행 N건 (#812).

    ``fuels``는 ``(fuel_type, planned_fuel_ton, cf_used)`` 목록이다. **빈 목록이면
    연료 행을 만들지 않는다** — `voyage_fuel_use`에 `idx_fuel_use_unique`가 있어
    연료 종류별 다중 행이 설계상 정상이고, 0건인 상태도 DB 차원에서는 가능하다.
    """
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "annual_inclusion_policy, regulation_year, created_from) "
            "VALUES (:id, :vid, 'PLANNED', 'Busan', 'Singapore', 3000, 14, "
            "'INCLUDE_AS_PLAN', 2026, 'MANUAL')"
        ),
        {"id": voyage_id, "vid": vessel_id},
    )
    for fuel_type, ton, cf in fuels:
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
                "cf_used, source) VALUES (:id, :ft, :ton, :cf, 'USER_INPUT')"
            ),
            {"id": voyage_id, "ft": fuel_type, "ton": Decimal(ton), "cf": Decimal(cf)},
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
        assert key in result["data"], key
    assert result["data"]["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@pytest.mark.asyncio
async def test_response_follows_the_calculation_envelope(session, vessel_id):
    """`API_SPEC §1.3.1` 계산 결과 응답 봉투 — 기능①·②와 **같은 최상위 키**다 (#752).

    종전에는 `data` 하나뿐이라 `disclaimer`·해시·`parameters_used`가 전부 빠져 있었다.
    그중 `disclaimer` 누락은 `PRD §0.3`(제품 내 모든 결과에 고지) 위반이다 — 화면이
    자체 상수로 그리고 있어 눈에 띄지 않았을 뿐, 리포트·외부 소비처가 생기면 그대로
    빠진다.

    **집합 동등으로 본다.** 부분집합 비교로 두면 나중에 필드가 하나 빠져도 통과한다.
    """
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")

    result = await _run(session, vessel_id)

    # `_duration_ms`는 라우트가 `meta.duration_ms`로 옮기고 응답에서 빼는 내부 키다.
    assert set(result) == {
        "data",
        "parameters_used",
        "calculation_run_id",
        "model_version",
        "input_hash",
        "parameter_hash",
        "warnings",
        "disclaimer",
        "_duration_ms",
    }

    # **`data` 밖으로 옮긴 두 개가 안에 남아 있지 않다** — 같은 값이 두 곳에 있으면
    # 어긋났을 때 어느 쪽이 정본인지 알 수 없다 (#752).
    assert "calculation_run_id" not in result["data"]
    assert "warnings" not in result["data"]

    assert result["disclaimer"] == DISCLAIMER
    assert result["input_hash"].startswith("sha256:")
    assert result["parameter_hash"].startswith("sha256:")
    # `#816`으로 정본 6필드가 됐다. 봉투가 그 값을 그대로 올리는지 본다.
    assert set(result["model_version"]) == {
        "engine",
        "decimal_precision",
        "decimal_rounding",
        "rng_algorithm",
        "numpy_version",
        "python_version",
    }
    # `TECH_SPEC §5.2.1.1` — 분포 프로파일이 응답에서 보여야 한다. 빠지면 분포가
    # 바뀐 뒤 같은 seed로 돌려도 결과가 달라지는데 그 사실이 드러날 자리가 없다.
    assert "simulation_profile" in result["parameters_used"]
    assert result["_duration_ms"] >= 1


@pytest.mark.asyncio
async def test_policy_decides_actual_versus_plan(session, vessel_id):
    """**`status`로 다시 판정하지 않는다** — 정본은 `annual_inclusion_policy`다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED")
    # EXCLUDE는 어느 쪽에도 들어가지 않는다.
    await _add_voyage(session, vessel_id, policy="EXCLUDE", status="DRAFT")

    result = await _run(session, vessel_id)

    assert result["data"]["deterministic"]["completed_voyage_count"] == 1
    assert result["data"]["deterministic"]["remaining_voyage_count"] == 1


@pytest.mark.asyncio
async def test_risk_comes_from_probability_not_margin(session, vessel_id):
    """`PRD §9.4.2` — 기능③ 위험도는 **목표 달성 확률** 기반이다.

    기능①·②의 마진 기반 함수를 쓰면 등급마다 `margin_ratio`를 요구해 500이 난다.
    """
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id)

    probability = Decimal(result["data"]["monte_carlo"]["target_success_probability"])
    expected = "LOW" if probability >= Decimal("0.8") else result["data"]["risk_level"]
    assert result["data"]["risk_level"] == expected


# ─────────────────────────────────────────────────────────────────────────────
# 스냅샷 격리 — TECH_SPEC §11
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_records_the_voyages_used(session, vessel_id):
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED")

    result = await _run(session, vessel_id)
    assert result["data"]["snapshot"]["voyage_count"] == 2

    stored = await session.scalar(
        text("SELECT jsonb_array_length(voyages_json) FROM simulation_snapshot WHERE id = :id"),
        {"id": result["data"]["snapshot"]["snapshot_id"]},
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
        {"id": result["data"]["snapshot"]["snapshot_id"]},
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
        {"id": result["data"]["snapshot"]["snapshot_id"]},
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
        first["data"]["monte_carlo"]["rating_probabilities"]
        == second["data"]["monte_carlo"]["rating_probabilities"]
    )
    assert first["data"]["monte_carlo"]["p50"] == second["data"]["monte_carlo"]["p50"]


@pytest.mark.asyncio
async def test_server_generates_a_seed_when_omitted(session, vessel_id):
    """`PRD §12.4.3` 자동 seed — 결과에 실어 「이 seed로 다시 실행」이 가능해야 한다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id, random_seed=None)

    # `TECH_SPEC §2.2.2` — seed는 128-bit hex 문자열로 실린다 (#751).
    entropy = result["data"]["monte_carlo"]["rng_metadata"]["seed_entropy"]
    assert isinstance(entropy, str)
    assert int(entropy, 16) > 0


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
    assert "복합 효과" in result["data"]["sensitivity_analysis"]["interaction_note"]


@pytest.mark.asyncio
async def test_no_remaining_plan_is_reported(session, vessel_id):
    """`AC-F3-004` — 확정 실적만으로 산출하되 그 사실을 알린다."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    result = await _run(session, vessel_id)
    assert "NO_REMAINING_VOYAGES" in result["warnings"]


# ─────────────────────────────────────────────────────────────────────────────
# 다중 연료 계획 항차 (#812)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fuel_type_count_does_not_change_the_result(session, vessel_id):
    """**연료 종류 수가 결과를 바꾸지 않는다** (#812) — 이 이슈의 완료 기준 1번.

    종전에는 계획 항차의 ``fuel_uses``마다 한 줄을 만들면서 **항차 전체 거리를 그대로
    복사**했다. 연료가 2종이면 그 항차 거리가 2배로 계상되어 분모만 커지고, 연말 예상
    CII가 1/N로 낮아져 **목표 달성 확률이 0%↔100%로 뒤집혔다.**

    총 연료·총 CO₂·거리가 같은 두 입력을 **연료 행 수만 다르게** 넣어 대조한다.
    HFO 150t(cf 3.114) 한 줄과, 같은 CO₂가 되도록 나눈 두 줄이다.
    """
    single = await _add_plan_voyage(session, vessel_id, fuels=[("HFO", "150", "3.114")])
    result_single = await _run(session, vessel_id)

    await session.execute(text("DELETE FROM voyage WHERE id = :id"), {"id": single})
    # 같은 CO₂: 100×3.114 + 50×3.114 = 150×3.114. 종류만 갈랐다.
    await _add_plan_voyage(
        session,
        vessel_id,
        fuels=[("HFO", "100", "3.114"), ("DIESEL_GAS_OIL", "50", "3.114")],
    )
    result_split = await _run(session, vessel_id)

    one = result_single["data"]["deterministic"]
    two = result_split["data"]["deterministic"]

    # **거리가 먼저다.** 이것이 어긋나면 아래 CII 비교는 원인을 가리지 못한다.
    assert two["planned_W_capacity_nm"] == one["planned_W_capacity_nm"], (
        "연료 행 수가 거리를 바꿨다 — 항차당 한 줄이 아니다 (#812)"
    )
    assert two["planned_M_gco2"] == one["planned_M_gco2"]
    assert two["projected_attained_cii"] == one["projected_attained_cii"]
    assert two["projected_rating"] == one["projected_rating"]
    assert two["remaining_voyage_count"] == one["remaining_voyage_count"] == 1


@pytest.mark.asyncio
async def test_mixed_fuels_keep_the_exact_co2_sum(session, vessel_id):
    """CF가 **다른** 연료를 섞어도 CO₂ 합이 정확하다 (#812).

    위 테스트는 같은 CF로 나눠 「거리」를 본다. 여기서는 CF가 다른 두 연료를 넣어
    **유효 CF로 합치는 계산 자체**를 본다 — 유효 CF가 틀리면 거리가 맞아도 배출이
    틀린다.

    HFO 100t(3.114) + DIESEL_GAS_OIL 50t(3.206) = 471.7 tCO₂ = 471,700,000 gCO₂.
    """
    await _add_plan_voyage(
        session,
        vessel_id,
        fuels=[("HFO", "100", "3.114"), ("DIESEL_GAS_OIL", "50", "3.206")],
    )

    result = await _run(session, vessel_id)

    planned_co2 = Decimal(result["data"]["deterministic"]["planned_M_gco2"])
    expected = (Decimal("100") * Decimal("3.114") + Decimal("50") * Decimal("3.206")) * Decimal(
        1_000_000
    )
    # 유효 CF가 float이라 마지막 자리에 표현 오차가 남는다. 상대오차로 본다 —
    # 절대 동등을 요구하면 float 표현 때문에 실패하고, 자릿수를 버리면 유효 CF가
    # 틀려도 통과한다.
    assert abs(planned_co2 - expected) / expected < Decimal("1e-12"), (
        f"유효 CF 합산이 연료별 합과 다르다: {planned_co2} vs {expected}"
    )


@pytest.mark.asyncio
async def test_plan_voyage_without_fuel_is_excluded_with_a_warning(session, vessel_id):
    """연료를 알 수 없는 계획 항차는 **빼되 조용히 빼지 않는다** (#812).

    거리만 넣는 대안은 「거리는 가는데 배출은 0」이라는 거짓 진술이 되어 분모만 키우고
    연말 예상 CII를 **실제보다 좋게** 만든다 — 이 이슈가 고치는 결함과 같은 방향이다.

    빼는 대신 경고를 남긴다. 응답의 ``remaining_voyage_count``는 스냅샷의 PLAN 행을
    세므로, 경고가 없으면 **「2건 중 1건만 계산했다」가 어디에도 드러나지 않는다.**
    """
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_plan_voyage(session, vessel_id, fuels=[("HFO", "150", "3.114")])
    await _add_plan_voyage(session, vessel_id, fuels=[])

    result = await _run(session, vessel_id)

    assert "SIMULATION_PLAN_NO_FUEL" in result["warnings"]
    # 항차 수는 스냅샷 기준이라 2건 그대로다 — 그래서 경고가 필요하다.
    assert result["data"]["deterministic"]["remaining_voyage_count"] == 2


@pytest.mark.asyncio
async def test_no_warning_when_every_plan_voyage_has_fuel(session, vessel_id):
    """경고가 **늘 붙지는 않는다** — 붙는 조건이 실제로 판정되는지 본다 (#812)."""
    await _add_voyage(session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED")
    await _add_plan_voyage(session, vessel_id, fuels=[("HFO", "150", "3.114")])

    result = await _run(session, vessel_id)

    assert "SIMULATION_PLAN_NO_FUEL" not in result["warnings"]


def test_remaining_rows_are_one_per_voyage():
    """``len(remaining)``이 **항차 수**다 (#812) — 두 가드가 같은 단위를 보게 하는 불변식.

    이 값 하나에 두 가지가 걸려 있다.

    * **가드 단위** — 서비스는 ``len(planned)``(항차)로, 엔진은 ``len(remaining)``으로
      상한을 본다(``calc/annual_simulation.py`` ``MAX_REMAINING_VOYAGES``). 둘이 다르면
      200항차 × 2연료 = 400줄에서 **엔진이 ValueError를 던지는데 서비스가 잡지 않는다.**
    * **민감도 ``voyage_count ±1``** — ``remaining[:-1]``이 연료 행 하나가 아니라
      **항차 하나**를 가감해야 `PRD §12.6`의 「잔여 항차 1개 취소/추가」가 된다.

    DB를 쓰지 않는다 — 조립 함수의 불변식이라 스냅샷 사본만 있으면 확인된다.
    """
    vessel = SimpleNamespace(
        ship_type="BULK_CARRIER",
        deadweight=Decimal("50000"),
        gross_tonnage=None,
        reference_speed_kn=Decimal("14"),
        reference_daily_foc_ton=Decimal("30"),
    )

    def plan(*fuels):
        return {
            "kind": "PLAN",
            "planned_distance_nm": "3000",
            "planned_speed_kn": "14",
            "fuel_uses": [{"planned_fuel_ton": ton, "cf_used": cf} for ton, cf in fuels],
        }

    rows = [
        plan(("100", "3.114")),  # 연료 1종
        plan(("100", "3.114"), ("50", "3.206")),  # 연료 2종
        plan(("40", "3.114"), ("30", "3.206"), ("30", "2.750")),  # 연료 3종
    ]

    _completed, remaining, warnings = _inputs_from_snapshot(rows, vessel)

    assert len(remaining) == 3, "연료 행 수가 아니라 항차 수여야 한다 (#812)"
    assert [v.distance_nm for v in remaining] == [3000.0, 3000.0, 3000.0]
    assert not warnings

    # 연료를 알 수 없는 항차는 빠지고 경고가 붙는다 — 줄 수도 함께 줄어든다.
    _c2, remaining2, warnings2 = _inputs_from_snapshot([*rows, plan()], vessel)

    assert len(remaining2) == 3
    assert warnings2 == ["SIMULATION_PLAN_NO_FUEL"]
