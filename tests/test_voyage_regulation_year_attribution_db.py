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
from cii_platform.errors import ParameterError, StateTransitionError, ValidationError
from cii_platform.imo_number import imo_check_digit
from cii_platform.services.cii_history import count_excluded_confirmed_voyages
from cii_platform.services.voyage import (
    create_voyage,
    get_voyage,
    set_actuals,
    spanned_utc_years,
    update_voyage,
)

_BASE = "https://testserver"
KST = timezone(timedelta(hours=9))

MARCH_2026 = datetime(2026, 3, 10, tzinfo=UTC)
MARCH_2026_END = datetime(2026, 3, 20, tzinfo=UTC)
DEC_28_2026 = datetime(2026, 12, 28, tzinfo=UTC)
JAN_3_2027 = datetime(2027, 1, 3, tzinfo=UTC)


#: 이 파일의 실적은 2026년 말~2027년 초 항차다. 실적 입력은 지금보다 뒤의 시각을 거절하므로
#: (#2420 결정 3) 「지금」을 그 항차들이 모두 지난 시각에 둔다 — 실제 날짜와 무관하게 같은 결과다.
PINNED_NOW = datetime(2027, 6, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_now(monkeypatch):
    monkeypatch.setattr("cii_platform.services.voyage.resolve_as_of", lambda _as_of: PINNED_NOW)


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
    assert error.details[0]["field_label"] == "기준연도"  # 항차 폼의 칸 이름 (#2469)
    # 문구는 허용 연도를 담는다 — 사용자가 무엇을 넣어야 하는지 알 수 있어야 한다.
    expected = " 또는 ".join(str(year) for year in years)
    # 정본 문구 (API_SPEC §3.3 `[#2133]`) — 바꾸려면 API_SPEC 개정이 먼저다.
    assert str(error) == f"기준연도는 항차가 걸친 연도({expected})여야 합니다."


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


# ── 계획 단계를 벗어난 항차의 기준연도 (결정 2026-10-08) ─────────────────────

DEC_20_2026 = datetime(2026, 12, 20, tzinfo=UTC)
DEC_28_2026_END = datetime(2026, 12, 28, tzinfo=UTC)
JAN_2_2027 = datetime(2027, 1, 2, tzinfo=UTC)
JAN_9_2027 = datetime(2027, 1, 9, tzinfo=UTC)


async def _insert_voyage(
    session,
    vessel_id,
    *,
    status,
    policy,
    year,
    planned=(None, None),
    actual=(None, None),
) -> UUID:
    """상태 전이를 거치지 않고 그 상태의 항차 한 건을 둔다 — 보려는 것은 연도 규칙이다."""
    return await insert_returning_id(
        session,
        "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
        "departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
        "planned_departure_at, planned_arrival_at, actual_departure_at, actual_arrival_at) "
        "VALUES (:vid, :st, :pol, :yr, 'BUSAN', 'SINGAPORE', 1000, 12, :pd, :pa, :ad, :aa) "
        "RETURNING id",
        {
            "vid": vessel_id,
            "st": status,
            "pol": policy,
            "yr": year,
            "pd": planned[0],
            "pa": planned[1],
            "ad": actual[0],
            "aa": actual[1],
        },
    )


async def test_a_confirmed_voyage_without_a_year_can_be_given_one_and_joins_the_year(
    session, vessel_id
):
    """안내(「기준연도를 넣고 반영으로」)를 사용자가 실행할 수 있어야 한다.

    종전에는 확정 항차의 PATCH가 계획값 가드에 막혀, 개요가 권한 일을 할 길이 없었다.
    """
    voyage_id = await _insert_voyage(
        session,
        vessel_id,
        status="CONFIRMED",
        policy="EXCLUDE",
        year=None,
        actual=(MARCH_2026, MARCH_2026_END),
    )
    assert await count_excluded_confirmed_voyages(session, vessel_id=vessel_id) == 1

    updated = await update_voyage(session, voyage_id, regulation_year=2026)

    assert updated["regulation_year"] == 2026
    assert updated["annual_inclusion_policy"] == "INCLUDE_AS_ACTUAL"
    assert updated["status"] == "CONFIRMED"
    assert await count_excluded_confirmed_voyages(session, vessel_id=vessel_id) == 0


async def test_the_year_given_to_a_confirmed_voyage_must_match_its_times(session, vessel_id):
    """실제 시각이 있으면 실제 시각과, 없으면 계획 시각과 대조한다."""
    with_actual = await _insert_voyage(
        session,
        vessel_id,
        status="CONFIRMED",
        policy="EXCLUDE",
        year=None,
        planned=(DEC_20_2026, DEC_28_2026_END),
        actual=(JAN_2_2027, JAN_9_2027),
    )
    with pytest.raises(ValidationError) as caught:
        await update_voyage(session, with_actual, regulation_year=2026)
    _assert_attribution_error(caught.value, 2027)

    plan_only = await _insert_voyage(
        session,
        vessel_id,
        status="CONFIRMED",
        policy="EXCLUDE",
        year=None,
        planned=(MARCH_2026, MARCH_2026_END),
    )
    with pytest.raises(ValidationError) as caught:
        await update_voyage(session, plan_only, regulation_year=2025)
    _assert_attribution_error(caught.value, 2026)


async def test_a_confirmed_voyage_that_already_has_a_year_cannot_be_moved(session, vessel_id):
    """처음 채우는 것만 연다 — 이미 어느 해에 들어간 확정 항차를 옮기는 것은 다른 일이다."""
    included = await _insert_voyage(
        session,
        vessel_id,
        status="CONFIRMED",
        policy="INCLUDE_AS_ACTUAL",
        year=2026,
        actual=(DEC_28_2026, JAN_3_2027),
    )
    with pytest.raises(StateTransitionError):
        await update_voyage(session, included, regulation_year=2027)

    # 연도는 있는데 반영 안 함인 확정 항차도 「처음 채우기」가 아니다.
    excluded_with_year = await _insert_voyage(
        session,
        vessel_id,
        status="CONFIRMED",
        policy="EXCLUDE",
        year=2026,
        actual=(DEC_28_2026, JAN_3_2027),
    )
    with pytest.raises(StateTransitionError):
        await update_voyage(session, excluded_with_year, regulation_year=2027)


@pytest.mark.parametrize("status", ["IN_PROGRESS", "COMPLETED", "CONFIRMED"])
async def test_other_plan_values_stay_locked_after_departure(session, vessel_id, status):
    """연 것은 기준연도 **하나**다 — 거리·시각은 종전대로 잠근다. 함께 보내도 거부한다."""
    policy = "EXCLUDE"
    voyage_id = await _insert_voyage(
        session, vessel_id, status=status, policy=policy, year=None, actual=(MARCH_2026, None)
    )
    with pytest.raises(StateTransitionError):
        await update_voyage(session, voyage_id, planned_distance_nm=Decimal("500"))
    with pytest.raises(StateTransitionError):
        await update_voyage(
            session, voyage_id, regulation_year=2026, planned_distance_nm=Decimal("500")
        )
    # 지우는 요청도 이 길이 아니다.
    with pytest.raises(StateTransitionError):
        await update_voyage(session, voyage_id, regulation_year=None, planned_speed_kn=13)


@pytest.mark.parametrize(
    ("status", "policy"), [("IN_PROGRESS", "INCLUDE_AS_PLAN"), ("COMPLETED", "INCLUDE_AS_ACTUAL")]
)
async def test_late_departure_is_refused_then_passes_after_the_year_is_corrected(
    session, vessel_id, status, policy
):
    """12월 계획 · 1월 출항 — 실적 거절 → 연도만 수정 → 실적 통과.

    실적을 그대로 받으면 2026년 누적에 2027년 항차가 들어간다. 연도 수정 없이 거절만 하면
    사용자는 실적도 연도도 못 고친다. 계획 시각(2026)으로 연도 수정을 막지 않는지도 본다.
    """
    voyage_id = await _insert_voyage(
        session,
        vessel_id,
        status=status,
        policy=policy,
        year=2026,
        planned=(DEC_20_2026, DEC_28_2026_END),
    )

    with pytest.raises(ValidationError) as caught:
        await set_actuals(
            session, voyage_id, actual_departure_at=JAN_2_2027, actual_arrival_at=JAN_9_2027
        )
    assert caught.value.field == "regulation_year"
    # 허용 연도와 지금 연도, 고칠 길을 함께 말한다.
    assert "2027" in str(caught.value)
    assert "2026" in str(caught.value)
    assert (await get_voyage(session, voyage_id))["actual_departure_at"] is None

    updated = await update_voyage(session, voyage_id, regulation_year=2027)
    assert updated["regulation_year"] == 2027
    assert updated["annual_inclusion_policy"] == policy

    saved = await set_actuals(
        session, voyage_id, actual_departure_at=JAN_2_2027, actual_arrival_at=JAN_9_2027
    )
    assert saved["actual_departure_at"] is not None


async def test_actual_times_spanning_two_years_accept_either_year(session, vessel_id):
    """해를 걸친 실제 시각은 두 해 모두 통과한다 — 서버가 대신 고르지 않는다."""
    for year in (2026, 2027):
        voyage_id = await _insert_voyage(
            session, vessel_id, status="IN_PROGRESS", policy="INCLUDE_AS_PLAN", year=year
        )
        saved = await set_actuals(
            session, voyage_id, actual_departure_at=DEC_28_2026, actual_arrival_at=JAN_3_2027
        )
        assert saved["regulation_year"] == year


async def test_once_actual_times_exist_the_year_edit_is_checked_against_them(session, vessel_id):
    voyage_id = await _insert_voyage(
        session,
        vessel_id,
        status="COMPLETED",
        policy="INCLUDE_AS_ACTUAL",
        year=2027,
        planned=(DEC_20_2026, DEC_28_2026_END),
        actual=(JAN_2_2027, JAN_9_2027),
    )
    with pytest.raises(ValidationError) as caught:
        await update_voyage(session, voyage_id, regulation_year=2026)
    _assert_attribution_error(caught.value, 2027)


async def test_actuals_without_times_do_not_reopen_an_already_mismatched_row(session, vessel_id):
    """시각을 건드리지 않는 실적 저장은 연도를 보지 않는다 — 대조할 실제 시각이 없다."""
    voyage_id = await _insert_voyage(
        session,
        vessel_id,
        status="IN_PROGRESS",
        policy="INCLUDE_AS_PLAN",
        year=2025,
        planned=(MARCH_2026, MARCH_2026_END),
    )
    saved = await set_actuals(session, voyage_id, actual_distance_nm=Decimal("990"))
    assert saved["actual_distance_nm"] is not None


# ── HTTP ────────────────────────────────────────────────────────────────────


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


def _valid_imo() -> str:
    """검사숫자가 맞는 임의의 IMO 번호 — 선박 등록이 검사숫자를 본다(`#2134`)."""
    first_six = f"{uuid.uuid4().int % 1_000_000:06d}"
    return f"{first_six}{imo_check_digit(first_six)}"


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
                    "imo_number": _valid_imo(),
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

            # 결정 2026-10-08 — 개요가 권한 일(기준연도 넣기)을 실제 요청으로 할 수 있다.
            voyage_url = f"{API_V1_PREFIX}/voyages/{voyage_id}"
            wrong = client.patch(voyage_url, json={"regulation_year": 2025}, headers=_csrf(client))
            assert wrong.status_code == 422, wrong.text
            assert wrong.json()["error"]["details"][0]["field"] == "regulation_year"
            locked = client.patch(
                voyage_url,
                json={"regulation_year": 2026, "planned_speed_kn": 13},
                headers=_csrf(client),
            )
            assert locked.json()["error"]["code"] == "STATE_TRANSITION_ERROR", locked.text

            filled = client.patch(voyage_url, json={"regulation_year": 2026}, headers=_csrf(client))
            assert filled.status_code == 200, filled.text
            assert filled.json()["data"]["regulation_year"] == 2026
            assert filled.json()["data"]["annual_inclusion_policy"] == "INCLUDE_AS_ACTUAL"
            assert client.get(history).json()["data"]["excluded_confirmed_voyage_count"] == 0

            # 한 번 채운 뒤에는 옮길 수 없다.
            moved_again = client.patch(
                voyage_url, json={"regulation_year": 2026}, headers=_csrf(client)
            )
            assert moved_again.json()["error"]["code"] == "STATE_TRANSITION_ERROR"

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
