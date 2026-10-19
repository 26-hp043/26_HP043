"""챗봇 도구 계층 (`#121` · IT-CHAT-016~023 · `#2395` IT-CHAT-097~099).

DB를 쓰지 않는 것만 여기 둔다 — 봉투 규약과 **화이트리스트 경계**다. 실제 계산을
도는 경로는 ``tests/test_chat_api_db.py``가 끝에서 끝까지 본다.

## 이 파일이 지키는 것

``PRD §16.3.1``이 「무엇을 보내지 않는가」를 정했고, 그것을 뚫는 가장 쉬운 길이
**도구 응답**이다. 사람이 `filter_outbound`를 부르는 것을 잊으면 아무 소리 없이
선박명이 나간다. 그래서 **도구 응답의 모양 자체**를 검사한다.
"""

from __future__ import annotations

import json

import pytest

from cii_platform.errors import (
    CalculationError,
    NotFoundError,
    ParameterError,
    ValidationError,
)
from cii_platform.services import chat_tools
from cii_platform.services.llm_guard import OUTBOUND_WHITELIST, OutboundFieldError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "implementation_name"),
    [
        (chat_tools.TOOL_LOOKUP_REGULATION, "_lookup_regulation"),
        (chat_tools.TOOL_PROJECT_YEAR_END, "_project_year_end"),
        (chat_tools.TOOL_CALC_VOYAGE_CII, "_calc_voyage_cii"),
        (chat_tools.TOOL_COMPARE_SCENARIOS, "_compare_scenarios"),
    ],
)
async def test_turn_year_is_used_only_when_the_tool_year_is_missing(
    monkeypatch, tool_name, implementation_name
):
    """자정 경계 뒤 도구가 시간을 다시 읽어 다른 '올해'를 고르지 않는다 (#2355)."""
    received: list[dict[str, object]] = []

    async def _lookup(_session, arguments, _vessel_id):
        received.append(arguments)
        return "{}"

    monkeypatch.setattr(chat_tools, implementation_name, _lookup)
    await chat_tools.run_tool(
        None,
        name=tool_name,
        arguments={},
        vessel_id="selected",
        current_year=2027,
    )
    await chat_tools.run_tool(
        None,
        name=tool_name,
        arguments={"regulation_year": 2025},
        vessel_id="selected",
        current_year=2027,
    )
    await chat_tools.run_tool(
        None,
        name=tool_name,
        arguments={"regulation_year": 2025},
        vessel_id="selected",
        current_year=2027,
        current_year_only=True,
    )
    assert received == [
        {"regulation_year": 2027},
        {"regulation_year": 2025},
        {"regulation_year": 2027},
    ]


def test_tool_schemas_cover_exactly_the_registered_tools() -> None:
    """IT-CHAT-016 — 등록된 도구 목록이 스키마와 일치하고, **쓰기 도구가 없다**."""
    names = [schema["name"] for schema in chat_tools.tool_schemas()]
    assert names == list(chat_tools.TOOL_NAMES)
    # `#121` 본문의 `create_voyage`를 넣지 않기로 한 결정이 코드에 남아 있는지 본다.
    assert "create_voyage" not in names


def test_year_end_tool_name_and_description_drop_the_simulation_framing() -> None:
    """`#1534`(결정요청 v6 `D-32`) — 이름과 설명이 **결정론 계산**을 말한다.

    이 도구는 몬테카를로 확률이 아니라 확정 실적 + 잔여 계획을 외삽한 값을 낸다
    (``PRD §3.3`` ⑶). 종전 이름 ``run_annual_simulation``과 설명의 「시뮬레이션」·
    「기능③」은 `PRD §12`의 확률 시뮬레이션을 가리켜 혼동을 낳았다 — 성질을
    단언한다(``AGENTS §4.6``): 그 두 표현이 **없어야 한다**.
    """
    assert chat_tools.TOOL_PROJECT_YEAR_END == "project_year_end"
    schema = next(
        s for s in chat_tools.tool_schemas() if s["name"] == chat_tools.TOOL_PROJECT_YEAR_END
    )
    description = str(schema["description"])
    assert "시뮬레이션" not in description
    assert "기능③" not in description


def test_tool_schemas_are_described_in_korean() -> None:
    """IT-CHAT-017 — 설명이 한국어다.

    모델이 도구를 고르는 근거가 이 설명이고 사용자는 한국어로 묻는다. 영어로 적으면
    한 번 더 번역해 판단하게 된다.
    """
    for schema in chat_tools.tool_schemas():
        description = str(schema["description"])
        assert any("가" <= ch <= "힣" for ch in description), schema["name"]


def test_envelope_carries_structure_not_domain_values() -> None:
    """IT-CHAT-018 — 봉투에는 **우리가 만든 상수만** 담긴다."""
    body = json.loads(chat_tools.envelope("calc_voyage_cii", result={"rating": "C"}))
    assert body == {"tool": "calc_voyage_cii", "ok": True, "result": {"rating": "C"}}

    failed = json.loads(chat_tools.envelope("calc_voyage_cii", error="없습니다."))
    assert failed == {"tool": "calc_voyage_cii", "ok": False, "error": "없습니다."}


def test_publishable_renames_api_fields_to_canonical_names() -> None:
    """IT-CHAT-019 — `estimated_rating` → `rating`으로 **경계에서** 맞춘다.

    화이트리스트를 넓히지 않는다는 결정(`chat_tools._PUBLISH_MAP` 주석)이 지켜지는지
    본다. 옮긴 **뒤**에 필터가 걸리므로, 나가는 이름이 곧 통과한 이름이다.
    """
    published = chat_tools._publishable(
        {
            "estimated_rating": "C",
            "attained_cii": "4.98",
            "next_worse_boundary_margin_ratio": "0.012",
            # 화이트리스트 밖 — 응답에 실제로 들어 있는 값들이다.
            "vessel_id": "3f2a9c10-0000-4000-8000-000000000002",
            "distance_nm": 1000.0,
            "fuel_consumption_ton": "80.0",
        },
        chat_tools._RESULT_KEYS,
    )
    assert published == {
        "rating": "C",
        "attained_cii": "4.98",
        # `#1334` ⑵ — 비율에는 **화면 표기가 함께 실린다**. 키는 늘어나지 않는다.
        "next_boundary_gap": "0.012 (1.2%)",
    }
    assert set(published) <= OUTBOUND_WHITELIST


def test_publishable_drops_unmapped_keys_and_the_filter_still_guards() -> None:
    """IT-CHAT-020 — 두 겹이 **다른 방향으로** 막는다.

    ⑴ 대응표에 없는 이름은 :func:`chat_tools._publishable`이 **조용히 뺀다.** 실패
    방향이 「값이 빠진다」이지 「값이 샌다」가 아니라는 것이 중요하다 — 누군가
    ``_RESULT_KEYS``만 늘리고 대응표를 잊어도 새는 쪽으로 기울지 않는다.

    ⑵ 그래도 아래 겹(``filter_outbound``)이 살아 있어야 한다. 대응표를 **잘못**
    고쳐 목록 밖 이름이 도착지가 되면 그때는 막혀야 한다.
    """
    assert chat_tools._publishable({"vessel_name": "DEMO"}, ("vessel_name",)) == {}

    from cii_platform.services.llm_guard import filter_outbound

    with pytest.raises(OutboundFieldError):
        filter_outbound({"vessel_name": "DEMO"})


def test_publish_map_targets_stay_inside_the_canonical_whitelist() -> None:
    """IT-CHAT-021 — 이름 대응표의 **도착지가 전부** 정본 목록 안이다.

    대응표에 새 항목을 넣을 때 도착지를 잘못 적으면 필터가 그때서야 막는다 —
    그것은 **런타임 실패**다. 여기서 미리 잡는다.
    """
    assert set(chat_tools._PUBLISH_MAP.values()) <= OUTBOUND_WHITELIST


async def test_unknown_tool_returns_an_error_envelope() -> None:
    """IT-CHAT-022 — 모르는 도구는 **예외가 아니라 봉투**로 돌아온다.

    예외로 올리면 한 턴이 통째로 죽는다. 모델이 이름을 틀리는 것은 흔한 일이고,
    봉투로 돌려주면 모델이 읽고 고쳐 부를 수 있다.
    """
    outcome = await chat_tools.run_tool(None, name="drop_table", arguments={}, vessel_id=None)  # type: ignore[arg-type]
    body = json.loads(outcome.envelope)
    assert body["ok"] is False
    assert "error" in body


def test_domain_error_text_never_carries_the_original_message() -> None:
    """IT-CHAT-048 — ⚠️ **도메인 오류의 원문을 봉투에 넣지 않는다** (2026-09-13 실측 결함).

    ``NotFoundError("선박을 찾을 수 없습니다: <UUID>")`` 같은 문구를 그대로 넘기고
    있었다. ``PRD §16.3.1``이 ``vessel_id``를 **전송 금지**로 두는데, 그 값이 오류
    칸을 타고 외부 모델로 나갔다 — **화이트리스트가 오류 경로로 뚫렸다.**

    어느 문구가 안전한지 목록으로 관리하는 방식은 성립하지 않는다: 새 오류가 생길
    때마다 검토가 필요하고, 빠뜨리면 조용히 샌다. 그래서 **종류별 고정 문구**로
    바꿨고, 이 검사가 그 규칙을 잠근다.
    """
    secret = "3d56c710-089e-4299-95b3-e48650318d45"
    for kind in (NotFoundError, ParameterError, CalculationError, ValidationError):
        text = chat_tools._error_text(kind(f"선박을 찾을 수 없습니다: {secret}"))
        assert secret not in text, kind.__name__
        # 우리가 만든 상수여야 한다 — 표에 있는 문구 그대로.
        assert text in {t for _k, t in chat_tools._ERROR_TEXT}, (kind.__name__, text)


async def test_unknown_vessel_does_not_leak_its_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """IT-CHAT-049 — **실제 경로**로도 식별자가 나가지 않는다.

    위 검사는 함수 하나를 본다. 이것은 ``run_tool``의 ``except`` 절이 그 함수를 **실제로
    쓰는지**를 본다 — `#121`에서 반복해 겪은 「구현은 있고 부르는 곳이 없는」 형태를
    막는다.
    """
    from uuid import uuid4

    ghost = uuid4()

    async def _boom(*_a, **_k):
        raise NotFoundError(f"선박을 찾을 수 없습니다: {ghost}")

    monkeypatch.setattr(chat_tools, "_calc_voyage_cii", _boom)
    outcome = await chat_tools.run_tool(
        None,  # type: ignore[arg-type]
        name=chat_tools.TOOL_CALC_VOYAGE_CII,
        arguments={},
        vessel_id=ghost,
    )
    body = json.loads(outcome.envelope)
    assert body["ok"] is False
    assert str(ghost) not in json.dumps(body, ensure_ascii=False)


async def test_calculation_tools_need_a_vessel_first() -> None:
    """IT-CHAT-023 — 선박이 정해지지 않으면 계산 도구가 돌지 않는다.

    ⚠️ **모델은 `vessel_id`를 모른다** — 식별자는 화이트리스트 밖이라 넘기지 않는다.
    그래서 「어느 선박인지」는 화면이나 `search_vessel`이 정하고, 서버가 들고 있는다.
    """
    for name in (
        chat_tools.TOOL_CALC_VOYAGE_CII,
        chat_tools.TOOL_COMPARE_SCENARIOS,
        chat_tools.TOOL_PROJECT_YEAR_END,
    ):
        outcome = await chat_tools.run_tool(None, name=name, arguments={}, vessel_id=None)  # type: ignore[arg-type]
        body = json.loads(outcome.envelope)
        assert body["ok"] is False, name


async def test_screen_result_tool_needs_a_run_from_the_screen() -> None:
    """`#1533` — 화면이 실행 id를 넘기지 않았으면 **읽지도 계산하지도 않고** 오류 봉투다.

    선박이 없어도 같은 오류다 — 이 도구는 선박이 아니라 화면의 실행을 기준으로 한다.
    """
    outcome = await chat_tools.run_tool(
        None,  # type: ignore[arg-type]
        name=chat_tools.TOOL_EXPLAIN_SCREEN_RESULT,
        arguments={},
        vessel_id=None,
    )
    body = json.loads(outcome.envelope)
    assert body["ok"] is False
    assert body["tool"] == chat_tools.TOOL_EXPLAIN_SCREEN_RESULT


def test_probabilities_carry_the_screen_percent() -> None:
    """`#1533` — 확률도 화면 표기(소수 1자리 %)를 덧붙인다 — ``next_boundary_gap``과 같은 규칙.

    화면이 81.2%로 보여 주는데 도구가 0.8123만 주면, 모델이 화면대로 말한 답이 수치 검증에
    걸려 폐기된다(`#1334` ⑵와 같은 경로).
    """
    out = chat_tools._publishable(
        {
            "target_success_probability": "0.8123",
            "rating_probabilities": {"B": "0.3", "A": "0.1"},
            "target_rating": "C",
        },
        chat_tools._ANNUAL_KEYS,
    )
    assert out["target_success_probability"] == "0.8123 (81.2%)"
    assert out["rating_probabilities"] == {"A": "0.1 (10.0%)", "B": "0.3 (30.0%)"}
    assert out["target_rating"] == "C"


def test_system_prompt_makes_regulation_answers_keep_their_meaning() -> None:
    """IT-CHAT-071 (`#1973` ①②④) — 규제값을 **뜻까지** 옮기게 한다.

    09-27 운영 답이 값은 맞게, 뜻은 틀리게 말했다 — 등급 경계를 「CII < 0.8600」처럼
    CII 값의 경계로 · 기준선을 「DWT에 관계없이 동일」로 · 감축률을 연도 없이. 문구가 아니라
    **규칙이 무엇을 가리키는가**를 본다(`AGENTS §4.6`): 경계는 비율 · 기준선은 조건과 용량
    규칙 · 감축률은 도구가 준 연도와 함께.
    """
    from cii_platform.services.chat import SYSTEM_PROMPT

    assert "비율" in SYSTEM_PROMPT and "d1" in SYSTEM_PROMPT
    assert "condition_expr" in SYSTEM_PROMPT and "capacity_rule" in SYSTEM_PROMPT
    assert "reduction_factor.year" in SYSTEM_PROMPT
    # 도구 응답에 실제로 있는 칸을 가리킨다 — 없는 칸을 가리키면 모델이 지어낸다.
    assert "condition_expr" in chat_tools._REFERENCE_LINE_FIELDS
    assert "capacity_rule" in chat_tools._REFERENCE_LINE_FIELDS
    assert {"d1", "d2", "d3", "d4"} <= set(chat_tools._BOUNDARY_FIELDS)


def test_the_prompt_puts_a_boundary_value_in_the_better_grade_like_the_engine() -> None:
    """IT-CHAT-077 (`#1973` 후속) — 경계에 **정확히 걸린 배는 더 우수한 등급**이다.

    (종전 번호 `IT-CHAT-073`은 같은 날 `#1985`가 먼저 써 겹쳤다 — 이쪽을 옮겼다.)

    09-28 운영 답이 「D등급: 기준 CII의 1.06배 이상, 1.18배 미만」이라 적었다 — 포함 방향이
    반대다. 원인은 규칙의 예시 「d1배 **미만**」이었고 모델은 그 틀을 따랐다. 규칙이 **엔진의
    판정과 같은 방향**을 가르치는지 엔진을 직접 돌려 대조한다 — 문구만 보면 엔진이 바뀌는 날
    다시 갈린다.
    """
    from decimal import Decimal

    from cii_platform.calc.rating_engine import DVector, determine_rating
    from cii_platform.services.chat import SYSTEM_PROMPT

    d = DVector(d1=Decimal("0.86"), d2=Decimal("0.94"), d3=Decimal("1.06"), d4=Decimal("1.18"))
    required = Decimal("5")
    on_edge = [
        determine_rating(attained_cii=required * factor, required_cii=required, d_vector=d).rating
        for factor in (d.d1, d.d2, d.d3, d.d4)
    ]
    assert on_edge == ["A", "B", "C", "D"], "엔진이 경계값을 더 우수한 등급으로 넣지 않는다"

    # 엔진이 그렇다면 규칙도 그 방향이어야 한다.
    assert "초과" in SYSTEM_PROMPT and "이하" in SYSTEM_PROMPT
    assert "더 우수한 등급" in SYSTEM_PROMPT
    assert "d1배 미만" not in SYSTEM_PROMPT, "경계를 아래 등급에 넣는 옛 예시가 남아 있다"


def test_grade_ranges_hand_the_model_finished_sentences() -> None:
    """IT-CHAT-078 (`#1973` 후속) — 등급 구간을 **옮겨 적을 문장**으로 준다.

    규칙을 「초과 · 이하」로 고친 뒤에도 운영 답이 「D: 1.0600배 이상, 1.1800배 미만」이었다
    (09-28). 방향을 모델이 추론하게 두지 않는다. 문장은 **엔진의 판정과 같은 방향**이어야
    한다 — 경계값에 걸린 배는 더 우수한 등급의 「이하」 쪽에 든다.
    """
    from decimal import Decimal

    from cii_platform.calc.rating_engine import DVector, determine_rating

    row = {"d1": "0.8600", "d2": "0.9400", "d3": "1.0600", "d4": "1.1800"}
    ranges = chat_tools._grade_ranges(row)
    # `#1973` 폐기 후속 — 배수마다 화면 자릿수의 백분율을 함께 싣는다(「106%」로 말해도 산다).
    assert ranges == {
        "A": "0.8600배(86.0%) 이하",
        "B": "0.8600배(86.0%) 초과 ~ 0.9400배(94.0%) 이하",
        "C": "0.9400배(94.0%) 초과 ~ 1.0600배(106.0%) 이하",
        "D": "1.0600배(106.0%) 초과 ~ 1.1800배(118.0%) 이하",
        "E": "1.1800배(118.0%) 초과",
    }
    assert not any("이상" in text or "미만" in text for text in ranges.values())

    # 각 경계값에서 엔진이 고르는 등급의 문장이 그 경계를 「이하」로 끝맺는다.
    d = DVector(**{key: Decimal(value) for key, value in row.items()})
    for key, value in row.items():
        grade = determine_rating(
            attained_cii=Decimal(value), required_cii=Decimal(1), d_vector=d
        ).rating
        percent = (Decimal(value) * 100).quantize(Decimal("0.1"))
        assert ranges[grade].endswith(f"{value}배({percent}%) 이하"), (key, grade, ranges[grade])


def test_grade_ranges_and_all_year_reductions_let_the_usual_phrasing_pass_the_guard() -> None:
    """IT-CHAT-079 (`#1973` 폐기 후속) — 「106%」·「2023년 5%」로 말한 답이 **폐기되지 않는다**.

    운영에서 「벌크선 D등급 경계」 질문의 답이 No-Compute로 폐기됐다. 도구는 배수(``1.0600``)와
    물은 해의 감축률 하나만 줬는데, 사람이 흔히 쓰는 표기(백분율)나 다른 해의 감축률을 덧붙이면
    그 수가 도구 응답에 없어 답 전체가 버려진다. 도구가 **그 표기와 그 값을 함께 싣는지**를
    수치 가드로 직접 돌려 본다 — 문자열 모양이 아니라 **가드를 통과하는가**가 지킬 성질이다.
    """
    from cii_platform.services.llm_guard import verify_numbers

    ranges = chat_tools._grade_ranges(
        {"d1": "0.8600", "d2": "0.9400", "d3": "1.0600", "d4": "1.1800"}
    )
    tool_output = json.dumps(
        {
            "rating_boundaries": [{"grade_ranges": ranges}],
            "reduction_factor": {
                "year": 2026,
                "z_factor_percent": "11.0",
                "by_year": [
                    {"year": 2023, "z_factor_percent": "5.0"},
                    {"year": 2026, "z_factor_percent": "11.0"},
                ],
            },
        },
        ensure_ascii=False,
    )
    verify_numbers(
        "D등급은 실적 CII가 기준 CII의 106% 초과 ~ 118% 이하입니다. "
        "참고로 2023년 감축률은 5%였습니다.",
        [tool_output],
    )


def test_grade_ranges_are_not_invented_when_a_boundary_is_missing() -> None:
    """빈 경계를 채워 넣으면 없는 경계를 말하게 된다."""
    assert chat_tools._grade_ranges({"d1": "0.86", "d2": None, "d3": "1.06", "d4": "1.18"}) == {}


def test_lookup_regulation_year_is_left_empty_unless_the_user_named_one() -> None:
    """IT-CHAT-072 (`#1973` ④) — 연도를 묻지 않았으면 비워 둬 **올해** 값을 받는다.

    09-27 21:40 답이 연도를 묻지 않은 질문에 「2023년 기준 5% 감축」이라 적었다. 비우면
    ``_regulation_year``가 올해로 보는데(`cii_current`와 같은 판단), 스키마가 그 사실을
    말하지 않아 모델이 한 해를 골라 넣을 여지가 있었다(정황 — 감사 기록에 인자는 없다).
    """
    schema = next(
        s for s in chat_tools.tool_schemas() if s["name"] == chat_tools.TOOL_LOOKUP_REGULATION
    )
    described = schema["input_schema"]["properties"]["regulation_year"]["description"]
    assert "비워" in described and "올해" in described
    assert chat_tools._regulation_year({}) == chat_tools.datetime.now(chat_tools.UTC).year


def test_number_check_is_unmoved_by_markdown_symbols() -> None:
    """`#2064` ⑵ — 서식 기호가 **폐기 판정을 흔들지 않는다**.

    화면에서 기호를 걷기로 했으므로, 가드는 여전히 **모델이 낸 원문**을 본다.
    ``**1.0600배**``처럼 숫자에 기호가 붙었을 때 숫자가 다른 것으로 읽히면
    멀쩡한 답이 폐기되거나(거짓 양성) 지어낸 수가 통과한다(거짓 음성).

    둘을 따로 주장하지 않고 **같은 문장의 기호 있는 판과 없는 판이 같은 판정을
    낸다**로 잠근다 — 기호를 어떻게 걷든 이 관계는 유지되어야 한다.
    """
    from cii_platform.services.llm_guard import (
        NumberFabricationError,
        extract_numbers,
        verify_numbers,
    )

    plain = "D등급: 실적 CII가 기준 CII의 1.0600배(106.0%) 초과 ~ 1.1800배(118.0%) 이하"
    marked = "D등급: 실적 CII가 기준 CII의 **1.0600배(106.0%)** 초과 ~ `1.1800배(118.0%)` 이하"

    assert extract_numbers(marked) == extract_numbers(plain)

    outputs = ['{"d3": "1.0600", "d4": "1.1800", "pct": ["106.0", "118.0"]}']
    verify_numbers(plain, outputs)
    verify_numbers(marked, outputs)

    # 반대 방향 — 기호를 붙여도 지어낸 수는 그대로 걸린다.
    for text in ("기준 CII의 1.2300배", "기준 CII의 **1.2300배**"):
        try:
            verify_numbers(text, outputs)
        except NumberFabricationError:
            continue
        raise AssertionError(f"지어낸 수가 통과했다: {text}")


def test_ratio_to_required_is_published_with_the_screen_percent() -> None:
    """`#2392` — 화면 제안 질문 「연말 예상 값은 기준 CII 대비 몇 %인가요?」에 답할 값.

    도구가 비율을 넘기지 않으면 모델이 실적 ÷ 기준을 직접 나누고, 그 답은 No-Compute
    가드에 폐기된다(10-09 운영). 화면 표기(``177.6%``)로 답해도 가드를 지나야 한다.
    """
    from cii_platform.services.llm_guard import verify_numbers

    published = chat_tools._publishable(
        {"attained_cii": "8.970000", "required_cii": "5.050000", "ratio_to_required": "1.77623"},
        chat_tools._RESULT_KEYS,
    )
    # `#2395` — 같은 문자열에 기준과의 차가 덧붙는다. 값과 화면 백분율 표기는 그대로다.
    assert published["ratio_to_required"].startswith("1.77623 (177.6%")
    tool_output = json.dumps(published, ensure_ascii=False)
    verify_numbers("연말 예상 CII는 기준 CII의 177.6%입니다.", [tool_output])


@pytest.mark.parametrize(
    ("ratio", "expected", "answer"),
    [
        (
            "0.98000",
            "0.98000 (98.0% · 기준 대비 -2.0%p · 기준보다 2.0%p 낮음)",
            "연말 예상 CII는 기준의 98.0%로, 기준보다 2.0% 낮습니다.",
        ),
        (
            "1.77623",
            "1.77623 (177.6% · 기준 대비 +77.6%p · 기준보다 77.6%p 높음)",
            "기준 CII보다 77.6%p 높습니다(기준 대비 +77.6%).",
        ),
        (
            "1.00000",
            "1.00000 (100.0% · 기준 대비 0.0%p · 기준과 같음)",
            "기준 CII와 같습니다(차 0%).",
        ),
        # 차는 **화면 백분율에서** 뺀다 — 97.95%는 화면에 98.0%이고 차는 -2.0이어야 한다.
        (
            "0.97950",
            "0.97950 (98.0% · 기준 대비 -2.0%p · 기준보다 2.0%p 낮음)",
            "기준 대비 -2.0%입니다.",
        ),
    ],
)
def test_ratio_to_required_carries_the_difference_from_the_baseline(ratio, expected, answer):
    """IT-CHAT-097 (`#2395` 결정 2) — 「기준 대비 몇 %」에 **기준과의 차**까지 도구가 싣는다.

    종전에는 ``98.0%``만 줬고, 모델이 「기준보다 2.0% 낮다」고 **뺀 수**가 No-Compute 가드에
    폐기됐다. 가드는 그대로이고 출처가 그 수를 싣는다 — 같은 값의 표기라 키는 늘지 않는다.
    """
    from cii_platform.services.llm_guard import NumberFabricationError, verify_numbers

    published = chat_tools._publishable({"ratio_to_required": ratio}, chat_tools._RESULT_KEYS)
    assert published == {"ratio_to_required": expected}
    tool_output = chat_tools.envelope(chat_tools.TOOL_PROJECT_YEAR_END, result=published)
    verify_numbers(answer, [tool_output])
    # 가드는 그대로다 — 도구가 주지 않은 차(2.1)는 여전히 막힌다.
    with pytest.raises(NumberFabricationError):
        verify_numbers("기준보다 2.1% 낮습니다.", [tool_output])


#: `#2395` — 시나리오 비교 서비스가 돌려주는 행 하나(``scenario_compare._scenario_json`` 모양).
#: 연료량·연료 종류 값을 **일부러 눈에 띄는 수**로 둬 봉투에 새면 바로 드러나게 한다.
_SCENARIO_ROW = {
    "scenario_id": None,
    "scenario_type": "SLOW_STEAMING",
    "scenario_name": "감속",
    "distance_nm": 5000.0,
    "speed_kn": 10.8,
    "duration_hours": "462.96",
    "fuel_ton": "250.1234",
    "co2_emission_ton": "778.8843",
    "attained_cii": "4.812345",
    "required_cii": "5.045066",
    "ratio_to_required": "0.95387",
    "estimated_rating": "B",
    "next_worse_boundary_margin": "0.123456",
    "next_worse_boundary_margin_ratio": "0.024470",
    "risk_level": "LOW",
    "weather_factor": 1.0,
    "weather_model_used": "NONE",
    "calculation_basis": {"fuel_type": "HFO", "fuel_cf": "3.114"},
}


async def test_scenario_tool_carries_type_speed_distance_duration_and_co2(monkeypatch):
    """IT-CHAT-098 (`#2395` 결정 2) — 시나리오 행이 **종류·속력·거리·소요시간·CO₂**를 싣는다.

    속도 시나리오 질문에 모델이 속력·거리로 시간을 나누고 CO₂를 셈해 답이 폐기됐다. 도구가
    그 값을 실으면 옮겨 적기만 하면 된다. ⚠️ 연료량·연료 종류는 여전히 나가지 않는다
    (``PRD §16.3.1`` 「보내지 않는 것」).
    """
    from cii_platform.services import scenario_compare
    from cii_platform.services.llm_guard import NumberFabricationError, verify_numbers

    async def _fake_compare(_session, _payload, *, persist):
        assert persist is False
        return {"data": {"fuel_type": "HFO", "scenarios": [dict(_SCENARIO_ROW)]}}

    monkeypatch.setattr(scenario_compare, "compare_scenarios", _fake_compare)
    raw = await chat_tools._compare_scenarios(
        None,
        {"current_speed_kn": "12", "fuel_type": "HFO", "regulation_year": 2026},
        "selected",
    )
    body = json.loads(raw)
    (row,) = body["result"]["scenarios"]
    assert row["scenario_type"] == "SLOW_STEAMING"
    assert row["speed_kn"] == 10.8
    assert row["distance_nm"] == 5000.0
    assert row["duration_hours"] == "462.96"
    assert row["co2_emission_ton"] == "778.8843"
    assert set(row) <= OUTBOUND_WHITELIST, row

    # 연료량·연료 종류는 키로도 값으로도 나가지 않는다.
    assert "fuel_ton" not in raw and "fuel_type" not in raw
    assert "250.1234" not in raw and "HFO" not in raw

    answer = (
        "감속 시나리오는 10.8kn로 5,000nm를 약 462.96시간에 가고, "
        "CO₂는 778.9톤입니다. 기준보다 4.6%p 낮습니다."
    )
    verify_numbers(answer, [raw])
    # 도구가 주지 않은 값(시간을 일로 나눈 19.3일)은 여전히 막힌다.
    with pytest.raises(NumberFabricationError):
        verify_numbers("감속 시나리오는 약 19.3일 걸립니다.", [raw])


async def test_voyage_tool_echoes_distance_and_speed_but_not_fuel(monkeypatch):
    """IT-CHAT-099 (`#2395` 결정 2) — 항차 CII 도구가 **거리·속력**을 되돌려 준다.

    응답 ``data``에는 속력이 없어 모델이 조건을 되짚는 문장(「12kn로 5,000nm」)도 버려질 수
    있었다. 연료량·연료 종류는 입력으로 받아도 봉투에 싣지 않는다.
    """
    from cii_platform.services import voyage_cii
    from cii_platform.services.llm_guard import NumberFabricationError, verify_numbers

    async def _fake_estimate(_session, payload, *, persist):
        assert persist is False
        return {
            "data": {
                "attained_cii": "4.982400",
                "required_cii": "5.045066",
                "ratio_to_required": "0.98758",
                "estimated_rating": "C",
                "co2_emission_ton": "1245.6000",
                "fuel_consumption_ton": "400.0000",
                "distance_nm": float(payload.distance_nm),
                "risk_level": "MEDIUM",
                "calculation_basis": {"fuel_cf_details": [{"fuel_type": "HFO"}]},
            }
        }

    monkeypatch.setattr(voyage_cii, "estimate_voyage_cii", _fake_estimate)
    raw = await chat_tools._calc_voyage_cii(
        None,
        {
            "distance_nm": "5000",
            "speed_kn": "12.5",
            "fuel_type": "HFO",
            "fuel_ton": "437.25",
            "regulation_year": 2026,
        },
        "selected",
    )
    result = json.loads(raw)["result"]
    assert result["distance_nm"] == 5000.0
    assert result["speed_kn"] == 12.5
    assert set(result) <= OUTBOUND_WHITELIST, result
    assert "fuel_ton" not in raw and "fuel_type" not in raw
    assert "437.25" not in raw and "HFO" not in raw

    verify_numbers("12.5kn로 5,000nm를 가면 CII는 4.982이고 기준보다 1.2%p 낮습니다.", [raw])
    with pytest.raises(NumberFabricationError):
        verify_numbers("12.5kn로 5,000nm면 약 400시간 걸립니다.", [raw])


@pytest.mark.parametrize("year", [2018, 2101, 2150])
@pytest.mark.parametrize(
    ("tool_name", "implementation_name"),
    [
        (chat_tools.TOOL_LOOKUP_REGULATION, "_lookup_regulation"),
        (chat_tools.TOOL_PROJECT_YEAR_END, "_project_year_end"),
        (chat_tools.TOOL_CALC_VOYAGE_CII, "_calc_voyage_cii"),
        (chat_tools.TOOL_COMPARE_SCENARIOS, "_compare_scenarios"),
    ],
)
async def test_year_outside_the_lookup_range_never_reaches_the_service(
    monkeypatch, tool_name, implementation_name, year
):
    """`#2480` — 2019~2100 밖의 해는 서비스를 부르지 않고 정해진 문장으로 답한다."""
    calls: list[dict[str, object]] = []

    async def _spy(_session, arguments, _vessel_id):
        calls.append(arguments)
        return "{}"

    monkeypatch.setattr(chat_tools, implementation_name, _spy)
    outcome = await chat_tools.run_tool(
        None,
        name=tool_name,
        arguments={"regulation_year": year},
        vessel_id="selected",
    )
    body = json.loads(outcome.envelope)
    assert calls == []
    assert body["ok"] is False
    assert body["error"] == "규제연도는 2019~2100 사이로 물어 주세요."


@pytest.mark.parametrize("year", [2019, 2100])
async def test_year_on_the_range_edge_still_reaches_the_service(monkeypatch, year):
    """`#2480` — 범위 경계의 해는 막지 않는다."""
    calls: list[dict[str, object]] = []

    async def _spy(_session, arguments, _vessel_id):
        calls.append(arguments)
        return "{}"

    monkeypatch.setattr(chat_tools, "_project_year_end", _spy)
    await chat_tools.run_tool(
        None,
        name=chat_tools.TOOL_PROJECT_YEAR_END,
        arguments={"regulation_year": year},
        vessel_id="selected",
    )
    assert len(calls) == 1


async def test_an_infinite_year_is_an_argument_error_not_a_crash():
    """`#2493` — 무한대 연도는 `int()`에서 `OverflowError`다. 종전에는 그대로 올라가 500이었다.

    범위 검사는 「정수로 읽히지 않음」으로 넘기고, 연도 해석이 기존 인자 오류로 답한다.
    """
    infinite = json.loads('{"regulation_year": Infinity}')
    assert chat_tools._year_out_of_range(infinite) is False
    with pytest.raises(chat_tools.ToolArgumentError):
        chat_tools._regulation_year(infinite)

    outcome = await chat_tools.run_tool(
        None,
        name=chat_tools.TOOL_PROJECT_YEAR_END,
        arguments=infinite,
        vessel_id="selected",
    )
    body = json.loads(outcome.envelope)
    assert body["ok"] is False
    assert body["error"]
