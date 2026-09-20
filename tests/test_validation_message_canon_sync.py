"""정본 VAL 문구 틀 ↔ 실제 422 응답 (`#1329`).

## 왜 필요한가

`API_SPEC §11`(= `PRD §9.1`)은 **문구의 정본**이다. 그런데 그 표가 실제 응답과 갈려도
아무 데서도 드러나지 않았다 — 실제로 **일곱 규칙이 어긋나 있었고**, 차이는 전부
`#860`·`#999` 같은 **앞선 결정**이었는데 표만 뒤처져 있었다.

**표가 낡으면 「문구 대조」 검사 자체가 성립하지 않는다** — 무엇과 맞춰야 하는지가
거짓이기 때문이다.

## 무엇을 단언하는가

표는 **문장이 아니라 틀**이다(`{field_label}`·`{하한}`). 그래서 글자 그대로 비교하지
않고 **틀이 만들어 내는 모양**을 본다.

1. 실제 응답이 그 틀을 따르는가 — 라벨로 시작하고 정해진 꼬리로 끝나는가
2. **두 입구(JSON·CSV)가 같은 말을 하는가** — 한 규칙에 두 문장이 있으면 사용자에게는
   두 규칙이다
3. 정본 표가 **없는 문구를 들고 있지 않은가** — 예시로 적은 문장은 실제로 나와야 한다
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.schemas.vessel import VesselCreateRequest, VesselPositionUpdateRequest
from cii_platform.api.schemas.voyage import VoyageCreateRequest

ROOT = Path(__file__).resolve().parents[1]


def _app() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/vessel")
    def vessel(payload: VesselCreateRequest) -> dict:  # pragma: no cover - 422만 본다
        return {}

    @app.post("/position")
    def position(payload: VesselPositionUpdateRequest) -> dict:  # pragma: no cover
        return {}

    @app.post("/voyage")
    def voyage(payload: VoyageCreateRequest) -> dict:  # pragma: no cover
        return {}

    return TestClient(app)


def _details(client: TestClient, path: str, body: dict) -> dict[str, str]:
    response = client.post(path, json=body)
    assert response.status_code == 422, response.text
    return {d["field"]: d["message"] for d in response.json()["error"]["details"]}


def test_val_002_names_the_field_and_its_storable_minimum() -> None:
    """VAL-002 — **「0보다 커야 합니다」가 아니다** (`#860`).

    `> 0`은 `1e-7`을 통과시켰고 DB가 `0.00`으로 반올림해 **500**이 났다. 하한이
    저장 가능한 최솟값으로 올라갔고, 문구도 **그 값과 어느 필드인지**를 말한다.
    """
    client = _app()
    messages = _details(
        client,
        "/vessel",
        {"imo_number": "9123456", "name": "x", "ship_type": "BULK_CARRIER", "gross_tonnage": 0},
    )

    assert messages["gross_tonnage"] == "총톤수(GT)는 0.01 이상이어야 합니다."


def test_val_003_separates_length_from_shape() -> None:
    """VAL-003 — 길이와 형식은 **고치는 방법이 다르다**."""
    client = _app()
    base = {"name": "x", "ship_type": "BULK_CARRIER"}

    short = _details(client, "/vessel", {**base, "imo_number": "123"})
    shape = _details(client, "/vessel", {**base, "imo_number": "12345AB"})

    assert short["imo_number"] == "IMO 번호는 7자 이상이어야 합니다."
    assert shape["imo_number"] == "IMO 번호 형식이 올바르지 않습니다."


def test_val_007_says_which_coordinate_and_which_bound() -> None:
    """VAL-007 — 「좌표 형식이 올바르지 않습니다」로는 **어느 칸인지** 알 수 없다."""
    client = _app()
    messages = _details(client, "/position", {"current_lat": 91, "current_lon": 181})

    assert messages["current_lat"] == "현재 위도는 90 이하여야 합니다."
    assert messages["current_lon"] == "현재 경도는 180 이하여야 합니다."


def test_val_009_names_which_speed() -> None:
    """VAL-009 — 요청에 속도 칸이 여럿이라 **어느 속도인지**를 말해야 한다."""
    client = _app()
    messages = _details(
        client,
        "/voyage",
        {
            "departure_port_name": "a",
            "arrival_port_name": "b",
            "planned_distance_nm": 1000,
            "planned_speed_kn": 0,
            "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 1}],
        },
    )

    assert messages["planned_speed_kn"] == "계획 속력은 1 이상이어야 합니다."


def test_the_csv_path_says_the_same_thing_as_the_json_path() -> None:
    """⚠️ **한 규칙에 두 문장이 있으면 사용자에게는 두 규칙이다** (`#1329`).

    종전에는 같은 값 오류가 CSV로는 `0보다 커야 합니다.`, 화면 입력으로는
    `계획 거리는 0.01 이상이어야 합니다.`로 나갔다.
    """
    from cii_platform.services.voyage_import import _min_message

    client = _app()
    json_message = _details(
        client,
        "/voyage",
        {
            "departure_port_name": "a",
            "arrival_port_name": "b",
            "planned_distance_nm": 0,
            "planned_speed_kn": 14,
            "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 1}],
        },
    )["planned_distance_nm"]

    assert _min_message("planned_distance_nm", Decimal("0.01")) == json_message


def test_the_canon_examples_are_messages_that_actually_appear() -> None:
    """정본 표가 **없는 문구를 들고 있지 않은지** 본다 (`#1329`).

    `PRD §17.3`이 그랬다 — 다섯 중 넷이 `src/` 전수 grep **0건**이었다. 없는 문구를
    정본이 들고 있으면 **무엇과 맞춰야 하는지가 거짓**이라 대조가 성립하지 않는다.
    """
    from cii_platform.calc.capacity import CapacityUnavailableError
    from cii_platform.services.calc_errors import spec_error

    client = _app()
    produced = set()
    produced.update(
        _details(
            client,
            "/vessel",
            {"imo_number": "123", "name": "x", "ship_type": "BULK_CARRIER", "gross_tonnage": 0},
        ).values()
    )
    produced.update(_details(client, "/position", {"current_lat": 91, "current_lon": 181}).values())
    produced.update(
        _details(
            client,
            "/voyage",
            {
                "departure_port_name": "a",
                "arrival_port_name": "b",
                "planned_distance_nm": 0,
                "planned_speed_kn": 0,
                "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 0}],
            },
        ).values()
    )
    # VAL-010은 Pydantic이 아니라 **서비스가** 만든다 — 같은 표에 있으므로 함께 본다.
    produced.add(
        spec_error(CapacityUnavailableError("dwt missing", axis="DWT", reason="missing")).message
    )

    text = (ROOT / "API_SPEC.md").read_text(encoding="utf-8")
    start = text.index("## 11. 검증 규칙 요약")
    table = text[start : text.index("\n---", start)]
    # 표가 「예:」로 든 문장만 본다 — 틀(`{field_label}` 포함)은 문장이 아니다.
    examples = re.findall(r"예: `([^`{}]+)`", table)

    assert examples, "§11에서 예시 문장을 찾지 못했다"
    assert set(examples) <= produced, (
        f"정본이 든 예시가 실제로 나오지 않는다: {set(examples) - produced}"
    )
