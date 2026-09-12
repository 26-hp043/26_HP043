"""선대 요약의 항로 좌표 (#763) — 지도가 항로선을 그리는 근거.

케이스: IT-MAP-001 ~ IT-MAP-005 (`TEST_PLAN §3.16`)

지도는 **진행 중 항차의 출발·도착 좌표**로 대권선을 그린다. 여기서 보는 것은 그
좌표가 어떤 규율로 실리는가다:

* 진행 중 항차가 없으면 ``None`` — **없는 항로를 지어내지 않는다**
* 좌표가 한쪽이라도 비면 ``None`` — **반쪽 선분은 배가 어디로 가는지 잘못 말한다**
* 여러 선박을 물어도 **쿼리가 늘지 않는다** — 이 엔드포인트는 방금 쿼리 수를 줄여
  놓은 자리다(`#989`)
* 선박당 하나만, ``find_in_progress``와 **같은 규칙**으로 고른다
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.services.fleet_summary import _route_of

AS_OF = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _insert_vessel(session, imo: str) -> UUID:
    row = await session.execute(
        text(
            "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight) "
            f"VALUES ('{imo}', 'MAP TEST {imo}', 'BULK_CARRIER', 30000, 50000) RETURNING id"
        )
    )
    return row.scalar_one()


async def _insert_voyage(
    session,
    vessel_id: UUID,
    *,
    status: str = "IN_PROGRESS",
    departed_at: str | None = "2026-08-01T00:00:00+00:00",
    coords: tuple[str, str, str, str] | None = ("35.1", "129.0333", "1.2833", "103.85"),
) -> str:
    columns = [
        "vessel_id",
        "status",
        "annual_inclusion_policy",
        "regulation_year",
        "departure_port_name",
        "arrival_port_name",
        "planned_distance_nm",
        "planned_speed_kn",
    ]
    values = [
        f"'{vessel_id}'::uuid",
        f"'{status}'",
        "'INCLUDE_AS_PLAN'" if status == "IN_PROGRESS" else "'INCLUDE_AS_ACTUAL'",
        "2026",
        "'BUSAN'",
        "'SINGAPORE'",
        "4200.00",
        "12.0",
    ]
    if departed_at is not None:
        columns.append("actual_departure_at")
        values.append(f"'{departed_at}'")
    if coords is not None:
        columns += ["departure_lat", "departure_lon", "arrival_lat", "arrival_lon"]
        values += list(coords)
    row = await session.execute(
        text(f"INSERT INTO voyage ({', '.join(columns)}) VALUES ({', '.join(values)}) RETURNING id")
    )
    return str(row.scalar_one())


@pytest.mark.asyncio
async def test_route_carries_both_ends(session):
    """IT-MAP-001 — 진행 중 항차의 네 좌표가 그대로 실린다."""
    vessel_id = await _insert_vessel(session, "7400101")
    await _insert_voyage(session, vessel_id)

    found = await voyage_repo.find_in_progress_for_vessels(session, [vessel_id])
    route = _route_of(found.get(vessel_id))

    assert route == {
        "departure_lat": "35.100000",
        "departure_lon": "129.033300",
        "arrival_lat": "1.283300",
        "arrival_lon": "103.850000",
    }


@pytest.mark.asyncio
async def test_a_half_route_is_not_drawn(session):
    """IT-MAP-002 — 좌표가 한쪽이라도 비면 ``None``이다.

    반쪽 선분을 그리면 **배가 어디로 가는지 잘못 말하고**, 화면은 그 사실을 알 수 없다.
    """
    vessel_id = await _insert_vessel(session, "7400102")
    await _insert_voyage(session, vessel_id, coords=None)

    found = await voyage_repo.find_in_progress_for_vessels(session, [vessel_id])

    assert _route_of(found.get(vessel_id)) is None


@pytest.mark.asyncio
async def test_no_in_progress_voyage_means_no_route(session):
    """IT-MAP-003 — 진행 중 항차가 없으면 ``None``. 없는 항로를 지어내지 않는다."""
    vessel_id = await _insert_vessel(session, "7400103")
    await _insert_voyage(session, vessel_id, status="COMPLETED")

    found = await voyage_repo.find_in_progress_for_vessels(session, [vessel_id])

    assert vessel_id not in found
    assert _route_of(None) is None


@pytest.mark.asyncio
async def test_one_query_for_the_whole_fleet(session):
    """IT-MAP-004 — 선박이 늘어도 **쿼리는 한 번**이다.

    척마다 물으면 200척에 200쿼리가 붙는데, 이 엔드포인트는 방금 쿼리 수를 줄여 놓은
    자리다(`#989` — 212쿼리 → 129쿼리). 성능 회귀를 여기서 막는다.
    """
    ids = [await _insert_vessel(session, f"740020{i}") for i in range(3)]
    for vessel_id in ids:
        await _insert_voyage(session, vessel_id)

    seen: list[str] = []
    original = session.execute

    async def counting(statement, *args, **kwargs):
        seen.append(str(statement))
        return await original(statement, *args, **kwargs)

    session.execute = counting  # type: ignore[method-assign]
    try:
        found = await voyage_repo.find_in_progress_for_vessels(session, ids)
    finally:
        session.execute = original  # type: ignore[method-assign]

    assert len(found) == 3
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_the_latest_departure_wins(session):
    """IT-MAP-005 — 선박당 하나만, **가장 최근 출항분**을 고른다.

    ``find_in_progress``와 **같은 규칙**이어야 한다 — 두 경로가 다른 항차를 고르면
    같은 화면의 두 값이 서로 다른 항차를 가리킨다.
    """
    vessel_id = await _insert_vessel(session, "7400301")
    await _insert_voyage(
        session,
        vessel_id,
        departed_at="2026-07-01T00:00:00+00:00",
        coords=("10.0", "10.0", "20.0", "20.0"),
    )
    await _insert_voyage(
        session,
        vessel_id,
        departed_at="2026-08-01T00:00:00+00:00",
        coords=("35.1", "129.0333", "1.2833", "103.85"),
    )

    bulk = await voyage_repo.find_in_progress_for_vessels(session, [vessel_id])
    single = await voyage_repo.find_in_progress(session, bulk[vessel_id].vessel_id)

    assert bulk[vessel_id].id == single.id
    assert _route_of(bulk[vessel_id])["departure_lat"] == "35.100000"
