"""저장 연간 실행의 낡음 표시 소급 처리 (#2373 · `maintenance/annual_needs_recalc.py`).

#2304가 세우는 표시는 **배포 뒤의 변경**만 안다. 배포 전에 입력이 바뀐 실행을 도구가 한 번
메우는데, 이 파일은 그 판정이 네 경우로 갈리는지 본다 — 입력이 바뀐 실행(대상) · 이미 표시된
실행(건너뜀) · 바뀌지 않은 실행(표시 안 함) · 견줄 수 없는 실행(건드리지 않고 사유).

배포 전 변경은 서비스를 거치지 않고 **생 SQL로** 바꿔 흉내 낸다 — 서비스를 거치면 표시가 함께 서서
소급 처리가 필요한 상태 자체가 만들어지지 않는다.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from test_annual_simulation_read_db import _add_voyage
from test_annual_simulation_read_db import session as session
from test_annual_simulation_read_db import vessel_id as vessel_id

from cii_platform.db.repositories.calculation_run import mark_annual_needs_recalc
from cii_platform.maintenance import annual_needs_recalc as backfill
from cii_platform.services.annual_simulation import (
    _uuid_binds,
    get_annual_simulation,
    run_annual_simulation,
)


async def _save(session, vessel_id) -> UUID:
    saved = await run_annual_simulation(
        session,
        vessel_id=vessel_id,
        regulation_year=2026,
        target_rating="C",
        simulation_runs=1000,
        random_seed=2373,
    )
    return UUID(saved["data"]["simulation_id"])


async def _flags(session, vessel_id) -> list[int]:
    rows = (
        await session.execute(
            text(
                "SELECT needs_recalc FROM calculation_run WHERE vessel_id=:v "
                "AND calculation_type='ANNUAL_MONTE_CARLO' ORDER BY created_at, id"
            ),
            {"v": vessel_id},
        )
    ).all()
    return [int(row.needs_recalc) for row in rows]


async def _check(session, vessel_id, simulation_id) -> backfill.RunCheck:
    checks = await backfill.evaluate(session, vessel_id=vessel_id)
    return next(c for c in checks if c.simulation_id == str(simulation_id))


async def _insert_run(
    session, vessel_id, *, voyages_json, vessel_json, not_underway_json=None
) -> UUID:
    """저장 스냅샷을 직접 정한 실행. 037·060 이전 실행의 모양(NULL)을 만들 때 쓴다."""
    snapshot_id, run_id, simulation_id = uuid4(), uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO simulation_snapshot (id, vessel_id, regulation_year, voyages_json, "
            "vessel_json, not_underway_json, input_hash, parameter_hash) "
            "VALUES (:id, :v, 2026, :voyages, :vessel, :nu, :h, :h)"
        ).bindparams(*_uuid_binds("id", "v")),
        {
            "id": snapshot_id,
            "v": vessel_id,
            "voyages": json.dumps(voyages_json),
            "vessel": None if vessel_json is None else json.dumps(vessel_json),
            "nu": None if not_underway_json is None else json.dumps(not_underway_json),
            "h": "sha256:" + "b" * 64,
        },
    )
    await session.execute(
        text(
            "INSERT INTO calculation_run (id, calculation_type, vessel_id, input_hash, "
            "parameter_hash, model_version, result_json, parameters_used) "
            "VALUES (:id, 'ANNUAL_MONTE_CARLO', :v, :h, :h, '{}', '{}', '{}')"
        ).bindparams(*_uuid_binds("id", "v")),
        {"id": run_id, "v": vessel_id, "h": "sha256:" + "b" * 64},
    )
    await session.execute(
        text(
            "INSERT INTO annual_simulation_run (id, calculation_run_id, vessel_id, "
            "regulation_year, target_rating, simulation_runs, snapshot_id) "
            "VALUES (:id, :run, :v, 2026, 'C', 1000, :snap)"
        ).bindparams(*_uuid_binds("id", "run", "v", "snap")),
        {"id": simulation_id, "run": run_id, "v": vessel_id, "snap": snapshot_id},
    )
    return simulation_id


async def test_pre_deploy_change_is_target_and_apply_marks_only_the_flag(session, vessel_id):
    """⑴ 배포 전에 입력이 바뀐 실행 — 미리 보기에 대상으로 나오고 적용하면 표시가 선다."""
    planned = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="PLAN-2373"
    )
    await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED", no="ACTUAL-2373"
    )
    simulation_id = await _save(session, vessel_id)
    before = await get_annual_simulation(session, simulation_id)
    # 이슈의 예와 같은 모양 — 계획 거리와 연료량이 줄었다(표시 없이).
    await session.execute(
        text("UPDATE voyage SET planned_distance_nm=500 WHERE id=:id"), {"id": planned}
    )
    await session.execute(
        text("UPDATE voyage_fuel_use SET planned_fuel_ton=29.3309 WHERE voyage_id=:id"),
        {"id": planned},
    )
    assert await _flags(session, vessel_id) == [0]

    check = await _check(session, vessel_id, simulation_id)
    assert check.status == backfill.STATUS_TARGET
    print("\n".join(check.differences))
    assert any("PLAN-2373 planned_distance_nm: 3000 → 500" in d for d in check.differences)
    assert any("연료 HFO planned_fuel_ton: 250 → 29.3309" in d for d in check.differences)
    # 미리 보기는 아무것도 쓰지 않는다.
    assert await _flags(session, vessel_id) == [0]

    checks = await backfill.evaluate(session, vessel_id=vessel_id)
    assert await backfill.apply(session, checks) == 1
    assert await _flags(session, vessel_id) == [1]
    assert await get_annual_simulation(session, simulation_id) == before
    # 두 번째 실행은 이미 표시된 것으로 건너뛴다 — 한 번만 하는 작업이다.
    again = await backfill.evaluate(session, vessel_id=vessel_id)
    assert [c.status for c in again] == [backfill.STATUS_ALREADY]
    assert await backfill.apply(session, again) == 0


async def test_already_marked_run_is_skipped_and_counted(session, vessel_id):
    """⑵ 이미 표시된 실행 — 입력이 달라도 다시 견주지 않고 「이미 표시됨」으로 센다."""
    planned = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="PLAN-2373"
    )
    simulation_id = await _save(session, vessel_id)
    await session.execute(
        text("UPDATE voyage SET planned_distance_nm=500 WHERE id=:id"), {"id": planned}
    )
    assert await mark_annual_needs_recalc(session, vessel_id) == 1

    check = await _check(session, vessel_id, simulation_id)
    assert check.status == backfill.STATUS_ALREADY and check.differences == []
    checks = await backfill.evaluate(session, vessel_id=vessel_id)
    assert backfill.summarize(checks)[backfill.STATUS_ALREADY] == 1
    assert await backfill.apply(session, checks) == 0


async def test_unchanged_old_run_is_not_marked(session, vessel_id):
    """⑶ 바뀌지 않은 옛 실행 — 같은 값 재기록·메모·출처·연료 CF가 바뀌어도 표시하지 않는다."""
    planned = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="PLAN-2373"
    )
    actual = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_ACTUAL", status="CONFIRMED", no="ACTUAL-2373"
    )
    simulation_id = await _save(session, vessel_id)
    # 계산 입력이 아닌 것 — 메모·출처 · 같은 값 · 연료 CF(PRD §8.4: 변경 이후 계산에만 적용).
    await session.execute(
        text("UPDATE voyage SET notes='메모만 고침', planned_distance_nm=3000 WHERE id=:id"),
        {"id": planned},
    )
    await session.execute(
        text("UPDATE voyage_fuel_use SET source='USER_INPUT', cf_used=3.2 WHERE voyage_id=:id"),
        {"id": actual},
    )
    await session.execute(text("UPDATE fuel_type SET cf=3.2 WHERE code='HFO'"))

    check = await _check(session, vessel_id, simulation_id)
    assert check.status == backfill.STATUS_CURRENT and check.differences == []
    checks = await backfill.evaluate(session, vessel_id=vessel_id)
    assert await backfill.apply(session, checks) == 0
    assert await _flags(session, vessel_id) == [0]


async def test_uncomparable_runs_are_listed_with_reason_and_untouched(session, vessel_id):
    """⑷ 견줄 수 없는 실행 — 제원 스냅샷 없음(037 이전) · 정박 스냅샷이 빈 채 지금은 정박이 있음."""
    no_vessel = await _insert_run(session, vessel_id, voyages_json=[], vessel_json=None)
    live = {
        "ship_type": "BULK_CARRIER",
        "deadweight": "50000",
        "gross_tonnage": None,
        "reference_speed_kn": "14",
        "reference_daily_foc_ton": "30",
    }
    no_nu = await _insert_run(session, vessel_id, voyages_json=[], vessel_json=live)
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, period_type, "
            "started_at, ended_at, distance_nm) VALUES (:id, :v, 2026, 'DRIFTING', "
            "'2026-01-02 00:00:00', '2026-01-03 00:00:00', 10)"
        ),
        {"id": uuid4(), "v": vessel_id},
    )

    first = await _check(session, vessel_id, no_vessel)
    assert first.status == backfill.STATUS_UNCOMPARABLE
    assert "마이그레이션 037" in first.reasons[0]
    second = await _check(session, vessel_id, no_nu)
    assert second.status == backfill.STATUS_UNCOMPARABLE
    assert "정박 스냅샷" in second.reasons[0]

    checks = await backfill.evaluate(session, vessel_id=vessel_id)
    assert await backfill.apply(session, checks) == 0
    assert await _flags(session, vessel_id) == [0, 0]
    table = backfill.format_table(checks)
    assert str(no_vessel) in table and "견줄 수 없음 2건" in table


async def test_vessel_spec_not_underway_and_json_report(session, vessel_id):
    """제원 · 정박 몫 차이도 잡고, JSON 보고에 실행마다 다른 항목을 싣는다."""
    await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="PLAN-2373"
    )
    period_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, period_type, "
            "started_at, distance_nm) VALUES (:id, :v, 2026, 'AT_ANCHOR', "
            "'2026-01-02 00:00:00', 0)"
        ),
        {"id": period_id, "v": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'OIL_FIRED_BOILER', 'HFO', 40, 3.114)"
        ),
        {"id": period_id},
    )
    simulation_id = await _save(session, vessel_id)
    assert (await _check(session, vessel_id, simulation_id)).status == backfill.STATUS_CURRENT
    await session.execute(
        text("UPDATE vessel SET deadweight=60000 WHERE id=:id"), {"id": vessel_id}
    )
    await session.execute(
        text("UPDATE not_underway_fuel_use SET fuel_ton=41 WHERE period_id=:id"),
        {"id": period_id},
    )
    check = await _check(session, vessel_id, simulation_id)
    assert check.status == backfill.STATUS_TARGET
    print("\n".join(check.differences))
    assert "제원 deadweight: 50000 → 60000" in check.differences
    assert "정박 몫 연료 HFO fuel_ton: 40 → 41" in check.differences
    report = backfill.report_json([check], applied=False, marked=0)
    assert report["mode"] == "dry-run" and report["runs"][0]["differences"] == check.differences


async def test_other_vessel_and_other_year_are_not_mixed(session, vessel_id):
    """다른 선박의 변경, 같은 선박의 다른 연도 항차는 이 실행의 차이가 아니다."""
    await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="PLAN-2373"
    )
    simulation_id = await _save(session, vessel_id)

    other = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight) "
            "VALUES (:id, :imo, 'OTHER 2373', 'BULK_CARRIER', 50000)"
        ),
        {"id": other, "imo": f"9{other.int % 1000000:06d}"},
    )
    other_voyage = await _add_voyage(
        session, other, policy="INCLUDE_AS_PLAN", status="PLANNED", no="OTHER-1"
    )
    other_run = await _save(session, other)
    await session.execute(
        text("UPDATE voyage SET planned_distance_nm=1 WHERE id=:id"), {"id": other_voyage}
    )
    next_year = await _add_voyage(
        session, vessel_id, policy="INCLUDE_AS_PLAN", status="PLANNED", no="Y2027"
    )
    await session.execute(
        text("UPDATE voyage SET regulation_year=2027 WHERE id=:id"), {"id": next_year}
    )

    checks = {c.simulation_id: c for c in await backfill.evaluate(session)}
    assert checks[str(simulation_id)].status == backfill.STATUS_CURRENT
    assert checks[str(other_run)].status == backfill.STATUS_TARGET
    assert all("PLAN-2373" not in d for d in checks[str(other_run)].differences)
    # 선박을 지정하면 그 선박의 실행만 본다.
    only = await backfill.evaluate(session, vessel_id=vessel_id)
    assert [c.simulation_id for c in only] == [str(simulation_id)]


def test_numeric_forms_are_normalized():
    assert backfill._num("100.000") == backfill._num(Decimal("100")) == "100"
    assert backfill._num(None) is None


def test_recovery_file_lists_only_targets(tmp_path):
    def make(status):
        return backfill.RunCheck(
            simulation_id=str(uuid4()),
            calculation_run_id=uuid4().hex,
            vessel_id=uuid4().hex,
            vessel="V",
            regulation_year=2026,
            as_of="2026-10-14T00:00:00+00:00",
            status=status,
        )

    checks = [make(s) for s in (backfill.STATUS_TARGET, backfill.STATUS_ALREADY)]
    path = tmp_path / "recovery.json"
    ids = backfill.write_recovery_file(str(path), checks)
    assert ids == [checks[0].calculation_run_id]
    assert json.loads(path.read_text(encoding="utf-8"))["calculation_run_ids"] == ids
