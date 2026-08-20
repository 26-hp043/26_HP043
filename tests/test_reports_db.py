"""리포트 데이터 수집 검증 (PRD §25, #361).

렌더링은 ``test_reports.py``가 본다. 여기서 보는 것은 **무엇을 담고 무엇을 담지
않는가**다.

* **진행 중 항차는 리포트 대상이 아니다** (`PRD §25.2`) — 실적이 확정되지 않은 값으로
  문서를 만들면 같은 항차의 리포트가 시점마다 달라진다.
* **시나리오 이력이 없으면 그 섹션을 생략한다** (`PRD §25.2.1`) — 없는 비교를 만들지
  않는다.
* **값을 다시 계산하지 않는다** — 화면과 문서가 갈리면 어느 쪽이 맞는지 판단할 근거가
  없다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError
from cii_platform.reports.csv_export import render_csv
from cii_platform.reports.document import TableSection
from cii_platform.services.report import build_annual_report, build_voyage_report

YEAR = 2026
AS_OF = datetime(YEAR, 7, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    """``test_cii_current_db.py``와 같은 방식으로 멱등하게 심는다."""
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


@pytest_asyncio.fixture
async def vessel_id(session):
    await _seed_parameters(session)
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton) "
            "VALUES (:id, :imo, 'REPORT TEST', 'BULK_CARRIER', 50000, 'HFO', 14, 30)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    return new_id


async def _make_voyage(session, vessel_id, *, status="CONFIRMED", with_fuel=True):
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_distance_nm, actual_departure_at, actual_arrival_at, "
            "annual_inclusion_policy, regulation_year, created_from, voyage_no) "
            "VALUES (:id, :vid, :status, 'Busan', 'Singapore', 3000, 14, 3100, "
            "'2026-03-01T00:00:00Z', '2026-03-10T00:00:00Z', :policy, 2026, "
            "'MANUAL', 'V-2026-001')"
        ),
        {
            "id": voyage_id,
            "vid": vessel_id,
            "status": status,
            "policy": "INCLUDE_AS_ACTUAL" if status == "CONFIRMED" else "EXCLUDE",
        },
    )
    if with_fuel:
        await session.execute(
            text(
                "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
                "actual_fuel_ton, cf_used, source) "
                "VALUES (:id, 'HFO', 250, 260, 3.114, 'USER_INPUT')"
            ),
            {"id": voyage_id},
        )
    return voyage_id


def _section(document, title):
    return next((s for s in document.sections if s.title == title), None)


# ─────────────────────────────────────────────────────────────────────────────
# 항차 완료 리포트 — PRD §25.2
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_progress_voyage_is_not_reportable(session, vessel_id):
    """실적이 확정되지 않은 값으로 문서를 만들면 리포트가 시점마다 달라진다."""
    voyage_id = await _make_voyage(session, vessel_id, status="IN_PROGRESS")
    with pytest.raises(StateTransitionError):
        await build_voyage_report(session, voyage_id, as_of=AS_OF)


@pytest.mark.asyncio
async def test_completed_voyage_is_reportable(session, vessel_id):
    voyage_id = await _make_voyage(session, vessel_id, status="COMPLETED")
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    assert "항차 완료 리포트" in document.title


@pytest.mark.asyncio
async def test_voyage_report_carries_summary_and_fuel(session, vessel_id):
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    summary = _section(document, "항차 요약")
    assert ("출발", "Busan") in summary.rows
    # 표시 형식은 `DESIGN_SYSTEM §4`다 (#584). 종전에는 `API_SPEC §1.7` 직렬화
    # 자릿수(`3100.00`)가 문서에 그대로 나가 화면(`3,100 nm`)과 달랐다.
    assert ("거리 — 실적", "3,100") in summary.rows

    fuels = _section(document, "연료 내역")
    assert fuels.rows[0][0] == "HFO"
    assert fuels.rows[0][2] == "260.0"  # 실적 — §4.2 🔒 연료 1자리


@pytest.mark.asyncio
async def test_voyage_cii_section_says_it_is_not_a_rating(session, vessel_id):
    """`COR-1` — 항차 단위 CII는 공식 등급 지표가 아니다. 각주가 문서에 있어야 한다."""
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    section = _section(document, "CII 기여도")
    assert section.note is not None
    assert "공식 등급 지표가 아닙니다" in section.note


@pytest.mark.asyncio
async def test_voyage_report_shows_its_share_of_the_year(session, vessel_id):
    """`PRD §25.2` — 「연간 누적(YTD)에 차지한 비중」이 이 섹션의 핵심이다."""
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    rows = dict(_section(document, "CII 기여도").rows)
    assert rows["연간 누적에서 차지한 비중"].endswith("%")


@pytest.mark.asyncio
async def test_scenario_section_is_omitted_when_there_is_no_history(session, vessel_id):
    """`PRD §25.2.1` — 없는 비교를 만들지 않는다."""
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    assert _section(document, "시나리오 사후 비교") is None


@pytest.mark.asyncio
async def test_scenario_section_quotes_stored_history(session, vessel_id):
    """저장된 값을 **그대로 인용**한다 — 재계산하면 과거 비교 근거가 바뀐다."""
    voyage_id = await _make_voyage(session, vessel_id)
    await session.execute(
        text(
            "INSERT INTO voyage_scenario (vessel_id, voyage_id, scenario_type, "
            "scenario_name, distance_nm, speed_kn, duration_hours, fuel_ton, "
            # risk_level은 chk_scenario_risk의 4값이다(마이그레이션 007) —
            # `#354`의 WATCH 계열과 다른 어휘라 그대로 쓰면 IntegrityError가 난다.
            "cii_value, estimated_rating, risk_level, is_adopted) VALUES "
            "(:vid, :yid, 'SLOW_STEAMING', '감속', 3000, 11.8, 254.24, 210.5, "
            "12.34567890, 'B', 'MEDIUM', true)"
        ),
        {"vid": vessel_id, "yid": voyage_id},
    )
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    section = _section(document, "시나리오 사후 비교")
    assert isinstance(section, TableSection)
    assert section.rows[0][0] == "감속 (채택)"
    # 저장된 값 그대로 — 재계산 흔적이 없어야 한다.
    #
    # ⚠️ **표시 반올림은 재계산이 아니다** (#584). 저장된 `12.345679`를 `§4.1` 🔒대로
    # 3자리로 **보이는** 것이며, 값을 다시 만들지 않는다. 종전에는 6자리가 그대로
    # 나가 「저장값을 인용했다」의 증거 역할을 겸했으나, 그 증거는 아래 note가 맡는다.
    assert section.rows[0][5] == "12.346"
    assert "재계산하지 않음" in section.note


@pytest.mark.asyncio
async def test_voyage_without_fuel_gets_a_reason_not_an_empty_table(session, vessel_id):
    """빈 표는 「아직 안 불러왔다」로 읽힌다."""
    voyage_id = await _make_voyage(session, vessel_id, with_fuel=False)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    fuels = _section(document, "연료 내역")
    assert fuels.rows == [["—", "—", "—", "—", "—", "기록 없음"]]


@pytest.mark.asyncio
async def test_unknown_voyage_is_404(session):
    with pytest.raises(NotFoundError):
        await build_voyage_report(session, uuid4(), as_of=AS_OF)


# ─────────────────────────────────────────────────────────────────────────────
# 연간 실적 리포트 — PRD §25.3
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_annual_report_has_the_four_required_parts(session, vessel_id):
    """`PRD §25.3` 구성 요소 — YTD · 연도별 추이 · not under way 기여 · 연말 예상."""
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    for title in ["2026년 누적 (YTD)", "연도별 추이", "not under way 기여", "연말 예상"]:
        assert _section(document, title) is not None, title


@pytest.mark.asyncio
async def test_annual_report_reuses_computed_values(session, vessel_id):
    """값을 다시 계산하지 않는다 — 화면(`#354`)과 같은 값이어야 한다."""
    from cii_platform.services.cii_current import get_current_cii

    await _make_voyage(session, vessel_id)
    current, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=AS_OF)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    rows = dict(_section(document, "2026년 누적 (YTD)").rows)
    assert rows["실적 CII (attained)"] == current["ytd"]["attained_cii"]
    assert rows["현재 누적 기준 예상 등급"] == current["ytd"]["rating"]


@pytest.mark.asyncio
async def test_not_underway_section_splits_by_type(session, vessel_id):
    """접안·묘박의 이동 거리 0과 운하 통과의 거리는 유형별로 나눠야 보인다."""
    period_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
            "period_type, started_at, ended_at, distance_nm) VALUES "
            "(:id, :vid, 2026, 'CANAL_TRANSIT', '2026-04-01T00:00:00Z', "
            "'2026-04-02T00:00:00Z', 80)"
        ),
        {"id": period_id, "vid": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'MAIN_ENGINE', 'HFO', 15, 3.114)"
        ),
        {"id": period_id},
    )

    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    section = _section(document, "not under way 기여")

    # §4.2 🔒 — 거리 0자리 · 연료 1자리 (#584)
    assert section.rows[0] == ["운하 통과", "1", "80", "15.0"]


@pytest.mark.asyncio
async def test_no_not_underway_records_says_so(session, vessel_id):
    """기록이 없는 것은 오류가 아니다 — 그 사실을 적는다."""
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    section = _section(document, "not under way 기여")
    assert section.rows[0][0] == "기록 없음"


@pytest.mark.asyncio
async def test_projection_says_why_when_it_cannot_be_made(session, vessel_id):
    """사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다."""
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    rows = dict(_section(document, "연말 예상").rows)
    assert rows["산출 여부"] == "산출하지 않음"
    assert rows["사유"] == "NO_BASIS"


@pytest.mark.asyncio
async def test_projection_carries_assumptions_when_available(session, vessel_id):
    """`PRD §3.3` ⑶ — 가정 없이 실으면 확정값처럼 읽힌다."""
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    rows = dict(_section(document, "연말 예상").rows)

    assert rows["산출 방식"].startswith("지금까지의 일평균")
    assert "잔여 일수" in rows


@pytest.mark.asyncio
async def test_annual_report_rejects_year_out_of_range(session, vessel_id):
    with pytest.raises(ValidationError):
        await build_annual_report(session, vessel_id, year=1900, as_of=AS_OF)


@pytest.mark.asyncio
async def test_unknown_vessel_is_404(session):
    with pytest.raises(NotFoundError):
        await build_annual_report(session, uuid4(), year=YEAR, as_of=AS_OF)


# ─────────────────────────────────────────────────────────────────────────────
# 렌더링까지 이어지는지 — 두 포맷이 같은 데이터를 쓴다 (PRD §25.4)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_document_renders_to_csv_with_the_same_numbers(session, vessel_id):
    """문서 모델의 값이 CSV에 그대로 나가야 한다 — 렌더러가 값을 만들지 않는다."""
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    csv_text = render_csv(document)

    attained = dict(_section(document, "2026년 누적 (YTD)").rows)["실적 CII (attained)"]
    assert attained in csv_text
    assert "REPORT TEST" in csv_text
