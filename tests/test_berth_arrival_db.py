"""선석 가용 시각 · 도착시각 맞춤 — DB 트리거와 HTTP 경로의 계약 (#2561 ②③ · 마이그레이션 072·073).

고정하는 것은 셋이다.

1. **트리거 집행** — ``vessel.anchorage_daily_foc_ton``은 양수(072),
   ``voyage_scenario.scenario_type``은 도착시각 맞춤 2종을 받는다(073). CUBRID는 CHECK를 검사하지
   않으므로(``DB_SCHEMA §7.4``) 실제로 넣어 보고 받는지·거부되는지만 본다.
2. **HTTP 경로** — 선석 시각을 넣은 ``POST /scenarios/compare``가 5행을 저장하고, 선박 제원의
   묘박 연료를 출처 ``VESSEL``로 쓴다. 073이 없으면 저장 단계에서 트리거가 REJECT해 500이다.
3. **채택** — 도착시각 맞춤 행도 채택하면 계획 거리·속력·연료가 그 시나리오의 **항해분**으로
   바뀐다(결정 D4 — 대기분은 계획에 담기지 않는다).

케이스: DB-CHK-026 · DB-CHK-027 · AT-SC-011 (`TEST_PLAN §5.1` · `§4.2`)

트리거 검사는 ``conn`` fixture의 트랜잭션 안이라 롤백된다 — 행을 남기지 않는다.
"""

from __future__ import annotations

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from cii_platform.api.main import app
from cii_platform.imo_number import imo_check_digit

_BASE = "https://testserver"


def _load_migration(name: str):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(f"migration_{name[:3]}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M072 = _load_migration("072_vessel_anchorage_daily_foc.py")


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``5``로 시작한다."""
    head = f"5{uuid.uuid4().int % 100_000:05d}"
    return head + str(imo_check_digit(head))


async def _insert_vessel(conn: AsyncConnection, anchorage: str | None) -> str:
    vessel_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, anchorage_daily_foc_ton) "
            "VALUES (:id, :imo, 'BERTH BOUND TEST', 'BULK_CARRIER', :foc)"
        ),
        {"id": vessel_id, "imo": _imo(), "foc": anchorage},
    )
    return vessel_id


async def _insert_scenario(conn: AsyncConnection, vessel_id: str, scenario_type: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, distance_nm, "
            " speed_kn, duration_hours, fuel_ton, cii_value, estimated_rating, risk_level) "
            "VALUES (:vid, :st, '도착시각 맞춤', 1000, 12.5, 80, 71.17, 4.43, 'B', 'LOW')"
        ),
        {"vid": vessel_id, "st": scenario_type},
    )


async def test_anchorage_triggers_exist(conn: AsyncConnection):
    """072가 만든 트리거 두 개가 DB에 실재한다 — 이름이 바뀌면 downgrade가 엉뚱한 것을 지운다."""
    rows = await conn.execute(text("SELECT name FROM db_trigger"))
    names = {row[0] for row in rows}
    expected = {_M072._trigger_name(event) for event in _M072._EVENTS}
    assert expected == {"trg_chk_anchorage_foc_ins", "trg_chk_anchorage_foc_upd"}
    assert expected <= names, sorted(expected - names)


@pytest.mark.parametrize("value", ["0.01", "3", "12.5", None])
async def test_vessel_accepts_positive_anchorage_fuel_and_null(conn: AsyncConnection, value):
    """양수와 NULL(미입력)은 들어간다."""
    vessel_id = await _insert_vessel(conn, value)
    stored = await conn.scalar(
        text("SELECT anchorage_daily_foc_ton FROM vessel WHERE id = :id"), {"id": vessel_id}
    )
    assert (stored is None) == (value is None)
    if value is not None:
        assert Decimal(stored) == Decimal(value)


@pytest.mark.parametrize("value", ["0", "-1"])
async def test_vessel_rejects_non_positive_anchorage_fuel(conn: AsyncConnection, value):
    """DB-CHK-026 — API를 거치지 않은 INSERT도 0 이하면 거부된다. UPDATE도 같다."""
    with pytest.raises(IntegrityError, match="trg_chk_anchorage_foc_ins"):
        await _insert_vessel(conn, value)


async def test_vessel_update_rejects_non_positive_anchorage_fuel(conn: AsyncConnection):
    vessel_id = await _insert_vessel(conn, "3")
    with pytest.raises(IntegrityError, match="trg_chk_anchorage_foc_upd"):
        await conn.execute(
            text("UPDATE vessel SET anchorage_daily_foc_ton = 0 WHERE id = :id"),
            {"id": vessel_id},
        )


@pytest.mark.parametrize("scenario_type", ["DIRECT_JIT", "DETOUR_JIT"])
async def test_scenario_type_accepts_the_arrival_matched_pair(conn: AsyncConnection, scenario_type):
    """DB-CHK-027 — 073이 넓힌 트리거가 새 두 값을 받는다. 없으면 선석 비교가 저장에서 500이다."""
    vessel_id = await _insert_vessel(conn, None)
    await _insert_scenario(conn, vessel_id, scenario_type)
    count = await conn.scalar(
        text("SELECT COUNT(*) FROM voyage_scenario WHERE vessel_id = :vid AND scenario_type = :st"),
        {"vid": vessel_id, "st": scenario_type},
    )
    assert count == 1


async def test_scenario_type_still_rejects_unknown_values(conn: AsyncConnection):
    """넓힌 뒤에도 목록 밖의 값은 거부된다 — 트리거를 지우기만 하고 다시 안 만든 상태를 잡는다."""
    vessel_id = await _insert_vessel(conn, None)
    with pytest.raises(IntegrityError, match="trg_chk_scenario_type_ins"):
        await _insert_scenario(conn, vessel_id, "BERTH_WAIT")


# --- 채택 --------------------------------------------------------------------


async def test_adopting_an_arrival_matched_scenario_moves_only_the_voyage_part(conn):
    """D4 — 도착시각 맞춤 행도 채택된다. 계획에 들어가는 것은 그 시나리오의 **항해분**이다."""
    from datetime import UTC, datetime

    from cii_platform.services.scenario_adopt import adopt_scenario

    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        vessel_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                "default_fuel_type) VALUES (:id, :imo, 'BERTH ADOPT', 'BULK_CARRIER', 50000, 'HFO')"
            ),
            {"id": vessel_id, "imo": _imo()},
        )
        voyage_id = UUID(
            await insert_returning_id(
                session,
                "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
                " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
                " planned_departure_at, created_from) "
                "VALUES (:vid, 'PLANNED', 'INCLUDE_AS_PLAN', 2026, 'BUSAN', 'SINGAPORE', 1000, 14, "
                " :dep, 'MANUAL') RETURNING id",
                {"vid": vessel_id, "dep": datetime(2026, 10, 26, 0, 0, tzinfo=UTC)},
            )
        )
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, cf_used, "
                "source) VALUES (:vid, 'HFO', 89.28, 3.114, 'USER_INPUT')"
            ),
            {"vid": voyage_id},
        )
        scenario_id = UUID(
            await insert_returning_id(
                session,
                "INSERT INTO voyage_scenario (vessel_id, scenario_type, scenario_name, "
                " distance_nm, speed_kn, duration_hours, fuel_ton, cii_value, estimated_rating, "
                " risk_level) VALUES (:vid, 'DIRECT_JIT', '직항 · 도착시각 맞춤', 1000, 12.5, 80, "
                " 71.1734, 4.43296703, 'B', 'LOW') RETURNING id",
                {"vid": vessel_id},
            )
        )

        data = await adopt_scenario(session, scenario_id, target_voyage_id=voyage_id)

        row = (
            await session.execute(
                text(
                    "SELECT planned_distance_nm, planned_speed_kn, planned_arrival_at "
                    "FROM voyage WHERE id = :id"
                ),
                {"id": voyage_id},
            )
        ).one()
        fuel = await session.scalar(
            text("SELECT planned_fuel_ton FROM voyage_fuel_use WHERE voyage_id = :id"),
            {"id": voyage_id},
        )
    assert data["adopted_scenario_type"] == "DIRECT_JIT"
    assert row.planned_speed_kn == Decimal("12.50")
    # 출발 + 80시간 = 선석 가용 시각. 대기가 0인 맞춤이라 계획 도착이 곧 선석 시각이다.
    arrival = row.planned_arrival_at
    arrival = arrival if arrival.tzinfo else arrival.replace(tzinfo=UTC)
    assert arrival == datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
    # 항해분 연료만 옮긴다 — 대기 연료를 담을 칸은 항차 계획에 없다.
    assert Decimal(fuel) == Decimal("71.1734")


# --- HTTP 경로 ---------------------------------------------------------------

_PAYLOAD: dict[str, Any] = {
    "regulation_year": 2026,
    "current_speed_kn": 14.0,
    "fuel_type": "HFO",
    "base_daily_foc_ton": 30.0,
    "direct_distance_nm": 1000.0,
    "berth_reference_at": "2026-10-26T00:00:00Z",
    "berth_available_at": "2026-10-29T08:00:00Z",
}


async def _cleanup(session, vessel_id: str) -> None:
    await session.execute(
        text("DELETE FROM voyage_scenario WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 잠시 끄고 즉시 복구
    # (test_hull_condition_db.py와 같은 패턴).
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS INACTIVE"))
    await session.execute(
        text("DELETE FROM calculation_run WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS ACTIVE"))
    await session.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
    await session.commit()


async def _delete_stub_user() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM audit_log"))
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
        await s.commit()
    await get_engine().dispose()


async def test_compare_with_berth_stores_five_rows_over_http(migrated_db, app_fresh_engine):
    """AT-SC-011 — 선석 시각을 넣은 비교가 5행을 저장하고 제원의 묘박 연료를 쓴다.

    - 저장된 행의 종류·속력이 응답과 같다(채택이 그 행을 가리킨다).
    - 묘박 연료는 제원(3t/일) → 출처 ``VESSEL``. 직항 대기 연료 3 × 8.571428 ÷ 24 = 1.07t.
    - 선박 응답에 새 칸이 실린다(``API_SPEC §2.1``).
    """
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await insert_returning_id(
                s,
                "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
                "reference_speed_kn, anchorage_daily_foc_ton) "
                "VALUES (:imo, 'BERTH HTTP TEST', 'BULK_CARRIER', 30000, 50000, 14.0, 3) "
                "RETURNING id",
                {"imo": _imo()},
            )
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            headers = {"X-CSRF-Token": client.cookies.get("csrf") or ""}
            resp = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **_PAYLOAD},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            vessel = client.get(f"/api/v1/vessels/{vessel_id}").json()["data"]

        async with sessionmaker() as s:
            stored = (
                await s.execute(
                    text(
                        "SELECT id, scenario_type, speed_kn FROM voyage_scenario "
                        "WHERE vessel_id = :vid"
                    ),
                    {"vid": vessel_id},
                )
            ).all()

        scenarios = body["data"]["scenarios"]
        assert [s["scenario_type"] for s in scenarios] == [
            "DIRECT",
            "DETOUR",
            "SLOW_STEAMING",
            "DIRECT_JIT",
            "DETOUR_JIT",
        ]
        by_id = {str(row.id).replace("-", ""): row for row in stored}
        assert len(by_id) == 5
        for item in scenarios:
            row = by_id[item["scenario_id"].replace("-", "")]
            assert row.scenario_type == item["scenario_type"]
            assert Decimal(row.speed_kn) == Decimal(str(item["speed_kn"]))
        assert body["data"]["conditions"]["anchorage_daily_foc_source"] == "VESSEL"
        assert scenarios[0]["berth"]["waiting_fuel_ton"] == "1.07"
        assert vessel["anchorage_daily_foc_ton"] == 3.0
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
