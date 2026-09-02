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
    #
    # 숫자가 아니라 **어느 선박이 정박 중인가**로 센다 (#650). 종전에는 `== 2`만
    # 확인해 로로 여객선이 빠진 것을 잡지 못했다 — 그 선박은 `IN_PORT`로 표시되면서
    # 진행 중 구간이 없었고, 접안 연료가 분자에 들어갈 자리가 없었다.
    ongoing = {
        row[0]
        for row in (
            await conn.execute(
                text("SELECT period_type FROM not_underway_period WHERE ended_at IS NULL")
            )
        ).all()
    }
    assert ongoing == {"CANAL_TRANSIT", "AT_ANCHOR", "IN_PORT"}


async def test_not_under_way_vessels_have_a_matching_open_period(conn):
    """**정박 중으로 표시된 선박에는 그 정박을 뒷받침하는 열린 구간이 있다** (#650).

    `API_SPEC §2.6`이 두 값을 잇는다.

    > `detail_status`의 `NOT_UNDER_WAY` 6값은 `not_underway_period.period_type`과
    > **같은 집합**이다 — 정박 구간의 성격이 곧 선박의 표시 상태가 된다

    이것을 **불변식으로 강제하지는 않는다** — 실사용에서는 상태만 먼저 바꾸고 구간을
    아직 입력하지 않은 중간 상태가 정상이다(두 엔드포인트가 별개라 시차가 생긴다).
    **시드는 시연 데이터이므로** 짝을 맞춘다. 짝이 없으면 그 상태의 화면 경로가
    한 번도 그려지지 않는다.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT v.name, v.detail_status, p.period_type "
                "FROM vessel v LEFT JOIN not_underway_period p "
                "  ON p.vessel_id = v.id AND p.ended_at IS NULL "
                "WHERE v.underway_state = 'NOT_UNDER_WAY' AND v.is_deleted = false"
            )
        )
    ).all()

    assert rows, "정박 중인 시드 선박이 없다 — 시드가 바뀌었는지 확인할 것"
    for name, detail_status, period_type in rows:
        assert period_type == detail_status, (
            f"{name}: 표시 상태는 {detail_status}인데 진행 중 구간은 {period_type}이다"
        )


async def test_in_port_period_carries_fuel(conn):
    """접안 구간에 연료가 달려 있다 (#650).

    구간만 있고 연료가 없으면 **분자 기여가 0**이라 「정박이 지속되면 등급이
    나빠진다」가 그 선박에서 성립하지 않는다. `#345`가 만든 `not_underway_fuel_use`가
    구간에 매달리므로, 구간이 곧 연료를 담을 자리다.
    """
    total = await conn.scalar(
        text(
            "SELECT coalesce(sum(f.fuel_ton), 0) FROM not_underway_fuel_use f "
            "JOIN not_underway_period p ON p.id = f.period_id "
            "WHERE p.period_type = 'IN_PORT'"
        )
    )
    assert total > 0, "접안 구간에 연료 표본이 없다 — IN_PORT 분자 경로가 비어 있다"


async def test_in_port_fuel_reaches_the_cii_numerator(conn):
    """**이 이슈의 완료 기준이다** (#650) — 접안 연료가 실제로 분자에 들어간다.

    구간과 연료가 시드에 있다는 것만으로는 부족하다. `#353`이 만든 분자 경로를
    실제로 지나는지, 즉 그 선박의 YTD 산출에 정박분이 잡히는지를 본다.

    종전에는 로로 여객선의 2026년 정박 구간이 **0건**이었다(드라이독은 2025년에
    끝났다). 그래서 「정박이 지속되면 등급이 나빠진다」가 이 선박에서만 성립하지
    않았다.
    """
    from datetime import UTC, datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.services.ytd_cii import compute_ytd_cii

    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        result = await compute_ytd_cii(
            session,
            vessel_id=VESSEL_IDS["ro_ro"],
            regulation_year=2026,
            as_of=datetime(2026, 8, 20, tzinfo=UTC),
        )

    assert result.not_underway_period_count == 1, "2026년 정박 구간이 잡히지 않았다"
    assert result.not_underway_co2_g > 0, "접안 연료가 분자에 들어가지 않았다"


async def test_planning_stage_voyage_exists(conn):
    """계획 단계 항차가 최소 한 건 있다 (#587).

    기능③ 연간 시뮬레이션은 **잔여 계획 항차**로 몬테카를로를 돌린다. 한 건도
    없으면 ``NO_REMAINING_VOYAGES`` 경고와 함께 목표 달성 확률 0%가 나와,
    심사에서 그 기능을 열면 빈 결과가 보인다.

    ``scenario_adopt``의 채택 대상도 계획 단계 항차뿐이다
    (``services/scenario_adopt.py`` ``PLANNING_STATUSES``).
    """
    count = await conn.scalar(
        text("SELECT count(*) FROM voyage WHERE status IN ('DRAFT', 'PLANNED')")
    )
    assert count >= 1, "기능③·시나리오 채택을 시연할 계획 단계 항차가 없다"


async def test_underway_vessel_has_an_in_progress_voyage(conn):
    """``UNDER_WAY``로 표시되는 배는 진행 중 항차를 갖는다 (#587).

    대시보드가 「운항 중 · 항해 중」으로 보이는 배의 실시간 CII 화면이
    「진행 중인 항차가 없습니다」를 내면 같은 배에 대해 두 화면이 반대를 말한다.

    ⚠️ **역방향은 단언하지 않는다.** ``NOT_UNDER_WAY``이면서 진행 중 항차를 갖는
    것은 **모순이 아니다** — ``API_SPEC §2.6``이 *「정박 구간의 성격이 곧 선박의
    표시 상태가 된다」*로 두 축을 갈라 정의한다. 운하를 통과하는 배는 항차가
    진행 중이면서 ``NOT_UNDER_WAY/CANAL_TRANSIT``인 것이 정상이고, 그 조합은
    ``test_canal_period_links_in_progress_voyage``가 따로 잠근다.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT v.name, "
                "(SELECT count(*) FROM voyage w "
                " WHERE w.vessel_id = v.id AND w.status = 'IN_PROGRESS') AS inprog "
                "FROM vessel v WHERE v.underway_state = 'UNDER_WAY'"
            )
        )
    ).all()
    assert rows, "UNDER_WAY 선박이 한 척도 없다 — 대시보드 상태 다양성이 깨진다"
    for row in rows:
        assert row.inprog >= 1, f"{row.name}: 운항 중인데 진행 중 항차가 없다"


async def test_in_progress_voyage_arrival_is_still_ahead(conn):
    """진행 중 항차의 도착 예정일이 아직 오지 않았다 (#587 → #792).

    **이 단언이 지키는 것은 시드가 상대 시각을 쓴다는 계약이다.**

    종전 문구는 근거를 「도착 예정일이 지나면 **누적이 날짜마다 늘어** 같은 시연을
    두 번 돌렸을 때 값이 달라진다」로 적었다. 그 근거는 **더 이상 사실이 아니다** —
    ``#649``(PR ``#664``)가 ``simulation_clock``에 상한을 넣어 실적이 없으면
    ``window_end``를 ``planned_arrival_at``에서 자른다. 값은 자라지 않는다.

    남은 이유는 **값이 아니라 화면**이다. 예정일을 지나면 ``IN_PROGRESS_PAST_ETA``
    경고가 서고, 시연에서 「도착 예정일이 한참 지난 진행 중 항차」가 보인다.

    ``#792`` 이전에는 시드가 **절대 날짜를 박아 두고 사람이 주기적으로 뒤로 미는**
    구조였고, 그 완화가 ``2026-09-02``에 만료돼 **`main`의 CI가 통째로 빨개졌다.**
    지금은 ``demo_seed._rel()``이 적재 시각을 기준으로 만든다 — 절대 시각이 다시
    들어오면 **언젠가 반드시** 여기서 잡힌다.
    """
    overdue = (
        await conn.execute(
            text(
                "SELECT voyage_no, planned_arrival_at FROM voyage "
                "WHERE status = 'IN_PROGRESS' AND actual_arrival_at IS NULL "
                "AND planned_arrival_at < now()"
            )
        )
    ).all()
    assert not overdue, (
        "진행 중 항차의 도착 예정일이 지났다 — 시드가 절대 시각으로 되돌아갔다"
        f"(demo_seed._rel 참조 · #792): "
        f"{[(r.voyage_no, str(r.planned_arrival_at)) for r in overdue]}"
    )


async def test_planned_voyage_departure_is_still_ahead(conn):
    """계획 단계 항차의 출항 예정일이 아직 오지 않았다 (#792).

    진행 중 항차와 **같은 부류인데 아무도 보고 있지 않았다.** 계획 항차의 출항
    예정일이 지나면 화면이 「계획인데 이미 출발했어야 하는 항차」를 보인다 —
    ``#587``이 세운 「다음 항차가 보인다」는 시연 서사가 거기서 무너진다.

    ``2026-09-02``에 진행 중 항차가 만료됐을 때 이 항차의 출항 예정일도 **사흘
    뒤**였다. 같은 날 등록하지 않았으면 사흘 뒤 같은 실패를 다시 봤을 것이다.
    """
    overdue = (
        await conn.execute(
            text(
                "SELECT voyage_no, planned_departure_at FROM voyage "
                "WHERE status = 'PLANNED' AND planned_departure_at < now()"
            )
        )
    ).all()
    assert not overdue, (
        "계획 항차의 출항 예정일이 지났다 — 시드가 절대 시각으로 되돌아갔다"
        f"(demo_seed._rel 참조 · #792): "
        f"{[(r.voyage_no, str(r.planned_departure_at)) for r in overdue]}"
    )


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
