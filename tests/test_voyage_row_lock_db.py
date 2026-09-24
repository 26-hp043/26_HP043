"""항차 상태에 의존하는 쓰기의 직렬화 — 두 세션을 실제로 교차시킨다 (`#1626` · `F-8` 안 「가」).

## 무엇이 문제였나

상태 전환 · PATCH · 실적 입력 · 삭제 · 시나리오 채택은 항차를 **읽고**, 파이썬에서 상태를
**판정하고**, ORM이 **무조건** UPDATE한다. 두 요청이 같은 옛 상태를 읽으면 둘 다 통과한다 —
한쪽이 `CANCELLED`로 종결한 뒤에도 다른 쪽이 `PLANNED`를 근거로 `IN_PROGRESS`를 확정하고,
채택은 해제 UPDATE가 둘 다 0건이라 **채택 행이 둘** 남는다. `#1796`이 CUBRID(READ COMMITTED)
에서 그대로 재현했다(⑹ 무조건 UPDATE는 마지막 쓰기가 이긴다 · ⑺ 채택 행 2건, 각 3/3).

고친 것은 `voyage_repo.get_by_id(for_update=True)` — **항차 행을 먼저 잠그고 읽는다.** 두 번째
요청은 첫 요청이 커밋할 때까지 기다렸다가 **바뀐 상태를 보고** 기존 422로 떨어진다.

## 교차는 「커밋 직전」에 건다

다섯 서비스는 **스스로 커밋한다.** 서비스 호출이 끝난 뒤에 두 번째 세션을 세우면 이미 커밋된
상태를 보게 되어 잠금이 있든 없든 같은 결과가 나온다(`#1629` 코멘트 — 돌연변이가 안 보였던
이유). 그래서 첫 세션의 ``commit``을 갈아 끼워 **잠금을 쥔 채 커밋 직전에 머물게** 하고, 그
사이에 두 번째 세션을 넣는다.

- 잠금이 **있으면** 두 번째는 `FOR UPDATE`에서 대기 → 첫 커밋 뒤 새 상태를 읽음 → 422.
- 잠금이 **없으면**(돌연변이 — `get_by_id`의 `for_update` 갈래를 지움) 두 번째는 대기 없이 옛
  상태를 읽고 **그대로 성공**한다. 아래 각 검사의 「돌연변이 결과」가 그것이다.

`conn` 픽스처는 한 연결을 돌려주므로 쓰지 않는다 — **연결이 둘이어야** 경합이 성립한다.
`test_auth_tokens.TestConcurrentIssue`(`#1630`)와 같은 틀이다. 세션은 `app_fresh_engine`이 갈아
끼운 것을 **호출 시점에** 받는다(`db_session.get_sessionmaker()`) — 모듈 수준에서 묶으면 앱의
캐시된 엔진을 쓰게 되어 테스트 변환기(INSERT `id` 자동 추가)가 없고, 파일만 따로 돌리면
`_setup`의 INSERT가 `NOT NULL` 오류로 끝난다(`#1860` 작업 중 확인).

## 교차 잠금 — 선박 → 항차 순서 (`#1860`)

CUBRID 11.4는 자식 행 INSERT의 FK 검사로 **부모 행에 S 잠금을 요구한다**(`#1860` ⑻
실측 · 부모 X 보유 중 자식 INSERT가 3/3 대기 · 커밋까지 쥐는지는 미측정 — `#1868`).
그래서 「항차 X를 쥔 채 선박을 참조하는
항차 INSERT」(채택 `CREATE_NEW_VOYAGE`)와 「선박 X를 쥔 채 항차를 참조하는 정박 구간
INSERT」(`services/not_underway`)가 교차하면 교착이다(⑼ 실측 3/3 · `errno=-968`). 채택이
선박 행을 **먼저** 잠가 순서를 선박 → 항차로 맞춘다(`TECH_SPEC §16.3`). 이 케이스는 커밋
직전이 아니라 **첫 세션이 선박 X를 쥐고 INSERT 전에 머무는 사이**에 둘째를 넣는다 —
교착은 두 INSERT가 서로의 부모를 기다릴 때 나므로, 커밋 직전 교차로는 보이지 않는다.

⚠️ 앱은 `lock_timeout=-1`(무한 대기)이다 — 첫 세션이 커밋하지 않으면 두 번째가 영영 기다린다.
그래서 첫 세션은 이벤트 루프를 막지 않는 `asyncio.sleep`으로만 머문다.

케이스 (`TEST_PLAN §3.1`): IT-STATE-009
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from conftest import insert_returning_id
from sqlalchemy import text

from cii_platform.db import session as db_session
from cii_platform.errors import StateTransitionError
from cii_platform.services.scenario_adopt import MODE_CREATE, adopt_scenario
from cii_platform.services.voyage import (
    delete_voyage,
    set_actuals,
    transition_voyage,
    update_voyage,
)

#: 첫 세션이 잠금을 쥔 채 커밋 직전에 머무는 시간. 두 번째가 끼어들 자리다.
#: 느린 러너에서도 두 번째가 잠금 문장에 닿을 여유 — 짧으면 검출력만 사라진다(PR #1850 리뷰).
_HOLD = 1.0
#: 두 번째 세션이 끼어드는 시점 — 첫 세션이 커밋 직전에 닿은 뒤.
_JOIN = 0.1


async def _setup(status: str, *, scenarios: int = 0) -> tuple[UUID, UUID, list[UUID]]:
    """선박 1 · 항차 1(연료 행 1) · 시나리오 n을 **커밋해** 만든다.

    두 연결이 모두 봐야 하므로 커밋한다 — `conn` 픽스처의 미커밋 행은 다른 연결에 보이지
    않는다(`#1796` ⑴). 시각 열은 넣지 않는다(채택의 `planned_arrival_at`은 그때 `null`이 되며
    그것이 명세다 — `API_SPEC §5.2`).
    """
    vessel_id = uuid4()
    scenario_ids: list[UUID] = []
    async with db_session.get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                " default_fuel_type) "
                "VALUES (:id, :imo, 'ROW LOCK TEST', 'BULK_CARRIER', 50000, 'HFO')"
            ),
            {"id": vessel_id.hex, "imo": f"9{vessel_id.int % 1000000:06d}"},
        )
        voyage_id = UUID(
            await insert_returning_id(
                s,
                "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
                " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
                " created_from) "
                "VALUES (:vid, :st, 'EXCLUDE', 2026, 'BUSAN', 'SINGAPORE', 1000, 12, 'MANUAL') "
                "RETURNING id",
                {"vid": vessel_id, "st": status},
            )
        )
        await s.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, cf_used, "
                " source) "
                "VALUES (:vid, 'HFO', 80, 3.114, 'USER_INPUT')"
            ),
            {"vid": voyage_id.hex},
        )
        for _ in range(scenarios):
            scenario_ids.append(
                UUID(
                    await insert_returning_id(
                        s,
                        "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, "
                        " distance_nm, speed_kn, duration_hours, fuel_ton, cii_value, "
                        " estimated_rating, risk_level) "
                        "VALUES (:vid, 'SLOW_STEAMING', '감속 운항', 2000, 10.5, 190.5, 120.25, "
                        " 5.1, 'C', 'MEDIUM') RETURNING id",
                        {"vid": vessel_id},
                    )
                )
            )
        await s.commit()
    return vessel_id, voyage_id, scenario_ids


async def _cleanup(vessel_id: UUID) -> None:
    async with db_session.get_sessionmaker()() as s:
        v = {"v": vessel_id.hex}
        await s.execute(
            text(
                "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
                "(SELECT id FROM voyage WHERE vessel_id = :v)"
            ),
            v,
        )
        await s.execute(text("DELETE FROM voyage_scenario WHERE vessel_id = :v"), v)
        await s.execute(text("DELETE FROM not_underway_period WHERE vessel_id = :v"), v)
        await s.execute(text("DELETE FROM voyage WHERE vessel_id = :v"), v)
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), v)
        await s.commit()


async def _voyage_row(voyage_id: UUID):
    """``(status, planned_distance_nm, actual_distance_nm)`` — 없으면 ``None``."""
    async with db_session.get_sessionmaker()() as s:
        result = await s.execute(
            text(
                "SELECT status, planned_distance_nm, actual_distance_nm "
                "FROM voyage WHERE id = :id AND is_deleted = 0"
            ),
            {"id": voyage_id.hex},
        )
        return result.one_or_none()


async def _adopted(voyage_id: UUID) -> set[str]:
    async with db_session.get_sessionmaker()() as s:
        result = await s.execute(
            text("SELECT id FROM voyage_scenario WHERE voyage_id = :id AND is_adopted = 1"),
            {"id": voyage_id.hex},
        )
        return {row[0] for row in result.all()}


def _hold_before_commit(session, reached: asyncio.Event) -> None:
    """서비스가 ``commit``을 부르는 순간 신호를 보내고 잠금을 쥔 채 ``_HOLD``만큼 머문다.

    서비스는 그 전에 이미 항차 행을 잠그고 읽고 판정했다 — 두 번째 세션이 끼어들 자리는
    정확히 여기다. 커밋 자체는 그대로 한다(트랜잭션 경계를 바꾸지 않는다).
    """
    real_commit = session.commit

    async def held_commit() -> None:
        reached.set()
        await asyncio.sleep(_HOLD)
        await real_commit()

    session.commit = held_commit


async def _interleave(first_call, second_call):
    """첫 세션이 커밋 직전에 멈춘 사이 두 번째 세션을 넣는다. 둘의 반환값을 돌려준다.

    ``second_call``이 서비스 예외를 내면 **그 예외 객체**를 돌려준다 — 잠금이 있으면
    두 번째는 새 상태를 보고 422(`StateTransitionError`)로 떨어지는 것이 기대값이다.
    """
    reached = asyncio.Event()
    maker = db_session.get_sessionmaker()

    async def first():
        async with maker() as s:
            _hold_before_commit(s, reached)
            return await first_call(s)

    async def second():
        # 첫 세션이 커밋에 닿지 못하고 죽으면 영영 기다리지 않게 상한을 둔다.
        await asyncio.wait_for(reached.wait(), timeout=_HOLD * 10)
        await asyncio.sleep(_JOIN)
        async with maker() as s:
            try:
                return await second_call(s)
            except StateTransitionError as exc:
                return exc

    return await asyncio.gather(first(), second())


# ─────────────────────────────────────────────────────────────────────────────
# IT-STATE-009 · 다섯 경로
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_transitions_do_not_overwrite_a_terminal_state(
    migrated_db, app_fresh_engine
):
    """전환 × 전환 — 종결(`CANCELLED`)이 먼저 확정되면 뒤의 `IN_PROGRESS`는 422다.

    돌연변이 결과: 두 번째가 옛 `PLANNED`를 읽고 통과해 **예외 없이 성공**한다(마지막
    쓰기가 이긴다 — `#1796` ⑹). 어느 쪽이 남든 한쪽의 전환이 조용히 사라진다.
    """
    vessel_id, voyage_id, _ = await _setup("PLANNED")
    try:
        _, second = await _interleave(
            lambda s: transition_voyage(s, voyage_id, "CANCELLED"),
            lambda s: transition_voyage(s, voyage_id, "IN_PROGRESS"),
        )
        assert isinstance(second, StateTransitionError)
        # 새 상태를 **보고** 거절한 것이어야 한다 — 옛 상태 위의 거절이 아니다.
        assert "CANCELLED" in str(second)
        row = await _voyage_row(voyage_id)
        assert row is not None and row[0] == "CANCELLED"
    finally:
        await _cleanup(vessel_id)


@pytest.mark.asyncio
async def test_patch_after_departure_is_rejected_when_interleaved(migrated_db, app_fresh_engine):
    """전환 × PATCH — 출항(`IN_PROGRESS`)이 먼저 확정되면 계획값 PATCH는 422다(`#865` 가드).

    돌연변이 결과: PATCH가 옛 `PLANNED`를 읽고 **계획 거리를 바꾼다** — 출항한 항차의
    계획이 바뀌어 계획 대비 실적 비교의 기준선이 사라진다.
    """
    vessel_id, voyage_id, _ = await _setup("PLANNED")
    try:
        _, second = await _interleave(
            lambda s: transition_voyage(s, voyage_id, "IN_PROGRESS"),
            lambda s: update_voyage(s, voyage_id, planned_distance_nm=Decimal("1200")),
        )
        assert isinstance(second, StateTransitionError)
        row = await _voyage_row(voyage_id)
        assert row is not None and row[0] == "IN_PROGRESS"
        assert Decimal(str(row[1])) == Decimal("1000")
    finally:
        await _cleanup(vessel_id)


@pytest.mark.asyncio
async def test_actuals_are_not_written_to_a_voyage_cancelled_meanwhile(
    migrated_db, app_fresh_engine
):
    """전환 × 실적 입력 — 취소가 먼저 확정되면 실적 입력은 422다.

    돌연변이 결과: 실적이 옛 `IN_PROGRESS`를 근거로 **취소된 항차에 남는다.**
    """
    vessel_id, voyage_id, _ = await _setup("IN_PROGRESS")
    try:
        _, second = await _interleave(
            lambda s: transition_voyage(s, voyage_id, "CANCELLED"),
            lambda s: set_actuals(s, voyage_id, actual_distance_nm=Decimal("900")),
        )
        assert isinstance(second, StateTransitionError)
        row = await _voyage_row(voyage_id)
        assert row is not None and row[0] == "CANCELLED"
        assert row[2] is None
    finally:
        await _cleanup(vessel_id)


@pytest.mark.asyncio
async def test_delete_does_not_remove_a_voyage_planned_meanwhile(migrated_db, app_fresh_engine):
    """전환 × 삭제 — `PLANNED`가 먼저 확정되면 삭제는 422다(먼저 취소해야 한다).

    돌연변이 결과: 삭제가 옛 `DRAFT`를 근거로 행을 **물리 삭제**한다. 첫 세션의 UPDATE는
    사라진 행을 겨눠 `StaleDataError`로 터진다 — 사용자에게는 500이다.
    """
    vessel_id, voyage_id, _ = await _setup("DRAFT")
    try:
        _, second = await _interleave(
            lambda s: transition_voyage(s, voyage_id, "PLANNED"),
            lambda s: delete_voyage(s, voyage_id),
        )
        assert isinstance(second, StateTransitionError)
        row = await _voyage_row(voyage_id)
        assert row is not None and row[0] == "PLANNED"
    finally:
        await _cleanup(vessel_id)


@pytest.mark.asyncio
async def test_concurrent_adoptions_leave_exactly_one_adopted_row(migrated_db, app_fresh_engine):
    """채택 × 채택 — 「항차당 채택 하나」는 항차 행 잠금이 지킨다 (`DB_SCHEMA §2.4`).

    두 번째는 대기 뒤 첫 채택을 **내리고** 자기 것을 올린다 — 예외가 아니라 나중 채택이
    이기는 것이 기대값이다(단일 요청에서 재채택할 때와 같다).

    ⚠️ 이 짝은 항차 잠금 돌연변이를 **검출하지 못한다** — `get_by_id`의 `for_update` 갈래를
    빼도 통과했다(2026-09-24 실측 · 단독 실행 포함). 두 채택이 같은 `voyage_scenario` 행을
    쓰며 순서가 정해지는 것으로 보인다(정황). 무엇을 지킬지 다시 정하는 일은 `#1869`.
    """
    vessel_id, voyage_id, (first_scenario, second_scenario) = await _setup("DRAFT", scenarios=2)
    try:
        _, second = await _interleave(
            lambda s: adopt_scenario(s, first_scenario, target_voyage_id=voyage_id),
            lambda s: adopt_scenario(s, second_scenario, target_voyage_id=voyage_id),
        )
        assert not isinstance(second, StateTransitionError)
        assert await _adopted(voyage_id) == {second_scenario.hex}
    finally:
        await _cleanup(vessel_id)


# ─────────────────────────────────────────────────────────────────────────────
# IT-STATE-009 · 교차 — 선박 X ↔ 항차 X (#1860)
# ─────────────────────────────────────────────────────────────────────────────


async def _hold_vessel_then_insert_period(vessel_id: UUID, voyage_id: UUID, reached: asyncio.Event):
    """정박 구간 생성이 DB에 내는 잠금 순서를 그대로 밟는다 — **선박 X → 항차 참조 INSERT.**

    `services/not_underway._assert_no_overlap`가 선박 행을 잠근 뒤 구간을 INSERT하는
    두 문장만 흉내 낸다. 서비스 그대로 부르면 잠금과 INSERT 사이에 멈출 자리가 없어
    둘째가 항차 X를 쥐기 전에 INSERT가 끝나 버린다(그러면 교착이 아니라 직렬화다).
    잠금을 쥔 채 ``_HOLD``만큼 머무는 동안 둘째가 들어온다.
    """
    async with db_session.get_sessionmaker()() as s:
        await s.execute(
            text("SELECT id FROM vessel WHERE id = :v FOR UPDATE"), {"v": vessel_id.hex}
        )
        reached.set()
        await asyncio.sleep(_HOLD)
        # 항차 A를 참조하는 자식 — FK 검사가 항차 행에 S 잠금을 요구한다.
        await s.execute(
            text(
                "INSERT INTO not_underway_period (id, vessel_id, regulation_year, period_type, "
                " started_at, ended_at, distance_nm, voyage_id) "
                "VALUES (:id, :v, 2026, 'AT_ANCHOR', '2026-06-01T00:00:00Z', "
                " '2026-06-02T00:00:00Z', 0, :voy)"
            ),
            {"id": uuid4().hex, "v": vessel_id.hex, "voy": voyage_id.hex},
        )
        await s.commit()


@pytest.mark.asyncio
async def test_create_mode_adoption_does_not_deadlock_with_a_period_insert(
    migrated_db, app_fresh_engine
):
    """정박 구간(선박 X → 항차 참조 INSERT) × 채택 `CREATE_NEW_VOYAGE`(항차 X → 선박 참조 INSERT).

    채택이 선박 행을 **먼저** 잠그므로 첫 세션이 커밋할 때까지 그 자리에서 기다렸다가
    새 항차를 만든다 — 둘 다 성공하고 구간 1건 · 새 항차 1건이 남는다.

    돌연변이 결과(채택 갈래의 `vessel_repo.lock_row` 제거): 채택이 항차 X만 쥔 채 새 항차를
    INSERT해 선박 S를 기다리고, 첫 세션의 구간 INSERT는 항차 S를 기다린다 — CUBRID가 교착을
    감지해 한쪽을 끊는다 — 기다리던 쪽이면 `errno=-968` "timed out waiting on S_LOCK … because
    of deadlock"(`#1860` ⑼ 3/3), 희생된 쪽이면 `errno=-72` "unilaterally aborted"(이 검사의
    돌연변이 실측). 끊긴 쪽이 어느 쪽이든 예외가 그대로 올라와
    이 검사가 실패한다.
    """
    vessel_id, voyage_id, (scenario_id,) = await _setup("DRAFT", scenarios=1)
    reached = asyncio.Event()

    async def second():
        await asyncio.wait_for(reached.wait(), timeout=_HOLD * 10)
        await asyncio.sleep(_JOIN)
        async with db_session.get_sessionmaker()() as s:
            return await adopt_scenario(
                s,
                scenario_id,
                target_voyage_id=voyage_id,
                adopt_mode=MODE_CREATE,
                departure_port_name="ULSAN",
                arrival_port_name="TOKYO",
                planned_departure_at=datetime(2026, 7, 1, tzinfo=UTC),
            )

    try:
        _, adopted = await asyncio.gather(
            _hold_vessel_then_insert_period(vessel_id, voyage_id, reached), second()
        )
        new_voyage_id = UUID(str(adopted["voyage_id"]))
        assert new_voyage_id != voyage_id
        assert await _voyage_row(new_voyage_id) is not None
        async with db_session.get_sessionmaker()() as s:
            periods = (
                await s.execute(
                    text("SELECT COUNT(*) FROM not_underway_period WHERE voyage_id = :id"),
                    {"id": voyage_id.hex},
                )
            ).scalar()
        assert periods == 1
    finally:
        await _cleanup(vessel_id)
