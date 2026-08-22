"""`API_SPEC §5.1` 응답 예시 ↔ 실제 응답 (#151).

## 왜 필요한가

종전 예시는 **인쇄된 입력으로 재현되지 않았다.** `fuel_ton`·`attained_cii`·
`co2_emission_ton`이 서로 맞지 않았고, `next_worse_boundary_margin`은 `§4.1`에서
이미 정정된 오기를 그대로 갖고 있었다.

`#151`이 지적한 대로 원인은 **입력 가정이 명시되지 않은 것**이다 — 연료 추정이
cubic speed model(``daily_foc × (v/v_ref)³ × distance/(v×24)``)이라 기준 선박의
``reference_speed_kn`` 없이는 ``fuel_ton``이 정해지지 않는다.

**값을 한 번 고치는 것으로는 부족하다.** 이슈 본문이 그 사실을 적었다 —
*「개별 수치만 고쳐도 다음 검토에서 다시 어긋난다」*. 그래서 문서에서 **요청과
응답을 둘 다 읽어** 실제로 실행하고 대조한다.

## 무엇을 대조하는가

``data.scenarios``의 **값**과 ``data.summary``다. `#559`의 응답 계약 테스트가
**필드 집합**을 보는 것과 층이 다르다 — 이쪽은 「문서에 인쇄된 숫자가 맞는가」다.

실행마다 달라지는 것(``scenario_id``·해시·``meta``)은 문서가 자리표시자로 두므로
대조에서 뺀다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app

_SPEC = Path(__file__).resolve().parents[1] / "API_SPEC.md"

#: 문서가 실행마다 달라지는 값을 적는 자리표시자. JSON이 아니라 파싱 전에 걷어낸다.
_PLACEHOLDER = re.compile(r"\{ \.\.\. \}")

#: `§5.1` 예시가 전제하는 선박. 문서 각주와 같은 값이어야 한다.
DEMO_BULK = "00000000-0000-4000-8000-000000000001"


def _section() -> str:
    text = _SPEC.read_text(encoding="utf-8")
    return text.split("### 5.1 시나리오 비교 계산", 1)[1].split("### 5.2", 1)[0]


def _json_blocks() -> list[dict]:
    """`§5.1`의 ```json``` 블록을 순서대로 읽는다."""
    blocks = re.findall(r"```json\n(.*?)\n```", _section(), re.S)
    return [json.loads(_PLACEHOLDER.sub("{}", block)) for block in blocks]


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url="https://testserver") as c:
        c.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        yield c


def test_the_spec_blocks_are_parsed_at_all():
    """블록을 읽지 못하면 아래 대조가 **아무것도 하지 않고 통과**한다."""
    blocks = _json_blocks()

    assert len(blocks) == 2, f"§5.1의 json 블록을 {len(blocks)}개 읽었다 — 요청·응답 둘이어야 한다"
    request, response = blocks
    assert "direct_distance_nm" in request
    assert len(response["data"]["scenarios"]) == 3


def test_the_example_request_uses_a_reproducible_weather_model():
    """`SIMPLE_RULE`은 Open-Meteo를 **실제로 호출한다** (`#151`).

    문서 예시가 외부 서비스의 그날 값에 따라 달라지면 재현 가능한 예시가 아니고,
    이 테스트도 네트워크에 매달린다.
    """
    request, _ = _json_blocks()

    assert request["weather_model"] == "NONE"


def test_the_example_response_is_what_the_server_returns(client):
    """`§5.1` 요청 예시를 **그대로** 보내 응답 예시와 대조한다.

    문서의 `vessel_id`는 `"uuid"` 자리표시자이므로 각주가 지정한 데모 선박으로
    바꿔 보낸다 — 그 선박의 `reference_speed_kn`이 곧 예시의 전제다.
    """
    request, expected = _json_blocks()

    response = client.post(
        f"{API_V1_PREFIX}/scenarios/compare",
        headers={"X-CSRF-Token": client.cookies.get("csrf")},
        json={**request, "vessel_id": DEMO_BULK},
    )

    assert response.status_code == 200, response.text
    got = response.json()["data"]

    assert got["summary"] == expected["data"]["summary"]

    for index, (want, actual) in enumerate(
        zip(expected["data"]["scenarios"], got["scenarios"], strict=True)
    ):
        # `scenario_id`는 실행마다 다르다 — 문서가 자리표시자로 둔다.
        want = {k: v for k, v in want.items() if k != "scenario_id"}
        actual = {k: v for k, v in actual.items() if k != "scenario_id"}
        assert actual == want, f"§5.1 시나리오 {index}({want['scenario_type']})가 어긋났다"


def test_the_example_still_shows_a_grade_change(client):
    """감속이 등급을 **실제로 한 단계 올린다** (`#151`).

    `base_daily_foc_ton`을 `35.0`에서 `18.0`으로 낮춘 이유가 이것이다 — `35.0`이면
    셋 다 `E`가 되어 `next_worse_boundary_margin`이 전부 `null`이 되고,
    `[ORACLE-S-1]`이 그 필드를 추가한 목적이 예시에서 사라진다.

    값이 바뀌어 예시가 다시 밋밋해지면 여기가 먼저 깨진다.
    """
    _, expected = _json_blocks()
    by_type = {s["scenario_type"]: s for s in expected["data"]["scenarios"]}

    assert by_type["DIRECT"]["estimated_rating"] != by_type["SLOW_STEAMING"]["estimated_rating"]
    for scenario in by_type.values():
        assert scenario["next_worse_boundary_margin"] is not None


def test_detour_shares_the_direct_grade_and_that_is_correct(client):
    """`DIRECT`와 `DETOUR`의 `attained_cii`가 같은 것은 **오기가 아니다** (`#151`).

    우회는 `M`과 `D`를 같은 비율로 키우므로 비율이 그대로다. 문서가 그 사실을
    각주로 적고 있으며, 값이 갈리면 각주가 거짓말이 된다.
    """
    _, expected = _json_blocks()
    by_type = {s["scenario_type"]: s for s in expected["data"]["scenarios"]}

    assert by_type["DETOUR"]["attained_cii"] == by_type["DIRECT"]["attained_cii"]
    # 반대로 **바뀌는 것**도 함께 본다 — 같기만 하면 우회가 아무 의미 없다는 뜻이다.
    assert by_type["DETOUR"]["co2_emission_ton"] != by_type["DIRECT"]["co2_emission_ton"]
    assert by_type["DETOUR"]["duration_hours"] != by_type["DIRECT"]["duration_hours"]
