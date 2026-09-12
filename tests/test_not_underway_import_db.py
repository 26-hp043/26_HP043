"""not under way 구간 CSV 가져오기 (``API_SPEC §8.2`` · `#765`).

`API_SPEC §2.9` 각주가 *「CSV 가져오기는 항차만 다루므로 이 경로를 대신하지 않는다」*고
적어 두었다 — 정박 연료는 **CII의 분자에 들어가는데**(`MEPC.412(84) §4.2`) 넣는 길이 한 건씩
누르는 화면뿐이었다. 그래서 안 넣게 되고, 그 결과가 「정박해도 등급이 안 떨어지는」 상태다.

여기서 보는 것 넷이다.

1. **실제로 들어가는가** — 구간과 연료가 함께 저장되고 CF 스냅샷이 붙는가
2. **부분 성공** — 한 행이 틀려도 나머지는 들어가고, 틀린 행의 **번호와 사유**가 나오는가
3. **겹치면 거부** — 시간대가 겹치는 구간을 받으면 같은 연료가 두 번 세어진다
4. **시간대 없는 값 거부** — 서버 시간대로 읽으면 9시간 어긋난 구간이 들어간다

케이스: IT-CSV-009 ~ IT-CSV-013 (`TEST_PLAN §3.4`)
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.not_underway_import import import_not_underway_periods

HEADER = "period_type,started_at,ended_at,distance_nm,fuel_type,fuel_ton,consumer_type,port_name\n"
IMO = "9999123"


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session):
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
            "reference_speed_kn) VALUES "
            "(:imo, 'NU IMPORT TEST', 'BULK_CARRIER', 30000, 50000, 14.0) RETURNING id"
        ),
        {"imo": IMO},
    )
    return row.scalar_one()


def _csv(*rows: str) -> bytes:
    return (HEADER + "".join(row + "\n" for row in rows)).encode("utf-8")


async def test_periods_and_fuel_are_stored(session, vessel_id):
    """IT-CSV-009 — 구간과 연료가 함께 들어가고 CF 스냅샷이 붙는다."""
    content = _csv(
        "IN_PORT,2026-03-01T00:00:00+09:00,2026-03-02T00:00:00+09:00,0,HFO,12.5,AUX_ENGINE,BUSAN",
        "AT_ANCHOR,2026-03-05T00:00:00+09:00,2026-03-06T00:00:00+09:00,3.5,HFO,4,,",
    )

    result = await import_not_underway_periods(session, vessel_id, content=content)

    assert result["imported_count"] == 2
    assert result["errors"] == []
    rows = (
        await session.execute(
            text(
                "SELECT p.period_type, p.distance_nm, f.fuel_ton, f.cf_used, f.consumer_type "
                "FROM not_underway_period p JOIN not_underway_fuel_use f ON f.period_id = p.id "
                "WHERE p.vessel_id = :vid ORDER BY p.started_at"
            ),
            {"vid": vessel_id},
        )
    ).all()
    assert [r.period_type for r in rows] == ["IN_PORT", "AT_ANCHOR"]
    assert float(rows[1].distance_nm) == 3.5
    # 비운 소비원은 보조기관이다 — 정박 중 연료의 대부분이 그것이다.
    assert rows[1].consumer_type == "AUX_ENGINE"
    # CF는 적재 시점 스냅샷이다 (`#378`·`PRD §8.4`).
    assert float(rows[0].cf_used) > 0


async def test_one_bad_row_does_not_sink_the_file(session, vessel_id):
    """IT-CSV-010 — 부분 성공. 틀린 행의 **번호와 사유**가 나온다."""
    content = _csv(
        "IN_PORT,2026-04-01T00:00:00+09:00,2026-04-02T00:00:00+09:00,0,HFO,10,,",
        "HOVERING,2026-04-05T00:00:00+09:00,,0,HFO,1,,",
        "IN_PORT,2026-04-10T00:00:00+09:00,2026-04-11T00:00:00+09:00,0,NOSUCHFUEL,1,,",
    )

    result = await import_not_underway_periods(session, vessel_id, content=content)

    assert result["imported_count"] == 1
    assert [e["row"] for e in result["errors"]] == [3, 4]
    assert result["errors"][0]["field"] == "period_type"
    assert result["errors"][1]["field"] == "fuel_type"


async def test_overlapping_periods_are_refused_row_by_row(session, vessel_id):
    """IT-CSV-011 — 겹치면 그 행만 떨어진다. 겹침을 받으면 연료가 두 번 세어진다."""
    content = _csv(
        "IN_PORT,2026-05-01T00:00:00+09:00,2026-05-03T00:00:00+09:00,0,HFO,10,,",
        "IN_PORT,2026-05-02T00:00:00+09:00,2026-05-04T00:00:00+09:00,0,HFO,10,,",
    )

    result = await import_not_underway_periods(session, vessel_id, content=content)

    assert result["imported_count"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["row"] == 3
    assert result["overlap_checked"] is True


async def test_naive_timestamps_are_refused(session, vessel_id):
    """IT-CSV-012 — 시간대가 없으면 거부한다(`#906`과 같은 규칙)."""
    content = _csv("IN_PORT,2026-06-01T00:00:00,2026-06-02T00:00:00+09:00,0,HFO,10,,")

    result = await import_not_underway_periods(session, vessel_id, content=content)

    assert result["imported_count"] == 0
    assert "시간대" in result["errors"][0]["message"]


async def test_dry_run_stores_nothing_and_says_overlap_was_not_checked(session, vessel_id):
    """IT-CSV-013 — 검증만 한다. **겹침은 보지 않았다는 사실**을 응답이 말한다."""
    content = _csv("IN_PORT,2026-07-01T00:00:00+09:00,,0,HFO,10,,")

    result = await import_not_underway_periods(session, vessel_id, content=content, dry_run=True)

    assert result["imported_count"] == 1
    assert result["dry_run"] is True
    assert result["overlap_checked"] is False
    count = (
        await session.execute(
            text("SELECT count(*) FROM not_underway_period WHERE vessel_id = :vid"),
            {"vid": vessel_id},
        )
    ).scalar_one()
    assert count == 0


async def test_missing_required_column_rejects_the_whole_file(session, vessel_id):
    """IT-CSV-014 — 파일 단위 문제는 **한 행도 읽지 않는다**(항차 CSV와 같은 규칙)."""
    from cii_platform.errors import ValidationError

    content = b"period_type,started_at\nIN_PORT,2026-08-01T00:00:00+09:00\n"

    try:
        await import_not_underway_periods(session, vessel_id, content=content)
    except ValidationError as error:
        assert "필수 컬럼" in str(error)
    else:  # pragma: no cover - 실패 경로
        raise AssertionError("필수 컬럼이 없는 파일이 통과했다")
