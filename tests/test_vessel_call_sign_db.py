"""``vessel.call_sign`` — 호출부호 칸의 DB·HTTP 계약 (#1197 A단계 · 마이그레이션 ``058``).

**막으려는 것은 대조 키가 조용히 갈리는 것이다.** 공공데이터(``해양수산부_선박운항정보``)는
IMO가 아니라 호출부호로 질의하므로, 저장된 값이 ``hlxq``·``HLXQ ``처럼 흩어지면 B단계의
교차 대조가 **아무 말 없이 빈다.** 그래서 두 층을 본다 —

1. **DB 트리거** ``trg_chk_call_sign_ins/upd`` — API를 거치지 않은 행(시드·복원·수기 SQL)도
   ``^[A-Z0-9]{4,7}$`` 밖이면 들어가지 않는다. CUBRID는 CHECK를 검사하지 않으므로
   (``DB_SCHEMA §7.4``) 실제로 위반을 넣어 보고 거부되는지만 본다.
2. **HTTP 왕복** — 등록 → 수정 → 조회가 접힌 값(strip · upper)을 그대로 돌려준다. 대역
   테스트(``test_vessels_api.py``)는 응답 조립만 보므로 실제 컬럼에 닿는지는 여기서 본다
   (`#433`의 교훈 — 응답 필드는 HTTP에서 확인한다).

케이스: DB-CHK-022 (`TEST_PLAN §5.1`)

## 데이터를 남기지 않는다

``TestClient``는 실제로 커밋한다(``test_input_boundaries_api_db.py``와 같다). 전용 IMO로
만들고 ``finally``에서 지운다. 트리거 검사는 ``conn`` fixture의 트랜잭션 안이라 롤백된다.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.api.main import API_V1_PREFIX, app

_BASE = "https://testserver"


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``8``로 시작한다."""
    return f"8{uuid.uuid4().int % 1_000_000:06d}"


async def _insert_vessel(conn: AsyncConnection, call_sign: str | None) -> str:
    vessel_id = uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, call_sign) "
            "VALUES (:id, :imo, 'CALL SIGN TEST', 'BULK_CARRIER', :cs)"
        ),
        {"id": vessel_id, "imo": _imo(), "cs": call_sign},
    )
    return vessel_id


# ---------------------------------------------------------------------------
# 1. 트리거
# ---------------------------------------------------------------------------


async def test_triggers_exist(conn: AsyncConnection):
    """058이 만든 트리거 둘이 DB에 실재한다 — 이름이 바뀌면 downgrade가 엉뚱한 것을 지운다."""
    rows = await conn.execute(
        text("SELECT name FROM db_trigger WHERE name LIKE 'trg_chk_call_sign_%'")
    )
    assert {row[0] for row in rows} == {"trg_chk_call_sign_ins", "trg_chk_call_sign_upd"}


async def _stored_call_sign(conn: AsyncConnection, vessel_id: str) -> str | None:
    return await conn.scalar(text("SELECT call_sign FROM vessel WHERE id = :id"), {"id": vessel_id})


@pytest.mark.parametrize("value", ["HLXQ", "HLXQ7", "3F1234", "KRA1234", None])
async def test_valid_shapes_and_null_are_accepted(conn: AsyncConnection, value):
    """RR No.19.55의 네 형식(4~7자)과 「모른다」(NULL)는 들어간다."""
    vessel_id = await _insert_vessel(conn, value)
    assert await _stored_call_sign(conn, vessel_id) == value


@pytest.mark.parametrize(
    "value",
    [
        "ABC",  # 3자
        "hlxq",  # 소문자 — REGEXP BINARY라 거부된다(050 실측과 같다)
        "HL-XQ",  # 기호
        "HLXQ ",  # 뒤 공백
    ],
)
async def test_insert_rejects_bad_shape(conn: AsyncConnection, value):
    """DB-CHK-022 — API를 거치지 않은 INSERT도 형식 밖이면 거부된다."""
    with pytest.raises(IntegrityError, match="trg_chk_call_sign_ins"):
        await _insert_vessel(conn, value)


async def test_eight_chars_die_at_the_column_before_the_trigger(conn: AsyncConnection):
    """8자는 ``VARCHAR(7)``이 먼저 거부한다 — 트리거까지 가지 않는다(실측 ``ProgrammingError``).

    어느 층이 막든 들어가지 않는다는 사실만 고정한다. 트리거 이름으로 매치하면 이 검사가
    거짓 실패한다(2026-09-20 실측).
    """
    with pytest.raises(DBAPIError):
        await _insert_vessel(conn, "ABCDEFGH")


async def test_update_rejects_bad_shape(conn: AsyncConnection):
    """UPDATE 쪽 트리거도 같은 식이다 — INSERT만 막으면 수기 UPDATE로 뚫린다."""
    vessel_id = await _insert_vessel(conn, "HLXQ")
    with pytest.raises(IntegrityError, match="trg_chk_call_sign_upd"):
        await conn.execute(
            text("UPDATE vessel SET call_sign = 'hl xq' WHERE id = :id"), {"id": vessel_id}
        )


async def test_first_two_digits_are_a_schema_rule_not_a_trigger_rule(conn: AsyncConnection):
    """「앞 두 글자가 모두 숫자가 아니다」(RR No.19.50)는 **API만** 본다 — 의도한 느슨함.

    DB는 ``^[A-Z0-9]{4,7}$``만 보므로 ``12AB``가 들어간다. 배정 관행이 나라마다 달라 세부
    규칙을 DB에 박으면 실재하는 부호를 거부할 수 있다(058 본문). 이 검사는 그 경계를
    고정한다 — DB가 더 엄격해지면 여기서 드러난다.
    """
    vessel_id = await _insert_vessel(conn, "12AB")
    assert await _stored_call_sign(conn, vessel_id) == "12AB"


# ---------------------------------------------------------------------------
# 2. HTTP 왕복
# ---------------------------------------------------------------------------


async def _cleanup(vessel_id: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": uuid.UUID(vessel_id)})
        await s.commit()


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def test_create_patch_get_round_trip(migrated_db, app_fresh_engine):
    """등록(소문자·공백) → 수정 → 조회가 접힌 값을 실제 컬럼에서 돌려준다."""
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            created = client.post(
                f"{API_V1_PREFIX}/vessels",
                json={
                    "imo_number": _imo(),
                    "name": "CALL SIGN ROUND TRIP",
                    "ship_type": "BULK_CARRIER",
                    "call_sign": " hlxq ",
                },
                headers=_csrf(client),
            )
            assert created.status_code == 201, created.text
            vessel_id = created.json()["data"]["id"]
            assert created.json()["data"]["call_sign"] == "HLXQ"

            patched = client.patch(
                f"{API_V1_PREFIX}/vessels/{vessel_id}",
                json={"call_sign": "d5ab123"},
                headers=_csrf(client),
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["data"]["call_sign"] == "D5AB123"

            fetched = client.get(f"{API_V1_PREFIX}/vessels/{vessel_id}")
            assert fetched.status_code == 200
            assert fetched.json()["data"]["call_sign"] == "D5AB123"

            # 형식 위반은 422이고 저장값은 그대로다.
            bad = client.patch(
                f"{API_V1_PREFIX}/vessels/{vessel_id}",
                json={"call_sign": "12AB"},
                headers=_csrf(client),
            )
            assert bad.status_code == 422, bad.text
            assert bad.json()["error"]["details"][0]["field_label"] == "호출부호"
            after_bad = client.get(f"{API_V1_PREFIX}/vessels/{vessel_id}").json()["data"]
            assert after_bad["call_sign"] == "D5AB123"
    finally:
        if vessel_id is not None:
            await _cleanup(vessel_id)
