"""챗봇 도구 계층 (`#121` · IT-CHAT-016~023).

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

from cii_platform.services import chat_tools
from cii_platform.services.llm_guard import OUTBOUND_WHITELIST, OutboundFieldError


def test_tool_schemas_cover_exactly_the_four_tools() -> None:
    """IT-CHAT-016 — `Q9`가 정한 4종이고, **쓰기 도구가 없다**."""
    names = [schema["name"] for schema in chat_tools.tool_schemas()]
    assert names == list(chat_tools.TOOL_NAMES)
    # `#121` 본문의 `create_voyage`를 넣지 않기로 한 결정이 코드에 남아 있는지 본다.
    assert "create_voyage" not in names


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
        "next_boundary_gap": "0.012",
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
    body = json.loads(
        await chat_tools.run_tool(None, name="drop_table", arguments={}, vessel_id=None)  # type: ignore[arg-type]
    )
    assert body["ok"] is False
    assert "error" in body


async def test_calculation_tools_need_a_vessel_first() -> None:
    """IT-CHAT-023 — 선박이 정해지지 않으면 계산 도구가 돌지 않는다.

    ⚠️ **모델은 `vessel_id`를 모른다** — 식별자는 화이트리스트 밖이라 넘기지 않는다.
    그래서 「어느 선박인지」는 화면이나 `search_vessel`이 정하고, 서버가 들고 있는다.
    """
    for name in (
        chat_tools.TOOL_CALC_VOYAGE_CII,
        chat_tools.TOOL_COMPARE_SCENARIOS,
        chat_tools.TOOL_RUN_ANNUAL_SIMULATION,
    ):
        body = json.loads(
            await chat_tools.run_tool(None, name=name, arguments={}, vessel_id=None)  # type: ignore[arg-type]
        )
        assert body["ok"] is False, name
