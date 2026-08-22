"""연간 시뮬레이션 조회·재실행 (API_SPEC §6.2~§6.4, #443).

**스냅샷을 남기는 이유가 여기에 있다.** `TECH_SPEC §11.1`이 격리를 요구한 것은
「몇 달 뒤에도 그때 무슨 데이터로 돌렸나」에 답하기 위해서인데(`§5.4` 재현성 계약),
꺼내 볼 경로가 없으면 남긴 것이 쓰이지 않는다.

세 가지를 본다.

1. **조회는 다시 계산하지 않는다** — 규정 파라미터가 바뀐 뒤 조회해도 그때의 값이
   그대로 나와야 한다. 다시 계산하면 「조회했을 뿐인데 값이 달라지는」 상태가 된다.
2. **스냅샷 항차는 그때의 상태를 보인다** — 원본이 수정돼도 따라 바뀌지 않는다.
3. **재실행은 같은 결과를 낸다** — 다르면 파라미터 변경(409)인지 재현성 실패(500)인지
   갈라서 알린다.

케이스 (`TEST_PLAN §14.5`):
    IT-SNAP-003 · IT-SNAP-004
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, ParameterError, ReproducibilityError
from cii_platform.services.annual_simulation import (
    _assert_same_outcome,
    get_annual_simulation,
    list_snapshot_voyages,
    reproduce_annual_simulation,
    run_annual_simulation,
)

YEAR = 2026


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    """이 선종·연도의 규정 파라미터. 이미 있으면 넣지 않는다(세션 seed와 공존)."""
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
            "VALUES (:id, :imo, 'READ TEST', 'BULK_CARRIER', 50000, 'HFO', 14, 30)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


async def _add_voyage(session, vessel_id, *, policy: str, status: str, no: str) -> UUID:
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, voyage_no, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_distance_nm, annual_inclusion_policy, regulation_year, created_from) "
            "VALUES (:id, :vid, :no, :status, 'Busan', 'Singapore', 3000, 14, "
            ":actual, :policy, 2026, 'MANUAL')"
        ),
        {
            "id": voyage_id,
            "vid": vessel_id,
            "no": no,
            "status": status,
            "policy": policy,
            "actual": Decimal("3100") if policy == "INCLUDE_AS_ACTUAL" else None,
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "actual_fuel_ton, cf_used, source) VALUES (:id, 'HFO', 250, :actual, "
            "3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id, "actual": Decimal("260") if policy == "INCLUDE_AS_ACTUAL" else None},
    )
    return voyage_id


@pytest_asyncio.fixture
async def executed(session, vessel_id):
    """항차 2건(확정 1 · 계획 1)으로 한 번 실행해 둔다."""
    await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED", no="V-2026-001"
    )
    await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="V-2026-002"
    )
    return await run_annual_simulation(
        session,
        vessel_id=vessel_id,
        regulation_year=YEAR,
        target_rating="C",
        simulation_runs=1000,
        random_seed=12345,
    )


# ─────────────────────────────────────────────────────────────────────────────
# §6.2 결과 조회
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_exactly_the_run_response(session, executed):
    """**이 엔드포인트의 계약**이다 — `API_SPEC §6.2` 「§6.1의 응답과 동일」.

    키 일부가 아니라 **전체가 같은지** 본다. 부분 비교로 두면 나중에 블록이 추가될 때
    조회 응답에만 빠져도 통과한다.
    """
    fetched = await get_annual_simulation(session, UUID(executed["simulation_id"]))

    assert fetched == executed


@pytest.mark.asyncio
async def test_get_does_not_recalculate(session, executed):
    """규정 파라미터가 바뀐 뒤 조회해도 **그때의 값**이 나온다.

    조회가 계산을 다시 하면 「조회했을 뿐인데 값이 달라지는」 상태가 된다 — 재현성
    계약(`TECH_SPEC §5.4`)이 지키려는 것이 정확히 그것이다.
    """
    await session.execute(
        text("UPDATE regulation_year SET z_factor_percent = 25 WHERE year = 2026")
    )

    fetched = await get_annual_simulation(session, UUID(executed["simulation_id"]))

    assert fetched["deterministic"] == executed["deterministic"]
    assert (
        fetched["monte_carlo"]["rating_probabilities"]
        == (executed["monte_carlo"]["rating_probabilities"])
    )


@pytest.mark.asyncio
async def test_get_unknown_id_is_not_found(session):
    with pytest.raises(NotFoundError):
        await get_annual_simulation(session, uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# §6.3 스냅샷 항차
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_voyages_carry_the_contract_fields(session, executed):
    """`API_SPEC §6.3` 응답 필드가 모두 채워진다."""
    rows = await list_snapshot_voyages(session, UUID(executed["simulation_id"]))

    assert len(rows) == executed["snapshot"]["voyage_count"]
    for row in rows:
        assert row["snapshot_voyage_id"]
        assert row["original_voyage_id"]
        assert row["status_at_snapshot"] in {"CONFIRMED", "PLANNED"}
        assert row["annual_inclusion_policy"] in {"INCLUDE_AS_ACTUAL", "INCLUDE_AS_PLAN"}
        assert row["distance_nm"] > 0
        assert row["fuel_uses"]
        # CF는 그때 쓴 값이다 (#378).
        assert row["fuel_uses"][0]["cf_used"] == pytest.approx(3.114)


@pytest.mark.asyncio
async def test_snapshot_voyages_show_actuals_where_they_exist(session, executed):
    """확정 항차는 **실적**, 계획 항차는 **계획**을 보인다 (`PRD §8.3` 우선순위).

    스냅샷에는 두 벌이 다 들어 있으므로, 어느 쪽을 보이는지가 계산과 어긋나면 화면이
    「계산에 쓰이지 않은 값」을 근거로 제시하게 된다.
    """
    rows = await list_snapshot_voyages(session, UUID(executed["simulation_id"]))
    by_policy = {row["annual_inclusion_policy"]: row for row in rows}

    assert by_policy["INCLUDE_AS_ACTUAL"]["distance_nm"] == pytest.approx(3100.0)
    assert by_policy["INCLUDE_AS_ACTUAL"]["fuel_uses"][0]["fuel_ton"] == pytest.approx(260.0)
    assert by_policy["INCLUDE_AS_PLAN"]["distance_nm"] == pytest.approx(3000.0)
    assert by_policy["INCLUDE_AS_PLAN"]["fuel_uses"][0]["fuel_ton"] == pytest.approx(250.0)


@pytest.mark.asyncio
async def test_snapshot_voyages_do_not_follow_later_edits(session, executed, vessel_id):
    """원본을 고쳐도 스냅샷 조회 결과는 그대로다 (`TECH_SPEC §11.4`).

    격리는 이미 `#64` 테스트가 DB 수준에서 확인한다. 여기서 다시 보는 것은 **조회
    경로가 원본을 읽지 않는가**다 — 스냅샷을 저장해 두고 조회에서 원본을 읽으면
    격리는 지켜졌는데 사용자에게는 깨져 보인다.
    """
    before = await list_snapshot_voyages(session, UUID(executed["simulation_id"]))

    await session.execute(
        text("UPDATE voyage SET actual_distance_nm = 9999 WHERE vessel_id = :vid"),
        {"vid": vessel_id},
    )

    after = await list_snapshot_voyages(session, UUID(executed["simulation_id"]))
    assert after == before


@pytest.mark.asyncio
async def test_snapshot_voyages_unknown_id_is_not_found(session):
    with pytest.raises(NotFoundError):
        await list_snapshot_voyages(session, uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# §6.4 재실행
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reproduce_returns_the_same_result(session, executed):
    """IT-SNAP-004 — 같은 seed·같은 스냅샷이면 결과가 같다."""
    again = await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))

    assert (
        again["monte_carlo"]["rating_probabilities"]
        == (executed["monte_carlo"]["rating_probabilities"])
    )
    assert again["deterministic"] == executed["deterministic"]
    assert again["sensitivity_analysis"] == executed["sensitivity_analysis"]


@pytest.mark.asyncio
async def test_reproduce_ignores_later_voyage_edits(session, executed, vessel_id):
    """원본 항차가 바뀌어도 재현은 **스냅샷**으로 한다 (`TECH_SPEC §11.4` 2항).

    원본을 다시 읽으면 그 사이의 편집이 섞여 「재현 실패」가 되는데, 그것은 재현성
    계약이 깨진 것이 아니라 **다른 입력으로 돌린 것**이다.
    """
    await session.execute(
        text("UPDATE voyage SET planned_distance_nm = 12000 WHERE vessel_id = :vid"),
        {"vid": vessel_id},
    )

    again = await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))

    assert again["deterministic"] == executed["deterministic"]


@pytest.mark.asyncio
async def test_reproduce_keeps_the_original_identifiers(session, executed):
    """응답의 식별자는 **원본의 것**이다 — 「원본을 다시 돌려 확인했다」는 뜻이다."""
    again = await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))

    assert again["simulation_id"] == executed["simulation_id"]
    assert again["calculation_run_id"] == executed["calculation_run_id"]
    assert again["snapshot"] == executed["snapshot"]


@pytest.mark.asyncio
async def test_reproduce_does_not_record_a_new_run(session, executed, vessel_id):
    """검증이지 실행이 아니다 — 이력이 늘면 무엇이 원본인지 흐려진다."""
    before = await _count_runs(session, vessel_id)

    await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))

    assert await _count_runs(session, vessel_id) == before


@pytest.mark.asyncio
async def test_reproduce_refuses_when_parameters_changed(session, executed):
    """`API_SPEC §6.4` 오류 표 — 409 `PARAMETER_ERROR`.

    **설명 가능한 변화와 재현성 실패를 갈라야 한다.** 파라미터가 바뀌어 값이 달라진
    것은 정상이며, 사용자가 할 일은 「새로 실행」이다.
    """
    await session.execute(
        text("UPDATE regulation_year SET z_factor_percent = 25 WHERE year = 2026")
    )

    with pytest.raises(ParameterError):
        await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))


@pytest.mark.asyncio
async def test_reproduce_unknown_id_is_not_found(session):
    with pytest.raises(NotFoundError):
        await reproduce_annual_simulation(session, uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# 재현 판정 규칙 (DB 없이)
# ─────────────────────────────────────────────────────────────────────────────


def _outcome(*, probabilities: dict, success: str = "0.8", p50: str = "5.0", rating: str = "C"):
    return {
        "monte_carlo": {
            "rating_probabilities": probabilities,
            "target_success_probability": success,
            "p50": p50,
            # 환경 정보 — 비교 대상이 아니다.
            "rng_metadata": {"numpy_version": "0.0.0", "platform": "test"},
        },
        "deterministic": {"projected_rating": rating},
    }


def test_reproduction_check_ignores_environment_metadata():
    """`numpy_version`·`platform`이 달라도 재현 실패가 아니다.

    이 값들은 **환경이 달라지면 당연히 달라진다**(`NEP 19`). 전체를 비교하면 다른
    머신에서 돌렸다는 이유만으로 500이 난다 — 그 500은 아무 문제도 알리지 않는다.
    """
    stored = _outcome(probabilities={"C": "0.7"})
    reproduced = _outcome(probabilities={"C": "0.7"})
    reproduced["monte_carlo"]["rng_metadata"] = {"numpy_version": "9.9.9", "platform": "other"}

    _assert_same_outcome(stored, reproduced)  # 예외가 나지 않아야 한다


def test_reproduction_check_catches_probability_drift():
    stored = _outcome(probabilities={"C": "0.7"})
    reproduced = _outcome(probabilities={"C": "0.6999"})

    with pytest.raises(ReproducibilityError):
        _assert_same_outcome(stored, reproduced)


def test_reproduction_check_catches_rating_drift():
    stored = _outcome(probabilities={"C": "0.7"}, rating="C")
    reproduced = _outcome(probabilities={"C": "0.7"}, rating="D")

    with pytest.raises(ReproducibilityError):
        _assert_same_outcome(stored, reproduced)


async def _count_runs(session, vessel_id) -> int:
    result = await session.execute(
        text("SELECT count(*) FROM annual_simulation_run WHERE vessel_id = :vid"),
        {"vid": vessel_id},
    )
    return int(result.scalar_one())


def test_error_codes_match_the_spec_status_table():
    """`API_SPEC §6.4` 오류 표 — 409 `PARAMETER_ERROR` · 500 `REPRODUCIBILITY_ERROR`.

    서비스가 올바른 예외를 던져도 **상태 코드 매핑이 없으면 500으로 뭉개진다.**
    두 실패는 사용자가 할 일이 다르므로(새로 실행 vs 관리자 문의) 코드가 갈려야 한다.
    """
    from cii_platform.errors import ERROR_HTTP_STATUS

    assert ERROR_HTTP_STATUS[ParameterError("x").code] == 409
    assert ERROR_HTTP_STATUS[ReproducibilityError("x").code] == 500
    assert ParameterError("x").code != ReproducibilityError("x").code


def test_the_three_routes_are_registered():
    """서비스가 있어도 **라우트를 잊으면 아무도 부를 수 없다.**

    `#443`이 고치는 상태가 정확히 그것이었다 — 명세에 있고 구현이 없었다. 서비스만
    테스트하면 같은 상태를 다시 만들어도 초록으로 보인다.

    OpenAPI 문서로 확인하는 이유는 `test_auth_failure_paths`와 같다: FastAPI의 지연
    라우터 등록 때문에 `app.routes` 나열은 믿을 수 없다.
    """
    from cii_platform.api.main import app

    paths = app.openapi()["paths"]
    assert "get" in paths["/api/v1/annual-simulations/{simulation_run_id}"]
    assert "get" in paths["/api/v1/annual-simulations/{simulation_run_id}/snapshot-voyages"]
    assert "post" in paths["/api/v1/annual-simulations/{simulation_run_id}/reproduce"]


# ─────────────────────────────────────────────────────────────────────────────
# §6.4 — 선박 제원 스냅샷 (#493)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_records_the_vessel_specs(session, executed):
    """스냅샷이 **계산이 읽는 제원 전부**를 담는다.

    `#493` 본문은 `reference_speed_kn`·`reference_daily_foc_ton` 둘을 들었으나
    `_recompute`가 capacity도 살아 있는 행에서 읽는다 — 그 셋이 **CII 분모**를
    바꾸므로 영향이 앞의 둘보다 크다.
    """
    from cii_platform.services.annual_simulation import VESSEL_SNAPSHOT_FIELDS

    stored = (
        await session.execute(
            text(
                "SELECT s.vessel_json FROM simulation_snapshot s "
                "JOIN annual_simulation_run r ON r.snapshot_id = s.id WHERE r.id = :id"
            ),
            {"id": UUID(executed["simulation_id"])},
        )
    ).scalar_one()

    assert set(stored) == set(VESSEL_SNAPSHOT_FIELDS)
    # 수치는 **문자열**이다 — float으로 거치면 `NUMERIC` 원본과 다른 값이 보관된다.
    assert stored["deadweight"] == "50000.00"
    assert stored["reference_speed_kn"] == "14.00"
    assert stored["ship_type"] == "BULK_CARRIER"


@pytest.mark.asyncio
async def test_reproduce_ignores_later_spec_removal(session, executed, vessel_id):
    """제원을 **비우면** 민감도 속도 지렛대가 꺼진다 — 재현이 그것을 따라가면 안 된다.

    ⚠️ **`#493` 본문의 전제를 정정한다.** 본문은 *「`PRD §12.4`의 속도–연료 관계가 이
    값으로 표본을 흔든다」*고 적었으나, 실측하면 `reference_speed_kn`·
    `base_daily_foc_ton`은 `calc/annual_simulation.py`에서 **산술에 한 번도 쓰이지
    않는다** — `_has_speed_model()`의 **존재 여부 게이트**일 뿐이다. `14 → 9`로 바꿔도
    결과가 같아, 그 형태로 쓴 테스트는 결함 상태에서도 통과한다(실제로 확인했다).

    두 값의 재현성 위험은 **NULL ↔ 비NULL 뒤집힘**이다. 그 상태를 만든다.
    """
    await session.execute(
        text("UPDATE vessel SET reference_daily_foc_ton = NULL WHERE id = :id"),
        {"id": vessel_id},
    )

    again = await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))

    assert again == executed


@pytest.mark.asyncio
async def test_reproduce_ignores_later_capacity_edits(session, executed, vessel_id):
    """DWT를 고쳐도 재현이 흔들리지 않는다.

    `#493` 본문이 들지 않은 경로다. capacity는 **CII 분모**라 값이 크게 달라진다 —
    제원 둘만 스냅샷했다면 이 테스트가 실패한다.
    """
    await session.execute(
        text("UPDATE vessel SET deadweight = 12345 WHERE id = :id"), {"id": vessel_id}
    )

    again = await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))

    assert again == executed


@pytest.mark.asyncio
async def test_reproduce_ignores_later_ship_type_edits(session, executed, vessel_id):
    """선종을 고쳐도 **틀린 사유로 끊지 않는다.**

    종전에는 살아 있는 선박으로 reference line을 다시 골라 `parameters_used`가
    달라졌고, **409 「규정 파라미터가 변경되어…」**가 났다. 실제 원인은 규정이 아니라
    선종 수정이다 — 이 이슈가 지적한 것과 같은 종류의 오진이 하나 더 있었다.
    """
    await session.execute(
        text("UPDATE vessel SET ship_type = 'TANKER' WHERE id = :id"), {"id": vessel_id}
    )

    again = await reproduce_annual_simulation(session, UUID(executed["simulation_id"]))

    assert again == executed


@pytest.mark.asyncio
async def test_reproduce_refuses_runs_made_before_the_spec_snapshot(session, executed):
    """`037` 이전 실행은 **사유를 밝히고 끊는다.**

    스냅샷 테이블은 immutable이라 그 행에 제원을 넣을 수 없다. 조용히 살아 있는
    제원으로 넘어가면 「같은 스냅샷으로 다시 돌렸다」가 거짓이 되고, 이 이슈가 보고한
    증상이 그대로 남는다.

    (immutable 트리거 때문에 UPDATE로 만들 수 없어 **행을 새로 넣어** 그 상태를
    재현한다.)
    """
    simulation_id = UUID(executed["simulation_id"])
    legacy_snapshot = uuid4()
    await session.execute(
        text(
            "INSERT INTO simulation_snapshot "
            "(id, vessel_id, regulation_year, voyages_json, vessel_json, "
            " input_hash, parameter_hash) "
            "SELECT :new_id, s.vessel_id, s.regulation_year, s.voyages_json, NULL, "
            " s.input_hash, s.parameter_hash "
            "FROM simulation_snapshot s "
            "JOIN annual_simulation_run r ON r.snapshot_id = s.id WHERE r.id = :id"
        ),
        {"new_id": legacy_snapshot, "id": simulation_id},
    )
    await session.execute(
        text("UPDATE annual_simulation_run SET snapshot_id = :snap WHERE id = :id"),
        {"snap": legacy_snapshot, "id": simulation_id},
    )

    with pytest.raises(NotFoundError) as exc:
        await reproduce_annual_simulation(session, simulation_id)

    assert "#493" in str(exc.value)
    # 「관리자에게 문의」가 아니라 **다시 실행하라**고 말한다 — 사용자가 할 수 있는 일이다.
    assert "다시 실행" in str(exc.value)


@pytest.mark.asyncio
async def test_input_hash_covers_the_vessel_specs(session, vessel_id):
    """제원이 다르면 `input_hash`도 달라야 한다.

    해시가 덮지 않으면 「스냅샷은 immutable인데 해시가 다르다」 검사가 **제원 변화를
    보지 못한다** — 이 이슈가 보고한 상태가 정확히 그것이다.
    """
    from cii_platform.services.annual_simulation import _input_hash

    common = {
        "vessel_id": vessel_id,
        "regulation_year": YEAR,
        "target_rating": "C",
        "runs": 1000,
        "seed": 12345,
        "voyages_json": [{"kind": "PLANNED"}],
    }
    base = _input_hash(**common, vessel_json={"deadweight": "50000.00"})
    changed = _input_hash(**common, vessel_json={"deadweight": "12345.00"})

    assert base != changed
