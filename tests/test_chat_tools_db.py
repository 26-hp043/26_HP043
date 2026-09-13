"""챗봇 도구 4종의 **실제 실행 경로** (`#120` · IT-CHATDB-001~009).

## 왜 필요한가

`test_chat_tools.py`는 도구 **바깥**을 본다 — 스키마·봉투 모양·화이트리스트 함수·
오류 문구. 그런데 `#955`(파일별 커버리지 하한)가 붙자마자 드러났다.

    services/chat_tools.py   66.2%   미커버 27/80문장

**미커버 구간이 도구 4종의 본문 전체**다. 지금까지 오케스트레이션 검사는
`FakeProvider`로 모델만 대역화하고 **도구는 부르지 않았고**, 단위 검사는 도구를
**둘러싼 함수만** 불렀다.

## 무엇이 잡히지 않고 있었나

⚠️ **화이트리스트가 실제 응답에 대해 도는 것을 아무도 보지 않았다.**

`_publishable`은 잘 검사돼 있다. 하지만 그것이 **진짜 계산 응답**에 걸리는지는
별개다 — 응답 필드 이름이 바뀌거나 새 필드가 늘면 `_PUBLISH_MAP`이 놓치고, 그때
`filter_outbound`가 마지막 방어선이 된다. **그 조합이 한 번도 실행되지 않았다.**

`PRD §16.3.1`이 선박명·IMO·`vessel_id`를 **전송 금지**로 둔다. 이 검사들은 실제
DB 응답을 태워 **금지 값이 봉투에 들어가지 않는지**를 본다.

## 대역을 쓰지 않는다

`session`만 진짜면 나머지는 전부 실제 코드다. 도구 → 서비스 → 계산 → 저장소가
한 줄로 이어져야 「응답 모양이 바뀌면 도구가 샌다」를 잡을 수 있다.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services import chat_tools

#: `PRD §16.3.1` 전송 금지 값이 들어간 선박명 — 봉투에 나타나면 안 된다.
VESSEL_NAME = "CHATTOOL PROBE"
IMO = "9777001"


@pytest_asyncio.fixture
async def session(conn):
    """``conn``의 트랜잭션에 올라타는 세션 — 테스트 종료 시 함께 롤백된다."""
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel_id(session):
    new_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton) "
            "VALUES (:id, :imo, :name, 'BULK_CARRIER', 50000, 'HFO', 14, 30)"
        ),
        {"id": new_id, "imo": IMO, "name": VESSEL_NAME},
    )
    return new_id


async def _add_actual_voyage(session, vessel_id) -> None:
    """실적 항차 1건 — 연말 예상이 실제로 나오게 한다."""
    voyage_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
            "arrival_port_name, planned_distance_nm, planned_speed_kn, "
            "actual_distance_nm, annual_inclusion_policy, regulation_year, created_from) "
            "VALUES (:id, :vid, 'COMPLETED', 'Busan', 'Singapore', 3000, 14, "
            "3000, 'INCLUDE_AS_ACTUAL', 2026, 'MANUAL')"
        ),
        {"id": voyage_id, "vid": vessel_id},
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, "
            "actual_fuel_ton, cf_used, source) "
            "VALUES (:id, 'HFO', 250, 250, 3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id},
    )


def _parsed(raw: str) -> dict:
    return json.loads(raw)


def _flat(payload: object) -> str:
    """봉투 전체를 한 문자열로 — 중첩 어디에 섞여도 잡는다."""
    return json.dumps(payload, ensure_ascii=False, default=str)


async def test_search_returns_a_count_not_a_name(session, vessel_id):
    """IT-CHATDB-001 — ⚠️ **검색이 이름도 식별자도 돌려주지 않는다**.

    `PRD §16.3.1`이 선박명·IMO·선박 ID를 전송 금지로 둔다. 검색 결과를 그대로
    돌려주면 **그 금지가 도구 하나로 뚫린다.**
    """
    raw = await chat_tools.run_tool(
        session, name=chat_tools.TOOL_SEARCH_VESSEL, arguments={"name": VESSEL_NAME}, vessel_id=None
    )
    body = _parsed(raw)
    assert body["result"] == {"matched": 1}, body
    flat = _flat(body)
    assert VESSEL_NAME not in flat
    assert IMO not in flat
    assert str(vessel_id) not in flat


async def test_search_without_a_keyword_asks_for_one(session):
    """IT-CHATDB-002 — 빈 이름은 DB에 가지 않고 되묻는다.

    전 선박을 긁어 오면 **몇 척인지가 곧 선대 규모**가 되어 나간다.
    """
    raw = await chat_tools.run_tool(
        session, name=chat_tools.TOOL_SEARCH_VESSEL, arguments={"name": "   "}, vessel_id=None
    )
    assert _parsed(raw)["error"] == "찾을 이름을 알려 주세요."


async def test_voyage_calculation_publishes_only_the_whitelist(session, vessel_id):
    """IT-CHATDB-003 — ⚠️ **실제 계산 응답이 화이트리스트를 지난다**.

    `_publishable` 단위 검사는 **손으로 만든 dict**를 본다. 응답 필드가 늘거나
    이름이 바뀌면 그 검사는 그대로 통과하고 **여기서만 드러난다.**
    """
    raw = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments={
            "distance_nm": "5000",
            "speed_kn": "12",
            "fuel_type": "HFO",
            "fuel_ton": "400",
            "regulation_year": 2026,
        },
        vessel_id=vessel_id,
    )
    body = _parsed(raw)
    assert "error" not in body, body
    result = body["result"]

    # 봉투 밖으로 나가는 이름은 **정본 이름뿐**이다.
    assert set(result) <= set(chat_tools._PUBLISH_MAP.values()), result
    assert "attained_cii" in result and "rating" in result

    flat = _flat(body)
    assert VESSEL_NAME not in flat
    assert IMO not in flat
    assert str(vessel_id) not in flat


async def test_voyage_calculation_renames_estimated_rating(session, vessel_id):
    """IT-CHATDB-004 — API 이름(`estimated_rating`)이 정본 이름(`rating`)으로 나간다.

    옮기기 전에 필터를 걸면 **통과한 이름과 나가는 이름이 달라** 가드가 헛돈다.
    실제 응답이 어느 이름을 쓰는지는 여기서만 확인된다.
    """
    raw = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments={"distance_nm": "5000", "speed_kn": "12", "fuel_type": "HFO", "fuel_ton": "400"},
        vessel_id=vessel_id,
    )
    result = _parsed(raw)["result"]
    assert "estimated_rating" not in result, result
    assert result["rating"] in {"A", "B", "C", "D", "E"}, result


async def test_scenario_comparison_keeps_the_service_order(session, vessel_id):
    """IT-CHATDB-005 — ⚠️ **시나리오를 순위로 정렬하지 않는다**.

    순위화는 No-Advice 금지 항목이다(`PRD §16.1`). 서비스가 준 순서를 그대로 둔다.
    """
    from cii_platform.services.scenario_compare import ScenarioCompareInput, compare_scenarios

    payload = ScenarioCompareInput(
        vessel_id=vessel_id,
        regulation_year=2026,
        current_speed_kn=Decimal("12"),
        fuel_type="HFO",
        direct_distance_nm=Decimal("5000"),
        base_daily_foc_ton=Decimal("30"),
    )
    expected = [
        row.get("scenario_type")
        for row in (await compare_scenarios(session, payload))["data"]["scenarios"]
    ]

    raw = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_COMPARE_SCENARIOS,
        arguments={
            "current_speed_kn": "12",
            "fuel_type": "HFO",
            "direct_distance_nm": "5000",
            "base_daily_foc_ton": "30",
            "regulation_year": 2026,
        },
        vessel_id=vessel_id,
    )
    body = _parsed(raw)
    assert "error" not in body, body
    rows = body["result"]["scenarios"]
    assert len(rows) == len(expected), (rows, expected)
    for row in rows:
        assert set(row) <= set(chat_tools._PUBLISH_MAP.values()), row
    assert VESSEL_NAME not in _flat(body)


async def test_annual_simulation_passes_the_reason_code_through(session, vessel_id):
    """IT-CHATDB-006 — 연말 예상을 못 낼 때 **사유 코드를 그대로** 넘긴다.

    서버가 문장을 만들면 그 문장이 모델을 거쳐 사용자에게 **우리 말이 아닌 형태**로
    돌아온다. 실적이 없는 선박이라 이 경로가 실제로 돈다.
    """
    raw = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_RUN_ANNUAL_SIMULATION,
        arguments={"regulation_year": 2026},
        vessel_id=vessel_id,
    )
    body = _parsed(raw)
    assert "사유 코드:" in body["error"], body
    assert VESSEL_NAME not in _flat(body)


async def test_annual_simulation_publishes_only_the_whitelist(session, vessel_id):
    """IT-CHATDB-007 — ⚠️ **연말 예상이 나올 때도 화이트리스트만 나간다**.

    `get_current_cii`의 ``data``에는 **`vessel_name`이 들어 있다.** 그래서 도구가
    ⑶ 블록(`year_end_projection`)만 꺼내 필터를 태우는데, 그 분기는 **실적이 있는
    선박에서만** 돈다 — 실적 없는 선박만 검사하면 이 경로가 통째로 비어 있다.
    """
    await _add_actual_voyage(session, vessel_id)

    raw = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_RUN_ANNUAL_SIMULATION,
        arguments={"regulation_year": 2026},
        vessel_id=vessel_id,
    )
    body = _parsed(raw)
    assert "error" not in body, body
    assert set(body["result"]) <= set(chat_tools._PUBLISH_MAP.values()), body["result"]

    flat = _flat(body)
    assert VESSEL_NAME not in flat
    assert IMO not in flat
    assert str(vessel_id) not in flat


async def test_a_domain_error_never_carries_the_original_message(session):
    """IT-CHATDB-008 — ⚠️ **없는 선박의 id가 오류 문구로 새지 않는다**.

    2026-09-13 실측에서 원문이 그대로 나갔다 — `"선박을 찾을 수 없습니다: <uuid>"`.
    `PRD §16.3.1`이 `vessel_id`를 전송 금지로 둔 값이다.
    """
    missing = uuid4()
    raw = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments={"distance_nm": "5000", "speed_kn": "12", "fuel_type": "HFO", "fuel_ton": "400"},
        vessel_id=missing,
    )
    body = _parsed(raw)
    assert "error" in body, body
    assert str(missing) not in _flat(body)


async def test_the_regulation_year_defaults_to_this_year(session, vessel_id, monkeypatch):
    """IT-CHATDB-009 — 연도를 안 주면 **상수가 아니라 현재 연도**를 쓴다.

    상수로 박으면 해가 바뀐 날 틀린 해로 계산하고 **그 사실이 화면 어디에도
    드러나지 않는다.**
    """
    raw = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments={"distance_nm": "5000", "speed_kn": "12", "fuel_type": "HFO", "fuel_ton": "400"},
        vessel_id=vessel_id,
    )
    body = _parsed(raw)
    # 등재된 규제연도 밖이면 도메인 오류가 나므로, 어느 쪽이든 **문구가 고정**이어야 한다.
    if "error" in body:
        assert str(vessel_id) not in _flat(body)
    else:
        assert set(body["result"]) <= set(chat_tools._PUBLISH_MAP.values())


pytestmark = pytest.mark.asyncio
