"""계산 이력의 항차 귀속 (#817 · 2026-09-11 결정 2-③ 「항차 컨텍스트가 있는 요청만 귀속」).

`calculation_run.voyage_id`가 **항상 NULL**이라 항차 단위 재계산 무효화(`PRD §8.4`)가
구조적으로 아무 일도 하지 않았다 — 무효화는 그 컬럼으로 찾는데 채우는 자리가 없었다. 이제
기능① 요청이 ``voyage_id``를 밝히면 계산 이력이 그 항차에 붙는다.

잠그는 것:

* 밝힌 요청만 귀속 — 밝히지 않은 가정 계산은 NULL이다
* ``voyage_id``는 결과·``input_hash``를 바꾸지 않는다 — 이력의 주소일 뿐이다
* 귀속된 계산은 그 항차의 **계획이 바뀌면** 재계산 필요로 표시된다(무효화가 살아난다)
* 다른 선박의 항차에는 붙지 않는다(422) · 없는 항차는 404
* 계산 이력이 있는 항차는 지워지지 않는다(409 — `#313` 가드가 비로소 동작한다)
* **기존 NULL 행은 소급하지 않는다** — `calc_run_guard()`(024)가 ``needs_recalc`` 외 UPDATE를 막는다
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import ConflictError, NotFoundError, ValidationError
from cii_platform.services.scenario_adopt import adopt_scenario
from cii_platform.services.voyage import delete_voyage, update_voyage
from cii_platform.services.voyage_cii import FuelUseInput, VoyageCiiInput, estimate_voyage_cii

DEPARTURE = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _vessel(session) -> UUID:
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, gross_tonnage) "
            "VALUES (:id, :imo, 'ATTRIBUTION TEST', 'BULK_CARRIER', 50000, 30000)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


async def _voyage(session, vessel_id: UUID, *, status: str = "PLANNED") -> UUID:
    policy = "INCLUDE_AS_PLAN" if status == "PLANNED" else "EXCLUDE"
    row = await session.execute(
        text(
            "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
            " planned_departure_at, created_from) "
            "VALUES (:vid, :st, :pol, 2026, 'BUSAN', 'SINGAPORE', 1000, 12, :dep, 'MANUAL') "
            "RETURNING id"
        ),
        {"vid": vessel_id, "st": status, "pol": policy, "dep": DEPARTURE},
    )
    return row.scalar_one()


def _payload(vessel_id: UUID, voyage_id: UUID | None = None) -> VoyageCiiInput:
    return VoyageCiiInput(
        vessel_id=vessel_id,
        regulation_year=2026,
        distance_nm=Decimal("1000"),
        speed_kn=Decimal("12"),
        fuel_uses=(FuelUseInput(fuel_type="HFO", fuel_ton=Decimal("80")),),
        voyage_id=voyage_id,
    )


async def _run_row(session, run_id: str):
    return (
        await session.execute(
            text("SELECT voyage_id, needs_recalc FROM calculation_run WHERE id = :id"),
            {"id": run_id},
        )
    ).one()


@pytest.mark.asyncio
async def test_only_requests_that_name_a_voyage_are_attributed(session):
    vessel_id = await _vessel(session)
    voyage_id = await _voyage(session, vessel_id)

    loose = await estimate_voyage_cii(session, _payload(vessel_id))
    bound = await estimate_voyage_cii(session, _payload(vessel_id, voyage_id))

    assert (await _run_row(session, loose["calculation_run_id"])).voyage_id is None
    assert (await _run_row(session, bound["calculation_run_id"])).voyage_id == voyage_id
    # 주소일 뿐 — 결과도 재현성 단위도 같다
    assert bound["input_hash"] == loose["input_hash"]
    assert bound["data"]["attained_cii"] == loose["data"]["attained_cii"]


@pytest.mark.asyncio
async def test_plan_change_marks_the_attributed_calculation_for_recalculation(session):
    """`PRD §8.4` 「항차 계획 변경 → 해당 항차 계산 결과 무효화」가 비로소 동작한다.

    종전에는 채울 자리가 없어 무효화가 **항상 0행**이었다 — 사용자는 계획이 바뀐 뒤에도 옛
    계산을 유효한 것으로 봤다.
    """
    vessel_id = await _vessel(session)
    voyage_id = await _voyage(session, vessel_id)
    other_id = await _voyage(session, vessel_id)
    bound = await estimate_voyage_cii(session, _payload(vessel_id, voyage_id))
    other = await estimate_voyage_cii(session, _payload(vessel_id, other_id))

    await update_voyage(session, voyage_id, planned_distance_nm=Decimal("1200"))

    assert (await _run_row(session, bound["calculation_run_id"])).needs_recalc is True
    # 범위는 그 항차까지다 — 다른 항차의 계산은 그대로
    assert (await _run_row(session, other["calculation_run_id"])).needs_recalc is False


async def _scenario(session, vessel_id: UUID) -> UUID:
    row = await session.execute(
        text(
            "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, distance_nm, "
            " speed_kn, duration_hours, fuel_ton, cii_value, estimated_rating, risk_level) "
            "VALUES (:vid, 'SLOW_STEAMING', '감속 운항', 2000, 10.5, 190.5, 120.25, 5.1, 'C', "
            " 'MEDIUM') RETURNING id"
        ),
        {"vid": vessel_id},
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_adopt_reports_a_real_invalidated_count(session):
    """채택 응답의 ``invalidated_calculation_runs``가 **참값**이다 (`#1077` · `API_SPEC §5.2`).

    ⚠️ `test_scenario_adopt_db.py`의 무효화 검사는 ``voyage_id``를 **raw SQL로 직접
    넣어** 계산 이력을 만든다 — 그래서 `#817` 이전에도 통과했고, 「실제 서비스가 만든
    계산이 채택으로 무효화되는가」는 **아무도 보지 않았다.** 화면이 이 수를 숨겨 온
    근거가 바로 「늘 0이라 참값이 아니다」였으므로, 표시를 여는 `#1077`은 그 전제가
    사라졌음을 **실제 경로로** 확인해야 한다.

    여기서는 계산을 ``estimate_voyage_cii``(실제 기능① 서비스)로 만든다.
    """
    vessel_id = await _vessel(session)
    voyage_id = await _voyage(session, vessel_id)
    other_id = await _voyage(session, vessel_id)
    scenario_id = await _scenario(session, vessel_id)

    bound = await estimate_voyage_cii(session, _payload(vessel_id, voyage_id))
    # 같은 항차의 계산이 둘이면 둘 다 세어야 한다.
    bound2 = await estimate_voyage_cii(session, _payload(vessel_id, voyage_id))
    # 다른 항차·귀속 없는 계산은 세지 않는다 — 넓게 잡으면 표시가 무의미해진다.
    other = await estimate_voyage_cii(session, _payload(vessel_id, other_id))
    loose = await estimate_voyage_cii(session, _payload(vessel_id))

    result = await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)

    assert result["invalidated_calculation_runs"] == 2
    assert (await _run_row(session, bound["calculation_run_id"])).needs_recalc is True
    assert (await _run_row(session, bound2["calculation_run_id"])).needs_recalc is True
    assert (await _run_row(session, other["calculation_run_id"])).needs_recalc is False
    assert (await _run_row(session, loose["calculation_run_id"])).needs_recalc is False


@pytest.mark.asyncio
async def test_adopt_reports_zero_when_everything_is_already_marked(session):
    """이미 전부 표시된 뒤의 재채택은 `0`이다 — **「계산 이력이 없다」와 같은 값**이다.

    `API_SPEC §5.2`가 그 두 뜻을 모두 규정한다(「이미 표시된 결과는 세지 않는다」).
    화면이 `0`을 「무효화된 계산이 없습니다」로 적으면 **옛 계산이 아직 유효하다**로
    읽히므로, 이 검사가 그 모호함이 서버 값의 성질임을 고정한다 (`#1077`).
    """
    vessel_id = await _vessel(session)
    voyage_id = await _voyage(session, vessel_id)
    empty_id = await _voyage(session, vessel_id)

    await estimate_voyage_cii(session, _payload(vessel_id, voyage_id))
    first = await adopt_scenario(
        session, await _scenario(session, vessel_id), target_voyage_id=voyage_id
    )
    again = await adopt_scenario(
        session, await _scenario(session, vessel_id), target_voyage_id=voyage_id
    )
    # 계산 이력이 한 건도 없는 항차 — 같은 0이다
    never = await adopt_scenario(
        session, await _scenario(session, vessel_id), target_voyage_id=empty_id
    )

    assert first["invalidated_calculation_runs"] == 1
    assert again["invalidated_calculation_runs"] == 0
    assert never["invalidated_calculation_runs"] == 0


@pytest.mark.asyncio
async def test_voyage_of_another_vessel_or_unknown_voyage_is_refused(session):
    """다른 선박의 항차에 붙으면 그 항차의 계획이 바뀔 때 엉뚱한 선박의 계산이 표시된다."""
    vessel_id = await _vessel(session)
    other_vessel = await _vessel(session)
    foreign_voyage = await _voyage(session, other_vessel)

    with pytest.raises(ValidationError) as exc:
        await estimate_voyage_cii(session, _payload(vessel_id, foreign_voyage))
    assert exc.value.field == "voyage_id"
    with pytest.raises(NotFoundError):
        await estimate_voyage_cii(session, _payload(vessel_id, uuid4()))


@pytest.mark.asyncio
async def test_voyage_with_attributed_history_cannot_be_hard_deleted(session):
    """`#313` 삭제 가드(409)가 비로소 동작한다 — 계산 이력은 규제 대응의 근거라 지우지 않는다."""
    vessel_id = await _vessel(session)
    voyage_id = await _voyage(session, vessel_id, status="DRAFT")
    await estimate_voyage_cii(session, _payload(vessel_id, voyage_id))

    with pytest.raises(ConflictError):
        await delete_voyage(session, voyage_id)
