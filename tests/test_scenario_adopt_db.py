"""시나리오 채택 (API_SPEC §5.2, #58).

**비교의 마지막 한 걸음이다.** 기능②가 「무엇이 나은가」를 보여 주는 데서 끝나면
그 판단이 운항 계획에 닿지 않는다.

여기서 잠그는 것은 넷이다.

1. **계획값이 실제로 바뀐다** — 채택했는데 항차가 그대로면 아무 일도 안 한 것이다
2. **계산 결과가 무효화된다** — 계획이 바뀌었는데 옛 계산이 현행으로 보이면
   사용자는 채택 전 값을 보고 판단한다
3. **계획 단계 항차만 받는다** — 출항한 뒤 계획을 갈아 끼우면 계획 대비 실적 비교의
   기준선이 사라진다
4. **채택은 항차당 하나다** — 둘이 채택돼 있으면 「무엇이 반영됐나」에 답할 수 없다

케이스 (`TEST_PLAN §14.5`):
    IT-ADOPT-001 · IT-ADOPT-002 · IT-ADOPT-003 · IT-ADOPT-004
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError
from cii_platform.services.scenario_adopt import (
    MODE_CREATE,
    UPDATED_FIELDS,
    adopt_scenario,
)

DEPARTURE = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> UUID:
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, default_fuel_type) "
            "VALUES (:id, :imo, 'ADOPT TEST', 'BULK_CARRIER', 50000, 'HFO')"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


async def _new_voyage(session, vessel_id: UUID, *, status: str = "PLANNED") -> UUID:
    policy = "INCLUDE_AS_PLAN" if status in {"PLANNED", "IN_PROGRESS"} else "EXCLUDE"
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
    voyage_id = row.scalar_one()
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'HFO', 80, 3.114, 'USER_INPUT')"
        ),
        {"vid": voyage_id},
    )
    return voyage_id


async def _new_scenario(
    session, vessel_id: UUID, *, scenario_type: str = "SLOW_STEAMING", distance: str = "2000"
) -> UUID:
    row = await session.execute(
        text(
            "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, distance_nm, "
            " speed_kn, duration_hours, fuel_ton, cii_value, estimated_rating, risk_level) "
            "VALUES (:vid, :st, '감속 운항', :dist, 10.5, 190.5, 120.25, 5.1, 'C', 'MEDIUM') "
            "RETURNING id"
        ),
        {"vid": vessel_id, "st": scenario_type, "dist": Decimal(distance)},
    )
    return row.scalar_one()


async def _voyage_row(session, voyage_id: UUID):
    result = await session.execute(
        text(
            "SELECT planned_distance_nm, planned_speed_kn, planned_arrival_at, status "
            "FROM voyage WHERE id = :id"
        ),
        {"id": voyage_id},
    )
    return result.one()


# ─────────────────────────────────────────────────────────────────────────────
# IT-ADOPT-001 · 계획값 반영
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adopting_updates_the_voyage_plan(session, vessel_id):
    """IT-ADOPT-001 — **이 엔드포인트의 계약**이다.

    채택했는데 항차가 그대로면 아무 일도 하지 않은 것이다.
    """
    voyage_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)

    data = await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)

    row = await _voyage_row(session, voyage_id)
    assert row.planned_distance_nm == Decimal("2000.00")
    assert row.planned_speed_kn == Decimal("10.50")
    assert data["adopted_scenario_type"] == "SLOW_STEAMING"
    assert data["updated_fields"] == list(UPDATED_FIELDS)


@pytest.mark.asyncio
async def test_arrival_time_follows_the_scenario_duration(session, vessel_id):
    """도착 예정 = 출발 예정 + 시나리오 소요 시간.

    감속하면 늦게 도착한다 — 그 사실이 계획에 반영되지 않으면 채택의 의미가 반쪽이다.
    """
    voyage_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)

    await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)

    row = await _voyage_row(session, voyage_id)
    assert row.planned_arrival_at is not None
    hours = (row.planned_arrival_at - DEPARTURE).total_seconds() / 3600
    assert round(hours, 1) == 190.5


@pytest.mark.asyncio
async def test_scenario_is_linked_to_the_voyage(session, vessel_id):
    """채택된 시나리오는 그 항차를 가리킨다 — 나중에 「무엇을 채택했나」에 답한다."""
    voyage_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)

    await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)

    row = await session.execute(
        text("SELECT is_adopted, voyage_id FROM voyage_scenario WHERE id = :id"),
        {"id": scenario_id},
    )
    adopted = row.one()
    assert adopted.is_adopted is True
    assert adopted.voyage_id == voyage_id


@pytest.mark.asyncio
async def test_only_one_scenario_stays_adopted(session, vessel_id):
    """둘이 채택돼 있으면 **「무엇이 반영됐나」에 답할 수 없다.**"""
    voyage_id = await _new_voyage(session, vessel_id)
    first = await _new_scenario(session, vessel_id, scenario_type="DETOUR")
    second = await _new_scenario(session, vessel_id, scenario_type="SLOW_STEAMING")

    await adopt_scenario(session, first, target_voyage_id=voyage_id)
    await adopt_scenario(session, second, target_voyage_id=voyage_id)

    rows = await session.execute(
        text("SELECT id FROM voyage_scenario WHERE voyage_id = :vid AND is_adopted = true"),
        {"vid": voyage_id},
    )
    adopted = [r.id for r in rows]
    assert adopted == [second]


# ─────────────────────────────────────────────────────────────────────────────
# IT-ADOPT-002 · 계산 무효화
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_existing_calculations_are_marked_for_recalculation(session, vessel_id):
    """IT-ADOPT-002 — `API_SPEC §5.2` · `PRD §8.4`.

    계획이 바뀌었는데 옛 계산이 현행으로 보이면 **사용자는 채택 전 값을 보고 판단한다.**
    """
    voyage_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)
    await session.execute(
        text(
            "INSERT INTO calculation_run (calculation_type, vessel_id, voyage_id, input_hash, "
            " parameter_hash, model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :voy, :ih, :ph, '{}'::jsonb, '{}'::jsonb, "
            " '{}'::jsonb)"
        ),
        {
            "vid": vessel_id,
            "voy": voyage_id,
            "ih": "sha256:" + "a" * 64,
            "ph": "sha256:" + "b" * 64,
        },
    )

    data = await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)

    assert data["invalidated_calculation_runs"] == 1
    row = await session.execute(
        text("SELECT needs_recalc FROM calculation_run WHERE voyage_id = :vid"),
        {"vid": voyage_id},
    )
    assert row.scalar_one() is True


@pytest.mark.asyncio
async def test_other_voyages_are_not_invalidated(session, vessel_id):
    """**범위는 그 항차까지다.**

    선박 전체를 표시하면 관계없는 계산까지 「다시 해야 한다」가 되어 표시가
    무의미해진다(선박 단위 무효화는 제원 변경의 몫이다 — `#283`).
    """
    voyage_id = await _new_voyage(session, vessel_id)
    other_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)
    await session.execute(
        text(
            "INSERT INTO calculation_run (calculation_type, vessel_id, voyage_id, input_hash, "
            " parameter_hash, model_version, result_json, parameters_used) "
            "VALUES ('VOYAGE_ESTIMATE', :vid, :voy, :ih, :ph, '{}'::jsonb, '{}'::jsonb, "
            " '{}'::jsonb)"
        ),
        {
            "vid": vessel_id,
            "voy": other_id,
            "ih": "sha256:" + "c" * 64,
            "ph": "sha256:" + "d" * 64,
        },
    )

    await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)

    row = await session.execute(
        text("SELECT needs_recalc FROM calculation_run WHERE voyage_id = :vid"),
        {"vid": other_id},
    )
    assert row.scalar_one() is False


# ─────────────────────────────────────────────────────────────────────────────
# 경계
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_scenario_is_not_found(session, vessel_id):
    """IT-ADOPT-003."""
    voyage_id = await _new_voyage(session, vessel_id)

    with pytest.raises(NotFoundError):
        await adopt_scenario(session, uuid4(), target_voyage_id=voyage_id)


@pytest.mark.asyncio
async def test_unknown_voyage_is_not_found(session, vessel_id):
    scenario_id = await _new_scenario(session, vessel_id)

    with pytest.raises(NotFoundError):
        await adopt_scenario(session, scenario_id, target_voyage_id=uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["IN_PROGRESS", "COMPLETED", "CONFIRMED"])
async def test_sailed_voyages_do_not_accept_a_new_plan(session, vessel_id, status):
    """출항한 뒤 계획을 갈아 끼우면 **계획 대비 실적 비교의 기준선이 사라진다.**

    `PRD §8.1.1`은 상태 전환을 규정하지 그 상태에서 무엇을 고칠 수 있는지는 말하지
    않는다 — 그 빈칸을 보수적으로 메운다.
    """
    voyage_id = await _new_voyage(session, vessel_id, status=status)
    scenario_id = await _new_scenario(session, vessel_id)

    with pytest.raises(StateTransitionError):
        await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)


@pytest.mark.asyncio
async def test_scenario_of_another_vessel_is_refused(session, vessel_id):
    """다른 배의 시나리오는 **이 배의 제원으로 계산된 것이 아니다.**"""
    other_vessel = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight) "
            "VALUES (:id, :imo, 'OTHER', 'BULK_CARRIER', 50000)"
        ),
        {"id": other_vessel, "imo": f"9{other_vessel.int % 1000000:06d}"},
    )
    voyage_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, other_vessel)

    with pytest.raises(ValidationError):
        await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)


@pytest.mark.asyncio
async def test_unknown_mode_is_refused(session, vessel_id):
    """기본값이 `UPDATE_EXISTING_PLAN`이다 — `UPDATE_EXISTING`이 아니다 (`§5.2`)."""
    voyage_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)

    with pytest.raises(ValidationError):
        await adopt_scenario(
            session, scenario_id, target_voyage_id=voyage_id, adopt_mode="UPDATE_EXISTING"
        )


# ─────────────────────────────────────────────────────────────────────────────
# CREATE_NEW_VOYAGE
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_mode_makes_a_new_voyage(session, vessel_id):
    """원본은 그대로 두고 새 항차를 만든다."""
    source_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)

    data = await adopt_scenario(
        session,
        scenario_id,
        target_voyage_id=source_id,
        adopt_mode=MODE_CREATE,
        departure_port_name="ULSAN",
        arrival_port_name="TOKYO",
        planned_departure_at=DEPARTURE,
    )

    assert UUID(str(data["voyage_id"])) != source_id
    source = await _voyage_row(session, source_id)
    assert source.planned_distance_nm == Decimal("1000.00"), "원본이 바뀌었다"

    created = await _voyage_row(session, UUID(str(data["voyage_id"])))
    assert created.planned_distance_nm == Decimal("2000.00")
    assert created.status == "DRAFT"


@pytest.mark.asyncio
async def test_create_mode_records_where_it_came_from(session, vessel_id):
    """`created_from=FEATURE_2_ADOPTED` — 나중에 「이 항차는 어디서 왔나」를 묻는다."""
    source_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)

    data = await adopt_scenario(
        session,
        scenario_id,
        target_voyage_id=source_id,
        adopt_mode=MODE_CREATE,
        departure_port_name="ULSAN",
        arrival_port_name="TOKYO",
        planned_departure_at=DEPARTURE,
    )

    row = await session.execute(
        text("SELECT created_from FROM voyage WHERE id = :id"), {"id": data["voyage_id"]}
    )
    assert row.scalar_one() == "FEATURE_2_ADOPTED"


@pytest.mark.asyncio
async def test_create_mode_requires_the_new_voyage_fields(session, vessel_id):
    """**기본값을 지어내지 않는다.**

    시나리오는 거리·속도·연료만 갖고 있어 어디서 어디로 언제 떠나는지를 모른다.
    원본 값을 몰래 복사하면 사용자는 「새 항차인데 옛 일정이 붙어 있는」 것을
    나중에 발견한다.
    """
    source_id = await _new_voyage(session, vessel_id)
    scenario_id = await _new_scenario(session, vessel_id)

    with pytest.raises(ValidationError):
        await adopt_scenario(
            session, scenario_id, target_voyage_id=source_id, adopt_mode=MODE_CREATE
        )


@pytest.mark.asyncio
async def test_create_mode_accepts_a_sailed_source(session, vessel_id):
    """새로 만드는 경우에는 원본의 상태를 묻지 않는다 — 원본을 고치지 않기 때문이다.

    지나간 항차를 참고해 다음 항차를 세우는 것은 정상적인 사용이다.
    """
    source_id = await _new_voyage(session, vessel_id, status="COMPLETED")
    scenario_id = await _new_scenario(session, vessel_id)

    data = await adopt_scenario(
        session,
        scenario_id,
        target_voyage_id=source_id,
        adopt_mode=MODE_CREATE,
        departure_port_name="ULSAN",
        arrival_port_name="TOKYO",
        planned_departure_at=DEPARTURE,
    )

    assert data["voyage_id"]


def test_the_route_is_registered():
    """서비스가 있어도 **라우트를 잊으면 아무도 부를 수 없다.**"""
    from cii_platform.api.main import app

    assert "post" in app.openapi()["paths"]["/api/v1/scenarios/{scenario_id}/adopt"]


def test_compare_response_carries_scenario_ids():
    """IT-ADOPT-004 — 채택하려면 **비교 응답에 id가 있어야** 한다.

    `#57`이 이미 넣었으나 그 사실이 이 이슈의 전제이므로 여기서 함께 잠근다.
    """
    from cii_platform.services.scenario_compare import _serialize_scenarios

    assert "scenario_ids" in _serialize_scenarios.__code__.co_varnames
