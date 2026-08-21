"""이슈 #347 대시보드 시연용 시드 확장(027) 검증.

완료 기준(이슈 #347):
- 선박 4척 이상, GT 축 1척 이상 — test_demo_vessel_seed.py가 담당(4척·축 분포 고정)
- 대시보드에서 등급·상태가 서로 다른 선박이 보임 — 상태는 SQL로, 등급은 **실제
  calc 엔진**을 돌려 고정한다(경고 배너용 위험 선박 = E 등급 포함)
- 실시간 화면에 쓸 진행 중 항차가 존재함
- ``test_demo_vessel_seed`` 갱신 후 통과 — 같은 PR에서 갱신

기대값 독립 원칙(test_demo_vessel_seed와 동일): 027의 상수를 import하지 않고
이 파일에 전사한다. 등급 계산만 엔진·규제 상수(``cii_platform.db.seed``)를 직접
쓴다 — 등급은 시연 서사의 핵심이므로 전사 대신 실제 산출으로 잠근다.
"""

from types import SimpleNamespace

from sqlalchemy import text

from cii_platform.calc.capacity import (
    resolve_reference_capacity,
    resolve_transport_capacity,
    select_reference_line,
)
from cii_platform.calc.cii_engine import FuelUse, calculate_attained_cii, calculate_required_cii
from cii_platform.calc.rating_engine import DVector, determine_rating, select_rating_boundary
from cii_platform.db.seed import (
    SEED_RATING_BOUNDARIES,
    SEED_REFERENCE_LINES,
    SEED_Z_FACTORS,
)

VESSEL_IDS = {
    "bulk": "00000000-0000-4000-8000-000000000001",
    "container": "00000000-0000-4000-8000-000000000002",
    "general": "00000000-0000-4000-8000-000000000003",
    "ro_ro": "00000000-0000-4000-8000-000000000004",
}


async def test_all_seeded_vessels_have_state_and_position(conn):
    """4척 전부 운항 상태·위치를 갖는다 — 미갱신(NULL) 선박이 섞이지 않는다.

    대시보드 카드가 항상 상태를 표시할 수 있는 것이 시연의 전제다.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT count(*) FROM vessel "
                "WHERE underway_state IS NULL OR detail_status IS NULL "
                "OR current_lat IS NULL OR current_lon IS NULL "
                "OR position_updated_at IS NULL"
            )
        )
    ).scalar_one()
    assert rows == 0


async def test_operation_statuses_are_mixed(conn):
    """운항 중·운하 통과 중·묘박 중·접안이 섞여 있다 (이슈 체크리스트).

    4가지 ``detail_status``가 각 1척씩 — 카드 그리드가 서로 다르게 보이는 배분.
    """
    statuses = {
        row[0] for row in (await conn.execute(text("SELECT detail_status FROM vessel"))).all()
    }
    assert statuses == {"SAILING", "CANAL_TRANSIT", "AT_ANCHOR", "IN_PORT"}


async def test_every_vessel_has_two_year_history(conn):
    """4척 모두 2025·2026 두 연도에 COMPLETED 항차를 갖는다 (연도별 이력 화면용)."""
    rows = (
        await conn.execute(
            text(
                "SELECT vessel_id::text, count(DISTINCT regulation_year) "
                "FROM voyage "
                "WHERE status = 'COMPLETED' AND annual_inclusion_policy = 'INCLUDE_AS_ACTUAL' "
                "GROUP BY vessel_id"
            )
        )
    ).all()
    by_vessel = dict(rows)
    assert set(by_vessel) == set(VESSEL_IDS.values())
    assert all(years >= 2 for years in by_vessel.values()), by_vessel


async def test_in_progress_voyage_is_at_most_one_per_vessel(conn):
    """진행 중 항차는 **선박당 최대 1건**이고, 항해 중인 배는 반드시 하나 갖는다.

    종전 이 테스트는 *「정확히 1건 — 컨테이너선 회항」*으로 고정했다. 그것은 당시
    **시드 형상을 적은 것**이지 지켜야 할 성질이 아니었고, 그 사이에 실제 결함을
    가리고 있었다 — **벌크선이 ``UNDER_WAY / SAILING``인데 진행 중 항차가 없어**
    선박 상세는 「항해 중」, 실시간 CII는 「진행 중 항차가 없습니다」를 냈다 (#587).

    지켜야 할 것은 **한 배에 진행 중 항차가 둘이 아닌 것**이다. 둘이면
    ``2-9 실시간 CII``가 어느 항차를 보일지 모호해진다.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT v.vessel_id::text, v.annual_inclusion_policy, v.actual_arrival_at, "
                "f.actual_fuel_ton "
                "FROM voyage v "
                "LEFT JOIN voyage_fuel_use f ON f.voyage_id = v.id "
                "WHERE v.status = 'IN_PROGRESS'"
            )
        )
    ).all()

    by_vessel: dict[str, int] = {}
    for row in rows:
        by_vessel[row[0]] = by_vessel.get(row[0], 0) + 1
    assert all(count == 1 for count in by_vessel.values()), by_vessel

    # 발표 동선이 쓰는 두 배는 반드시 진행 중 항차를 갖는다.
    # 벌크선 = 위험 선박 드릴다운, 컨테이너선 = 운하 통과 서사.
    assert VESSEL_IDS["bulk"] in by_vessel
    assert VESSEL_IDS["container"] in by_vessel

    for row in rows:
        # 진행 중 항차의 정책은 INCLUDE_AS_PLAN (chk_status_policy가 강제).
        assert row[1] == "INCLUDE_AS_PLAN"
        # 아직 도착·실적은 없다 — 계획값만 존재.
        assert row[2] is None
        assert row[3] is None


async def test_completed_voyages_have_actuals(conn):
    """완료 항차 8건은 전부 실적(연료·거리)을 갖는다 — 연간 실적 집계의 입력."""
    rows = (
        await conn.execute(
            text(
                "SELECT count(*) FROM voyage v "
                "JOIN voyage_fuel_use f ON f.voyage_id = v.id "
                "WHERE v.status = 'COMPLETED' AND v.annual_inclusion_policy = 'INCLUDE_AS_ACTUAL'"
                " AND (f.actual_fuel_ton IS NULL OR v.actual_distance_nm IS NULL)"
            )
        )
    ).scalar_one()
    assert rows == 0


async def test_not_underway_samples_include_required_types(conn):
    """``DRYDOCK``·``CANAL_TRANSIT`` 포함 + consumer_type 4값 전부 (이슈 체크리스트)."""
    period_types = {
        row[0]
        for row in (await conn.execute(text("SELECT period_type FROM not_underway_period"))).all()
    }
    assert {"CANAL_TRANSIT", "DRYDOCK", "AT_ANCHOR"} <= period_types

    consumers = {
        row[0]
        for row in (
            await conn.execute(text("SELECT consumer_type FROM not_underway_fuel_use"))
        ).all()
    }
    assert consumers == {"MAIN_ENGINE", "AUX_ENGINE", "OIL_FIRED_BOILER", "OTHER"}

    # 진행 중 구간(ended_at NULL)이 있다 — 실시간 정박 악화 시연용.
    ongoing = await conn.scalar(
        text("SELECT count(*) FROM not_underway_period WHERE ended_at IS NULL")
    )
    assert ongoing == 2


async def test_canal_period_links_in_progress_voyage(conn):
    """운하 통과 구간이 진행 중 항차를 맥락 참조로 건다 — 상태(CANAL_TRANSIT)와 연결."""
    row = (
        await conn.execute(
            text(
                "SELECT p.voyage_id::text, v.status FROM not_underway_period p "
                "JOIN voyage v ON v.id = p.voyage_id "
                "WHERE p.period_type = 'CANAL_TRANSIT'"
            )
        )
    ).one()
    assert row[1] == "IN_PROGRESS"


async def _vessel_row(conn, vessel_id: str):
    row = (
        await conn.execute(
            text(
                "SELECT ship_type, deadweight, gross_tonnage FROM vessel "
                "WHERE id = CAST(:vid AS uuid)"
            ).bindparams(vid=vessel_id)
        )
    ).one()
    return SimpleNamespace(
        ship_type=row.ship_type,
        deadweight=row.deadweight,
        gross_tonnage=row.gross_tonnage,
    )


async def _rating_for_2026_completed_voyage(conn, vessel_id: str) -> str:
    """해당 선박의 2026년 COMPLETED 항차로 등급을 실제 계산한다.

    규제 파라미터는 ``cii_platform.db.seed`` 상수에서 온다(CI에서
    ``scripts/seed.py``가 적재되지 않으므로 상수 직접 사용).
    """
    vessel = await _vessel_row(conn, vessel_id)
    voyage = (
        await conn.execute(
            text(
                "SELECT v.actual_distance_nm, f.fuel_type, f.actual_fuel_ton, f.cf_used "
                "FROM voyage v JOIN voyage_fuel_use f ON f.voyage_id = v.id "
                "WHERE v.vessel_id = CAST(:vid AS uuid) AND v.status = 'COMPLETED' "
                "AND v.regulation_year = 2026",
            ).bindparams(vid=vessel_id)
        )
    ).one()

    ref_line = select_reference_line(vessel, SEED_REFERENCE_LINES)
    boundary = select_rating_boundary(vessel, SEED_RATING_BOUNDARIES)
    z_2026 = {row.year: row.z_factor_percent for row in SEED_Z_FACTORS}[2026]

    attained = calculate_attained_cii(
        [FuelUse(voyage.fuel_type, voyage.actual_fuel_ton, voyage.cf_used)],
        resolve_transport_capacity(vessel),
        voyage.actual_distance_nm,
    )
    required = calculate_required_cii(
        ref_line.a_decimal,
        ref_line.c,
        resolve_reference_capacity(vessel, ref_line),
        z_2026,
    )
    return determine_rating(
        attained.attained_cii,
        required.required_cii,
        DVector(boundary.d1, boundary.d2, boundary.d3, boundary.d4),
    ).rating


async def test_2026_ratings_are_mixed_with_risk_vessel(conn):
    """경고 배너 시연 조건 — 등급이 서로 다르고 위험 선박(E)이 최소 1척.

    벌크선이 E(연료 과다 620t/4,300nm), 나머지가 B~C여야 대시보드에서
    위험 선박이 식별된다. 등급은 표가 아니라 **실제 calc 엔진 산출**으로
    잠근다 — 값 조정이 등급을 바꾸면 이 테스트가 즉시 잡는다.
    """
    ratings = {
        key: await _rating_for_2026_completed_voyage(conn, vid) for key, vid in VESSEL_IDS.items()
    }
    assert ratings["bulk"] == "E", "위험 선박 서사 — 벌크선 2026은 E여야 한다"
    assert len(set(ratings.values())) >= 3, f"등급 다양성 부족: {ratings}"


async def test_bulk_vessel_deteriorates_2025_to_2026(conn):
    """위험 선박 서사 — 벌크선은 2025 D → 2026 E로 **악화**한다.

    「등급 하락」 배너(#352)의 시연 데이터가 연도 사이 악화 흐름을 담아야 한다.
    """
    vessel = await _vessel_row(conn, VESSEL_IDS["bulk"])
    ref_line = select_reference_line(vessel, SEED_REFERENCE_LINES)
    boundary = select_rating_boundary(vessel, SEED_RATING_BOUNDARIES)
    z_by_year = {row.year: row.z_factor_percent for row in SEED_Z_FACTORS}
    d_vector = DVector(boundary.d1, boundary.d2, boundary.d3, boundary.d4)

    ratings_by_year = {}
    rows = (
        await conn.execute(
            text(
                "SELECT v.regulation_year, v.actual_distance_nm, "
                "f.actual_fuel_ton, f.cf_used "
                "FROM voyage v JOIN voyage_fuel_use f ON f.voyage_id = v.id "
                "WHERE v.vessel_id = CAST(:vid AS uuid) AND v.status = 'COMPLETED'"
            ).bindparams(vid=VESSEL_IDS["bulk"])
        )
    ).all()
    for year, distance, fuel_ton, cf in rows:
        attained = calculate_attained_cii(
            [FuelUse("HFO", fuel_ton, cf)],
            resolve_transport_capacity(vessel),
            distance,
        )
        required = calculate_required_cii(
            ref_line.a_decimal,
            ref_line.c,
            resolve_reference_capacity(vessel, ref_line),
            z_by_year[year],
        )
        ratings_by_year[year] = determine_rating(
            attained.attained_cii, required.required_cii, d_vector
        ).rating

    assert ratings_by_year == {2025: "D", 2026: "E"}
