"""이슈 #346 vessel 위치·운항 상태 컬럼 마이그레이션 검증.

완료 기준(이슈 #346):
- 5개 컬럼이 추가되고 downgrade로 원복됨 (zz_roundtrip이 전체를 담당)
- 허용값 외 값이 거부됨 — ``underway_state`` 2값·``detail_status`` 7값·위경도 범위
- 기존 선박 3척이 NULL 상태로 정상 조회됨 (018 seed)

정합 규칙 (마이그레이션 026 CHECK — UIFLOW v2.0 §2-4 표):
- 상태 페어 — 둘 다 NULL 또는 ``SAILING``↔``UNDER_WAY``·나머지 6값↔``NOT_UNDER_WAY``
- 위치 페어 — 위도·경도는 같이 있고, 위치가 있으면 ``position_updated_at`` 필수
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _insert_vessel(conn, imo="1234567") -> str:
    row = await conn.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type) "
            "VALUES (:imo, 'TEST VESSEL', 'BULK_CARRIER') RETURNING id"
        ),
        {"imo": imo},
    )
    return str(row.scalar_one())


async def _update_state(conn, vessel_id: str, set_clause: str) -> None:
    await conn.execute(text(f"UPDATE vessel SET {set_clause} WHERE id = '{vessel_id}'::uuid"))


@pytest.mark.asyncio
async def test_seed_vessels_query_ok_with_null_state(conn):
    """018 seed 3척이 NULL 상태로 정상 조회된다 (완료 기준 3).

    위치·상태를 모르는 미갱신 선박이 조회에서 깨지지 않는 것이 026의 NULL 허용
    설계의 핵심이다.
    """
    rows = await conn.execute(
        text(
            "SELECT count(*), "
            "count(underway_state) + count(detail_status) + count(current_lat) "
            "+ count(current_lon) + count(position_updated_at) "
            "FROM vessel"
        )
    )
    total, non_null_new_columns = rows.one()
    assert total >= 3, "018 seed 선박 3척이 보이지 않음"
    assert non_null_new_columns == 0, "새 컬럼은 기존 행에서 전부 NULL이어야 함"


@pytest.mark.asyncio
async def test_valid_state_combinations_accepted(conn):
    """유효 조합 8종(미설정 + SAILING/UNDER_WAY + 6값/NOT_UNDER_WAY)은 저장된다."""
    valid = [
        (None, None),
        ("UNDER_WAY", "SAILING"),
        ("NOT_UNDER_WAY", "IN_PORT"),
        ("NOT_UNDER_WAY", "AT_ANCHOR"),
        ("NOT_UNDER_WAY", "DRIFTING"),
        ("NOT_UNDER_WAY", "STS"),
        ("NOT_UNDER_WAY", "CANAL_TRANSIT"),
        ("NOT_UNDER_WAY", "DRYDOCK"),
    ]
    for i, (underway, detail) in enumerate(valid):
        vessel_id = await _insert_vessel(conn, imo=f"100000{i}")
        set_clause = (
            "underway_state = NULL, detail_status = NULL"
            if underway is None
            else f"underway_state = '{underway}', detail_status = '{detail}'"
        )
        await _update_state(conn, vessel_id, set_clause)
        row = await conn.execute(
            text(f"SELECT underway_state, detail_status FROM vessel WHERE id = '{vessel_id}'::uuid")
        )
        result = row.one()
        assert result.underway_state == underway
        assert result.detail_status == detail


@pytest.mark.asyncio
async def test_underway_state_rejects_unknown_value(conn):
    """underway_state 허용값 2종 밖은 거부된다."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _update_state(conn, vessel_id, "underway_state = 'MAYBE'")


@pytest.mark.asyncio
async def test_detail_status_rejects_unknown_value(conn):
    """detail_status 허용값 7종 밖은 거부된다 (period_type의 6값 + SAILING)."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _update_state(conn, vessel_id, "detail_status = 'STEAMING'")


@pytest.mark.asyncio
async def test_sailing_requires_underway_pair(conn):
    """SAILING ↔ UNDER_WAY 정합 — SAILING에 NOT_UNDER_WAY는 거부된다."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _update_state(
            conn, vessel_id, "underway_state = 'NOT_UNDER_WAY', detail_status = 'SAILING'"
        )


@pytest.mark.asyncio
async def test_at_anchor_requires_not_underway_pair(conn):
    """IN_PORT ↔ NOT_UNDER_WAY 정합 — IN_PORT에 UNDER_WAY는 거부된다."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _update_state(
            conn, vessel_id, "underway_state = 'UNDER_WAY', detail_status = 'IN_PORT'"
        )


@pytest.mark.asyncio
async def test_half_set_state_rejected(conn):
    """반쪽 상태(한 축만 설정)는 거부된다."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _update_state(conn, vessel_id, "underway_state = 'UNDER_WAY'")


@pytest.mark.asyncio
async def test_lat_above_90_rejected(conn):
    """위도가 90을 넘으면 거부된다 (chk_vessel_lat_range).

    conn fixture는 단일 트랜잭션이라 제약 위반이 서버 트랜잭션을 abort시킨다 —
    실패 문장은 테스트당 하나씩만 둔다 (#96 선례).
    """
    vessel_id = await _insert_vessel(conn)
    ts = "'2026-08-15T00:00:00+00'::timestamptz"

    with pytest.raises(IntegrityError):
        await _update_state(
            conn,
            vessel_id,
            f"current_lat = 90.000001, current_lon = 0, position_updated_at = {ts}",
        )


@pytest.mark.asyncio
async def test_lon_below_minus_180_rejected(conn):
    """경도가 −180 미만이면 거부된다 (chk_vessel_lon_range)."""
    vessel_id = await _insert_vessel(conn)
    ts = "'2026-08-15T00:00:00+00'::timestamptz"

    with pytest.raises(IntegrityError):
        await _update_state(
            conn,
            vessel_id,
            f"current_lat = 0, current_lon = -180.000001, position_updated_at = {ts}",
        )


@pytest.mark.asyncio
async def test_lat_lon_boundary_values_accepted(conn):
    """경계값(±90·±180) 자체는 저장된다."""
    vessel_id = await _insert_vessel(conn)
    ts = "'2026-08-15T00:00:00+00'::timestamptz"

    await _update_state(
        conn, vessel_id, f"current_lat = 90, current_lon = -180, position_updated_at = {ts}"
    )
    row = await conn.execute(
        text(f"SELECT current_lat, current_lon FROM vessel WHERE id = '{vessel_id}'::uuid")
    )
    assert row.one() == (90, -180)


@pytest.mark.asyncio
async def test_position_requires_timestamp(conn):
    """위치가 있는데 position_updated_at이 없으면 거부된다 (UIFLOW §2-8 표시 계약)."""
    vessel_id = await _insert_vessel(conn)

    with pytest.raises(IntegrityError):
        await _update_state(conn, vessel_id, "current_lat = 35.1, current_lon = 129.0")


@pytest.mark.asyncio
async def test_half_position_rejected(conn):
    """위도만·경도만 있는 반쪽 위치는 거부된다."""
    vessel_id = await _insert_vessel(conn)
    ts = "'2026-08-15T00:00:00+00'::timestamptz"

    with pytest.raises(IntegrityError):
        await _update_state(conn, vessel_id, f"current_lat = 35.1, position_updated_at = {ts}")
