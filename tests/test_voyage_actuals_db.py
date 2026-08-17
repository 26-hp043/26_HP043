"""항차 실적 입력 — DB 실동작 (`API_SPEC §3.6`, #440).

**계산이 아니라 보존과 경계를 본다.** 이 엔드포인트가 지켜야 하는 것은 셋이다.

1. **계획값을 지우지 않는다** — `PRD §8.4`가 「계획값과 실제값을 모두 보존」으로
   규정한다. 계획 대비 실적 차이가 `#363` 피드백 루프의 입력이므로, 계획값을 잃으면
   그 비교가 영영 불가능해진다.
2. **상태를 바꾸지 않는다** — 실적 입력과 전환을 한 요청에서 처리하면
   `PRD §8.1.1` 전환 가드가 자기 입력을 보고 통과한다.
3. **(항차, 유종) 중복을 만들지 않는다** — `DB_SCHEMA §2.3` [S-2]. 중복이 생기면
   CO₂가 이중 산정되는데, 값이 그럴듯해서 드러나지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError
from cii_platform.services.voyage import set_actuals


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _insert_vessel(session, imo: str = "9440001") -> str:
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, deadweight) "
            "VALUES (:imo, 'ACTUALS TEST', 'BULK_CARRIER', 50000) RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _insert_voyage(session, vessel_id: str, *, status: str = "COMPLETED") -> str:
    policy = "INCLUDE_AS_ACTUAL" if status in {"COMPLETED", "CONFIRMED"} else "INCLUDE_AS_PLAN"
    if status in {"DRAFT", "CANCELLED", "ARCHIVED"}:
        policy = "EXCLUDE"
    row = await session.execute(
        text(
            "INSERT INTO voyage "
            "(vessel_id, status, annual_inclusion_policy, regulation_year, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn) "
            "VALUES (:vid, :st, :pol, 2026, 'BUSAN', 'SINGAPORE', 1000, 12) RETURNING id"
        ),
        {"vid": vessel_id, "st": status, "pol": policy},
    )
    return str(row.scalar_one())


async def _insert_fuel(session, voyage_id: str, *, planned: float = 100) -> None:
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use "
            "(voyage_id, fuel_type, planned_fuel_ton, cf_used, source) "
            "VALUES (:vid, 'HFO', :planned, 3.114, 'USER_INPUT')"
        ),
        {"vid": voyage_id, "planned": planned},
    )


async def _fuel_rows(session, voyage_id: str) -> list:
    rows = await session.execute(
        text(
            "SELECT fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source "
            "FROM voyage_fuel_use WHERE voyage_id = :vid ORDER BY fuel_type"
        ),
        {"vid": voyage_id},
    )
    return list(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 보존
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_planned_value_survives_actual_input(session):
    """**이 이슈의 핵심 계약**이다 — `PRD §8.4` 「계획값과 실제값을 모두 보존」."""
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_fuel(session, voyage_id, planned=100)

    await set_actuals(
        session,
        UUID(voyage_id),
        fuel_uses=[{"fuel_type": "HFO", "actual_fuel_ton": Decimal("85"), "source": None}],
    )

    (row,) = await _fuel_rows(session, voyage_id)
    assert row.planned_fuel_ton == Decimal("100.0000"), "계획값이 지워졌다"
    assert row.actual_fuel_ton == Decimal("85.0000")


@pytest.mark.asyncio
async def test_existing_cf_snapshot_is_not_overwritten(session):
    """실적을 나중에 넣었다고 **그때의 CF로 과거가 바뀌면 재현성이 깨진다** (`#378`).

    CF가 개정된 뒤 실적을 입력하는 상황을 만든다 — 기존 행의 `cf_used`는 그대로여야
    한다.
    """
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_fuel(session, voyage_id)
    await session.execute(text("UPDATE fuel_type SET cf = 9.999 WHERE code = 'HFO'"))

    await set_actuals(
        session,
        UUID(voyage_id),
        fuel_uses=[{"fuel_type": "HFO", "actual_fuel_ton": Decimal("85"), "source": None}],
    )

    (row,) = await _fuel_rows(session, voyage_id)
    assert row.cf_used == Decimal("3.114000"), "과거 snapshot이 현재 CF로 덮였다"


@pytest.mark.asyncio
async def test_new_fuel_type_gets_current_cf(session):
    """기존에 없던 유종은 **지금 시점의 CF**를 박는다."""
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id)

    await set_actuals(
        session,
        UUID(voyage_id),
        fuel_uses=[
            {"fuel_type": "DIESEL_GAS_OIL", "actual_fuel_ton": Decimal("40"), "source": None}
        ],
    )

    (row,) = await _fuel_rows(session, voyage_id)
    assert row.fuel_type == "DIESEL_GAS_OIL"
    assert row.actual_fuel_ton == Decimal("40.0000")
    assert row.cf_used > 0
    # 계획값이 없는 실적 행이다 — 계획 없이 뛴 항차가 실제로 있다.
    assert row.planned_fuel_ton is None


# ─────────────────────────────────────────────────────────────────────────────
# 경계
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_is_not_changed(session):
    """전환은 별도 호출이다 (`API_SPEC §3.6`).

    한 요청에서 함께 처리하면 `COMPLETED → CONFIRMED` 가드가 **자기 입력을 보고**
    통과한다.
    """
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id, status="COMPLETED")
    await _insert_fuel(session, voyage_id)

    data = await set_actuals(
        session,
        UUID(voyage_id),
        actual_distance_nm=Decimal("1100"),
        fuel_uses=[{"fuel_type": "HFO", "actual_fuel_ton": Decimal("85"), "source": None}],
    )

    assert data["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_planned_voyage_cannot_have_actuals(session):
    """**아직 뜨지 않은 항차에 실적이 있을 수 없다.**

    받아 두면 `PRD §8.3` 값 우선순위가 「PLANNED인데 actual이 있는」 정의되지 않은
    상태를 만난다.
    """
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id, status="PLANNED")

    with pytest.raises(StateTransitionError):
        await set_actuals(
            session,
            UUID(voyage_id),
            actual_distance_nm=Decimal("1100"),
        )


@pytest.mark.asyncio
async def test_confirmed_voyage_cannot_be_silently_edited(session):
    """확정된 실적을 조용히 갈아 끼우지 않는다 — 연말 DCS 보고의 근거다."""
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id, status="CONFIRMED")

    with pytest.raises(StateTransitionError):
        await set_actuals(
            session,
            UUID(voyage_id),
            actual_distance_nm=Decimal("1100"),
        )


@pytest.mark.asyncio
async def test_duplicate_fuel_type_in_one_request_is_rejected(session):
    """(항차, 유종) 중복은 **CO₂ 이중 산정**이 된다 (`DB_SCHEMA §2.3` [S-2])."""
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id)

    with pytest.raises(ValidationError):
        await set_actuals(
            session,
            UUID(voyage_id),
            fuel_uses=[
                {"fuel_type": "HFO", "actual_fuel_ton": Decimal("40"), "source": None},
                {"fuel_type": "HFO", "actual_fuel_ton": Decimal("45"), "source": None},
            ],
        )


@pytest.mark.asyncio
async def test_unknown_fuel_type_is_rejected(session):
    """연료 마스터에 없는 코드는 받지 않는다 — CF를 지어낼 수 없다."""
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id)

    with pytest.raises(ValidationError):
        await set_actuals(
            session,
            UUID(voyage_id),
            fuel_uses=[{"fuel_type": "PLUTONIUM", "actual_fuel_ton": Decimal("1"), "source": None}],
        )


@pytest.mark.asyncio
async def test_missing_voyage_is_not_found(session):
    with pytest.raises(NotFoundError):
        await set_actuals(session, uuid4(), actual_distance_nm=Decimal("100"))


@pytest.mark.asyncio
async def test_distance_only_input_is_allowed(session):
    """실거리만 먼저 알고 연료는 나중에 오는 경우가 실제로 있다."""
    vessel_id = await _insert_vessel(session)
    voyage_id = await _insert_voyage(session, vessel_id)
    await _insert_fuel(session, voyage_id)

    data = await set_actuals(
        session,
        UUID(voyage_id),
        actual_distance_nm=Decimal("1100"),
    )

    assert data["actual_distance_nm"] == 1100.0
    (row,) = await _fuel_rows(session, voyage_id)
    assert row.actual_fuel_ton is None, "연료를 보내지 않았는데 값이 생겼다"
