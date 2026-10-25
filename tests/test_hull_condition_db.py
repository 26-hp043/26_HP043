"""선체·추진 상태 보정 % — DB 트리거와 HTTP 경로의 계약 (#2561 · 마이그레이션 ``071``).

고정하는 것은 둘이다.

1. **범위 집행** — ``vessel.hull_condition_percent``는 −30 ~ +100이다. CUBRID는 CHECK를 검사하지
   않으므로(``DB_SCHEMA §7.4``) 실제로 위반을 넣어 보고 거부되는지만 본다. 막으려는 것은 API를
   거치지 않은 행(시드·복원·수기 SQL)이다.
2. **HTTP 경로** — ``POST /scenarios/compare``가 보정 %를 요청 → 선박 제원 → 미입력 순으로 정하고,
   그 출처를 ``data.conditions``에 싣고, 연료와 CII를 ``(1 + %/100)``배로 바꾸는가. 엔진만 보면
   응답 조립에서 빠진 것을 못 본다(``#433``).

케이스: DB-CHK-025 · AT-SC-008 (`TEST_PLAN §5.1` · `§4.2`)

트리거 검사는 ``conn`` fixture의 트랜잭션 안이라 롤백된다 — 행을 남기지 않는다.
"""

from __future__ import annotations

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.api.main import app
from cii_platform.imo_number import imo_check_digit

_BASE = "https://testserver"


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "071_vessel_hull_condition_percent.py"
    )
    spec = importlib.util.spec_from_file_location("migration_071", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION = _load_migration()


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``6``으로 시작한다."""
    head = f"6{uuid.uuid4().int % 100_000:05d}"
    return head + str(imo_check_digit(head))


async def _insert_vessel(conn: AsyncConnection, hull: str | None) -> str:
    vessel_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, hull_condition_percent) "
            "VALUES (:id, :imo, 'HULL BOUND TEST', 'BULK_CARRIER', :hull)"
        ),
        {"id": vessel_id, "imo": _imo(), "hull": hull},
    )
    return vessel_id


async def test_triggers_exist(conn: AsyncConnection):
    """071이 만든 트리거 두 개가 DB에 실재한다 — 이름이 바뀌면 downgrade가 엉뚱한 것을 지운다."""
    rows = await conn.execute(text("SELECT name FROM db_trigger"))
    names = {row[0] for row in rows}
    expected = {_MIGRATION._trigger_name(event) for event in _MIGRATION._EVENTS}
    assert expected == {"trg_chk_hull_condition_ins", "trg_chk_hull_condition_upd"}
    assert expected <= names, sorted(expected - names)


@pytest.mark.parametrize("value", ["-30", "0", "12.5", "100", None])
async def test_vessel_accepts_the_domain_range_and_null(conn: AsyncConnection, value):
    """양 끝·0(보정 없음)·실무값·NULL(미입력)은 들어간다. 음수는 정상 입력이다."""
    vessel_id = await _insert_vessel(conn, value)
    stored = await conn.scalar(
        text("SELECT hull_condition_percent FROM vessel WHERE id = :id"), {"id": vessel_id}
    )
    assert (stored is None) == (value is None)
    if value is not None:
        assert Decimal(stored) == Decimal(value)


@pytest.mark.parametrize("value", ["-30.01", "100.01", "250"])
async def test_vessel_insert_rejects_out_of_range(conn: AsyncConnection, value):
    """DB-CHK-025 — API를 거치지 않은 INSERT도 범위 밖이면 거부된다."""
    with pytest.raises(IntegrityError, match="trg_chk_hull_condition_ins"):
        await _insert_vessel(conn, value)


async def test_vessel_update_rejects_out_of_range(conn: AsyncConnection):
    """UPDATE 쪽도 같은 식이다 — INSERT만 막으면 수기 UPDATE로 뚫린다."""
    vessel_id = await _insert_vessel(conn, "10")
    with pytest.raises(IntegrityError, match="trg_chk_hull_condition_upd"):
        await conn.execute(
            text("UPDATE vessel SET hull_condition_percent = -40 WHERE id = :id"),
            {"id": vessel_id},
        )


# --- HTTP 경로 ---------------------------------------------------------------

_PAYLOAD: dict[str, Any] = {
    "regulation_year": 2026,
    "current_speed_kn": 14.0,
    "fuel_type": "HFO",
    "base_daily_foc_ton": 30.0,
    "direct_distance_nm": 1000.0,
}


async def _cleanup(session, vessel_id: str) -> None:
    await session.execute(
        text("DELETE FROM voyage_scenario WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 잠시 끄고 즉시 복구
    # (test_scenario_compare_db.py와 같은 패턴).
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


async def test_compare_resolves_the_hull_condition_over_http(migrated_db, app_fresh_engine):
    """AT-SC-008 — 선박 제원값 → 요청 덮어쓰기 → 0% 덮어쓰기를 한 선박으로 차례로 본다.

    - 제원 +20%면 출처 ``VESSEL``이고, 연료·CII가 0%의 정확히 1.2배다(CII는 거리가 소거돼
      연료 배율이 그대로 옮는다 · ``TECH_SPEC §4.1``).
    - 요청 0%는 출처 ``REQUEST``이고, **보정을 넣기 전과 같은 해시**다(0은 해시 재료가 아니다).
    - 덮어쓰기는 선박 제원을 바꾸지 않는다.
    """
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await insert_returning_id(
                s,
                "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
                "reference_speed_kn, hull_condition_percent) "
                "VALUES (:imo, 'HULL HTTP TEST', 'BULK_CARRIER', 30000, 50000, 14.0, 20) "
                "RETURNING id",
                {"imo": _imo()},
            )
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            headers = {"X-CSRF-Token": client.cookies.get("csrf") or ""}

            def compare(**extra: object) -> dict[str, Any]:
                resp = client.post(
                    "/api/v1/scenarios/compare",
                    json={"vessel_id": vessel_id, **_PAYLOAD, **extra},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text
                return resp.json()

            from_vessel = compare()
            zero = compare(hull_condition_percent=0)
            out_of_range = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **_PAYLOAD, "hull_condition_percent": 101},
                headers=headers,
            )
            vessel_after = client.get(f"/api/v1/vessels/{vessel_id}").json()["data"]

        assert _hull_keys(from_vessel["data"]["conditions"]) == {
            "hull_condition_percent": 20.0,
            "hull_condition_source": "VESSEL",
        }
        assert _hull_keys(zero["data"]["conditions"]) == {
            "hull_condition_percent": 0.0,
            "hull_condition_source": "REQUEST",
        }
        for scaled, base in zip(
            from_vessel["data"]["scenarios"], zero["data"]["scenarios"], strict=True
        ):
            assert scaled["scenario_type"] == base["scenario_type"]
            ratio = Decimal(scaled["attained_cii"]) / Decimal(base["attained_cii"])
            assert abs(ratio - Decimal("1.2")) < Decimal("0.00001"), scaled["scenario_type"]
            assert abs(
                Decimal(str(scaled["fuel_ton"])) / Decimal(str(base["fuel_ton"])) - Decimal("1.2")
            ) < Decimal("0.001")
        assert from_vessel["input_hash"] != zero["input_hash"]
        # 범위 밖 덮어쓰기는 422 — 화면·챗봇과 같은 범위다.
        assert out_of_range.status_code == 422, out_of_range.text
        # 덮어쓰기는 이번 비교에만 쓴다 — 제원은 그대로다.
        assert vessel_after["hull_condition_percent"] == 20.0
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


async def test_zero_and_unset_keep_the_pre_2561_hash(migrated_db, app_fresh_engine):
    """미입력과 0%는 보정을 넣기 전과 **같은 계산·같은 해시**다 — 출처만 다르게 적는다."""
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await insert_returning_id(
                s,
                "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
                "reference_speed_kn) "
                "VALUES (:imo, 'HULL UNSET TEST', 'BULK_CARRIER', 30000, 50000, 14.0) "
                "RETURNING id",
                {"imo": _imo()},
            )
            await s.commit()

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            headers = {"X-CSRF-Token": client.cookies.get("csrf") or ""}
            unset = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **_PAYLOAD},
                headers=headers,
            ).json()
            zero = client.post(
                "/api/v1/scenarios/compare",
                json={"vessel_id": vessel_id, **_PAYLOAD, "hull_condition_percent": 0},
                headers=headers,
            ).json()

        assert unset["data"]["conditions"]["hull_condition_source"] == "NOT_SET"
        assert unset["data"]["conditions"]["hull_condition_percent"] is None
        assert zero["data"]["conditions"]["hull_condition_source"] == "REQUEST"
        assert unset["input_hash"] == zero["input_hash"]
        assert [s["attained_cii"] for s in unset["data"]["scenarios"]] == [
            s["attained_cii"] for s in zero["data"]["scenarios"]
        ]
    finally:
        await _delete_stub_user()
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)


def _hull_keys(conditions: dict) -> dict:
    """``data.conditions``에서 선체 상태 두 키만 — 선석 키(#2561 ②③)는 따로 본다."""
    return {k: conditions[k] for k in ("hull_condition_percent", "hull_condition_source")}
