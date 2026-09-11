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

from cii_platform.calc.hash import compute_parameter_hash
from cii_platform.errors import (
    ModelVersionMismatchError,
    NotFoundError,
    ParameterError,
    ReproducibilityError,
)
from cii_platform.services import annual_simulation as annual_simulation_service
from cii_platform.services.annual_simulation import (
    PARAMETERS_SCHEMA_V1,
    WARNING_MODEL_VERSION_DIFFERS,
    _assert_same_outcome,
    _model_version_diff,
    build_parameters_used,
    get_annual_simulation,
    list_snapshot_voyages,
    parameters_schema_version,
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


def _without_duration(envelope: dict) -> dict:
    """``_duration_ms``만 뺀 응답 (#752).

    **두 실행의 계산 시간은 당연히 다르다.** 그 하나 때문에 응답 전체 비교를 포기하고
    ``data``만 보면, 해시·``parameters_used``·``model_version``이 어긋나도 통과한다 —
    재현 판정이 봐야 하는 것이 정확히 그쪽이다.
    """
    return {k: v for k, v in envelope.items() if k != "_duration_ms"}


@pytest.mark.asyncio
async def test_get_returns_exactly_the_run_response(session, executed):
    """**이 엔드포인트의 계약**이다 — `API_SPEC §6.2` 「§6.1의 응답과 동일」.

    키 일부가 아니라 **전체가 같은지** 본다. 부분 비교로 두면 나중에 블록이 추가될 때
    조회 응답에만 빠져도 통과한다.
    """
    fetched = await get_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

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

    fetched = await get_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert fetched["data"]["deterministic"] == executed["data"]["deterministic"]
    assert (
        fetched["data"]["monte_carlo"]["rating_probabilities"]
        == (executed["data"]["monte_carlo"]["rating_probabilities"])
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
    rows = await list_snapshot_voyages(session, UUID(executed["data"]["simulation_id"]))

    assert len(rows) == executed["data"]["snapshot"]["voyage_count"]
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
    rows = await list_snapshot_voyages(session, UUID(executed["data"]["simulation_id"]))
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
    before = await list_snapshot_voyages(session, UUID(executed["data"]["simulation_id"]))

    await session.execute(
        text("UPDATE voyage SET actual_distance_nm = 9999 WHERE vessel_id = :vid"),
        {"vid": vessel_id},
    )

    after = await list_snapshot_voyages(session, UUID(executed["data"]["simulation_id"]))
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
    again = await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert (
        again["data"]["monte_carlo"]["rating_probabilities"]
        == (executed["data"]["monte_carlo"]["rating_probabilities"])
    )
    assert again["data"]["deterministic"] == executed["data"]["deterministic"]
    assert again["data"]["sensitivity_analysis"] == executed["data"]["sensitivity_analysis"]


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

    again = await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert again["data"]["deterministic"] == executed["data"]["deterministic"]


@pytest.mark.asyncio
async def test_reproduce_keeps_the_original_identifiers(session, executed):
    """응답의 식별자는 **원본의 것**이다 — 「원본을 다시 돌려 확인했다」는 뜻이다."""
    again = await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert again["data"]["simulation_id"] == executed["data"]["simulation_id"]
    assert again["calculation_run_id"] == executed["calculation_run_id"]
    assert again["data"]["snapshot"] == executed["data"]["snapshot"]


@pytest.mark.asyncio
async def test_reproduce_does_not_record_a_new_run(session, executed, vessel_id):
    """검증이지 실행이 아니다 — 이력이 늘면 무엇이 원본인지 흐려진다."""
    before = await _count_runs(session, vessel_id)

    await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

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
        await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))


@pytest.mark.asyncio
async def test_reproduce_reports_the_integrity_failure_when_both_hashes_mismatch(
    session, executed, monkeypatch, caplog
):
    """두 해시가 **동시에** 어긋나면 500이 409를 이긴다 (`#837`).

    종전에는 파라미터 해시가 어긋나는 순간 409를 던져 **입력 해시 검사가 실행조차
    되지 않았다.** 사용자는 409 안내대로 새로 실행하고 정상 결과를 받으므로, 스냅샷
    무결성이 깨졌다는 사실은 **아무 데도 드러나지 않는다.**

    입력 해시 불일치는 immutable 스냅샷(`009`)에서 「저장된 값과 계산식 중 하나가
    어긋났다」는 뜻이라 더 심각하다. 가려진 파라미터 변경도 로그로 남는지 함께 본다.
    """
    await session.execute(
        text("UPDATE regulation_year SET z_factor_percent = 25 WHERE year = 2026")
    )
    monkeypatch.setattr(annual_simulation_service, "_input_hash", lambda **_: "sha256:" + "f" * 64)

    with (
        caplog.at_level("WARNING", logger=annual_simulation_service.__name__),
        pytest.raises(ReproducibilityError),
    ):
        await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert "parameter_hash" in caplog.text, "가려진 파라미터 변경이 로그에 남지 않았습니다"


@pytest.mark.asyncio
async def test_reproduce_still_gives_409_when_only_parameters_changed(session, executed):
    """파라미터**만** 바뀐 흔한 경우는 여전히 409다 — 순서를 바꾼 부작용이 없는지.

    입력 해시를 먼저 계산하게 되면서, 파라미터만 바뀐 정상 상황이 스냅샷 문제(500)로
    **오인되지 않는가**가 요점이다. 그렇게 되면 사용자가 「새로 실행」 대신 관리자를
    찾게 된다.
    """
    await session.execute(
        text("UPDATE regulation_year SET z_factor_percent = 25 WHERE year = 2026")
    )

    with pytest.raises(ParameterError):
        await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))


@pytest.mark.asyncio
async def test_reproduce_rebuilds_with_the_stored_schema_version(session, executed, monkeypatch):
    """#816 — ``parameters_used``를 **저장된 행의 버전으로** 다시 만든다.

    ``reproduce``는 저장된 ``parameter_hash``를 그대로 두고 **지금 코드로**
    ``parameters_used``를 다시 만들어 비교한다. 그래서 빌더가 v2로 바뀌는 순간,
    버전을 보지 않으면 **과거 실행 전부**가 409 ``PARAMETER_ERROR``를 받는다 — 바뀐
    것은 규정이 아니라 우리 코드인데 사용자에게는 「규정 파라미터가 변경되어 재현할
    수 없습니다」가 나간다. ``calculation_run``은 ``calc_run_guard()``(마이그레이션
    024)가 UPDATE를 막으므로 **저장된 해시를 소급해 고칠 수도 없다.**

    「409가 나지 않았다」만으로는 배선이 검증되지 않는다 — 버전을 통째로 무시해도
    지금은 v1이 최신이라 그대로 통과한다. 그래서 넷을 모두 본다.

    1. 버전 필드가 **없는** 행이 v1으로 판정된다 (``#816`` 이전 행이 전부 그렇다)
    2. 빌더가 실제로 ``version=1``로 호출된다
    3. 가상의 v2로 만들었다면 해시가 **달랐다** — 이 테스트에 판별력이 있음을 증명한다
    4. 재현 결과와 해시가 원본과 **같다**

    DB는 ``conn`` fixture의 트랜잭션이 종료 시 롤백하므로 남지 않는다. 파라미터는
    ``_seed_parameters``의 합성값이라 선박·사용자 식별정보를 담지 않는다.
    """
    simulation_id = UUID(executed["data"]["simulation_id"])
    row = (
        await session.execute(
            text(
                "SELECT c.parameters_used, c.parameter_hash "
                "FROM annual_simulation_run r "
                "JOIN calculation_run c ON c.id = r.calculation_run_id "
                "WHERE r.id = :id"
            ),
            {"id": simulation_id},
        )
    ).one()

    # ⑴ 버전 필드가 없다 = v1. 이것이 기존 162건이 놓인 상태다.
    assert "parameter_schema_version" not in row.parameters_used
    assert parameters_schema_version(row.parameters_used) == PARAMETERS_SCHEMA_V1

    seen: list[int] = []
    captured: dict = {}

    def _spy(version: int, **kwargs):
        seen.append(version)
        captured.update(kwargs)
        # 모듈 속성이 아니라 **테스트가 import한 이름**이라 재귀하지 않는다.
        return build_parameters_used(version, **kwargs)

    monkeypatch.setattr(annual_simulation_service, "build_parameters_used", _spy)

    again = await reproduce_annual_simulation(session, simulation_id)

    # ⑵ 저장된 버전으로 **한 번** 호출됐다.
    assert seen == [PARAMETERS_SCHEMA_V1], seen

    # ⑶ 판별력 — 최신이 v2가 되면 해시가 달라진다. 이 단언이 없으면 위 ⑵는
    #    「어차피 v1뿐이라 통과」와 구분되지 않는다.
    v1_used = build_parameters_used(PARAMETERS_SCHEMA_V1, **captured)
    marker = "__hypothetical_v2_field__"
    assert marker not in v1_used, "표지가 v1과 충돌한다 — 이 단언의 판별력이 사라진다"
    assert compute_parameter_hash({**v1_used, marker: "v2"}) != row.parameter_hash

    # ⑷ 결과와 해시가 원본과 같다 — 「409가 안 났다」가 아니라 **같은 값**이다.
    assert compute_parameter_hash(v1_used) == row.parameter_hash
    assert again["data"]["deterministic"] == executed["data"]["deterministic"]
    assert again["data"]["sensitivity_analysis"] == executed["data"]["sensitivity_analysis"]
    assert (
        again["data"]["monte_carlo"]["rating_probabilities"]
        == executed["data"]["monte_carlo"]["rating_probabilities"]
    )


@pytest.mark.asyncio
async def test_reproduce_takes_the_version_from_the_row_not_a_constant(
    session, executed, monkeypatch
):
    """#816 — 빌더에 넘기는 버전은 **행을 판정한 값**이지 상수가 아니다.

    위 테스트는 「v1 행이 v1으로 재현된다」까지만 본다. 지금은 v1이 최신이라, 코드가
    행을 보지 않고 ``PARAMETERS_SCHEMA_V1``을 그대로 넘겨도 똑같이 통과한다.

    그래서 여기서는 **판정 함수만** 가상의 v2를 돌려주게 바꾸고, 빌더가 그 값을
    받는지 본다. 상수를 넘기고 있었다면 ``seen``은 ``[1]``이 된다.

    v2 빌더는 아직 없으므로 :class:`ValueError`가 아니라 `#816`의 미등록 버전 처리를
    그대로 타야 한다 — 조용히 v1으로 떨어뜨리면 해시 불일치의 이유가 「버전이
    다르다」인지 「값이 다르다」인지 가려진다.

    DB는 ``conn`` fixture 롤백으로 정리된다.
    """
    seen: list[int] = []

    def _spy(version: int, **kwargs):
        seen.append(version)
        return build_parameters_used(version, **kwargs)

    monkeypatch.setattr(annual_simulation_service, "build_parameters_used", _spy)
    monkeypatch.setattr(annual_simulation_service, "parameters_schema_version", lambda _: 2)

    with pytest.raises(ValueError, match="알 수 없는 parameters_used 스키마 버전: 2"):
        await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert seen == [2], "행이 판정한 버전이 아니라 상수를 넘기고 있다 (#816)"


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
    """`API_SPEC §6.4` 오류 표 — 409 `PARAMETER_ERROR` · 409 `MODEL_VERSION_MISMATCH` ·
    500 `REPRODUCIBILITY_ERROR`.

    서비스가 올바른 예외를 던져도 **상태 코드 매핑이 없으면 500으로 뭉개진다.**
    세 실패는 사용자가 할 일이 다르므로(새로 실행 vs 새 환경에서 새로 실행 vs 관리자
    문의) 코드가 갈려야 한다.
    """
    from cii_platform.errors import ERROR_HTTP_STATUS

    assert ERROR_HTTP_STATUS[ParameterError("x").code] == 409
    assert ERROR_HTTP_STATUS[ModelVersionMismatchError("x").code] == 409
    assert ERROR_HTTP_STATUS[ReproducibilityError("x").code] == 500
    codes = {
        ParameterError("x").code,
        ModelVersionMismatchError("x").code,
        ReproducibilityError("x").code,
    }
    assert len(codes) == 3


# ── model_version — 재현성 계약의 셋째 조건 (#833 · TECH_SPEC §5.4 1항) ─────────


def _foreign_environment(monkeypatch, stored_version: dict) -> dict:
    """지금 환경의 ``model_version``을 **NumPy만 다른** 값으로 바꾼다 (`§10.2` 업그레이드)."""
    changed = {**stored_version, "numpy_version": "9.9.9"}
    monkeypatch.setattr(annual_simulation_service, "_model_version", lambda: changed)
    return changed


@pytest.mark.asyncio
async def test_reproduce_warns_when_the_environment_differs_but_the_result_matches(
    session, executed, monkeypatch
):
    """환경이 달라도 값이 같으면 재현은 성공이다 — 다만 그 사실을 경고로 남긴다.

    NumPy 마이너 업그레이드 뒤에도 값은 대개 같다(`§10.2`). 거절하면 사용자가 확인하려던
    것을 못 하고, 조용히 통과시키면 환경이 바뀐 뒤 처음 값이 갈리는 순간이 「갑자기
    깨졌다」로 보인다.
    """
    _foreign_environment(monkeypatch, executed["model_version"])

    result = await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert WARNING_MODEL_VERSION_DIFFERS in result["warnings"]
    # 응답의 model_version은 여전히 **저장된 것**이다 — 원본이 어느 환경에서 돌았는지가 뜻이다.
    assert result["model_version"] == executed["model_version"]


@pytest.mark.asyncio
async def test_reproduce_gives_409_not_500_when_environment_and_result_both_differ(
    session, executed, monkeypatch
):
    """`API_SPEC §6.4` — 409 `MODEL_VERSION_MISMATCH`.

    종전에는 이 경우도 500 `REPRODUCIBILITY_ERROR`였다 — 원인은 환경 변화인데
    「우리 계산이 깨졌다」로 보고됐다(`#833`). 어느 필드가 달랐는지를 ``details``에 싣는다.
    """
    _foreign_environment(monkeypatch, executed["model_version"])

    def _drift(stored, reproduced):
        raise ReproducibilityError("재현 결과가 원본과 다릅니다(p50).")

    monkeypatch.setattr(annual_simulation_service, "_assert_same_outcome", _drift)

    with pytest.raises(ModelVersionMismatchError) as exc:
        await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert exc.value.details == [
        {
            "field": "numpy_version",
            "stored": executed["model_version"]["numpy_version"],
            "current": "9.9.9",
        }
    ]
    assert "계산 결함이 아닙니다" in str(exc.value)


@pytest.mark.asyncio
async def test_reproduce_keeps_500_when_the_environment_is_the_same_and_the_result_differs(
    session, executed, monkeypatch
):
    """같은 환경에서 값이 다르면 여전히 재현성 계약 위반(500)이다 — 409로 눌러 감추지 않는다."""

    def _drift(stored, reproduced):
        raise ReproducibilityError("재현 결과가 원본과 다릅니다(p50).")

    monkeypatch.setattr(annual_simulation_service, "_assert_same_outcome", _drift)

    with pytest.raises(ReproducibilityError):
        await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))


def test_model_version_diff_compares_every_field_and_treats_missing_as_different():
    """여섯 필드 전부를 본다. 저장값이 비면(기록 이전 실행) 전부 다른 것으로 본다."""
    current = {"engine": "e", "numpy_version": "2.1.0", "python_version": "3.12.4"}
    assert _model_version_diff(current, current) == []
    assert _model_version_diff({**current, "python_version": "3.12.5"}, current) == [
        {"field": "python_version", "stored": "3.12.5", "current": "3.12.4"}
    ]
    assert {d["field"] for d in _model_version_diff({}, current)} == set(current)


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
            {"id": UUID(executed["data"]["simulation_id"])},
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

    again = await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert _without_duration(again) == _without_duration(executed)


@pytest.mark.asyncio
async def test_reproduce_ignores_later_capacity_edits(session, executed, vessel_id):
    """DWT를 고쳐도 재현이 흔들리지 않는다.

    `#493` 본문이 들지 않은 경로다. capacity는 **CII 분모**라 값이 크게 달라진다 —
    제원 둘만 스냅샷했다면 이 테스트가 실패한다.
    """
    await session.execute(
        text("UPDATE vessel SET deadweight = 12345 WHERE id = :id"), {"id": vessel_id}
    )

    again = await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert _without_duration(again) == _without_duration(executed)


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

    again = await reproduce_annual_simulation(session, UUID(executed["data"]["simulation_id"]))

    assert _without_duration(again) == _without_duration(executed)


@pytest.mark.asyncio
async def test_reproduce_refuses_runs_made_before_the_spec_snapshot(session, executed):
    """`037` 이전 실행은 **사유를 밝히고 끊는다.**

    스냅샷 테이블은 immutable이라 그 행에 제원을 넣을 수 없다. 조용히 살아 있는
    제원으로 넘어가면 「같은 스냅샷으로 다시 돌렸다」가 거짓이 되고, 이 이슈가 보고한
    증상이 그대로 남는다.

    (immutable 트리거 때문에 UPDATE로 만들 수 없어 **행을 새로 넣어** 그 상태를
    재현한다.)
    """
    simulation_id = UUID(executed["data"]["simulation_id"])
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
