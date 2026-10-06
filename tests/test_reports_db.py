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

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import ensure_regulation_year, insert_if_not_exists, same_uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.errors import NotFoundError, StateTransitionError, ValidationError
from cii_platform.reports.csv_export import render_csv
from cii_platform.reports.document import ChartSection, TableSection
from cii_platform.services import report as report_service
from cii_platform.services.data_quality import SEVERITY_UNCONFIRMED, get_fleet_data_quality
from cii_platform.services.report import build_annual_report, build_voyage_report

YEAR = 2026
AS_OF = datetime(YEAR, 7, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


async def _seed_parameters(session) -> None:
    """``test_cii_current_db.py``와 같은 방식으로 멱등하게 심는다."""
    await ensure_regulation_year(session, 2026)
    await insert_if_not_exists(
        session,
        "INSERT INTO cii_reference_line "
        "(ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c, source_ref) "
        "VALUES ('BULK_CARRIER', 'DWT < 279000', 'DWT', '4745', 4745, 0.622, 'TEST')",
    )
    await insert_if_not_exists(
        session,
        "INSERT INTO cii_rating_boundary "
        "(ship_type, condition_expr, capacity_basis, d1, d2, d3, d4, source_ref) "
        "VALUES ('BULK_CARRIER', 'all', 'DWT', 0.86, 0.94, 1.06, 1.18, 'TEST')",
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


async def _make_voyage(
    session,
    vessel_id,
    *,
    status="CONFIRMED",
    with_fuel=True,
    policy=None,
    regulation_year=2026,
):
    """기본값은 종전과 같다 — ``policy``·``regulation_year``만 골라 쓸 수 있게 열었다 (`#1090`)."""
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_distance_nm, actual_departure_at, actual_arrival_at, "
            "annual_inclusion_policy, regulation_year, created_from, voyage_no) "
            "VALUES (:id, :vid, :status, 'Busan', 'Singapore', 3000, 14, 3100, "
            "'2026-03-01T00:00:00Z', '2026-03-10T00:00:00Z', :policy, :ryear, "
            "'MANUAL', 'V-2026-001')"
        ).bindparams(),
        {
            "id": voyage_id,
            "vid": vessel_id,
            "status": status,
            "policy": policy or ("INCLUDE_AS_ACTUAL" if status == "CONFIRMED" else "EXCLUDE"),
            "ryear": regulation_year,
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
    # 유종도 표시 문구다 (`#598`). 종전에는 같은 표에서 「출처」만 한국어였다.
    assert fuels.rows[0][0] == "중유"
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


# ── 시나리오 사후 비교 — 3종과 실적 (`PRD §25.2.1` · `#2092`) ──────────────────────

#: 비교 한 번이 남기는 3종의 저장값. ``(종류, 이름, 거리, 속력, 소요, 연료, CII, 등급)``
_COMPARED = [
    ("DIRECT", "직항", "3000", "14", "214.29", "250.0000", "5.19000000", "C"),
    ("DETOUR", "우회", "3360", "14", "240.00", "280.0000", "5.19000000", "C"),
    ("SLOW_STEAMING", "감속", "3000", "11.9", "252.10", "180.6250", "3.74977500", "A"),
]


async def _compare(session, vessel_id, *, with_run=True, cii_shift="0", mutate=None):
    """비교 한 번을 저장 형태 그대로 심는다 — 시나리오 3행(항차 연결 없음) + 이력 1건.

    서비스(`scenario_compare`)를 부르지 않는 것은 값을 손으로 정해 두어야 **인용**을
    대조할 수 있기 때문이다. ``cii_shift``는 두 번째 비교를 첫 번째와 구별하는 데 쓴다.
    ``mutate``는 이력의 ``scenarios[]``를 저장 직전에 고치는 함수다 — 옛 모양을 흉내 낼 때 쓴다.
    """
    from cii_platform.db.repositories import calculation_run as calc_run_repo

    ids = {}
    scenarios = []
    for kind, name, distance, speed, hours, fuel, cii, rating in _COMPARED:
        scenario_id = uuid4()
        ids[kind] = scenario_id
        value = Decimal(cii) + Decimal(cii_shift)
        await session.execute(
            text(
                "INSERT INTO voyage_scenario (id, vessel_id, scenario_type, scenario_name, "
                "distance_nm, speed_kn, duration_hours, fuel_ton, cii_value, "
                "estimated_rating, risk_level) VALUES (:id, :vid, :kind, :name, :distance, "
                ":speed, :hours, :fuel, :cii, :rating, 'MEDIUM')"
            ),
            {
                "id": scenario_id,
                "vid": vessel_id,
                "kind": kind,
                "name": name,
                "distance": Decimal(distance),
                "speed": Decimal(speed),
                "hours": Decimal(hours),
                "fuel": Decimal(fuel),
                "cii": value,
                "rating": rating,
            },
        )
        scenarios.append(
            {
                "scenario_id": str(scenario_id),
                "scenario_type": kind,
                "scenario_name": name,
                "distance_nm": float(distance),
                "speed_kn": float(speed),
                "duration_hours": hours,
                "fuel_ton": fuel,
                "attained_cii": str(value),
                "estimated_rating": rating,
                "calculation_basis": {
                    "transport_capacity": "50000",
                    "transport_capacity_basis": "DWT",
                },
            }
        )
    if with_run:
        if mutate is not None:
            scenarios = mutate(scenarios)
        await calc_run_repo.insert_scenario(
            session,
            vessel_id=vessel_id,
            input_hash="sha256:" + "a" * 64,
            parameter_hash="sha256:" + "b" * 64,
            model_version={"engine": "test"},
            result_json={"scenarios": scenarios, "summary": {}},
            parameters_used={},
            warnings=[],
            duration_ms=1,
        )
    return ids


async def _adopt(session, scenario_id, voyage_id, *, adopted=True):
    """채택이 남기는 것 — 그 행에 항차를 잇고 표시를 켠다(`services/scenario_adopt.py`)."""
    await session.execute(
        text("UPDATE voyage_scenario SET voyage_id = :yid, is_adopted = :flag WHERE id = :id"),
        {"yid": voyage_id, "flag": 1 if adopted else 0, "id": scenario_id},
    )


@pytest.mark.asyncio
async def test_scenario_section_puts_three_scenarios_beside_the_actual(session, vessel_id):
    """`PRD §25.2.1` — 직항·우회·감속 3종과 실적을 나란히. 종전에는 채택된 한 행뿐이었다."""
    voyage_id = await _make_voyage(session, vessel_id)
    ids = await _compare(session, vessel_id)
    await _adopt(session, ids["SLOW_STEAMING"], voyage_id)

    section = _section(
        await build_voyage_report(session, voyage_id, as_of=AS_OF), "시나리오 사후 비교"
    )

    assert isinstance(section, TableSection)
    assert section.headers == [
        "구분",
        "거리 (nm)",
        "속력 (kn)",
        "소요 (h)",
        "연료 (t)",
        "CII",
        "예상 등급",
    ]
    # 저장된 값 그대로 — 표시 자릿수(`DESIGN_SYSTEM §4.2`)만 입힌다 (#584).
    assert section.rows[:3] == [
        ["직항", "3,000", "14.0", "214.3", "250.0", "5.190", "C"],
        ["우회", "3,360", "14.0", "240.0", "280.0", "5.190", "C"],
        ["감속 (채택)", "3,000", "11.9", "252.1", "180.6", "3.750", "A"],
    ]
    # 실적 — 거리 3,100 nm · 3/1~3/10 = 216 h · 연료 260 t.
    # CII = 260 × 3.114 × 1,000,000 ÷ (50,000 × 3,100) = 809,640,000 ÷ 155,000,000 = 5.2234…
    assert section.rows[3] == ["실적", "3,100", "—", "216.0", "260.0", "5.223", "산출 안 함"]
    assert "재계산하지 않음" in section.note


@pytest.mark.asyncio
async def test_scenario_section_marks_exactly_one_adopted_row(session, vessel_id):
    """채택된 시나리오가 표에서 구분된다 — 표시 문구가 아니라 **한 행만 다르다**를 본다."""
    voyage_id = await _make_voyage(session, vessel_id)
    ids = await _compare(session, vessel_id)
    await _adopt(session, ids["DETOUR"], voyage_id)

    section = _section(
        await build_voyage_report(session, voyage_id, as_of=AS_OF), "시나리오 사후 비교"
    )

    names = [row[0] for row in section.rows[:3]]
    marked = [
        name for name, plain in zip(names, ["직항", "우회", "감속"], strict=True) if name != plain
    ]
    assert len(marked) == 1 and marked[0].startswith("우회")


@pytest.mark.asyncio
async def test_scenario_section_cites_only_the_adopted_comparison(session, vessel_id):
    """비교를 여러 번 돌렸어도 **지금 채택된 행이 속한 한 묶음**만 싣는다.

    옛 채택 행은 항차에 이어진 채 남는다(`_clear_previous_adoption`은 표시만 내린다).
    그 행이 섞이면 3종보다 많은 행이 잡힌다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    first = await _compare(session, vessel_id)
    second = await _compare(session, vessel_id, cii_shift="1")
    await _adopt(session, first["DIRECT"], voyage_id, adopted=False)  # 옛 채택
    await _adopt(session, second["SLOW_STEAMING"], voyage_id)

    section = _section(
        await build_voyage_report(session, voyage_id, as_of=AS_OF), "시나리오 사후 비교"
    )

    assert len(section.rows) == 4
    # 두 번째 비교의 값(+1)만 있다.
    assert [row[5] for row in section.rows[:3]] == ["6.190", "6.190", "4.750"]
    assert [row[0] for row in section.rows[:3]] == ["직항", "우회", "감속 (채택)"]


@pytest.mark.asyncio
async def test_scenario_section_is_omitted_when_nothing_was_adopted(session, vessel_id):
    """비교만 하고 채택하지 않았다 — 그 비교가 이 항차의 것인지 저장 구조가 말해 주지 않는다.

    선박의 다른 비교를 끌어와 「이 항차의 비교」로 싣지 않는다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    await _compare(session, vessel_id)

    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    assert _section(document, "시나리오 사후 비교") is None


@pytest.mark.asyncio
async def test_scenario_without_its_comparison_says_so(session, vessel_id):
    """채택 행을 만든 이력이 없다(`#2088` 이전의 저장하지 않는 경로) — 일부만 저장된 경우다.

    없는 두 종류는 **「—」가 아닌 다른 말**이다. 같은 기호면 「계산했는데 값이 없다」로
    읽힌다. 실적 CII도 비교가 쓴 용량을 몰라 낼 수 없다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    ids = await _compare(session, vessel_id, with_run=False)
    await _adopt(session, ids["SLOW_STEAMING"], voyage_id)

    section = _section(
        await build_voyage_report(session, voyage_id, as_of=AS_OF), "시나리오 사후 비교"
    )

    direct, detour, slow, actual = section.rows
    assert slow == ["감속 (채택)", "3,000", "11.9", "252.1", "180.6", "3.750", "A"]
    assert direct[0] == "직항" and detour[0] == "우회"
    missing = direct[1]
    assert missing not in ("—", "", "0")
    assert set(direct[1:]) == set(detour[1:]) == {missing}
    # 실적의 기록값은 그대로 있고, CII만 다른 말이다 — 「없음」 셋이 서로 구별된다.
    assert actual[1] == "3,100" and actual[4] == "260.0"
    assert actual[5] not in ("—", missing) and not actual[5][0].isdigit()
    # 각주도 용량을 숫자로 적지 못한다 — 모른다고 적는다.
    assert "용량을 알 수 없어" in section.note and "50,000" not in section.note


@pytest.mark.asyncio
async def test_scenario_note_reuses_the_cor1_wording_and_names_the_capacity(session, vessel_id):
    """각주 — 2026-10-06 결정 1·2 (`#2092`).

    ⑴ 「항차 단위 CII는 공식 등급 지표가 아니다」는 같은 문서의 「CII 기여도」 절이 쓰는
    문구(``COR-1``)를 **그대로** 싣는다 — 두 절의 문구가 갈리면 한쪽만 고쳐진다.
    ⑵ 실적 CII의 분모 용량을 **숫자로** 적는다 — 인용한 비교가 쓴 값이라, 비교 뒤 제원이
    고쳐진 선박에서는 다른 화면의 값과 다를 수 있고 그 이유를 읽는 사람이 알 수 있어야 한다.
    """
    from cii_platform.reports.document import VOYAGE_CII_NOTE

    voyage_id = await _make_voyage(session, vessel_id)
    ids = await _compare(session, vessel_id)
    await _adopt(session, ids["SLOW_STEAMING"], voyage_id)

    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    section = _section(document, "시나리오 사후 비교")

    # 정본 문구 (PRD §25.2 · COR-1) — 「CII 기여도」 절과 **같은 상수**다.
    assert VOYAGE_CII_NOTE in section.note
    assert _section(document, "CII 기여도").note == VOYAGE_CII_NOTE
    # 정본 문구 (PRD §6.3 「자동 결정 금지」) — 바꾸려면 PRD 개정이 먼저다.
    no_auto_decision = "시스템은 시나리오별 수치만 비교하며, 최종 운항 판단은 사용자에게 있습니다."
    assert no_auto_decision in section.note
    # 비교가 쓴 용량 50,000 DWT — 실적 CII 5.223이 이 분모로 나온 값이다.
    assert "50,000 DWT" in section.note
    assert section.rows[3][5] == "5.223"
    # 표지 셋의 뜻이 각주에 있다.
    for marker in ("이력 없음", "계산 불가", "—"):
        assert f"「{marker}」" in section.note, marker


@pytest.mark.asyncio
async def test_partial_fuel_actuals_do_not_print_a_partial_sum(session, vessel_id):
    """유종이 둘인데 하나만 실적이 있다 — 그 하나의 합을 표지 없이 싣지 않는다.

    종전에는 「연료」 칸이 기록된 유종의 합(260.0)을 그대로 실어, 세 시나리오의 연료 옆에서
    **이 항차의 연료 전체**로 읽혔다. CII는 이미 「계산 불가」였으므로 연료도 같은 표지다 —
    같은 이유(모든 유종의 실적이 없다)로 낼 수 없는 값이다. 「—」가 아닌 것은 기록이 있기
    때문이다 — 「—」는 아무것도 적히지 않은 칸의 말이다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, cf_used, source) "
            "VALUES (:id, 'LNG', 40, 2.750, 'USER_INPUT')"
        ),
        {"id": voyage_id},
    )
    ids = await _compare(session, vessel_id)
    await _adopt(session, ids["SLOW_STEAMING"], voyage_id)

    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    actual = _section(document, "시나리오 사후 비교").rows[3]

    assert actual[1] == "3,100", "기록된 실적 거리는 그대로다"
    assert actual[4] == report_service.ACTUAL_CII_NOT_COMPUTABLE, actual
    assert actual[5] == report_service.ACTUAL_CII_NOT_COMPUTABLE, actual
    assert "260" not in actual[4]
    # 유종별 기록은 「연료 내역」에 그대로 남는다 — 지운 것이 아니라 합을 내지 않은 것이다.
    fuel_rows = _section(document, "연료 내역").rows
    assert sorted(row[2] for row in fuel_rows) == ["260.0", "—"]


@pytest.mark.asyncio
async def test_a_malformed_comparison_run_does_not_break_the_report(session, vessel_id):
    """키가 빠진 이력 항목은 그 **행만** 「이력 없음」이고 리포트는 산다.

    종전에는 ``item["fuel_ton"]`` 같은 접근이 ``KeyError``로 올라가 **리포트 전체가 500**
    이었다. 저장 경로(`services/scenario_compare.py`)는 `#373` 이후 이 키를 전부 써 왔지만,
    이력 한 건의 모양이 문서 전체를 막아서는 안 된다. 네 모양을 한 번에 본다 — 키가 빠진
    형제 항목 · 키가 빠진 **채택** 항목 · dict가 아닌 항목 · 문자열로 든 ``calculation_basis``.
    """

    def _old_shape(items):
        direct, detour, slow = items
        detour = {k: v for k, v in detour.items() if k not in ("fuel_ton", "attained_cii")}
        direct = {**direct, "calculation_basis": "DWT 50000"}
        # 채택 행의 id는 남긴다 — 이력을 찾는 키다. 나머지 키는 전부 없다.
        slow = {"scenario_id": slow["scenario_id"], "scenario_type": "SLOW_STEAMING"}
        # 깨진 항목을 **맨 앞**에 둔다 — 뒤에 두면 저장소의 채택 항목 탐색(`any`)이 그 앞에서
        # 끝나 dict 가드를 지나지 않는다(검토 돌연변이로 확인).
        return ["garbage", direct, detour, slow]

    voyage_id = await _make_voyage(session, vessel_id)
    ids = await _compare(session, vessel_id, mutate=_old_shape)
    await _adopt(session, ids["SLOW_STEAMING"], voyage_id)

    section = _section(
        await build_voyage_report(session, voyage_id, as_of=AS_OF), "시나리오 사후 비교"
    )

    direct, detour, slow, actual = section.rows
    # 온전한 항목은 이력의 값으로.
    assert direct == ["직항", "3,000", "14.0", "214.3", "250.0", "5.190", "C"]
    # 키가 빠진 항목은 그 종류만 「이력 없음」 — 「—」(기록 없음)와 다른 말이다.
    assert detour == ["우회", *[report_service.SCENARIO_NOT_STORED] * 6]
    # 채택 행은 이력 항목이 깨져도 **제 행의 값**으로 남는다.
    assert slow == ["감속 (채택)", "3,000", "11.9", "252.1", "180.6", "3.750", "A"]
    # 용량을 읽을 수 있는 항목이 없으므로 실적 CII는 「계산 불가」, 각주도 그렇게 적는다.
    assert actual[5] == report_service.ACTUAL_CII_NOT_COMPUTABLE
    assert "용량을 알 수 없어" in section.note


@pytest.mark.asyncio
async def test_actual_row_does_not_borrow_planned_values(session, vessel_id):
    """실적이 아직 없는 항차 — 계획값으로 메우지 않는다."""
    voyage_id = await _make_voyage(session, vessel_id, status="COMPLETED", with_fuel=False)
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, cf_used, source) "
            "VALUES (:id, 'HFO', 250, 3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id},
    )
    await session.execute(
        text(
            "UPDATE voyage SET actual_distance_nm = NULL, actual_departure_at = NULL, "
            "actual_arrival_at = NULL WHERE id = :id"
        ),
        {"id": voyage_id},
    )
    ids = await _compare(session, vessel_id)
    await _adopt(session, ids["DIRECT"], voyage_id)

    section = _section(
        await build_voyage_report(session, voyage_id, as_of=AS_OF), "시나리오 사후 비교"
    )

    actual = section.rows[3]
    assert actual[:5] == ["실적", "—", "—", "—", "—"]
    # 기록이 없는 것(「—」)과 낼 수 없는 것은 다른 말이다.
    assert actual[5] != "—" and not actual[5][0].isdigit()
    # 시나리오 3행은 영향받지 않는다.
    assert section.rows[0][0] == "직항 (채택)" and section.rows[2][5] == "3.750"


@pytest.mark.asyncio
async def test_scenario_rows_are_the_same_in_preview_and_csv(session, vessel_id):
    """미리보기(HTML — PDF도 이 HTML에서 나온다)와 CSV가 **같은 행**을 싣는다."""
    from cii_platform.reports.html import render_html

    voyage_id = await _make_voyage(session, vessel_id)
    ids = await _compare(session, vessel_id)
    await _adopt(session, ids["SLOW_STEAMING"], voyage_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    section = _section(document, "시나리오 사후 비교")

    html = render_html(document)
    lines = list(csv.reader(io.StringIO(render_csv(document).lstrip("\ufeff"))))
    start = next(i for i, line in enumerate(lines) if line and line[0] == "구분")
    assert lines[start + 1 : start + 5] == section.rows
    for row in section.rows:
        assert f">{row[0]}<" in html, row[0]


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
    # 리포트는 계산을 다시 하지 않고 **같은 값**을 `DESIGN_SYSTEM §4`로 보인다 (#584).
    # 원문 문자열과 비교하면 표시 규칙을 넣는 순간 깨지므로, 같은 포매터를 통과시켜 대조한다.
    from cii_platform.services.report import _display

    assert rows["실적 CII (attained)"] == _display(current["ytd"]["attained_cii"], "cii")
    assert rows["현재 누적 기준 예상 등급"] == current["ytd"]["rating"]
    # 표시 규칙이 실제로 걸렸는지도 함께 본다 — 위 단언만으로는 둘 다 원문이어도 통과한다.
    assert (
        rows["실적 CII (attained)"] != current["ytd"]["attained_cii"]
        or len(current["ytd"]["attained_cii"].split(".")[-1]) == 3
    )


@pytest.mark.asyncio
async def test_annual_report_carries_the_rating_boundaries(session, vessel_id):
    """`#2002` 완료 기준 ③ — 등급 경계값이 문서에 실리고 **CSV에도 나온다**.

    CII 경계는 YTD 엔진이 낸 ``ytd.boundaries``를 옮긴 것이어야 한다(재계산 금지) —
    화면(`§2.14`)과 같은 값이다. 백분율은 심은 경계 행(0.86 · 0.94 · 1.06 · 1.18)이다.
    """
    from cii_platform.services.cii_current import get_current_cii
    from cii_platform.services.report import _display

    await _make_voyage(session, vessel_id)
    current, _ = await get_current_cii(session, vessel_id, year=YEAR, as_of=AS_OF)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    band = _section(document, "등급 경계")
    assert isinstance(band, ChartSection) and band.chart == "rating_band"
    rows = {row[0]: row[1:] for row in band.table.rows}
    assert [rows[g][:2] for g in "ABCDE"] == [
        ["—", "86"],
        ["86", "94"],
        ["94", "106"],
        ["106", "118"],
        ["118", "—"],
    ]
    # 리터럴만 맞추면 「같은 값」일 뿐이다 — YTD 엔진이 고르는 **같은 경계 행**인지 본다.
    from cii_platform.db.repositories import vessel as vessel_repo
    from cii_platform.services.ytd_cii import _select_rating_boundary

    chosen = await _select_rating_boundary(session, await vessel_repo.get_by_id(session, vessel_id))
    upper_edges = [rows[g][1] for g in "ABCD"]
    assert [Decimal(edge) for edge in upper_edges] == [
        Decimal(chosen.d1) * 100,
        Decimal(chosen.d2) * 100,
        Decimal(chosen.d3) * 100,
        Decimal(chosen.d4) * 100,
    ]
    published = current["ytd"]["boundaries"]
    assert rows["A"][3] == _display(published["superior_boundary"], "cii")
    assert rows["C"][2:] == [
        _display(published["lower_boundary"], "cii"),
        _display(published["upper_boundary"], "cii"),
    ]
    assert rows["E"][2] == _display(published["inferior_boundary"], "cii")

    # 올해 위치 — 기준 대비 비율(`§2.14` ``ratio_to_required``)을 %로 옮긴 것
    ((label, value),) = band.markers
    ratio = Decimal(current["ytd"]["ratio_to_required"]) * 100
    assert abs(Decimal(value) - ratio) <= Decimal("0.05"), (value, ratio)

    csv_rows = list(csv.reader(io.StringIO(render_csv(document).lstrip("\ufeff"))))
    assert ["등급 경계"] in csv_rows
    assert ["C", "94", "106", *rows["C"][2:]] in csv_rows
    assert [label, value] in csv_rows


@pytest.mark.asyncio
async def test_annual_report_declares_its_conclusion(session, vessel_id):
    """결론은 YTD 섹션이 **선언**한다 — 올해 누적 등급과 값 한 쌍 (`#2002` · `§8.6`)."""
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    ytd = _section(document, "2026년 누적 (YTD)")
    assert ytd.lead == ("현재 누적 기준 예상 등급", "실적 CII (attained)")
    # 다른 섹션은 결론을 선언하지 않는다 — 결론이 둘이면 결론이 아니다.
    others = [s for s in document.sections if s is not ytd and getattr(s, "lead", ()) != ()]
    assert others == []


@pytest.mark.asyncio
async def test_annual_trend_is_a_chart_that_keeps_its_table(session, vessel_id):
    """추이 차트는 표를 품는다 — CSV는 그 표를 그대로 낸다 (`PRD §16.4`)."""
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    trend = _section(document, "연도별 추이")
    assert isinstance(trend, ChartSection) and trend.chart == "trend"
    # 낱말이 아니라 **행**으로 본다 — 「연도」·「등급」은 다른 절에도 있어 표를 빼도 통과한다.
    csv_rows = list(csv.reader(io.StringIO(render_csv(document).lstrip("\ufeff"))))
    assert trend.table.headers in csv_rows
    this_year = next(row for row in trend.table.rows if row[0] == str(YEAR))
    assert this_year in csv_rows


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
async def test_not_underway_fuel_is_read_in_one_query(session, vessel_id, monkeypatch):
    """정박 연료를 **구간마다** 읽지 않는다 (#827).

    목록 화면(`services/not_underway.py:249`)은 배치 함수를 쓰는데 **리포트 경로만
    빠져 있었다.** 정박은 항차마다 최소 2회 생겨 한 해 구간 수가 금방 수백 건이 되고,
    그 수가 그대로 쿼리 수가 된다.

    **구간을 셋 넣는다** — 한 건이면 N+1과 배치의 쿼리 수가 같아 구분되지 않는다.
    """
    for index, period_type in enumerate(("CANAL_TRANSIT", "DRIFTING", "STS")):
        period_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
                "period_type, started_at, ended_at, distance_nm) VALUES "
                "(:id, :vid, 2026, :ptype, :start, :end, 10)"
            ),
            {
                "id": period_id,
                "vid": vessel_id,
                "ptype": period_type,
                # 바인드 파라미터에는 **문자열이 아니라 datetime**을 넘긴다 — asyncpg가
                # 직접 받는 자리라 SQL 리터럴처럼 문자열을 쓰면 DataError가 난다.
                "start": datetime(2026, 5, index + 1, tzinfo=UTC),
                "end": datetime(2026, 5, index + 2, tzinfo=UTC),
            },
        )
        await session.execute(
            text(
                "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
                "fuel_ton, cf_used) VALUES (:id, 'MAIN_ENGINE', 'HFO', 2, 3.114)"
            ),
            {"id": period_id},
        )

    calls = {"batch": 0}
    original = report_service.not_underway_repo.list_fuel_uses_for_periods

    async def counted(*args, **kwargs):
        calls["batch"] += 1
        return await original(*args, **kwargs)

    async def forbidden(*args, **kwargs):
        raise AssertionError("구간마다 조회하면 N+1이다 — 배치 함수를 쓴다")

    monkeypatch.setattr(report_service.not_underway_repo, "list_fuel_uses_for_periods", counted)
    monkeypatch.setattr(report_service.not_underway_repo, "list_fuel_uses", forbidden)

    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    section = _section(document, "not under way 기여")

    # 구간이 셋인데 조회는 **한 번**이다.
    assert calls["batch"] == 1
    # 호출 수만 보면 결과가 비어도 통과한다 — 값이 맞는지 함께 본다.
    assert sorted(row[0] for row in section.rows) == ["STS 이송", "운하 통과", "표류"]
    assert all(row[3] == "2.0" for row in section.rows)


@pytest.mark.asyncio
async def test_no_not_underway_records_says_so(session, vessel_id):
    """기록이 없는 것은 오류가 아니다 — 그 사실을 적는다."""
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    section = _section(document, "not under way 기여")
    assert section.rows[0][0] == "기록 없음"


@pytest.mark.asyncio
async def test_projection_says_why_when_it_cannot_be_made(session, vessel_id):
    """사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.

    **원문 코드도 마찬가지다 (`#631`).** 종전에는 이 단언이 ``"NO_BASIS"``였다 —
    결함을 그대로 고정해 두고 있었다. `AGENTS §4.6`상 깨진 단언에 정본 인용이 없으므로
    「테스트가 낡았다」로 판정해 같은 PR에서 갱신한다.
    """
    from cii_platform.reports.labels import PROJECTION_REASON_LABELS

    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    rows = dict(_section(document, "연말 예상").rows)
    assert rows["산출 여부"] == "산출하지 않음"
    assert rows["사유"] == PROJECTION_REASON_LABELS["NO_BASIS"]
    assert "NO_BASIS" not in rows["사유"]


@pytest.mark.asyncio
async def test_projection_carries_assumptions_when_available(session, vessel_id):
    """`PRD §3.3` ⑶ — 가정 없이 실으면 확정값처럼 읽힌다.

    `#798`에서 산출 방식이 **일평균 외삽 → 남은 거리 기반**으로 바뀌었다. 문서는
    이 문구로 두 값(「누적」·「연말 예상」)이 왜 다른지를 설명한다 — 종전에는 방식
    자체가 둘을 **구조적으로 같게** 만들어, 같은 숫자가 두 제목으로 나란히 찍혔다.
    """
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    rows = dict(_section(document, "연말 예상").rows)

    assert rows["산출 방식"] == "확정 실적에 잔여 계획 항차를 더한다 (남은 거리 기반)"
    for label in (
        "잔여 일수",
        "잔여 계획 항차",
        "잔여 계획 거리 (nm)",
        "잔여 계획 CO₂ (tCO₂)",
        "확정 실적 거리 (nm)",
        "확정 실적 CO₂ (tCO₂)",
    ):
        assert label in rows, label

    # 없어진 행이 되살아나면 문서가 뜻 없는 숫자를 다시 인쇄한다.
    for gone in ("경과 일수", "일평균 거리 (nm)", "일평균 연료 (t)"):
        assert gone not in rows, gone


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


# ---------------------------------------------------------------------------
# 수치 열 선언 (#1247)
#
# 렌더러의 규칙은 `test_reports.py`가 본다. 여기서 보는 것은 **실제 문서의 선언이
# 맞는가**다 — 수치로 선언한 열에 라벨·사용자 입력이 섞여 있으면 선언이 틀린 것이고,
# 수치 열을 선언하지 않았으면 음수 열이 생기는 날 `'-12.5`가 다시 나간다.
# ---------------------------------------------------------------------------


def _numeric_declared_cells(document) -> list[tuple[str, str, str]]:
    """(표 제목, 머리글, 셀) — 수치로 선언된 열의 값 전부."""
    cells = []
    for section in document.sections:
        # 차트가 품은 표도 CSV로 나간다 (`#2002`).
        if isinstance(section, ChartSection):
            section = section.table
        if not isinstance(section, TableSection) or section.kinds is None:
            continue
        for row in section.rows:
            for header, kind, cell in zip(section.headers, section.kinds, row, strict=True):
                if kind == "numeric":
                    cells.append((section.title, header, cell))
    return cells


async def _scenario_and_periods(session, vessel_id, voyage_id) -> None:
    await session.execute(
        text(
            "INSERT INTO voyage_scenario (vessel_id, voyage_id, scenario_type, "
            "scenario_name, distance_nm, speed_kn, duration_hours, fuel_ton, "
            "cii_value, estimated_rating, risk_level, is_adopted) VALUES "
            "(:vid, :yid, 'SLOW_STEAMING', '=감속', 3000, 11.8, 254.24, 210.5, "
            "12.34567890, 'B', 'MEDIUM', true)"
        ),
        {"vid": vessel_id, "yid": voyage_id},
    )
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


@pytest.mark.asyncio
async def test_every_report_table_declares_its_numeric_columns(session, vessel_id):
    """수치를 싣는 표는 전부 선언이 있고, 선언한 열의 값은 숫자(또는 「없음」 표지)뿐이다.

    표마다 **적어도 한 열**이 수치여야 한다 — 「제출 전 자체 점검」만 예외다(`3건`처럼
    단위가 붙어 문자열이 맞다). 수치 열에 `=감속` 같은 사용자 입력이 나오면 선언이
    틀린 것이고, 그 열은 종전 규칙으로 되돌아가 접두를 받는다.
    """
    from cii_platform.reports.csv_export import NUMERIC_CELL

    voyage_id = await _make_voyage(session, vessel_id)
    await _scenario_and_periods(session, vessel_id, voyage_id)

    voyage_doc = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    annual_doc = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    # 차트가 품은 표도 CSV로 나가므로 선언 검사 대상이다 (`#2002`).
    tables = [
        s.table if isinstance(s, ChartSection) else s
        for doc in (voyage_doc, annual_doc)
        for s in doc.sections
        if isinstance(s, (TableSection, ChartSection))
    ]
    assert {t.title for t in tables} >= {
        "연료 내역",
        "시나리오 사후 비교",
        "등급 경계",
        "연도별 추이",
        "not under way 기여",
        "제출 전 자체 점검",
    }
    undeclared = [t.title for t in tables if t.kinds is None or "numeric" not in t.kinds]
    assert undeclared == ["제출 전 자체 점검"]

    cells = _numeric_declared_cells(voyage_doc) + _numeric_declared_cells(annual_doc)
    assert cells, "수치로 선언된 셀이 하나도 없다"
    # 숫자가 아닌 값은 **서버가 정한 「없음」 표지**뿐이다 (`#2092`). 사후 비교 표는 「저장된
    # 비교에 없다」·「낼 수 없다」를 `—`(기록 없음)와 다른 말로 적는다 — 사용자 입력이 아니고,
    # CSV에서는 숫자 문법에 안 맞아 문자열 규칙으로 되돌아간다.
    absent = {
        "—",
        report_service.SCENARIO_NOT_STORED,
        report_service.ACTUAL_CII_NOT_COMPUTABLE,
    }
    not_numbers = [c for c in cells if c[2] not in absent and not NUMERIC_CELL.fullmatch(c[2])]
    assert not_numbers == [], not_numbers


@pytest.mark.asyncio
async def test_real_document_csv_keeps_user_input_escaped_next_to_numbers(session, vessel_id):
    """실제 문서에서 시나리오 이름(사용자 입력)은 접두를 받고 옆의 수치는 받지 않는다."""
    voyage_id = await _make_voyage(session, vessel_id)
    await _scenario_and_periods(session, vessel_id, voyage_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    csv_text = render_csv(document)

    assert "'=감속 (채택)" in csv_text
    line = next(line for line in csv_text.split("\r\n") if line.startswith("'=감속"))
    # 이름 다음 다섯 칸(거리·속력·소요·연료·CII)에는 접두가 없다.
    assert "'" not in line.split(",", 1)[1]


# ---------------------------------------------------------------------------
# 시각 표기 (#646)
#
# `#584`가 `meta`의 「생성 시각」·「기준 시각」만 KST로 고치고 **본문 행 둘을 두고
# 갔다.** 한 문서 안에서 두 표기가 섞이면 어느 쪽이 현지 시각인지 독자가 알 수 없다.
#
# 문서 전체를 훑는다 — 특정 행만 보면 다음에 시각이 하나 더 늘어도 걸리지 않는다.
# ---------------------------------------------------------------------------


def _all_values(document) -> list[str]:
    """문서에 실린 모든 문자열 — meta · 항목·값 · 표 행."""
    values = [value for _, value in document.meta]
    for section in document.sections:
        rows = getattr(section, "rows", [])
        for row in rows:
            values.extend(str(cell) for cell in row)
    return values


@pytest.mark.asyncio
async def test_voyage_report_times_are_kst(session, vessel_id):
    """항차 리포트의 출항·입항이 KST다.

    종전에는 `2026-02-10T07:00:00+00:00`처럼 **UTC ISO**가 그대로 나갔다. 같은 문서의
    「생성 시각」은 `2026-08-22 16:26:33 KST`였다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    rows = dict(_section(document, "항차 요약").rows)

    for label in ("출항 (실적)", "입항 (실적)"):
        assert label in rows
        if rows[label] != "—":
            assert rows[label].endswith("KST"), f"{label}: {rows[label]}"


@pytest.mark.asyncio
async def test_no_utc_iso_survives_anywhere_in_the_voyage_report(session, vessel_id):
    """문서 **어디에도** UTC ISO가 남지 않는다.

    행 이름을 열거하지 않는다 — 시각이 하나 더 늘어도 그대로 걸린다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    leaked = [v for v in _all_values(document) if "+00:00" in v or _looks_like_iso(v)]
    assert not leaked, f"UTC ISO 표기가 남았다: {leaked}"


@pytest.mark.asyncio
async def test_no_utc_iso_survives_anywhere_in_the_annual_report(session, vessel_id):
    """연간 리포트도 같다."""
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    leaked = [v for v in _all_values(document) if "+00:00" in v or _looks_like_iso(v)]
    assert not leaked, f"UTC ISO 표기가 남았다: {leaked}"


# ─────────────────────────────────────────────────────────────────────────────
# CII 적용 대상이 문서에 남는다 (#653)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_voyage_report_states_the_applicability(session, vessel_id):
    """**리포트는 심사·대외 제출에 나간다.**

    「이 값은 규제 대상이 아닌 선박의 참고값」이 문서에 없으면 오해가 그대로 남는다.
    이 픽스처 선박은 `gross_tonnage`가 NULL이라 「판정 불가」다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    meta = dict(document.meta)
    assert "CII 적용 대상" in meta
    assert "판정 불가" in meta["CII 적용 대상"]
    assert "내부 분석용" in meta["CII 적용 대상"]


@pytest.mark.asyncio
async def test_annual_report_states_the_applicability(session, vessel_id):
    """연간 리포트도 같다 — 한쪽에만 있으면 두 문서가 다른 말을 한다."""
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    meta = dict(document.meta)
    assert "판정 불가" in meta["CII 적용 대상"]


@pytest.mark.asyncio
async def test_applicability_warning_reaches_the_report(session, vessel_id):
    """경고 채널로도 같은 사실이 나간다 (`API_SPEC §1.6`).

    종전에는 `NON_CII_VESSEL`이 **GT를 알 때만** 붙어, GT가 NULL인 선박은 문서에
    아무 경고도 남기지 않았다.
    """
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    assert any("판정할 수 없습니다" in w for w in document.warnings), document.warnings


@pytest.mark.asyncio
async def test_applicable_vessel_says_so_without_a_warning(session):
    """적용 대상이면 **경고를 붙이지 않는다** — 정상 상태에 경고를 붙이면 진짜 예외가 묻힌다."""
    await _seed_parameters(session)
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, gross_tonnage, deadweight, "
            "is_cii_applicable_hint, default_fuel_type, reference_speed_kn, "
            "reference_daily_foc_ton) "
            "VALUES (:id, :imo, 'BIG SHIP', 'BULK_CARRIER', 30000, 50000, true, 'HFO', 14, 30)"
        ),
        {"id": new_id, "imo": f"9{new_id.int % 1000000:06d}"},
    )
    await session.commit()

    document = await build_annual_report(session, str(new_id), year=YEAR, as_of=AS_OF)

    assert dict(document.meta)["CII 적용 대상"] == "해당 (GT 5,000 이상)"
    assert not any("적용 대상" in w for w in document.warnings), document.warnings


@pytest.mark.asyncio
async def test_no_raw_source_code_survives_in_the_report(session, vessel_id):
    """문서 **어디에도** 연료 출처 원문 코드가 남지 않는다 (`#645`).

    열 이름을 짚지 않는다 — 출처가 다른 절에 하나 더 실려도 그대로 걸린다.
    `#631` 이후 리포트에 남아 있던 마지막 원문 코드가 이것이었다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    from cii_platform.reports.labels import FUEL_SOURCE_LABELS, FUEL_TYPE_LABELS

    leaked = [v for v in _all_values(document) if v in FUEL_SOURCE_LABELS]
    assert not leaked, f"연료 출처 원문 코드가 남았다: {leaked}"

    # 유종도 함께 본다 (`#598`). `#645`가 출처를 고칠 때 **같은 표의 옆 칸**이
    # 남아 있었다 — 훑는 대상을 넓히지 않으면 다음 칸도 같은 방식으로 남는다.
    leaked_fuel = [v for v in _all_values(document) if v in FUEL_TYPE_LABELS]
    assert not leaked_fuel, f"유종 원문 코드가 남았다: {leaked_fuel}"


@pytest.mark.asyncio
async def test_fuel_type_is_shown_in_korean(session, vessel_id):
    """빠진 것이 아니라 **한국어로 바뀐** 것이다 (`#598`).

    위 훑기만 있으면 유종 열을 통째로 빼도 통과한다. 유종이 없으면 무엇의
    배출량인지 문서에서 읽을 수 없다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    assert "중유" in _all_values(document)


@pytest.mark.asyncio
async def test_fuel_source_is_shown_in_korean(session, vessel_id):
    """빠진 것이 아니라 **한국어로 바뀐** 것이다.

    위 테스트만 있으면 열을 통째로 빼도 통과한다. `DESIGN_SYSTEM §11`(🔒)이 출처
    표기를 요구하므로 값이 실제로 실려 있어야 한다.
    """
    voyage_id = await _make_voyage(session, vessel_id)
    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)

    values = set(_all_values(document))
    from cii_platform.reports.labels import FUEL_SOURCE_LABELS

    assert values & set(FUEL_SOURCE_LABELS.values()), "연료 출처 표기가 문서에 없다"


def _looks_like_iso(value: str) -> bool:
    """`2026-02-10T07:00:00` 형태인가 — 구분자가 `T`면 ISO다.

    KST 표기는 공백을 쓴다(`2026-08-22 16:26:33 KST`). 「T가 들어 있다」로 보면
    `KST`의 T에 걸리므로 **날짜 뒤 T**만 본다.
    """
    import re

    return bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", value))


# ─────────────────────────────────────────────────────────────────────────────
# 제출 전 자체 점검 (`PRD §21` 「공식 보고서 보조」 · `#770`)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_check_section_is_part_of_the_annual_report(session, vessel_id):
    """IT-REPORT-001 — **새 리포트가 아니라 절**이다.

    `PRD §25.1`이 「대관 제출용 공식 보고서 생성」을 하지 않는다로 못박았다. 「제출 전
    검토용」이라는 이름의 별도 문서를 만들면 그 경계가 흐려진다 — 받는 사람은 제목으로
    용도를 읽는다.
    """
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    section = _section(document, "제출 전 자체 점검")
    assert section is not None
    assert document.title.startswith("연간 실적 리포트")


@pytest.mark.asyncio
async def test_self_check_says_it_is_not_for_submission(session, vessel_id):
    """IT-REPORT-002 — **용도 고지**가 절에 실린다. 판정은 적합 판정이 아니다."""
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    note = _section(document, "제출 전 자체 점검").note or ""
    assert "제출용 문서가 아닙니다" in note
    assert "규제 적합 판정이 아닙니다" in note


@pytest.mark.asyncio
async def test_self_check_says_g5_is_not_applied(session, vessel_id):
    """IT-REPORT-005 — **G5 미반영**을 고지에 적는다 (#762).

    검증기관 공식값과 대조하는 사무직이 차이의 이유를 이 문서에서 읽어야 한다. 문서
    전체 면책은 「공식이 아니다」만 말하고 무엇이 빠졌는지는 말하지 않는다. 표의 행이
    아니라 고지 문장이다 — 건수가 없어 늘 같은 값이 찍히는 칸은 죽은 칸이다.
    """
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    section = _section(document, "제출 전 자체 점검")
    # 정본 문구 (PRD §25.3 · #762) — 바꾸려면 PRD 개정이 먼저다.
    assert (
        "G5 보정계수·항해 조정(MEPC.355(78))은 반영하지 않았습니다. 보정 대상 선박"
        "(빙등급·셔틀탱커·STS 작업·냉동 컨테이너)은 검증기관 값보다 CII가 높게 나올 수"
        " 있습니다."
    ) in (section.note or "")
    assert not [row for row in section.rows if "G5" in row[0]], "행이 아니라 고지다"


@pytest.mark.asyncio
async def test_self_check_counts_substitutions_by_axis(session, vessel_id):
    """IT-REPORT-003 — 대체 계산을 **축으로 나눈다.** 연료와 거리는 고칠 곳이 다르다."""
    await _make_voyage(session, vessel_id)
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    rows = {row[0]: row for row in _section(document, "제출 전 자체 점검").rows}
    assert "연료 대체 계산" in rows
    assert "거리 대체 계산" in rows
    # 판정 칸은 건수에서 나온다 — 0건이면 「해당 없음」이다.
    for label in ("연료 대체 계산", "거리 대체 계산"):
        count = int(rows[label][1].removesuffix("건"))
        assert rows[label][2] == ("확인 필요" if count else "해당 없음"), label


@pytest.mark.asyncio
async def test_self_check_tells_in_progress_from_unconfirmed(session, vessel_id):
    """IT-REPORT-006 — 진행 중과 실적 확정 전은 **다른 행**이다 (`#1532`).

    종전에는 진행 중 항차 수에 「실적 미입력 (진행 중)」이라는 이름이 붙어 있었다 — 표가
    세는 것과 표에 적힌 이름이 달랐다. 행 이름은 표시 문구라 리터럴로 잠그지 않고
    (`AGENTS §4.6`), **확정을 말하는 행과 진행을 말하는 행이 따로 있고 각각의 수가
    재료와 같다**는 성질을 본다.
    """
    await _make_voyage(session, vessel_id)
    await _make_voyage(session, vessel_id, status="COMPLETED", policy="INCLUDE_AS_ACTUAL")
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    rows = _section(document, "제출 전 자체 점검").rows
    unconfirmed = [row for row in rows if "확정" in row[0]]
    in_progress = [row for row in rows if "진행 중" in row[0]]

    assert len(unconfirmed) == 1 and len(in_progress) == 1
    assert unconfirmed[0] is not in_progress[0]
    # 확정 전 1건(COMPLETED) — 진행 중 항차는 없다. 판정은 건수에서 나온다.
    assert unconfirmed[0][1] == "1건" and unconfirmed[0][2] == "확인 필요"
    assert in_progress[0][1] == "0건" and in_progress[0][2] == "해당 없음"
    # 「미입력」이라는 말은 표 어디에도 없다 — 실적은 들어가 있다(`PRD §8.1`).
    assert not [row for row in rows if "미입력" in row[0]]


@pytest.mark.asyncio
async def test_self_check_unconfirmed_count_matches_the_data_quality_screen(session, vessel_id):
    """리포트의 확정 전 건수와 데이터 점검 화면의 「실적 확정 전」 행 수가 같다 (`#1532`).

    같은 조회(`INCLUDE_AS_ACTUAL` 항차 중 `COMPLETED`)로 세기 때문이다 — 다른 쿼리로
    세면 화면과 인쇄물이 다른 수를 내고, 사무직은 어느 쪽을 믿을지 알 수 없다.
    """
    await _make_voyage(session, vessel_id, status="COMPLETED", policy="INCLUDE_AS_ACTUAL")
    await _make_voyage(session, vessel_id, status="COMPLETED", policy="INCLUDE_AS_ACTUAL")
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    row = next(row for row in _section(document, "제출 전 자체 점검").rows if "확정" in row[0])
    screen = await get_fleet_data_quality(session, regulation_year=YEAR)
    mine = [
        item
        for item in screen["issues"]
        if item["severity"] == SEVERITY_UNCONFIRMED and same_uuid(item["vessel_id"], vessel_id)
    ]

    assert len(mine) == 2, "화면이 두 항차를 확정 전으로 세지 않으면 대조가 성립하지 않는다"
    assert row[1] == f"{len(mine)}건"


@pytest.mark.asyncio
async def test_missing_capacity_stops_the_report_itself(session, vessel_id):
    """IT-REPORT-004 — 제원이 비면 **리포트가 아예 나오지 않는다.**

    처음에는 자체 점검 표에 「선박 제원」 행을 두었는데, 용량 축이 비면 YTD 계산이 서지
    않아 **리포트 생성이 먼저 막힌다.** 그 행은 늘 「확인」만 찍히는 죽은 칸이었다 —
    검사가 그것을 드러내 뺐다. 대신 **막힌다는 사실**을 여기서 잠근다.
    """
    from sqlalchemy import text

    from cii_platform.errors import AppError

    await _make_voyage(session, vessel_id)
    await session.execute(
        text("UPDATE vessel SET deadweight = NULL, gross_tonnage = NULL WHERE id = :vid"),
        {"vid": vessel_id},
    )
    await session.commit()

    with pytest.raises(AppError) as error:
        await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)

    assert "재화중량톤수" in str(error.value) or "총톤수" in str(error.value)


# ─────────────────────────────────────────────────────────────────────────────
# 집계 범위와 맞지 않는 값을 한 문서에 함께 적지 않는다 (#1090)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_share_is_not_printed_for_a_voyage_outside_the_aggregate(session, vessel_id):
    """집계에서 빠진 항차에 「연간 누적에서 차지한 비중」을 찍지 않는다.

    분모 ``ytd.total_co2_t``는 ``INCLUDE_AS_ACTUAL``·같은 규제연도 항차만 더한 값이다.
    분자를 그 집합 **밖의** 항차로 두면 나오는 수는 비중이 아니고, 같은 문서의
    「연간 집계 반영: 연간 반영 안 함」과 **정면으로 어긋난다.**
    """
    # 🔴 **집계에 들어가는 항차를 먼저 하나 만든다.**
    #
    # 이것이 없으면 ``ytd.total_co2_t``가 0이라 종전 코드도 분모 0 가드에 걸려 「—」를
    # 낸다 — 결함을 못 잡는 가짜 검사가 된다(실제로 처음 이렇게 썼다가 돌연변이 검사에서
    # 드러났다).
    await _make_voyage(session, vessel_id)
    voyage_id = await _make_voyage(session, vessel_id, status="COMPLETED")

    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    rows = dict(_section(document, "CII 기여도").rows)
    summary = dict(_section(document, "항차 요약").rows)

    assert summary["연간 집계 반영"] == "연간 반영 안 함", "전제가 깨졌다 — EXCLUDE 항차여야 한다"

    # 사유를 **같은 칸에** 붙인다 (2026-09-17 결정). 리포트는 잘라서 인용되기도 하므로,
    # 위 행과 떨어져 읽히면 「—」가 「값이 아직 안 나왔다」로 보인다.
    #
    # 문구는 새로 짓지 않고 `INCLUSION_POLICY_LABELS`를 그대로 가져다 쓴다.
    assert rows["연간 누적에서 차지한 비중"] == "— (연간 반영 안 함)", (
        "집계에 들어가지 않은 항차에 비중이 찍혔거나 사유가 빠졌다"
    )


@pytest.mark.asyncio
async def test_a_different_regulation_year_is_not_a_mismatch(session, vessel_id):
    """⚠️ **이슈 `#1090`의 전제 하나를 반증하는 검사다.**

    이슈는 「``regulation_year``가 다른 항차에도 비중을 찍는다」고 적었다. 그런데
    리포트는 ``year``를 **그 항차의 규제연도**로 잡아 그 해의 누적을 구한다 — 2025년
    항차는 2025년 누적과 견주므로 어긋날 자리가 없다.

    그래서 여기서는 **비중이 정상적으로 찍히는 것**을 확인한다. 이 검사가 「—」를
    기대하도록 뒤집히면, 누군가 닿지 않는 조건을 다시 넣었다는 뜻이다.
    """
    voyage_id = await _make_voyage(session, vessel_id, regulation_year=2025)

    document = await build_voyage_report(session, voyage_id, as_of=AS_OF)
    rows = dict(_section(document, "CII 기여도").rows)

    assert rows["연간 누적에서 차지한 비중"].endswith("%")


@pytest.mark.asyncio
async def test_not_underway_table_is_cut_at_the_same_as_of_as_the_ytd(session, vessel_id):
    """정박 표와 연간 누적이 **같은 시점**으로 잘린다.

    누적(YTD)은 ``started_at <= as_of``로 자르는데 이 표만 연도 전체를 세고 있었다.
    ``as_of``(7/1) 뒤에 시작하는 구간이 표에만 잡히면, 한 문서 안에서 정박 건수·연료와
    누적 CO₂가 서로 맞지 않는다 — 리포트는 받는 사람이 되물을 수단이 없다.
    """
    future_period = uuid4()
    await session.execute(
        text(
            "INSERT INTO not_underway_period (id, vessel_id, regulation_year, "
            "period_type, started_at, ended_at, distance_nm) VALUES "
            "(:id, :vid, 2026, 'CANAL_TRANSIT', '2026-09-01T00:00:00Z', "
            "'2026-09-02T00:00:00Z', 80)"
        ),
        {"id": future_period, "vid": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO not_underway_fuel_use (period_id, consumer_type, fuel_type, "
            "fuel_ton, cf_used) VALUES (:id, 'MAIN_ENGINE', 'HFO', 15, 3.114)"
        ),
        {"id": future_period},
    )

    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    section = _section(document, "not under way 기여")

    assert section.rows[0][0] == "기록 없음", (
        f"as_of(7/1) 뒤에 시작하는 구간이 표에 잡혔다: {section.rows}"
    )


@pytest.mark.asyncio
async def test_the_empty_not_underway_row_follows_the_digit_rules(session, vessel_id):
    """빈 행도 ``DESIGN_SYSTEM §4.2`` 자릿수를 따른다 — 거리 0자리 · 연료 1자리.

    종전 이 행만 손으로 적은 ``"0.00"``이라 **같은 표의 다른 행과 자릿수가 달랐다**
    (같은 표의 실제 행은 `["운하 통과", "1", "80", "15.0"]`).
    """
    document = await build_annual_report(session, vessel_id, year=YEAR, as_of=AS_OF)
    section = _section(document, "not under way 기여")

    assert section.rows[0] == ["기록 없음", "0", "0", "0.0"]


# ─────────────────────────────────────────────────────────────────────────────
# 렌더링은 DB 커넥션을 쥐고 기다리지 않는다 — #1363
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rendering_does_not_hold_the_db_connection(session, vessel_id, monkeypatch):
    """문서를 다 읽었으면 **렌더링 전에 트랜잭션을 닫는다** (`#1363` · `#1364`).

    수집은 읽기만 하지만 읽기도 트랜잭션을 열어(autobegin) 커넥션을 체크아웃한 채로 둔다.
    그 상태로 렌더링(1초 안팎, 동시 상한이 1이라 줄을 서면 더)에 들어가면 커넥션이 그
    시간만큼 묶이고, 기본 풀(5+10)이 마르면 **리포트와 무관한 요청까지** 30초 뒤 실패한다.

    렌더링 시점의 세션 상태를 그대로 본다 — 「닫았다」를 코드로 확인하는 가장 좁은 방법이다.
    """
    from cii_platform.api.routes.reports import voyage_report_route
    from cii_platform.reports import pdf as pdf_module

    voyage_id = await _make_voyage(session, vessel_id)
    seen: dict[str, bool] = {}

    def _probe_render(_html: str) -> bytes:
        seen["in_transaction"] = session.in_transaction()
        return b"%PDF-fake"

    monkeypatch.setattr(pdf_module, "render_pdf", _probe_render)

    response = await voyage_report_route(
        request=None,  # 라우트 본문이 쓰지 않는다 — 미들웨어용 인자다
        voyage_id=voyage_id,
        session=session,
        _office=None,
        format="pdf",
        as_of=AS_OF,
    )

    assert response.body == b"%PDF-fake"
    assert seen["in_transaction"] is False, "렌더링 동안 DB 커넥션을 쥐고 있었다"
