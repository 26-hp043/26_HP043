"""``voyage.planned_distance_source`` — 계획 거리 출처의 DB·HTTP 계약 (#1256 · ``059``).

**막으려는 것은 「추정값입니다」가 거짓말이 되는 것이다.** ``PRD §15.2``는 좌표로 채운 거리에
「좌표 기반 추정 거리」를 붙이라고 정하는데, 저장된 항차에는 그 사실이 남지 않았다(#1052 ⓷).
컬럼이 생긴 뒤에도 두 방향으로 거짓말이 될 수 있다 —

* 사람이 직접 넣은 숫자에 「추정」이 붙는다(옛 출처가 새 숫자에 남는 경우 · 추측 backfill)
* 트리거 밖의 값이 들어가 화면이 모르는 출처를 만난다

그래서 두 층을 본다 —

1. **DB 트리거** ``trg_chk_planned_distance_source_ins/upd`` — API를 거치지 않은 행(시드·복원·
   수기 SQL)도 두 값과 NULL 밖이면 들어가지 않는다. CUBRID는 CHECK를 검사하지 않으므로
   (``DB_SCHEMA §7.4``) 실제로 위반을 넣어 보고 거부되는지만 본다.
2. **HTTP 왕복** — 생성 → 수정 → 조회가 출처를 실제 컬럼에서 돌려주고, **거리만 고친 PATCH가
   출처를 「모른다」로 돌리는지** 본다. 대역 테스트(``test_voyages_api.py``)는 응답 조립만 보므로
   실제 컬럼에 닿는지는 여기서 본다(`#433`의 교훈 — 응답 필드는 HTTP에서 확인한다).

케이스: DB-CHK-023 (`TEST_PLAN §5.1`)

## 데이터를 남기지 않는다

``TestClient``는 실제로 커밋한다(``test_vessel_call_sign_db.py``와 같다). 전용 IMO로 만들고
``finally``에서 항차 → 선박 순으로 지운다. 트리거 검사는 ``conn`` fixture의 트랜잭션 안이라
롤백된다.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.api.schemas.voyage import DISTANCE_SOURCES

_BASE = "https://testserver"


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``8``로 시작한다."""
    return f"8{uuid.uuid4().int % 1_000_000:06d}"


async def _insert_vessel(conn: AsyncConnection) -> str:
    vessel_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type) "
            "VALUES (:id, :imo, 'DISTANCE SOURCE TEST', 'BULK_CARRIER')"
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
            " planned_distance_source) "
            "VALUES (:id, :vid, 'DRAFT', 'EXCLUDE', 'BUSAN', 'SINGAPORE', 1000, 12, :src)"
        ),
        {"id": voyage_id, "vid": vessel_id, "src": source},
    )
    return voyage_id


async def _stored_source(conn: AsyncConnection, voyage_id: str) -> str | None:
    return await conn.scalar(
        text("SELECT planned_distance_source FROM voyage WHERE id = :id"), {"id": voyage_id}
    )


# ---------------------------------------------------------------------------
# 1. 트리거
# ---------------------------------------------------------------------------


async def test_triggers_exist(conn: AsyncConnection):
    """059가 만든 트리거 둘이 DB에 실재한다 — 이름이 바뀌면 downgrade가 엉뚱한 것을 지운다."""
    rows = await conn.execute(
        text("SELECT name FROM db_trigger WHERE name LIKE 'trg_chk_planned_distance_source_%'")
    )
    assert {row[0] for row in rows} == {
        "trg_chk_planned_distance_source_ins",
        "trg_chk_planned_distance_source_upd",
    }


@pytest.mark.parametrize("value", [*DISTANCE_SOURCES, None])
async def test_api_values_and_null_are_accepted(conn: AsyncConnection, value):
    """API 스키마가 받는 값 전부와 「모른다」(NULL)는 들어간다.

    스키마의 ``DISTANCE_SOURCES``를 그대로 돌린다 — 두 목록이 갈리면 API가 받은 값을
    트리거가 REJECT해 500이 되는데, 그것을 여기서 잡는다.
    """
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id, value)
    assert await _stored_source(conn, voyage_id) == value


@pytest.mark.parametrize(
    "value",
    [
        "MODEL_ESTIMATE",  # 연료 출처의 값 — 거리 출처가 아니다
        "user_input",  # 소문자
        "ESTIMATE",
        "",
    ],
)
async def test_insert_rejects_unknown_source(conn: AsyncConnection, value):
    """DB-CHK-023 — API를 거치지 않은 INSERT도 두 값 밖이면 거부된다."""
    vessel_id = await _insert_vessel(conn)
    with pytest.raises(IntegrityError, match="trg_chk_planned_distance_source_ins"):
        await _insert_voyage(conn, vessel_id, value)


async def test_update_rejects_unknown_source(conn: AsyncConnection):
    """UPDATE 쪽 트리거도 같은 식이다 — INSERT만 막으면 수기 UPDATE로 뚫린다."""
    vessel_id = await _insert_vessel(conn)
    voyage_id = await _insert_voyage(conn, vessel_id, "USER_INPUT")
    with pytest.raises(IntegrityError, match="trg_chk_planned_distance_source_upd"):
        await conn.execute(
            text("UPDATE voyage SET planned_distance_source = 'GUESS' WHERE id = :id"),
            {"id": voyage_id},
        )


# ---------------------------------------------------------------------------
# 2. HTTP 왕복
# ---------------------------------------------------------------------------


async def _cleanup(vessel_id: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        # 연료 행은 voyage 삭제에 CASCADE로 따라간다. 선박은 항차가 남아 있으면 RESTRICT다.
        await s.execute(
            text("DELETE FROM voyage WHERE vessel_id = :v"), {"v": uuid.UUID(vessel_id)}
        )
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": uuid.UUID(vessel_id)})
        await s.commit()


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


_VOYAGE = {
    "departure_port_name": "BUSAN",
    "departure_lat": 35.1,
    "departure_lon": 129.0333,
    "arrival_port_name": "SINGAPORE",
    "arrival_lat": 1.2833,
    "arrival_lon": 103.85,
    "planned_distance_nm": 2470.2,
    "planned_speed_kn": 14,
    "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 331}],
}


async def test_create_patch_get_round_trip(migrated_db, app_fresh_engine):
    """좌표 추정으로 만든 항차 → 거리만 고친 PATCH → 조회가 「모른다」를 실제 컬럼에서 돌려준다."""
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            vessel = client.post(
                f"{API_V1_PREFIX}/vessels",
                json={
                    "imo_number": _imo(),
                    "name": "DISTANCE SOURCE RT",
                    "ship_type": "BULK_CARRIER",
                },
                headers=_csrf(client),
            )
            assert vessel.status_code == 201, vessel.text
            vessel_id = vessel.json()["data"]["id"]

            created = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages",
                json={**_VOYAGE, "planned_distance_source": "COORDINATE_ESTIMATE"},
                headers=_csrf(client),
            )
            assert created.status_code == 201, created.text
            voyage_id = created.json()["data"]["id"]
            assert created.json()["data"]["planned_distance_source"] == "COORDINATE_ESTIMATE"

            # 거리만 고쳤다 — 옛 「추정」 표시가 새 숫자에 남아 있으면 거짓말이다.
            patched = client.patch(
                f"{API_V1_PREFIX}/voyages/{voyage_id}",
                json={"planned_distance_nm": 2600},
                headers=_csrf(client),
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["data"]["planned_distance_nm"] == 2600.0
            assert patched.json()["data"]["planned_distance_source"] is None

            fetched = client.get(f"{API_V1_PREFIX}/voyages/{voyage_id}")
            assert fetched.status_code == 200
            assert fetched.json()["data"]["planned_distance_source"] is None

            # 거리와 출처를 함께 보내면 그 출처가 붙는다.
            relabelled = client.patch(
                f"{API_V1_PREFIX}/voyages/{voyage_id}",
                json={"planned_distance_nm": 2650, "planned_distance_source": "USER_INPUT"},
                headers=_csrf(client),
            )
            assert relabelled.status_code == 200, relabelled.text
            listed = client.get(f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages").json()["data"]
            assert [row["planned_distance_source"] for row in listed] == ["USER_INPUT"]

            # 목록 밖의 값은 422이고 저장값은 그대로다.
            bad = client.patch(
                f"{API_V1_PREFIX}/voyages/{voyage_id}",
                json={"planned_distance_source": "GUESS"},
                headers=_csrf(client),
            )
            assert bad.status_code == 422, bad.text
            assert bad.json()["error"]["details"][0]["field_label"] == "계획 거리 출처"
            after_bad = client.get(f"{API_V1_PREFIX}/voyages/{voyage_id}").json()["data"]
            assert after_bad["planned_distance_source"] == "USER_INPUT"
    finally:
        if vessel_id is not None:
            await _cleanup(vessel_id)


async def test_create_without_source_is_unknown(migrated_db, app_fresh_engine):
    """출처 없이 거리만 보낸 생성은 「모른다」다 — 추정으로도 직접 입력으로도 적지 않는다."""
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            vessel = client.post(
                f"{API_V1_PREFIX}/vessels",
                json={
                    "imo_number": _imo(),
                    "name": "DISTANCE SOURCE NULL",
                    "ship_type": "BULK_CARRIER",
                },
                headers=_csrf(client),
            )
            assert vessel.status_code == 201, vessel.text
            vessel_id = vessel.json()["data"]["id"]

            created = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages", json=_VOYAGE, headers=_csrf(client)
            )
            assert created.status_code == 201, created.text
            assert "planned_distance_source" in created.json()["data"]
            assert created.json()["data"]["planned_distance_source"] is None
    finally:
        if vessel_id is not None:
            await _cleanup(vessel_id)
