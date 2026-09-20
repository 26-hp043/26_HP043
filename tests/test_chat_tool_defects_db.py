"""챗봇 도구의 네 결함 (`#1334`).

네 가지가 서로 다른 층에 있지만 **한 화면에서 같이 드러난다** — 「다음 등급까지 얼마나
남았어?」 한 번에 ⑴ 인자가 빠지면 500 ⑵ 화면 표기로 답하면 폐기 ⑶ 지어낸 「7%」는 통과
⑷ 그 사이 지울 수 없는 계산 행이 쌓인다.

## ⑵와 ⑶은 **함께** 고쳐야 한다

따로 고치면 각각 반대 방향으로 깨진다.

* ⑶만 고치면 — `%`가 붙은 한 자리를 대조하는데 도구가 백분율을 주지 않으므로
  **화면과 같은 `1.2%`가 전부 폐기**된다(⑵가 악화).
* ⑵만 고치면 — 지어낸 `7%`는 여전히 한 자리라 **무검사로 통과**한다(⑶ 그대로).

케이스 (`TEST_PLAN §14.5`): IT-CHAT — 도구 인자 · 수치 가드 · 계산 격리
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import ensure_regulation_year, insert_if_not_exists
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.services import chat_tools
from cii_platform.services.llm_guard import (
    NumberFabricationError,
    extract_numbers,
    verify_numbers,
)

YEAR = 2026


# --------------------------------------------------------------------------
# ⑴ 도구 인자 오류가 턴을 죽이지 않는다
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({"distance_nm": 1000, "speed_kn": 14, "fuel_type": "HFO"}, id="missing"),
        pytest.param(
            {"distance_nm": "약 100", "speed_kn": 14, "fuel_type": "HFO", "fuel_ton": 80},
            id="not-a-number",
        ),
        pytest.param(
            {
                "distance_nm": 1000,
                "speed_kn": 14,
                "fuel_type": "HFO",
                "fuel_ton": 80,
                "regulation_year": "2026년",
            },
            id="year-with-unit",
        ),
    ],
)
async def test_bad_tool_arguments_come_back_as_an_envelope(arguments) -> None:
    """500이 아니라 **봉투**다 (`#1334` ⑴).

    500이면 `answer()`에서 라우트까지 예외가 올라가 턴이 끊기고, **롤백으로 방금
    저장한 사용자 질문까지 사라진다.**
    """
    outcome = await chat_tools.run_tool(
        None,  # type: ignore[arg-type]
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments=arguments,
        vessel_id=uuid4(),
    )
    body = json.loads(outcome.envelope)

    assert body["ok"] is False
    assert body["error"] == chat_tools._error_text(chat_tools.ToolArgumentError("x"))


async def test_a_bad_optional_argument_is_not_swallowed() -> None:
    """선택 인자가 읽히지 않으면 **`None`으로 삼키지 않는다** (`#1334` ⑴).

    삼키면 모델이 보낸 조건이 **조용히 사라지고**, 그 답은 사용자가 물은 것과 다른
    계산의 결과가 된다 — 오류보다 나쁘다.
    """
    outcome = await chat_tools.run_tool(
        None,  # type: ignore[arg-type]
        name=chat_tools.TOOL_COMPARE_SCENARIOS,
        arguments={"current_speed_kn": 14, "fuel_type": "HFO", "direct_distance_nm": "약 1000"},
        vessel_id=uuid4(),
    )

    assert json.loads(outcome.envelope)["ok"] is False


def test_the_envelope_names_no_argument() -> None:
    """어느 인자가 잘못됐는지도 말하지 않는다.

    인자 이름은 모델이 스스로 보낸 것이라 유출은 아니지만, 문구를 인자마다 만들면
    **오류 문구가 값을 실어 나르는 경로**가 하나 더 생긴다(`#1310`이 화이트리스트가
    오류 경로로 뚫린 것을 고쳤다).
    """
    text_out = chat_tools._error_text(chat_tools.ToolArgumentError("fuel_ton"))

    assert "fuel_ton" not in text_out


# --------------------------------------------------------------------------
# ⑵ 화면 표기로 답할 수 있다  ·  ⑶ 지어낸 백분율은 막힌다
# --------------------------------------------------------------------------

#: 도구가 내려주는 비율 한 건. 화면은 이 값을 `1.2%`로 그린다.
GAP_RATIO = "0.012345"


def _tool_output() -> str:
    return chat_tools.envelope(
        chat_tools.TOOL_CALC_VOYAGE_CII,
        result=chat_tools._publishable(
            {"next_worse_boundary_margin_ratio": GAP_RATIO},
            chat_tools._RESULT_KEYS,
        ),
    )


def test_the_tool_carries_the_screen_notation() -> None:
    """도구 응답에 **비율과 백분율이 함께** 있다 (`#1334` ⑵).

    가드를 넓히는 대신 **출처 쪽**을 고친 것이다 — 가드가 ×100을 무조건 허용하면
    도구가 `0.07`을 준 답에서 `7%`도 통과하는데, **다른 뜻의 수**다.
    """
    numbers = extract_numbers(_tool_output())

    assert GAP_RATIO in numbers
    assert "1.2" in numbers


def test_answering_like_the_screen_is_not_discarded() -> None:
    """종전에는 **이것이 폐기됐다** — 화면과 같은 표기인데.

    `_rounded_forms` 주석이 같은 문제를 이미 한 번 겪었다: 「화면과 같은 자릿수로
    말할 수 없으면 **면책이 거짓**이 된다」(`PRD §6.3`). 자릿수는 고쳤는데 단위는
    고치지 않았던 것이다.
    """
    verify_numbers("다음 등급까지 여유는 1.2%입니다.", [_tool_output()])


def test_the_ratio_form_still_passes() -> None:
    """대조군 — 종전에 통과하던 표기는 그대로 통과해야 한다."""
    verify_numbers("다음 등급까지 여유는 0.012입니다.", [_tool_output()])


def test_a_made_up_percent_is_discarded() -> None:
    """⑶ — 한 자리라서 **무검사로 통과**하던 자리 (`#1334`).

    통과한 답은 「검증된 답」으로 저장되고 `prior_answers`로 **다음 턴에 다시
    허용**된다 — 한 번 새면 대화 내내 남는다.
    """
    with pytest.raises(NumberFabricationError):
        verify_numbers("다음 등급까지 여유는 7%입니다.", [_tool_output()])


@pytest.mark.parametrize("sentence", ["3가지 방법이 있습니다.", "2026년 기준입니다."])
def test_ordinary_small_numbers_are_still_ignored(sentence: str) -> None:
    """무시 목록을 **통째로 없애지 않았다** — 없애면 맞는 답이 폐기된다."""
    verify_numbers(sentence, [_tool_output()])


# --------------------------------------------------------------------------
# ⑷ 챗봇 계산이 지울 수 없는 행을 남기지 않는다
# --------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest_asyncio.fixture
async def vessel(session):
    await ensure_regulation_year(session, YEAR, z_factor=9.0)
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

    vessel_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
            "default_fuel_type, reference_speed_kn, reference_daily_foc_ton) "
            "VALUES (:id, :imo, 'CHAT ISOLATION TEST', 'BULK_CARRIER', 50000, "
            "'HFO', 14, 30)"
        ),
        {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
    )
    await session.commit()
    return vessel_id


async def _run_count(session, vessel_id) -> int:
    row = await session.execute(
        text("SELECT COUNT(*) FROM calculation_run WHERE vessel_id = :v"), {"v": vessel_id}
    )
    return int(row.scalar_one())


@pytest.mark.asyncio
async def test_the_screen_path_still_records_its_calculation(session, vessel) -> None:
    """**먼저 화면 경로가 남기는지 확인한다.**

    남기지 않으면 아래 검사가 **아무것도 고정하지 못한다** — 0 == 0으로 통과한다.
    """
    from cii_platform.services.voyage_cii import FuelUseInput, VoyageCiiInput, estimate_voyage_cii

    before = await _run_count(session, vessel)
    response = await estimate_voyage_cii(
        session,
        VoyageCiiInput(
            vessel_id=vessel,
            regulation_year=YEAR,
            distance_nm=Decimal("1000"),
            speed_kn=Decimal("14"),
            fuel_uses=(FuelUseInput(fuel_type="HFO", fuel_ton=Decimal("80")),),
        ),
    )

    assert await _run_count(session, vessel) == before + 1
    assert response["calculation_run_id"] is not None


@pytest.mark.asyncio
async def test_the_chat_path_leaves_nothing_behind(session, vessel) -> None:
    """⑷ — 챗봇 도구는 `calculation_run`에 행을 남기지 않는다 (`PRD §16.2`).

    ⚠️ 그 표에는 **출처 열이 없고 삭제 금지 트리거**가 걸려 있다. 시연 중 질문
    한 번마다 모델이 만든 입력의 행이 **화면 계산과 구별 없이** 쌓이고 지울 수 없다 —
    **답변이 폐기돼도 행은 남는다.**
    """
    before = await _run_count(session, vessel)
    outcome = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments={"distance_nm": 1000, "speed_kn": 14, "fuel_type": "HFO", "fuel_ton": 80},
        vessel_id=vessel,
    )

    assert json.loads(outcome.envelope)["ok"] is True, outcome.envelope
    assert await _run_count(session, vessel) == before


@pytest.mark.asyncio
async def test_the_chat_path_still_answers_with_real_numbers(session, vessel) -> None:
    """저장을 끊었다고 **계산까지 끊긴 것이 아니다.**

    챗봇과 화면이 **같은 함수**를 쓴다 — 경로를 따로 만들면 「챗봇이 말하는 값과
    화면 값이 다르다」가 생긴다.
    """
    outcome = await chat_tools.run_tool(
        session,
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments={"distance_nm": 1000, "speed_kn": 14, "fuel_type": "HFO", "fuel_ton": 80},
        vessel_id=vessel,
    )
    body = json.loads(outcome.envelope)

    assert body["result"]["attained_cii"]
    assert body["result"]["rating"]
