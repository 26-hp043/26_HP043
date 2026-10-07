"""항차의 귀속 연도 — 출항 또는 도착 시각의 UTC 해 중 하나 (#2133).

## 무엇을 막는가

``regulation_year``는 규정 파라미터에 실재하는지만 봤다(VAL-005 · ``#1332``). 그래서
**2026년 3월 항차를 2025년으로 저장할 수 있었고**, 그 항차는 두 해의 누적과 등급을 모두
조용히 바꿨다. 정박 구간은 처음부터 대조했다(``not_underway._resolve_regulation_year``) —
항차도 같은 함수(``services.voyage.spanned_utc_years``)로 허용 집합을 만든다.

## 결정 (#2133 「결정 (2026-10-07)」)

* 출항 또는 도착 시각의 **UTC** 해 중 하나만 허용한다(`#1333`).
* 연말을 걸친 항차는 **사용자가 고른 한 해에 통째로** 귀속한다 — 12/28~1/3 항차는 2026·2027
  둘 다 통과한다.
* 계획 단계에서 **출항 시각이 비어 있으면 대조하지 않는다.**

## 선박 개요

연간 반영 안 함(``EXCLUDE``)으로 남은 **실적 확정** 항차 수를 이력 응답(`API_SPEC §2.7`)에
싣는다. 화면은 그 값으로 「실적이 없다」와 「확정 항차가 연간에서 빠져 있다」를 가른다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.errors import ParameterError, ValidationError
from cii_platform.services.cii_history import count_excluded_confirmed_voyages
from cii_platform.services.voyage import create_voyage, spanned_utc_years, update_voyage

_BASE = "https://testserver"
KST = timezone(timedelta(hours=9))

MARCH_2026 = datetime(2026, 3, 10, tzinfo=UTC)
MARCH_2026_END = datetime(2026, 3, 20, tzinfo=UTC)
DEC_28_2026 = datetime(2026, 12, 28, tzinfo=UTC)
JAN_3_2027 = datetime(2027, 1, 3, tzinfo=UTC)


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
            "VALUES (:id, :imo, 'ATTRIBUTION TEST', 'BULK_CARRIER', 50000)"
        ),
        {"id": new_id, "imo": f"8{new_id.int % 1000000:06d}"},
    )
    return new_id


def _create_kwargs(**over) -> dict:
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
        **over,
    }


def _assert_attribution_error(error: ValidationError, *years: int) -> None:
    assert error.field == "regulation_year"
    # 문구는 허용 연도를 담는다 — 사용자가 무엇을 넣어야 하는지 알 수 있어야 한다.
    expected = " 또는 ".join(str(year) for year in years)
    # 정본 문구 (API_SPEC §3.3 `[#2133]`) — 바꾸려면 API_SPEC 개정이 먼저다.
    assert str(error) == f"규제연도는 항차가 걸친 연도({expected})여야 합니다."


# ── 허용 집합 ───────────────────────────────────────────────────────────────


def test_spanned_years_are_utc_years_of_both_ends():
    assert spanned_utc_years(MARCH_2026, MARCH_2026_END) == [2026]
    assert spanned_utc_years(DEC_28_2026, JAN_3_2027) == [2026, 2027]
    assert spanned_utc_years(MARCH_2026, None) == [2026]


def test_spanned_years_read_the_utc_year_not_the_local_one():
    """KST 1/1 새벽은 UTC로 전년도다 (`#1333`) — 현지 해를 읽으면 다음 해로 들어간다."""
    kst_new_year = datetime(2027, 1, 1, 3, 0, tzinfo=KST)
    assert spanned_utc_years(kst_new_year, None) == [2026]


# ── 생성 ────────────────────────────────────────────────────────────────────


async def test_create_rejects_a_year_the_voyage_does_not_span(session, vessel_id):
    """2026년 3월 항차에 2025를 넣으면 거부한다 — 이슈의 완료 기준이다."""
    with pytest.raises(ValidationError) as caught:
        await create_voyage(
            session,
            vessel_id,
            **_create_kwargs(
                planned_departure_at=MARCH_2026,
                planned_arrival_at=MARCH_2026_END,
                regulation_year=2025,
            ),
        )
    _assert_attribution_error(caught.value, 2026)


async def test_create_accepts_the_year_the_voyage_spans(session, vessel_id):
    created = await create_voyage(
        session,
        vessel_id,
        **_create_kwargs(
            planned_departure_at=MARCH_2026,
            planned_arrival_at=MARCH_2026_END,
            regulation_year=2026,
        ),
    )
    assert created["regulation_year"] == 2026


@pytest.mark.parametrize("year", [2026, 2027])
async def test_year_end_voyage_accepts_either_year(session, vessel_id, year):
    """12/28 출항·1/3 도착 항차는 2026과 2027 중 사용자가 고른 해에 통째로 들어간다."""
    created = await create_voyage(
        session,
        vessel_id,
        **_create_kwargs(
            planned_departure_at=DEC_28_2026,
            planned_arrival_at=JAN_3_2027,
            regulation_year=year,
        ),
    )
    assert created["regulation_year"] == year


async def test_year_end_voyage_still_rejects_an_unrelated_year(session, vessel_id):
    with pytest.raises(ValidationError) as caught:
        await create_voyage(
            session,
            vessel_id,
            **_create_kwargs(
                planned_departure_at=DEC_28_2026,
                planned_arrival_at=JAN_3_2027,
                regulation_year=2025,
            ),
        )
    _assert_attribution_error(caught.value, 2026, 2027)


@pytest.mark.parametrize("arrival", [None, MARCH_2026_END])
async def test_missing_departure_skips_the_check(session, vessel_id, arrival):
    """출항 시각을 모르면 대조할 값이 없다 — 모르는 것을 틀렸다고 하지 않는다."""
    created = await create_voyage(
        session,
        vessel_id,
        **_create_kwargs(planned_arrival_at=arrival, regulation_year=2025),
    )
    assert created["regulation_year"] == 2025


async def test_missing_parameters_still_win_over_attribution(session, vessel_id):
    """규정 파라미터가 없는 해는 종전대로 409다 — 시각 대조보다 먼저 본다(VAL-005)."""
    far = datetime(2049, 3, 10, tzinfo=UTC)
    with pytest.raises(ParameterError):
        await create_voyage(
            session,
            vessel_id,
            **_create_kwargs(
                planned_departure_at=far,
                planned_arrival_at=far + timedelta(days=5),
                regulation_year=2049,
            ),
        )


# ── 수정 ────────────────────────────────────────────────────────────────────


async def _march_voyage(session, vessel_id) -> UUID:
    created = await create_voyage(
        session,
        vessel_id,
        **_create_kwargs(
            planned_departure_at=MARCH_2026,
            planned_arrival_at=MARCH_2026_END,
            regulation_year=2026,
        ),
    )
    return UUID(str(created["id"]))


async def test_patch_year_alone_is_checked_against_stored_times(session, vessel_id):
    voyage_id = await _march_voyage(session, vessel_id)
    with pytest.raises(ValidationError) as caught:
        await update_voyage(session, voyage_id, regulation_year=2025)
    _assert_attribution_error(caught.value, 2026)


async def test_patch_times_alone_is_checked_against_the_stored_year(session, vessel_id):
    """시각만 이듬해로 옮기면 저장된 2026과 어긋난다 — 연도를 따라 옮기지 않고 거부한다."""
    voyage_id = await _march_voyage(session, vessel_id)
    with pytest.raises(ValidationError) as caught:
        await update_voyage(
            session,
            voyage_id,
            planned_departure_at=datetime(2027, 3, 10, tzinfo=UTC),
            planned_arrival_at=datetime(2027, 3, 20, tzinfo=UTC),
        )
    _assert_attribution_error(caught.value, 2027)


async def test_patch_times_and_year_together_passes(session, vessel_id):
    voyage_id = await _march_voyage(session, vessel_id)
    updated = await update_voyage(
        session,
        voyage_id,
        planned_departure_at=datetime(2027, 3, 10, tzinfo=UTC),
        planned_arrival_at=datetime(2027, 3, 20, tzinfo=UTC),
        regulation_year=2027,
    )
    assert updated["regulation_year"] == 2027


async def test_patch_not_touching_year_or_times_works_on_an_already_mismatched_row(
    session, vessel_id
):
    """이미 어긋나 저장된 행(이 규칙 전 데이터)의 메모 수정까지 막지 않는다."""
    voyage_id = await insert_returning_id(
        session,
        "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
        "departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
        "planned_departure_at, planned_arrival_at) VALUES (:vid, 'DRAFT', 'EXCLUDE', 2025, "
        "'BUSAN', 'SINGAPORE', 1000, 12, :dep, :arr) RETURNING id",
        {"vid": vessel_id, "dep": MARCH_2026, "arr": MARCH_2026_END},
    )
    updated = await update_voyage(session, UUID(str(voyage_id)), notes="메모")
    assert updated["notes"] == "메모"


# ── 선박 개요 — 연간에서 빠진 확정 항차 수 ─────────────────────────────────


async def _insert(session, vessel_id, *, status, policy, year, deleted=0) -> None:
    await insert_returning_id(
        session,
        "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
        "departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
        "is_deleted) VALUES (:vid, :st, :pol, :yr, 'BUSAN', 'SINGAPORE', 1000, 12, :del) "
        "RETURNING id",
        {"vid": vessel_id, "st": status, "pol": policy, "yr": year, "del": deleted},
    )


async def test_excluded_confirmed_count_counts_only_confirmed_exclude_rows(session, vessel_id):
    await _insert(session, vessel_id, status="CONFIRMED", policy="EXCLUDE", year=None)
    await _insert(session, vessel_id, status="CONFIRMED", policy="EXCLUDE", year=2025)
    # 세지 않는 것 — 반영 중인 확정 · 완료(확정 전) · 삭제된 행
    await _insert(session, vessel_id, status="CONFIRMED", policy="INCLUDE_AS_ACTUAL", year=2026)
    await _insert(session, vessel_id, status="COMPLETED", policy="EXCLUDE", year=None)
    await _insert(session, vessel_id, status="CONFIRMED", policy="EXCLUDE", year=None, deleted=1)

    assert await count_excluded_confirmed_voyages(session, vessel_id=vessel_id) == 2


async def test_excluded_confirmed_count_is_zero_without_such_rows(session, vessel_id):
    assert await count_excluded_confirmed_voyages(session, vessel_id=vessel_id) == 0


# ── HTTP ────────────────────────────────────────────────────────────────────


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def test_http_create_rejects_and_history_carries_the_excluded_count(
    migrated_db, app_fresh_engine
):
    """2026년 3월 항차에 2025 → 422, 규제연도 없이 확정한 항차 → 이력에 1건."""
    body = {
        "departure_port_name": "BUSAN",
        "arrival_port_name": "SINGAPORE",
        "planned_distance_nm": 2470.2,
        "planned_speed_kn": 14,
        "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 331}],
        "planned_departure_at": "2026-03-10T00:00:00Z",
        "planned_arrival_at": "2026-03-20T00:00:00Z",
        "regulation_year": 2025,
    }
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            created = client.post(
                f"{API_V1_PREFIX}/vessels",
                json={
                    "imo_number": f"6{uuid.uuid4().int % 1_000_000:06d}",
                    "name": "ATTRIBUTION HTTP",
                    "ship_type": "BULK_CARRIER",
                    "deadweight": 50000,
                },
                headers=_csrf(client),
            )
            assert created.status_code == 201, created.text
            vessel_id = created.json()["data"]["id"]
            voyages = f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages"

            rejected = client.post(voyages, json=body, headers=_csrf(client))
            assert rejected.status_code == 422, rejected.text
            error = rejected.json()["error"]
            assert error["code"] == "VALIDATION_ERROR"
            assert error["details"][0]["field"] == "regulation_year"
            assert "2026" in error["details"][0]["message"]

            history = f"{API_V1_PREFIX}/vessels/{vessel_id}/cii-history"
            before = client.get(history)
            assert before.status_code == 200, before.text
            assert before.json()["data"]["excluded_confirmed_voyage_count"] == 0

            # 규제연도 없이 확정까지 — 연간 반영 안 함으로 남는다.
            del body["regulation_year"]
            ok = client.post(voyages, json=body, headers=_csrf(client))
            assert ok.status_code == 201, ok.text
            voyage_id = ok.json()["data"]["id"]
            for to_status in ("PLANNED", "IN_PROGRESS"):
                moved = client.post(
                    f"{API_V1_PREFIX}/voyages/{voyage_id}/transition",
                    json={"to_status": to_status},
                    headers=_csrf(client),
                )
                assert moved.status_code == 200, moved.text
            actuals = client.put(
                f"{API_V1_PREFIX}/voyages/{voyage_id}/actuals",
                json={
                    "actual_distance_nm": 2470.2,
                    "fuel_uses": [{"fuel_type": "HFO", "actual_fuel_ton": 330}],
                },
                headers=_csrf(client),
            )
            assert actuals.status_code == 200, actuals.text
            for to_status in ("COMPLETED", "CONFIRMED"):
                moved = client.post(
                    f"{API_V1_PREFIX}/voyages/{voyage_id}/transition",
                    json={"to_status": to_status, "annual_inclusion_policy": "EXCLUDE"},
                    headers=_csrf(client),
                )
                assert moved.status_code == 200, moved.text

            after = client.get(history)
            assert after.status_code == 200, after.text
            assert after.json()["data"]["excluded_confirmed_voyage_count"] == 1
    finally:
        if vessel_id is not None:
            from cii_platform.db.session import get_sessionmaker

            async with get_sessionmaker()() as s:
                await s.execute(
                    text(
                        "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
                        "(SELECT id FROM voyage WHERE vessel_id = :v)"
                    ),
                    {"v": uuid.UUID(vessel_id)},
                )
                await s.execute(
                    text(
                        "DELETE FROM audit_log WHERE entity_id IN "
                        "(SELECT id FROM voyage WHERE vessel_id = :v)"
                    ),
                    {"v": uuid.UUID(vessel_id)},
                )
                await s.execute(
                    text("DELETE FROM voyage WHERE vessel_id = :v"), {"v": uuid.UUID(vessel_id)}
                )
                await s.execute(
                    text("DELETE FROM vessel WHERE id = :v"), {"v": uuid.UUID(vessel_id)}
                )
                await s.commit()
