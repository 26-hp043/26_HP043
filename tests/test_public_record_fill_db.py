"""「이 값으로 채우기」 — 공적 기록 시각을 항차·정박 구간에 옮기는 경로 (#1923 · `API_SPEC §3.12`).

데이터 점검(``UIFLOW 2-11``)의 「공적 기록과 다름」은 알리기만 했다(`#1197` 1단계). 이 파일은
2단계 — **사용자가 누른 칸 하나만** 공적 재항 기록의 시각으로 바뀌고, 그 출처가 행과 감사 로그에
남는지를 실제 DB와 HTTP로 본다.

막으려는 것
-----------

* **누르지 않았는데 바뀌는 것** — 데이터 점검 조회는 값을 바꾸지 않는다(``PRD §17.1``).
* **누른 칸 옆 칸까지 바뀌는 것** — 출항을 채웠는데 도착이 바뀌면 안 된다.
* **확정 실적이 조용히 갈리는 것** — ``CONFIRMED``는 ``revert_confirmed``가 없으면 422이고,
  있으면 되돌리기 전환(``VOYAGE_TRANSITION``) → 채움(``VOYAGE_ACTUALS_FILL``)이 **한
  트랜잭션**이다. 감사 INSERT가 실패하면 되돌림도 값 변경도 남지 않는다(``TECH_SPEC §13.1``).
* **사용자가 본 적 없는 값이 들어가는 것** — 기록이 그 사이 갱신되면 409.
* **다른 배의 기록이 들어가는 것** — 호출부호가 다르면 422.
* **「공적 기록에서 채움」이 거짓말이 되는 것** — 사람이 시각을 **다른 값으로** 고치면 출처가
  NULL로 돌아가고, 같은 값을 다시 보낸 저장(실적 폼은 저장된 시각을 미리 채운다)은 출처를
  지우지 않는다.

케이스: IT-FILL-001 ~ IT-FILL-008 (`TEST_PLAN §14.2`)

데이터를 남기지 않는다
----------------------

``TestClient``는 실제로 커밋한다. 이 파일 전용 선박(IMO ``8`` 시작 · 호출부호 ``F`` 시작)을
만들고 ``finally``에서 감사 행 → 구간 → 항차 → 기록 → 선박 순으로 지운다. 트리거 검사는
``conn`` fixture의 트랜잭션 안이라 롤백된다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.api.schemas.voyage import ACTUAL_TIME_SOURCES
from cii_platform.db.types import JSONText

_BASE = "https://testserver"
YEAR = 2026

#: 064가 만든 트리거 여덟 — 이름이 바뀌면 downgrade가 엉뚱한 것을 지운다.
_TRIGGERS = {
    f"trg_chk_{column}_{event}"
    for column in (
        "actual_departure_source",
        "actual_arrival_source",
        "started_at_source",
        "ended_at_source",
    )
    for event in ("ins", "upd")
}

#: 넣은 출항(06:45 KST의 오전·오후 착오를 흉내) · 공적 기록 출항 — 12시간 차이.
_ENTERED_DEPARTURE = datetime.fromisoformat("2026-03-01T00:00:00+00:00")
_ENTERED_ARRIVAL = datetime.fromisoformat("2026-03-11T00:00:00+00:00")
_RECORD_ARRIVAL = datetime.fromisoformat("2026-02-28T20:00:00+00:00")
_RECORD_DEPARTURE = datetime.fromisoformat("2026-03-01T12:00:00+00:00")
_FETCHED_AT = datetime.fromisoformat("2026-09-26T00:00:00+00:00")


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``8``로 시작한다."""
    return f"8{uuid.uuid4().int % 1_000_000:06d}"


def _call_sign() -> str:
    """호출부호 형식(``^[A-Z0-9]{4,7}$`` · 058)에 맞는 전용 값."""
    return f"F{uuid.uuid4().hex[:5].upper()}"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


# ---------------------------------------------------------------------------
# 1. 트리거 (064)
# ---------------------------------------------------------------------------


async def _insert_vessel(conn: AsyncConnection) -> str:
    vessel_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type) "
            "VALUES (:id, :imo, 'FILL TRIGGER TEST', 'BULK_CARRIER')"
        ),
        {"id": vessel_id, "imo": _imo()},
    )
    return vessel_id


async def _insert_voyage(conn: AsyncConnection, vessel_id: str, source: str | None) -> str:
    voyage_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, annual_inclusion_policy, "
            " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
            " actual_departure_source, actual_arrival_source) "
            "VALUES (:id, :vid, 'DRAFT', 'EXCLUDE', 'BUSAN', 'SINGAPORE', 1000, 12, :src, :src)"
        ),
        {"id": voyage_id, "vid": vessel_id, "src": source},
    )
    return voyage_id


async def test_triggers_exist(conn: AsyncConnection):
    """064가 만든 트리거 여덟이 DB에 실재한다."""
    rows = await conn.execute(
        text(
            "SELECT name FROM db_trigger WHERE name LIKE 'trg_chk_actual_%_source_%' "
            "OR name LIKE 'trg_chk_started_at_source_%' OR name LIKE 'trg_chk_ended_at_source_%'"
        )
    )
    assert {row[0] for row in rows} == _TRIGGERS


@pytest.mark.parametrize("value", [*ACTUAL_TIME_SOURCES, None])
async def test_schema_values_and_null_are_accepted(conn: AsyncConnection, value):
    """스키마의 ``ACTUAL_TIME_SOURCES`` 전부와 「모른다」(NULL)는 들어간다.

    두 목록이 갈리면 서버가 적은 값을 트리거가 REJECT해 500이 된다 — 여기서 잡는다.
    """
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id, value)
    stored = await conn.execute(
        text("SELECT actual_departure_source, actual_arrival_source FROM voyage WHERE id = :id"),
        {"id": voyage_id},
    )
    assert tuple(stored.one()) == (value, value)


@pytest.mark.parametrize("value", ["COORDINATE_ESTIMATE", "public_record", "AIS", ""])
async def test_insert_rejects_unknown_source(conn: AsyncConnection, value):
    """IT-FILL-001 — API를 거치지 않은 INSERT도 두 값 밖이면 거부된다."""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError, match=r"trg_chk_actual_\w+_source_ins"):
        await _insert_voyage(conn, vessel_id, value)


async def test_update_rejects_unknown_source_on_both_tables(conn: AsyncConnection):
    """UPDATE 쪽도 막힌다 — 항차와 정박 구간 둘 다."""
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id, "USER_INPUT")
    with pytest.raises(IntegrityError, match="trg_chk_actual_arrival_source_upd"):
        await conn.execute(
            text("UPDATE voyage SET actual_arrival_source = 'GUESS' WHERE id = :id"),
            {"id": voyage_id},
        )

    period_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, period_type, "
            " started_at, ended_at, port_name) "
            "VALUES (:id, :vid, 2026, 'IN_PORT', :st, :en, 'BUSAN')"
        ),
        {"id": period_id, "vid": vessel_id, "st": _RECORD_ARRIVAL, "en": _RECORD_DEPARTURE},
    )
    with pytest.raises(IntegrityError, match="trg_chk_ended_at_source_upd"):
        await conn.execute(
            text("UPDATE not_underway_period SET ended_at_source = 'GUESS' WHERE id = :id"),
            {"id": period_id},
        )


# ---------------------------------------------------------------------------
# 2. HTTP — 실제 커밋되는 경로
# ---------------------------------------------------------------------------


class _Seed:
    """이 파일 전용 선박 · 항차 · (정박 구간) · 공적 기록 한 벌."""

    def __init__(self) -> None:
        self.vessel_id = uuid.uuid4().hex
        self.voyage_id = uuid.uuid4().hex
        self.period_id = uuid.uuid4().hex
        self.record_id = uuid.uuid4().hex
        self.call_sign = _call_sign()
        self.call_seq = f"{uuid.uuid4().int % 1000:03d}"

    @property
    def record_key(self) -> dict[str, object]:
        return {
            "source": "MOF_VESSEL_OPS",
            "port_authority_code": "020",
            "call_year": YEAR,
            "call_seq": self.call_seq,
        }

    def voyage_url(self) -> str:
        return f"{API_V1_PREFIX}/voyages/{uuid.UUID(self.voyage_id)}"

    def fill_url(self) -> str:
        return f"{self.voyage_url()}/public-record-fill"


async def _seed(status: str, *, with_period: bool = False) -> _Seed:
    from cii_platform.db.session import get_sessionmaker

    seed = _Seed()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, call_sign) "
                "VALUES (:id, :imo, 'FILL TEST', 'BULK_CARRIER', :sign)"
            ),
            {"id": seed.vessel_id, "imo": _imo(), "sign": seed.call_sign},
        )
        await s.execute(
            text(
                "INSERT INTO voyage (id, vessel_id, voyage_no, status, annual_inclusion_policy, "
                " regulation_year, departure_port_name, arrival_port_name, planned_distance_nm, "
                " actual_distance_nm, planned_speed_kn, actual_departure_at, actual_arrival_at, "
                " created_from) "
                "VALUES (:id, :vid, 'V-FILL-1', :st, 'INCLUDE_AS_ACTUAL', :yr, 'BUSAN', "
                " 'SINGAPORE', 2880, 2880, 12, :dep, :arr, 'MANUAL')"
            ),
            {
                "id": seed.voyage_id,
                "vid": seed.vessel_id,
                "st": status,
                "yr": YEAR,
                "dep": _ENTERED_DEPARTURE,
                "arr": _ENTERED_ARRIVAL,
            },
        )
        await s.execute(
            text(
                "INSERT INTO voyage_fuel_use "
                "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
                "VALUES (:id, 'HFO', 240, 240, 3.114, 'USER_INPUT')"
            ),
            {"id": seed.voyage_id},
        )
        if with_period:
            # 공적 기록 입항보다 12시간 늦게 넣은 정박 구간 — 항차 출항 전에 끝난다.
            await s.execute(
                text(
                    "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
                    " period_type, started_at, ended_at, port_name, voyage_id) "
                    "VALUES (:id, :vid, :yr, 'IN_PORT', :st, :en, 'BUSAN', :voy)"
                ),
                {
                    "id": seed.period_id,
                    "vid": seed.vessel_id,
                    "yr": YEAR,
                    "st": datetime.fromisoformat("2026-02-28T08:00:00+00:00"),
                    "en": datetime.fromisoformat("2026-02-28T23:00:00+00:00"),
                    "voy": seed.voyage_id,
                },
            )
        await s.execute(
            text(
                "INSERT INTO port_call_record (id, source, port_authority_code, "
                " port_authority_name, call_year, call_seq, call_sign, arrival_at, departure_at, "
                " reports, fetched_at) "
                "VALUES (:id, 'MOF_VESSEL_OPS', '020', '부산', :yr, :seq, :sign, :arr, :dep, "
                " '[]', :fetched)"
            ),
            {
                "id": seed.record_id,
                "yr": YEAR,
                "seq": seed.call_seq,
                "sign": seed.call_sign,
                "arr": _RECORD_ARRIVAL,
                "dep": _RECORD_DEPARTURE,
                "fetched": _FETCHED_AT,
            },
        )
        await s.commit()
    return seed


async def _cleanup(seed: _Seed) -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    async with get_sessionmaker()() as s:
        for sql in (
            "DELETE FROM audit_log WHERE entity_id = :voy",
            "DELETE FROM not_underway_period WHERE vessel_id = :vid",
            "DELETE FROM voyage WHERE vessel_id = :vid",
            "DELETE FROM port_call_record WHERE id = :rec",
            "DELETE FROM vessel WHERE id = :vid",
        ):
            await s.execute(
                text(sql),
                {"voy": seed.voyage_id, "vid": seed.vessel_id, "rec": seed.record_id},
            )
        await s.commit()
    await get_engine().dispose()


async def _row(sql: str, **params) -> dict:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        result = await s.execute(text(sql), params)
        return dict(result.mappings().one())


async def _voyage_row(seed: _Seed) -> dict:
    return await _row(
        "SELECT status, actual_departure_at, actual_arrival_at, actual_departure_source, "
        " actual_arrival_source FROM voyage WHERE id = :id",
        id=seed.voyage_id,
    )


async def _events(seed: _Seed) -> list[dict]:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        rows = await s.execute(
            text(
                'SELECT "action", user_id, details_json FROM audit_log '
                'WHERE entity_id = :id ORDER BY "timestamp", "action"'
            ).columns(details_json=JSONText()),
            {"id": seed.voyage_id},
        )
        return [dict(row) for row in rows.mappings()]


def _body(seed: _Seed, field: str = "DEPARTURE", **extra) -> dict:
    recorded = _RECORD_ARRIVAL if field in {"ARRIVAL", "BERTH_START"} else _RECORD_DEPARTURE
    return {
        "field": field,
        "record": seed.record_key,
        "recorded_at": recorded.isoformat(),
        **extra,
    }


def _same_instant(stored, expected: datetime) -> bool:
    """DB가 돌려준 시각과 기대 순간이 같은가 — tz 없는 값은 UTC로 읽는다."""
    if stored.tzinfo is None:
        from datetime import UTC

        stored = stored.replace(tzinfo=UTC)
    return stored == expected


def _data_quality_mismatches(client: TestClient, seed: _Seed) -> tuple[dict | None, list[dict]]:
    response = client.get(f"{API_V1_PREFIX}/fleet/data-quality", params={"regulation_year": YEAR})
    assert response.status_code == 200, response.text
    for item in response.json()["data"]["issues"]:
        if (
            item["severity"] == "PUBLIC_RECORD"
            and item["voyage_id"]
            and (uuid.UUID(item["voyage_id"]) == uuid.UUID(seed.voyage_id))
        ):
            return item["public_record"], item["public_record"]["mismatches"]
    return None, []


async def test_completed_voyage_departure_is_filled(migrated_db, app_fresh_engine):
    """IT-FILL-002 · IT-FILL-003 — 조회만으로는 아무것도 바뀌지 않고, 누른 칸 하나만 바뀐다.

    데이터 점검의 어긋남 행이 채우기 재료(``voyage_status`` · 기항 열쇠 · ``fetched_at`` ·
    ``period_id``)를 **HTTP 응답에** 싣는지도 여기서 본다 — 서비스 반환값만 보면 응답 조립
    누락을 못 본다(`#433`).
    """
    seed = await _seed("COMPLETED")
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200

            block, mismatches = _data_quality_mismatches(client, seed)
            assert block is not None, "어긋남이 데이터 점검에 뜨지 않았다"
            assert block["voyage_status"] == "COMPLETED"
            [mismatch] = mismatches
            assert set(mismatch) == {
                "field",
                "entered_at",
                "recorded_at",
                "difference_minutes",
                "port_authority_code",
                "port_authority_name",
                "call_year",
                "call_seq",
                "fetched_at",
                "period_id",
            }
            assert mismatch["field"] == "DEPARTURE"
            assert mismatch["call_year"] == YEAR
            assert mismatch["call_seq"] == seed.call_seq
            assert mismatch["period_id"] is None

            # 누르지 않았다 — 조회는 값도 출처도 바꾸지 않는다.
            untouched = await _voyage_row(seed)
            assert _same_instant(untouched["actual_departure_at"], _ENTERED_DEPARTURE)
            assert untouched["actual_departure_source"] is None
            assert await _events(seed) == []

            response = client.post(seed.fill_url(), json=_body(seed), headers=_csrf(client))
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            assert set(data) == {
                "field",
                "before",
                "after",
                "source",
                "reverted_from_status",
                "voyage",
                "period",
            }, "감사 재료(_audit)가 응답에 새면 클라이언트가 계약으로 읽는다"
            assert data["field"] == "DEPARTURE"
            assert data["source"] == "PUBLIC_RECORD"
            assert data["reverted_from_status"] is None
            assert data["period"] is None
            assert data["voyage"]["actual_departure_source"] == "PUBLIC_RECORD"
            assert data["voyage"]["actual_arrival_source"] is None
            assert data["voyage"]["status"] == "COMPLETED"

            # 조회 응답도 같은 출처를 실제 컬럼에서 돌려준다.
            fetched = client.get(seed.voyage_url()).json()["data"]
            assert fetched["actual_departure_source"] == "PUBLIC_RECORD"

            # 채운 뒤에는 그 어긋남이 사라진다.
            _, after = _data_quality_mismatches(client, seed)
            assert after == []

        row = await _voyage_row(seed)
        assert _same_instant(row["actual_departure_at"], _RECORD_DEPARTURE)
        # 누른 칸 옆 칸은 그대로다.
        assert _same_instant(row["actual_arrival_at"], _ENTERED_ARRIVAL)
        assert row["actual_arrival_source"] is None
        assert row["status"] == "COMPLETED"

        [event] = await _events(seed)
        assert event["action"] == "VOYAGE_ACTUALS_FILL"
        assert event["user_id"], "주체가 비어 있다"
        details = event["details_json"]
        assert details["field"] == "DEPARTURE"
        assert details["target"] == "voyage"
        assert details["source"] == "PUBLIC_RECORD"
        assert details["reverted_from_status"] is None
        assert datetime.fromisoformat(details["before"]) == _ENTERED_DEPARTURE
        assert datetime.fromisoformat(details["after"]) == _RECORD_DEPARTURE
        assert details["public_record"]["port_authority_code"] == "020"
        assert details["public_record"]["call_year"] == YEAR
        assert details["public_record"]["call_seq"] == seed.call_seq
        assert details["public_record"]["fetched_at"]
    finally:
        await _cleanup(seed)


async def test_confirmed_voyage_needs_revert_confirmed(migrated_db, app_fresh_engine):
    """IT-FILL-004 — 확정 항차는 ``revert_confirmed`` 없이 422이고 아무것도 바뀌지 않는다.

    있으면 되돌리기(``VOYAGE_TRANSITION`` CONFIRMED→COMPLETED) → 채움(``VOYAGE_ACTUALS_FILL``)이
    남고, 항차는 ``COMPLETED``로 남는다 — 재확정은 사용자가 `2-8`에서 한다.
    """
    seed = await _seed("CONFIRMED")
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            headers = _csrf(client)

            refused = client.post(seed.fill_url(), json=_body(seed), headers=headers)
            assert refused.status_code == 422, refused.text
            unchanged = await _voyage_row(seed)
            assert unchanged["status"] == "CONFIRMED"
            assert _same_instant(unchanged["actual_departure_at"], _ENTERED_DEPARTURE)
            assert unchanged["actual_departure_source"] is None
            assert await _events(seed) == []

            filled = client.post(
                seed.fill_url(), json=_body(seed, revert_confirmed=True), headers=headers
            )
            assert filled.status_code == 200, filled.text
            data = filled.json()["data"]
            assert data["reverted_from_status"] == "CONFIRMED"
            assert data["voyage"]["status"] == "COMPLETED"

        row = await _voyage_row(seed)
        assert row["status"] == "COMPLETED"
        assert _same_instant(row["actual_departure_at"], _RECORD_DEPARTURE)
        assert row["actual_departure_source"] == "PUBLIC_RECORD"

        events = await _events(seed)
        assert sorted(event["action"] for event in events) == [
            "VOYAGE_ACTUALS_FILL",
            "VOYAGE_TRANSITION",
        ]
        transition = next(e for e in events if e["action"] == "VOYAGE_TRANSITION")
        assert transition["details_json"]["from_status"] == "CONFIRMED"
        assert transition["details_json"]["to_status"] == "COMPLETED"
        fill = next(e for e in events if e["action"] == "VOYAGE_ACTUALS_FILL")
        assert fill["details_json"]["reverted_from_status"] == "CONFIRMED"
    finally:
        await _cleanup(seed)


async def test_a_failed_audit_leaves_nothing_behind(
    migrated_db, app_fresh_engine, monkeypatch: pytest.MonkeyPatch
):
    """IT-FILL-005 — 감사 INSERT가 실패하면 되돌림도 값 변경도 남지 않는다(한 트랜잭션)."""
    from cii_platform.db.repositories import audit_log as audit_repo

    seed = await _seed("CONFIRMED")
    try:
        with TestClient(app, base_url=_BASE, raise_server_exceptions=False) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200

            # 로그인 뒤에 깨뜨린다 — dev-login도 같은 함수로 LOGIN_SUCCESS를 적는다.
            async def boom(*_args, **_kwargs):
                raise RuntimeError("audit_log INSERT 실패 주입 (#1923)")

            monkeypatch.setattr(audit_repo, "insert_event", boom)
            response = client.post(
                seed.fill_url(), json=_body(seed, revert_confirmed=True), headers=_csrf(client)
            )
            assert response.status_code == 500, response.text

        row = await _voyage_row(seed)
        assert row["status"] == "CONFIRMED"
        assert _same_instant(row["actual_departure_at"], _ENTERED_DEPARTURE)
        assert row["actual_departure_source"] is None
    finally:
        monkeypatch.undo()
        await _cleanup(seed)


async def test_refusals_change_nothing(migrated_db, app_fresh_engine):
    """IT-FILL-006 — 없는 기록 404 · 다른 배의 기록 422 · 화면이 본 값과 다름 409."""
    seed = await _seed("COMPLETED")
    other = await _seed("COMPLETED")
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            headers = _csrf(client)

            missing = client.post(
                seed.fill_url(),
                json={**_body(seed), "record": {**seed.record_key, "call_seq": "ZZZ"}},
                headers=headers,
            )
            assert missing.status_code == 404, missing.text

            # 다른 배(다른 호출부호)의 기항을 이 항차에 옮기려 한다.
            foreign = client.post(
                seed.fill_url(),
                json={**_body(seed), "record": other.record_key},
                headers=headers,
            )
            assert foreign.status_code == 422, foreign.text
            assert foreign.json()["error"]["details"][0]["field"] == "record"

            # 화면이 본 뒤 수집기가 정정본을 받았다 — 사용자가 확인한 값이 아니다.
            stale = client.post(
                seed.fill_url(),
                json={**_body(seed), "recorded_at": "2026-03-01T13:00:00+00:00"},
                headers=headers,
            )
            assert stale.status_code == 409, stale.text

            # 항차 칸에 정박 구간을 보내면 422 — 어느 행을 고칠지 모호하다.
            ambiguous = client.post(
                seed.fill_url(),
                json=_body(seed, period_id=str(uuid.uuid4())),
                headers=headers,
            )
            assert ambiguous.status_code == 422, ambiguous.text

        row = await _voyage_row(seed)
        assert _same_instant(row["actual_departure_at"], _ENTERED_DEPARTURE)
        assert row["actual_departure_source"] is None
        assert await _events(seed) == []
    finally:
        await _cleanup(seed)
        await _cleanup(other)


async def test_human_edit_resets_the_source_only_when_the_value_changes(
    migrated_db, app_fresh_engine
):
    """IT-FILL-007 — 채운 뒤 사람이 **다른 시각**을 넣으면 출처는 NULL, 같은 시각을 다시 보낸
    저장은 출처를 지우지 않는다.

    실적 폼은 저장된 시각을 미리 채워 두고 저장 때 그대로 보낸다 — 연료만 고친 저장이
    「공적 기록에서 채움」을 지우면 사용자가 고치지 않은 시각의 출처가 사라진다.
    """
    seed = await _seed("COMPLETED")
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            headers = _csrf(client)
            assert (
                client.post(seed.fill_url(), json=_body(seed), headers=headers).status_code == 200
            )

            actuals = f"{seed.voyage_url()}/actuals"
            resent = client.put(
                actuals,
                json={
                    "actual_departure_at": _RECORD_DEPARTURE.isoformat(),
                    "actual_distance_nm": 2881,
                },
                headers=headers,
            )
            assert resent.status_code == 200, resent.text
            assert resent.json()["data"]["actual_departure_source"] == "PUBLIC_RECORD"

            edited = client.put(
                actuals,
                json={"actual_departure_at": "2026-03-01T11:00:00+00:00"},
                headers=headers,
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["data"]["actual_departure_source"] is None

            # 사람이 넣는 경로는 PUBLIC_RECORD를 붙이지 못한다(확인 A — 서버만 붙인다).
            claimed = client.put(
                actuals,
                json={
                    "actual_departure_at": _RECORD_DEPARTURE.isoformat(),
                    "actual_departure_source": "PUBLIC_RECORD",
                },
                headers=headers,
            )
            assert claimed.status_code == 422, claimed.text

        row = await _voyage_row(seed)
        assert row["actual_departure_source"] is None
    finally:
        await _cleanup(seed)


async def test_berth_start_is_filled_on_the_period(migrated_db, app_fresh_engine):
    """IT-FILL-008 — 정박 구간 시작을 채우면 그 구간의 ``started_at_source``만 바뀌고,
    구간 수정(``§2.11``)으로 다른 시각을 넣으면 NULL로 돌아간다."""
    seed = await _seed("COMPLETED", with_period=True)
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            headers = _csrf(client)

            _, mismatches = _data_quality_mismatches(client, seed)
            berth = [m for m in mismatches if m["field"] == "BERTH_START"]
            assert len(berth) == 1, mismatches
            assert uuid.UUID(berth[0]["period_id"]) == uuid.UUID(seed.period_id)

            # 정박 칸에 구간을 빼면 422 — 어느 구간인지 모른다.
            no_period = client.post(
                seed.fill_url(), json=_body(seed, "BERTH_START"), headers=headers
            )
            assert no_period.status_code == 422, no_period.text

            response = client.post(
                seed.fill_url(),
                json=_body(seed, "BERTH_START", period_id=berth[0]["period_id"]),
                headers=headers,
            )
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            assert data["period"]["started_at_source"] == "PUBLIC_RECORD"
            assert data["period"]["ended_at_source"] is None
            assert data["voyage"]["actual_departure_source"] is None

            period_url = f"{API_V1_PREFIX}/not-underway-periods/{uuid.UUID(seed.period_id)}"
            edited = client.patch(
                period_url, json={"started_at": "2026-02-28T19:00:00+00:00"}, headers=headers
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["data"]["started_at_source"] is None

        period = await _row(
            "SELECT started_at, started_at_source, ended_at_source FROM not_underway_period "
            "WHERE id = :id",
            id=seed.period_id,
        )
        assert period["started_at_source"] is None
        assert period["ended_at_source"] is None
        [event] = await _events(seed)
        assert event["details_json"]["target"] == "not_underway_period"
        assert uuid.UUID(event["details_json"]["period_id"]) == uuid.UUID(seed.period_id)
    finally:
        await _cleanup(seed)
