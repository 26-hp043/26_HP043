"""항차 출항·도착 시각 순서 검증 — 네 경로가 한 판정을 지난다 (#2090).

## 무엇을 막는가

``planned_departure_at``·``planned_arrival_at``(계획 쌍)과 ``actual_departure_at``·
``actual_arrival_at``(실적 쌍)에 순서 검사가 없어, 도착이 출항보다 앞서도 201·200으로 저장됐다.
저장된 뒤 진행분 계산(``simulation_clock``)이 창이 빈 항차를 0으로 돌려줘 **값이 그럴듯하게
틀렸다.** 생성·수정·실적 입력·CSV 가져오기가 ``services.voyage.time_order_violation`` 하나를 지난다.

## 같은 시각

거부한다 — 정박 구간의 「종료는 시작보다 뒤」(``not_underway``)와 같은 쪽이고 화면 폼
(``voyageRules.ts`` ``to <= from``)도 같다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.errors import ValidationError
from cii_platform.imo_number import imo_check_digit
from cii_platform.services.voyage import (
    create_voyage,
    get_voyage,
    set_actuals,
    time_order_violation,
    update_voyage,
)
from cii_platform.services.voyage_import import import_voyages

_BASE = "https://testserver"
T0 = datetime(2026, 7, 1, tzinfo=UTC)
LATER = T0 + timedelta(days=10)
EARLIER = T0 - timedelta(days=10)
MESSAGE = "도착 시각은 출항 시각보다 뒤여야 합니다."

HEADER = (
    "voyage_no,departure_port_name,arrival_port_name,"
    "planned_distance_nm,planned_speed_kn,fuel_type,planned_fuel_ton,"
    "planned_departure_at,planned_arrival_at"
)


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``7``로 시작한다.

    검사숫자를 맞춘다(`#2134`) — 등록 요청이 검사한다. 그래서 앞 여섯 자리만 무작위다.
    """
    head = f"7{uuid.uuid4().int % 100_000:05d}"
    return head + str(imo_check_digit(head))


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session) -> UUID:
    new_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight) "
            "VALUES (:id, :imo, 'TIME ORDER TEST', 'BULK_CARRIER', 50000)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


def _create_kwargs(**times) -> dict:
    return {
        "voyage_no": None,
        "departure_port_name": "BUSAN",
        "departure_lat": None,
        "departure_lon": None,
        "arrival_port_name": "SINGAPORE",
        "arrival_lat": None,
        "arrival_lon": None,
        "planned_distance_nm": Decimal("1000"),
        "planned_speed_kn": Decimal("12"),
        "planned_departure_at": None,
        "planned_arrival_at": None,
        "regulation_year": None,
        "fuel_uses": [
            {"fuel_type": "HFO", "planned_fuel_ton": Decimal("100"), "source": "USER_INPUT"}
        ],
        "notes": None,
        **times,
    }


async def _voyage(session, vessel_id, *, status="IN_PROGRESS", **cols) -> UUID:
    policy = "EXCLUDE" if status == "DRAFT" else "INCLUDE_AS_PLAN"
    names = "".join(f", {k}" for k in cols)
    values = "".join(f", :{k}" for k in cols)
    new_id = await insert_returning_id(
        session,
        "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
        "departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn"
        f"{names}) VALUES (:vid, :st, :pol, 2026, 'BUSAN', 'SINGAPORE', 1000, 12{values}) "
        "RETURNING id",
        {"vid": vessel_id, "st": status, "pol": policy, **cols},
    )
    return UUID(str(new_id))


def _assert_order_error(error: ValidationError, field: str) -> None:
    assert error.field == field
    assert MESSAGE in str(error)


# ── 판정 함수 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("departure", "arrival", "bad"),
    [
        (T0, LATER, False),
        (T0, EARLIER, True),
        (T0, T0, True),
        (T0, None, False),
        (None, T0, False),
        (None, None, False),
        # 시간대 없는 값은 UTC로 읽는다 — 저장소가 돌려주는 값과 요청 값이 섞여도 비교가 된다.
        (T0.replace(tzinfo=None), EARLIER, True),
    ],
)
def test_time_order_violation_rules(departure, arrival, bad):
    for kind, field in (("planned", "planned_arrival_at"), ("actual", "actual_arrival_at")):
        found = time_order_violation(kind, departure, arrival)
        assert (found is not None) is bad
        if found is not None:
            assert found[0] == field


# ── 생성 ────────────────────────────────────────────────────────────────────


async def test_create_rejects_arrival_before_departure(session, vessel_id):
    with pytest.raises(ValidationError) as caught:
        await create_voyage(
            session,
            vessel_id,
            **_create_kwargs(planned_departure_at=LATER, planned_arrival_at=T0),
        )
    _assert_order_error(caught.value, "planned_arrival_at")


async def test_create_rejects_equal_times(session, vessel_id):
    with pytest.raises(ValidationError) as caught:
        await create_voyage(
            session, vessel_id, **_create_kwargs(planned_departure_at=T0, planned_arrival_at=T0)
        )
    _assert_order_error(caught.value, "planned_arrival_at")


@pytest.mark.parametrize("times", [{}, {"planned_departure_at": T0}, {"planned_arrival_at": T0}])
async def test_create_accepts_missing_side(session, vessel_id, times):
    data = await create_voyage(session, vessel_id, **_create_kwargs(**times))
    assert data["status"] == "DRAFT"


# ── 수정 (저장된 값과 합친 결과) ─────────────────────────────────────────────


async def test_patch_one_side_that_flips_the_stored_pair_is_rejected(session, vessel_id):
    voyage_id = await _voyage(
        session, vessel_id, status="DRAFT", planned_departure_at=T0, planned_arrival_at=LATER
    )
    # 도착만 보낸다 — 요청만 보면 값이 하나뿐이라 통과하지만 저장된 출항과 합치면 뒤집힌다.
    with pytest.raises(ValidationError) as caught:
        await update_voyage(session, voyage_id, planned_arrival_at=EARLIER)
    _assert_order_error(caught.value, "planned_arrival_at")

    # 출항만 도착 뒤로 미루는 쪽도 같다.
    with pytest.raises(ValidationError) as caught:
        await update_voyage(session, voyage_id, planned_departure_at=LATER + timedelta(days=1))
    _assert_order_error(caught.value, "planned_arrival_at")


async def test_patch_that_keeps_order_or_clears_a_side_passes(session, vessel_id):
    voyage_id = await _voyage(
        session, vessel_id, status="DRAFT", planned_departure_at=T0, planned_arrival_at=LATER
    )
    ok = await update_voyage(session, voyage_id, planned_arrival_at=LATER + timedelta(days=1))
    assert ok["planned_arrival_at"] is not None
    cleared = await update_voyage(session, voyage_id, planned_arrival_at=None)
    assert cleared["planned_arrival_at"] is None


async def test_patch_not_touching_times_works_on_an_already_inverted_row(session, vessel_id):
    """이미 뒤집혀 저장된 행도 시각을 건드리지 않는 수정은 막지 않는다 — 검증은 쓰기 값만 본다."""
    voyage_id = await _voyage(
        session, vessel_id, status="DRAFT", planned_departure_at=LATER, planned_arrival_at=T0
    )
    data = await update_voyage(session, voyage_id, notes="메모")
    assert data["notes"] == "메모"


# ── 실적 입력 ───────────────────────────────────────────────────────────────


async def test_actuals_reject_arrival_before_departure(session, vessel_id):
    voyage_id = await _voyage(session, vessel_id)
    with pytest.raises(ValidationError) as caught:
        await set_actuals(session, voyage_id, actual_departure_at=LATER, actual_arrival_at=T0)
    _assert_order_error(caught.value, "actual_arrival_at")


async def test_actuals_one_side_is_merged_with_the_stored_value(session, vessel_id):
    voyage_id = await _voyage(session, vessel_id, actual_departure_at=T0, actual_arrival_at=LATER)
    with pytest.raises(ValidationError) as caught:
        await set_actuals(session, voyage_id, actual_arrival_at=EARLIER)
    _assert_order_error(caught.value, "actual_arrival_at")


async def test_actuals_pair_is_independent_of_the_planned_pair(session, vessel_id):
    """계획 쌍과 실적 쌍은 각자 본다 — 실적 도착이 계획 출항보다 앞서도 막지 않는다."""
    voyage_id = await _voyage(session, vessel_id, planned_departure_at=LATER)
    data = await set_actuals(
        session,
        voyage_id,
        actual_departure_at=T0,
        actual_arrival_at=T0 + timedelta(days=1),
    )
    assert data["actual_arrival_at"] is not None


# ── CSV ─────────────────────────────────────────────────────────────────────


async def test_csv_row_with_inverted_times_is_a_row_error(session, vessel_id):
    content = (
        HEADER
        + "\nV-1,Busan,Tokyo,1000,13.5,HFO,80,2026-07-01T00:00:00Z,2026-06-01T00:00:00Z"
        + "\nV-2,Busan,Tokyo,1000,13.5,HFO,80,2026-07-01T00:00:00Z,2026-07-05T00:00:00Z"
        + "\nV-3,Busan,Tokyo,1000,13.5,HFO,80,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z"
        + "\nV-4,Busan,Tokyo,1000,13.5,HFO,80,,2026-07-05T00:00:00Z\n"
    ).encode()
    result = await import_voyages(session, vessel_id, content=content)

    assert result["imported_count"] == 2
    assert [(e["row"], e["field"]) for e in result["errors"]] == [
        (2, "planned_arrival_at"),
        (4, "planned_arrival_at"),
    ]
    assert all(e["message"] == MESSAGE for e in result["errors"])


# ── HTTP: 응답 본문 ─────────────────────────────────────────────────────────


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def test_http_create_and_patch_return_422_pointing_at_the_arrival_field(
    migrated_db, app_fresh_engine
):
    body = {
        "departure_port_name": "BUSAN",
        "arrival_port_name": "SINGAPORE",
        "planned_distance_nm": 2470.2,
        "planned_speed_kn": 14,
        "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 331}],
        "planned_departure_at": "2026-07-01T00:00:00Z",
        "planned_arrival_at": "2026-06-01T00:00:00Z",
    }
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            created = client.post(
                f"{API_V1_PREFIX}/vessels",
                json={
                    "imo_number": _imo(),
                    "name": "TIME ORDER HTTP",
                    "ship_type": "BULK_CARRIER",
                },
                headers=_csrf(client),
            )
            assert created.status_code == 201, created.text
            vessel_id = created.json()["data"]["id"]

            response = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages", json=body, headers=_csrf(client)
            )
            assert response.status_code == 422, response.text
            error = response.json()["error"]
            assert error["code"] == "VALIDATION_ERROR"
            assert error["details"][0]["field"] == "planned_arrival_at"
            assert error["details"][0]["message"] == MESSAGE

            body["planned_arrival_at"] = "2026-07-05T00:00:00Z"
            ok = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages", json=body, headers=_csrf(client)
            )
            assert ok.status_code == 201, ok.text
            patched = client.patch(
                f"{API_V1_PREFIX}/voyages/{ok.json()['data']['id']}",
                json={"planned_arrival_at": "2026-06-01T00:00:00Z"},
                headers=_csrf(client),
            )
            assert patched.status_code == 422, patched.text
            assert patched.json()["error"]["details"][0]["field"] == "planned_arrival_at"
    finally:
        if vessel_id is not None:
            from cii_platform.db.session import get_sessionmaker

            async with get_sessionmaker()() as s:
                await s.execute(
                    text("DELETE FROM voyage WHERE vessel_id = :v"), {"v": uuid.UUID(vessel_id)}
                )
                await s.execute(
                    text("DELETE FROM vessel WHERE id = :v"), {"v": uuid.UUID(vessel_id)}
                )
                await s.commit()


# ── 읽기·계산 경로 ──────────────────────────────────────────────────────────


async def test_already_inverted_row_is_still_readable(session, vessel_id):
    """DB에 이미 뒤집힌 행이 있어도 읽기가 깨지지 않는다 — 검증은 쓰기에만 건다."""
    voyage_id = await _voyage(
        session, vessel_id, status="DRAFT", planned_departure_at=LATER, planned_arrival_at=T0
    )
    data = await get_voyage(session, voyage_id)
    assert data["planned_departure_at"] is not None
