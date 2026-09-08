"""진행 중 항차는 **그 항차의 연도에만** 들어간다 (#815).

## 무엇이 문제였나

진행 중 항차 조회(``find_in_progress``)에 **연도 조건이 없었고**, 기여분은 무조건
더해졌다. 그래서 ``?year=2024``로 물어도 **2026년에 항해 중인 항차의 누적분이
2024년 확정 실적에 합산**됐다.

끝난 해의 실적이 조회할 때마다 달라졌고, 그 값이 **연간 실적 리포트 PDF에도 그대로**
실렸다.

## 왜 이 파일이 따로 있나

`#750`이 만든 ``test_ytd_definition_sync_db.py``는 **네 경로가 서로 같은 값을 내는가**를
본다. 여기서 보는 것은 다른 질문이다 — **조회한 해의 값이 맞는가**다. 네 경로가 사이좋게
전부 틀린 값을 내면 `#750`의 검사는 통과한다.

## 과거 연도 실적이 있어야 한다

과거 연도에 확정 실적이 없으면 값이 ``None``이라, 오염이 있어도 「데이터 없음」과
구분되지 않는다. 그래서 픽스처가 **작년 실적을 넣는다.**

케이스 (`TEST_PLAN §14.5`): 정본 정합 — `PRD §3.3.8` 집계 구간
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
from cii_platform.services.fleet_summary import get_fleet_summary
from cii_platform.services.report import build_annual_report
from tests.test_ytd_definition_sync_db import _add_confirmed, _seed_parameters

YEAR = 2026
PAST = 2025
MID_YEAR = datetime(YEAR, 7, 1, tzinfo=UTC)

#: 작년 실적만의 정확값 — 400 t × 3.114 × 1e6 / (50,000 DWT × 5,000 nm).
PAST_ONLY = (Decimal("400") * Decimal("3.114") * Decimal(1_000_000)) / (
    Decimal("50000") * Decimal("5000")
)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel(session):
    """작년 확정 실적 + **올해** 진행 중 항차를 가진 선박."""
    await _seed_parameters(session)
    await session.execute(
        text(
            "INSERT INTO regulation_year "
            "(year, z_factor_percent, effective_from, source_ref, version) "
            "SELECT :y, 9.0, '2025-01-01', 'TEST', '1.0' "
            "WHERE NOT EXISTS (SELECT 1 FROM regulation_year WHERE year = :y)"
        ),
        {"y": PAST},
    )

    vessel_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton, "
            "underway_state, detail_status) VALUES (:id, :imo, 'YEAR SCOPE TEST', "
            "'BULK_CARRIER', 50000, 'HFO', 14, 30, 'UNDER_WAY', 'SAILING')"
        ),
        {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
    )

    await _add_confirmed(session, vessel_id, year=PAST)

    in_progress = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_departure_at, annual_inclusion_policy, regulation_year, created_from) "
            "VALUES (:id, :vid, 'IN_PROGRESS', 'Singapore', 'Busan', 3000, 14, "
            ":departed, 'INCLUDE_AS_PLAN', :year, 'MANUAL')"
        ),
        {
            "id": in_progress,
            "vid": vessel_id,
            "year": YEAR,
            "departed": datetime(YEAR, 6, 25, tzinfo=UTC),
        },
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "cf_used, source) VALUES (:id, 'HFO', 250, 3.114, 'USER_INPUT')"
        ),
        {"id": in_progress},
    )
    return vessel_id


@pytest.mark.asyncio
async def test_the_in_progress_voyage_moves_this_year(session, vessel):
    """**먼저 진행분이 올해 값을 실제로 바꾸는지 확인한다** (#815).

    이것이 성립하지 않으면 아래 「과거 연도는 안 바뀐다」가 무의미하다 — 진행분이
    애초에 0이면 어느 해를 물어도 오염이 없다.
    """
    data, _ = await get_current_cii(session, vessel, year=YEAR, as_of=MID_YEAR)

    assert data["ytd"]["data_available"] is True
    assert data["current_voyage"] is not None, "올해 조회에는 진행 중 항차가 보여야 한다"


@pytest.mark.asyncio
async def test_past_year_query_excludes_the_in_progress_voyage(session, vessel):
    """`?year=<과거>` 조회에 현재 진행분이 들어가지 않는다 (#815).

    ⑴ 누적값뿐 아니라 ⑵ 항차 구간값과 ``meta.simulated``도 함께 비어야 한다 —
    같은 항차에서 나오는 값들이라, 하나만 지우면 화면이 「2025년을 보는데 지금 뛰는
    항차의 구간값이 함께 떠 있는」 상태가 된다.
    """
    data, meta = await get_current_cii(session, vessel, year=PAST, as_of=MID_YEAR)

    assert Decimal(data["ytd"]["attained_cii"]) == PAST_ONLY.quantize(Decimal("0.000001")), (
        f"과거 연도에 진행분이 섞였다: {data['ytd']['attained_cii']}"
    )
    assert data["ytd"]["total_distance_nm"] == "5000.00"
    assert data["ytd"]["total_fuel_ton"] == "400.00"
    assert data["current_voyage"] is None, "과거 연도 조회에 지금 뛰는 항차가 딸려 왔다"
    assert meta["simulated"] is False


@pytest.mark.asyncio
async def test_dashboard_past_year_excludes_the_in_progress_voyage(session, vessel):
    """선대 요약도 같다 (#815). 이 값 위에서 위험 배너·정렬·`days_to_d`가 돈다."""
    fleet = await get_fleet_summary(session, regulation_year=PAST, as_of=MID_YEAR)

    mine = next(v for v in fleet["vessels"] if v["vessel_id"] == str(vessel))

    assert Decimal(mine["ytd_attained_cii"]) == PAST_ONLY.quantize(Decimal("0.0001")), (
        f"과거 연도에 진행분이 섞였다: {mine['ytd_attained_cii']}"
    )


@pytest.mark.asyncio
async def test_past_year_report_prints_confirmed_actuals_only(session, vessel):
    """연간 실적 리포트 PDF도 확정 실적만 담는다 (#815).

    `#815`가 지적한 전파 경로다 — 리포트 헤더가 이 값을 그대로 인쇄한다.
    """
    document = await build_annual_report(session, vessel, year=PAST, as_of=MID_YEAR)

    header = next(s for s in document.sections if s.title == f"{PAST}년 누적 (YTD)")
    rows = dict(header.rows)

    # 진행분이 섞이면 거리 5,000 · 연료 400을 넘는다. 표시 형식은 리포트의
    # `_display`가 정하므로 **값 자체를 파싱해** 비교한다 — 형식 문자열을 박아 두면
    # 자릿수 규칙이 바뀔 때 이 검사가 오염과 무관하게 깨진다.
    def _number(text: str) -> Decimal:
        return Decimal(text.replace(",", ""))

    assert _number(rows["누적 거리 (nm)"]) == Decimal("5000")
    assert _number(rows["누적 연료 (t)"]) == Decimal("400")
