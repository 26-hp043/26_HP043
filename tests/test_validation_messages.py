"""Pydantic 422를 한국어로 (``API_SPEC §1.3.2`` 언어 규정 · §11 · #900).

세 가지를 본다.

1. **문장** — ``type``·``ctx``에서 만든 문장이 ``API_SPEC §11``의 틀과 같고, 조사가 받침을
   따른다. 정본 예시(「운항 거리는 0보다 커야 합니다.」)를 **글자 그대로** 재현한다
2. **새지 않는다** — 모르는 ``type``도, 영문 ``ValueError``도 영문 원문을 내보내지 않는다
3. **라벨이 빠지지 않는다** — **모든 엔드포인트의 요청 필드**가 한글 라벨을 가진다. OpenAPI를
   읽어 전수 대조한다(``app.routes``는 이 FastAPI 판에서 하위 경로를 감싸 보이지 않는다 —
   ``tests/test_api_spec_endpoints_sync.py`` 모듈 설명). 새 요청 필드가 라벨 없이 들어오면
   여기서 걸린다 — 종전 17항목이던 표가 84개를 빠뜨린 채 몇 주를 지났다

DB가 필요 없다.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, field_validator

from cii_platform.api.error_handlers import validation_error_handler
from cii_platform.api.field_labels import field_label
from cii_platform.api.main import app
from cii_platform.api.validation_messages import FALLBACK, is_korean, josa, korean_message

_HANGUL = re.compile(r"[가-힣]")


# ─────────────────────────────────────────────────────────────────────────────
# 1. 문장
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("선명", "선명을"),  # 받침 있음
        ("비밀번호", "비밀번호를"),  # 받침 없음
        ("이메일", "이메일을"),
        ("총톤수(GT)", "총톤수(GT)를"),  # 괄호 설명은 건너뛰고 앞 낱말로
        ("시작 시각(부터)", "시작 시각(부터)을"),
        ("CII", "CII을(를)"),  # 한글로 끝나지 않으면 둘 다 적는다
    ],
)
def test_object_particle_follows_the_final_consonant(word, expected):
    assert josa(word, "을", "를") == expected


def test_reproduces_the_api_spec_example_verbatim():
    """``API_SPEC §1.3.2`` 예시 · §11 VAL-002 — 「운항 거리는 0보다 커야 합니다.」"""
    error = {"type": "greater_than", "ctx": {"gt": Decimal("0")}, "msg": "Input should be > 0"}
    assert korean_message(error, field_label("distance_nm")) == "운항 거리는 0보다 커야 합니다."


def test_missing_follows_val_001():
    """``API_SPEC §11`` VAL-001 — 「{field_label}을/를 입력하세요.」"""
    assert korean_message({"type": "missing"}, "비밀번호") == "비밀번호를 입력하세요."
    assert korean_message({"type": "missing"}, "선명") == "선명을 입력하세요."


@pytest.mark.parametrize(
    ("error", "label", "expected"),
    [
        (
            {"type": "string_too_long", "ctx": {"max_length": 100}},
            "표시 이름",
            "표시 이름은 100자 이하여야 합니다.",
        ),
        (
            {"type": "string_too_short", "ctx": {"min_length": 1}},
            "선명",
            "선명은 1자 이상이어야 합니다.",
        ),
        ({"type": "string_pattern_mismatch"}, "이메일", "이메일 형식이 올바르지 않습니다."),
        ({"type": "int_parsing"}, "페이지 크기", "페이지 크기는 정수여야 합니다."),
        ({"type": "decimal_parsing"}, "계획 거리", "계획 거리는 숫자여야 합니다."),
        (
            {"type": "less_than_equal", "ctx": {"le": 100}},
            "페이지 크기",
            "페이지 크기는 100 이하여야 합니다.",
        ),
        (
            {"type": "greater_than_equal", "ctx": {"ge": 1.0}},
            "속력",
            "속력은 1 이상이어야 합니다.",
        ),
        (
            {"type": "enum", "ctx": {"expected": "'DRAFT', 'PLANNED' or 'IN_PROGRESS'"}},
            "바꿀 상태",
            "바꿀 상태는 다음 중 하나여야 합니다: DRAFT, PLANNED, IN_PROGRESS.",
        ),
        ({"type": "uuid_parsing"}, "선박", "선박 형식이 올바르지 않습니다."),
        (
            {"type": "datetime_parsing"},
            "종료 시각",
            "종료 시각 형식이 올바르지 않습니다(예: 2026-09-12T09:00:00+09:00).",
        ),
        (
            {"type": "too_short", "ctx": {"min_length": 1}},
            "연료 사용량",
            "연료 사용량은 최소 1개가 필요합니다.",
        ),
    ],
)
def test_common_types_become_korean_sentences(error, label, expected):
    assert korean_message(error, label) == expected


def test_korean_custom_validator_message_is_kept():
    """직접 만든 검증기는 이미 규정을 지킨다 — Pydantic이 붙이는 머리말만 뗀다."""
    error = {"type": "value_error", "msg": "Value error, 종료 시각은 시작 시각보다 뒤여야 합니다."}
    assert korean_message(error, "종료 시각") == "종료 시각은 시작 시각보다 뒤여야 합니다."


# ─────────────────────────────────────────────────────────────────────────────
# 2. 새지 않는다
# ─────────────────────────────────────────────────────────────────────────────


def test_english_custom_validator_message_does_not_leak():
    error = {"type": "value_error", "msg": "Value error, must be positive"}
    message = korean_message(error, "계획 거리")
    assert message == FALLBACK.format(label="계획 거리")
    assert "must" not in message


def test_unknown_type_falls_back_to_korean():
    error = {"type": "some_future_type", "msg": "Something went wrong"}
    assert korean_message(error, "선명") == "선명 값이 올바르지 않습니다."


def test_error_without_a_field_still_reads():
    assert korean_message({"type": "missing"}, "") == "입력값을 입력하세요."


class _Payload(BaseModel):
    distance_nm: Decimal = Field(gt=0)
    display_name: str = Field(max_length=5)
    speed_kn: int

    @field_validator("speed_kn")
    @classmethod
    def _english(cls, value: int) -> int:
        if value == 13:
            raise ValueError("unlucky number")
        return value


@pytest.fixture
def echo() -> TestClient:
    probe = FastAPI()
    probe.add_exception_handler(RequestValidationError, validation_error_handler)

    @probe.post("/echo")
    async def _echo(payload: _Payload) -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(probe)


def _all_text(body: dict) -> list[str]:
    error = body["error"]
    texts = [error["message"]]
    for detail in error["details"]:
        texts += [detail["message"], detail["field_label"]]
    return texts


def test_handler_emits_no_english_sentence(echo: TestClient):
    resp = echo.post("/echo", json={"distance_nm": 0, "display_name": "가" * 9, "speed_kn": 13})

    assert resp.status_code == 422
    body = resp.json()
    messages = [d["message"] for d in body["error"]["details"]]
    assert "운항 거리는 0보다 커야 합니다." in messages
    assert "표시 이름은 5자 이하여야 합니다." in messages
    assert "속력 값이 올바르지 않습니다." in messages  # 영문 ValueError는 폴백
    assert all(is_korean(t) for t in _all_text(body)), _all_text(body)
    assert body["error"]["message"] == messages[0]


def test_malformed_json_names_the_body_not_a_character_offset(echo: TestClient):
    resp = echo.post("/echo", content=b"{not json", headers={"Content-Type": "application/json"})

    detail = resp.json()["error"]["details"][0]
    assert detail == {
        "field": "",
        "field_label": "요청 본문",
        "message": "요청 본문이 올바른 JSON이 아닙니다.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. 라벨이 빠지지 않는다 — 전 엔드포인트
# ─────────────────────────────────────────────────────────────────────────────


def _request_fields() -> dict[str, set[str]]:
    """OpenAPI의 모든 요청 필드 경로 → 그 필드를 받는 엔드포인트.

    배열 원소 안의 필드는 ``fuel_uses[].fuel_ton`` 꼴이다 — ``field_label``이 인덱스를 지운
    형태로 찾는 규칙(``fuel_uses[0].fuel_ton`` → ``fuel_uses[].fuel_ton``)과 같은 모양이다.
    """
    spec = app.openapi()
    comps = spec.get("components", {}).get("schemas", {})

    def resolve(schema: dict) -> dict:
        while "$ref" in schema:
            schema = comps[schema["$ref"].split("/")[-1]]
        return schema

    def walk(schema: dict, prefix: str, out: set[str], depth: int = 0) -> None:
        if depth > 6:
            return
        schema = resolve(schema)
        for key in ("anyOf", "oneOf", "allOf"):
            for sub in schema.get(key, []):
                walk(sub, prefix, out, depth + 1)
        if schema.get("type") == "array" and "items" in schema and prefix:
            walk(schema["items"], prefix.rstrip(".") + "[].", out, depth + 1)
        for name, sub in schema.get("properties", {}).items():
            path = f"{prefix}{name}"
            out.add(path)
            walk(sub, f"{path}.", out, depth + 1)

    fields: dict[str, set[str]] = {}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            found: set[str] = {p["name"] for p in operation.get("parameters", [])}
            for content in operation.get("requestBody", {}).get("content", {}).values():
                walk(content.get("schema", {}), "", found)
            for name in found:
                fields.setdefault(name, set()).add(f"{method.upper()} {path}")
    return fields


def test_request_fields_are_discovered_at_all():
    """전수 대조가 빈 목록으로 통과하지 않게 — 알려진 필드가 보여야 한다."""
    fields = _request_fields()
    assert len(fields) > 80
    for known in ("distance_nm", "display_name", "fuel_uses[].fuel_ton", "planned_departure_at"):
        assert known in fields


def test_every_request_field_has_a_korean_label():
    missing = {
        name: sorted(routes)
        for name, routes in _request_fields().items()
        if not _HANGUL.search(field_label(name))
    }
    assert not missing, (
        "한글 라벨이 없는 요청 필드 — src/cii_platform/api/field_labels.py에 등록하세요 "
        "(라벨은 화면의 입력칸 이름을 따릅니다):\n"
        + "\n".join(f"  {k}  ←  {', '.join(v)}" for k, v in sorted(missing.items()))
    )
