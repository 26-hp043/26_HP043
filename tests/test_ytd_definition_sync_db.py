"""YTD 정의가 모든 경로에서 같은가 (`PRD §3.3.8`, #750 · #866).

## 무엇이 문제였나

「연간 누적(YTD)」이 **엔드포인트마다 다른 값**을 냈다. 실측(2026-08-29)에서 같은
선박·같은 연도에 대시보드 8.9799 · 선박 상세 8.980 · 실시간 CII 7.028270이 나왔고,
연간 실적 리포트는 **한 문서 안에 7.028과 8.980을 함께** 인쇄했다.

수식을 다시 구현한 곳은 없었다. ``compute_ytd_cii``의 ``in_progress`` 인자를
**넘기는 호출과 넘기지 않는 호출**이 섞여 있었을 뿐이다 — 화면은 멀쩡한 채 값만
갈렸다.

## 왜 이 파일이 따로 있나

각 경로는 자기 테스트 파일이 있고 **각자는 통과했다.** 갈린 것은 경로 사이라,
한 파일에서 나란히 놓고 대조해야 잡힌다.

⚠️ **경로를 빠뜨리면 그 경로는 계속 갈린 채로 남는다** (`#866`). 종전에는 리포트
쪽에서 **연간 실적** 리포트만 보고 있었고, 같은 파일의 ``build_voyage_report``
(항차 완료 리포트)가 ``as_of``·``in_progress`` 없이 부르는 것을 덮지 못했다 —
그 리포트의 「연간 누적 CO₂」가 화면과 29% 어긋난 채 배포됐다(1,930.68 t vs
2,495.46 t). 지금은 **항차 완료 리포트를 다섯 번째 경로로** 함께 본다.

## 진행 중 항차가 있어야 한다

**진행 중 항차가 없으면 모든 경로가 원래 같은 값을 낸다.** 그런 선박으로 검사하면
정의가 다시 갈려도 통과한다 — 이 파일의 모든 검사가 진행 중 항차를 만드는 이유다.

케이스 (`TEST_PLAN §14.5`): 정본 정합 — `PRD §3.3.8` · `API_SPEC §2.7`·`§2.8`
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services.cii_current import get_current_cii
from cii_platform.services.cii_history import list_cii_history
from cii_platform.services.fleet_summary import get_fleet_summary
from cii_platform.services.report import build_annual_report, build_voyage_report

YEAR = 2026
MID_YEAR = datetime(YEAR, 7, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    await session.execute(
        text(
            "INSERT INTO regulation_year "
            "(year, z_factor_percent, effective_from, source_ref, version) "
            "SELECT 2026, 11.0, '2026-01-01', 'TEST', '1.0' "
            "WHERE NOT EXISTS (SELECT 1 FROM regulation_year WHERE year = 2026)"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_reference_line "
            "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', '4745', 4745, 0.622, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_reference_line WHERE ship_type = 'BULK_CARRIER')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO cii_rating_boundary "
            "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
            "SELECT 'BULK_CARRIER', 'all', 'DWT', 0.86, 0.94, 1.06, 1.18, 'TEST' "
            "WHERE NOT EXISTS "
            "(SELECT 1 FROM cii_rating_boundary WHERE ship_type = 'BULK_CARRIER')"
        )
    )


async def _add_confirmed(session, vessel_id, *, year: int) -> None:
    """그 해의 실적 확정 항차 1건 — 5,000 nm · HFO 400 t."""
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_distance_nm, actual_arrival_at, annual_inclusion_policy, "
            "regulation_year, created_from) "
            "VALUES (:id, :vid, 'CONFIRMED', 'Busan', 'Singapore', 5000, 14, "
            "5000, :arrived, 'INCLUDE_AS_ACTUAL', :year, 'MANUAL')"
        ),
        {
            "id": voyage_id,
            "vid": vessel_id,
            "year": year,
            "arrived": datetime(year, 6, 20, tzinfo=UTC),
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "actual_fuel_ton, cf_used, source) VALUES (:id, 'HFO', 400, 400, "
            "3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id},
    )


@pytest_asyncio.fixture
async def vessel_with_voyage_in_progress(session):
    """실적 확정 1건 + **진행 중** 1건을 가진 선박.

    진행 중 항차의 기여분은 ``reference_daily_foc_ton``과 경과 시간으로 산출되므로
    (`PRD §3.3.8` 각주), 제원이 둘 다 있어야 값이 실제로 실린다.
    """
    await _seed_parameters(session)
    vessel_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton, "
            "underway_state, detail_status) VALUES (:id, :imo, 'YTD SYNC TEST', "
            "'BULK_CARRIER', 50000, 'HFO', 14, 30, 'UNDER_WAY', 'SAILING')"
        ),
        {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
    )

    await _add_confirmed(session, vessel_id, year=YEAR)

    in_progress = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_departure_at, annual_inclusion_policy, regulation_year, created_from) "
            "VALUES (:id, :vid, 'IN_PROGRESS', 'Singapore', 'Busan', 3000, 14, "
            ":departed, 'INCLUDE_AS_PLAN', 2026, 'MANUAL')"
        ),
        {"id": in_progress, "vid": vessel_id, "departed": datetime(YEAR, 6, 25, tzinfo=UTC)},
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "cf_used, source) VALUES (:id, 'HFO', 250, 3.114, 'USER_INPUT')"
        ),
        {"id": in_progress},
    )
    return vessel_id


async def _all_paths(session, vessel_id) -> dict[str, str | None]:
    """YTD를 내는 **모든 경로**의 올해 attained CII를 모은다.

    ``#866`` — 항차 완료 리포트를 다섯 번째 경로로 넣었다. 종전에는 **연간 실적**
    리포트만 보고 있어, 같은 파일의 :func:`build_voyage_report`가 ``as_of``·
    ``in_progress`` 없이 부르는 것을 이 검사가 덮지 못했다. 경로를 하나 빠뜨리면
    그 경로는 「각자는 통과하는」 상태로 남는다 — 이 파일의 존재 이유가 그것이다.
    """
    current, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=MID_YEAR)
    history = await list_cii_history(session, vessel_id=vessel_id, to_year=YEAR, as_of=MID_YEAR)
    fleet = await get_fleet_summary(session, regulation_year=YEAR, as_of=MID_YEAR)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=MID_YEAR)

    confirmed_id = await session.scalar(
        text(
            "SELECT id FROM voyage WHERE vessel_id = :vid AND status = 'CONFIRMED' "
            "ORDER BY created_at LIMIT 1"
        ),
        {"vid": vessel_id},
    )
    voyage_document = await build_voyage_report(session, confirmed_id, as_of=MID_YEAR)
    contribution = next(s for s in voyage_document.sections if s.title == "CII 기여도")

    this_year = next(row for row in history["years"] if row["regulation_year"] == YEAR)
    mine = next(v for v in fleet["vessels"] if v["vessel_id"] == str(vessel_id))
    header = next(s for s in document.sections if s.title == f"{YEAR}년 누적 (YTD)")
    trend = next(s for s in document.sections if s.title == "연도별 추이")

    return {
        "cii_current": current["ytd"]["attained_cii"],
        "cii_history": this_year["attained_cii"],
        "fleet_summary": mine["ytd_attained_cii"],
        "report_header": dict(header.rows)["실적 CII (attained)"],
        "report_trend": next(r[2] for r in trend.rows if r[0] == str(YEAR)),
        "voyage_report": dict(contribution.rows)["연간 누적 CII"],
    }


@pytest.mark.asyncio
async def test_the_in_progress_voyage_actually_moves_the_number(
    session, vessel_with_voyage_in_progress
):
    """**먼저 진행분이 값을 실제로 바꾸는지 확인한다** (#750).

    이 검사가 없으면 아래 대조는 무의미하다 — 진행분이 0이면 네 경로가 어떤 정의를
    쓰든 같은 값이 나오고, 정의가 다시 갈려도 통과한다.
    """
    values = await _all_paths(session, vessel_with_voyage_in_progress)

    # 실적 확정분만 집계했을 때의 값: 400t × 3.114 × 1e6 / (50000 × 5000)
    actual_only = (Decimal("400") * Decimal("3.114") * Decimal(1_000_000)) / (
        Decimal("50000") * Decimal("5000")
    )

    assert Decimal(values["cii_current"]) != actual_only.quantize(Decimal("0.000001")), (
        "진행 중 항차가 값을 바꾸지 않는다 — 이 픽스처로는 정의 차이를 잡을 수 없다"
    )


@pytest.mark.asyncio
async def test_all_paths_report_the_same_ytd(session, vessel_with_voyage_in_progress):
    """`PRD §3.3.8` — 모든 경로가 **같은 attained CII**를 낸다 (#750 · #866).

    등급이 붙는 값은 ⑴ YTD 하나뿐이고(`PRD §3.3` 표), 그 값 위에서 대시보드의 위험
    배너·등급 분포·정렬·`days_to_d`가 돈다(`§3.3.7`). 경로마다 다르면 **규제 트리거
    판정이 갈릴 수 있다.**
    """
    values = await _all_paths(session, vessel_with_voyage_in_progress)

    # 표시 자릿수가 경로마다 다르므로 값으로 비교한다 — 문자열 비교는 6자리와
    # 3자리를 「다르다」로 판정해 진짜 불일치를 가린다.
    numbers = {name: Decimal(value) for name, value in values.items() if value is not None}

    assert len(numbers) == 6, f"값을 내지 못한 경로가 있다: {values}"

    reference = numbers["cii_current"]
    for name, value in numbers.items():
        assert value == reference.quantize(value), f"{name}가 다른 YTD를 낸다: {values}"


@pytest.mark.asyncio
async def test_annual_report_prints_one_ytd(session, vessel_with_voyage_in_progress):
    """리포트 **한 문서 안**의 YTD 행과 연도별 추이 올해 행이 같다 (`PRD §25.3`, #750).

    종전에는 헤더가 `get_current_cii`, 추이 표가 `list_cii_history`에서 와 **한
    문서에 7.028과 8.980이 함께** 인쇄됐다. `PRD §25.3`은 YTD 행의 출처를 연도별
    이력 API(`#355`)로 지정한다 — 이제 둘이 같은 행에서 나온다.
    """
    values = await _all_paths(session, vessel_with_voyage_in_progress)

    assert values["report_header"] == values["report_trend"]


@pytest.mark.asyncio
async def test_past_years_are_not_touched_by_the_in_progress_voyage(
    session, vessel_with_voyage_in_progress
):
    """**과거 연도는 진행분에 흔들리지 않는다** (#750).

    진행 중 항차는 올해에만 존재한다. 과거 연도 행에 넣으면 그 해에는 없던 항차가
    확정 이력을 바꾼다 — 확정된 과거는 조회할 때마다 달라지면 안 된다.
    """
    history = await list_cii_history(
        session,
        vessel_id=vessel_with_voyage_in_progress,
        from_year=YEAR - 1,
        to_year=YEAR,
        as_of=MID_YEAR,
    )

    last_year = next(row for row in history["years"] if row["regulation_year"] == YEAR - 1)

    # 작년에는 항차가 없다 — 진행분이 새어 들어가면 값이 생긴다.
    assert last_year["data_available"] is False
    assert last_year["attained_cii"] is None


@pytest.mark.asyncio
async def test_dashboard_past_year_is_not_touched_by_the_in_progress_voyage(
    session, vessel_with_voyage_in_progress
):
    """대시보드도 **과거 연도에는 진행분을 넣지 않는다** (#750 · `#815`).

    `#750`이 선대 요약에 진행분을 넣으면서 **과거 연도 조회에도 더해지는 경로가
    열렸다.** 확정된 과거 실적이 오염되고, 대시보드는 값이 틀려도 멀쩡해 보인다 —
    `#815`가 `cii/current`에서 보고한 것과 같은 종류의 오염이다.

    이 검사는 :func:`test_past_years_are_not_touched_by_the_in_progress_voyage`의
    선대 요약 판이다. 두 경로가 **각각** 막혀 있어야 한다 — 한쪽만 보면 다른 쪽이
    열려도 통과한다.
    """
    fleet = await get_fleet_summary(session, regulation_year=YEAR - 1, as_of=MID_YEAR)

    mine = next(
        v for v in fleet["vessels"] if v["vessel_id"] == str(vessel_with_voyage_in_progress)
    )

    # 작년에는 항차가 없다 — 진행분이 새어 들어가면 값이 생긴다.
    assert mine["ytd_attained_cii"] is None, (
        f"과거 연도에 진행분이 섞였다: {mine['ytd_attained_cii']}"
    )
