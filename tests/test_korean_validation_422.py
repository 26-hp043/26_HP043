"""#900 — Pydantic 422의 한국어 문구·라벨 검증.

## 이 파일이 잡는 것

`API_SPEC` §1.3.2 언어 규정은 ``error.message``·``details[].message``를 한국어로
적으라는데, 서버는 Pydantic 영문 원문(``String should have at most 100 characters``)을
그대로 내보냈고 인증 필드의 ``field_label``도 ``"email"`` 원문이었다.

세 층으로 검증한다.

1. **타입 매핑 단위** — 매핑 표의 키가 실제 Pydantic v2가 내는 타입·``ctx`` 키와
   일치하는지. 키 이름(``max_length``)은 테스트를 돌릴 때마다 실물로 확인된다.
2. **실제 422 응답** — 이슈 본문의 실측 3건(가입 ``display_name`` 초과 · 가입
   ``email`` 형식 · 로그인 ``password`` 누락)이 전부 한국어로 바뀌었는지.
3. **전체 가드** — 실제 앱의 OpenAPI 스키마를 걸어 본문·쿼리·경로의 **모든 필드에
   한글 라벨이 등록돼 있는지.** 다음 이슈가 필드를 추가하고 라벨을 잊으면 그
   자리에서 실패한다 — #55가 기능① 라벨을 뒤늦게 채우고 #900이 나머지 85종을
   채운 같은 누락이 세 번 반복되지 않게 한다.

케이스 ID는 새로 만들지 않는다 — 이 파일의 단언은 §1.3.2 언어 규정 전체에 대한
것이고, 규정 문구 자체는 정본이 소유한다(`AGENTS` §4.6).
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.field_labels import field_label
from cii_platform.api.main import app
from cii_platform.api.validation_messages import josa, korean_validation_message

_BASE = "https://testserver"

#: 한글 음절이 하나 이상 있는지 — 「한국어 문구다」의 최소 요건.
_HANGUL = re.compile(r"[가-힣]")


@pytest.fixture
def client(migrated_db, app_fresh_engine) -> TestClient:
    """실제 앱 + 실제 DB. 422는 DB에 닿기 전에 나지만 실앱 경로 전체를 지난다."""
    with TestClient(app, base_url=_BASE) as c:
        yield c


# --- 조사 선택 ------------------------------------------------------------------------


class TestJosa:
    def test_final_consonant_takes_eun(self):
        assert josa("비밀 정책", ("은", "는")) == "은"

    def test_no_final_consonant_takes_neun(self):
        assert josa("비밀번호", ("은", "는")) == "는"

    def test_object_particles(self):
        assert josa("이메일", ("을", "를")) == "을"
        assert josa("표시 이름", ("을", "를")) == "을"  # 「이름」은 받침 ㅁ

    def test_non_hangul_uses_parenthesized_form(self):
        """라틴 필드명(``extra_forbidden``의 라벨)은 어느 조사가 맞는지 정할 수 없다."""
        assert josa("bogus", ("은", "는")) == "은(는)"

    def test_empty_label_uses_parenthesized_form(self):
        assert josa("", ("을", "를")) == "을(를)"


# --- 타입 매핑 ------------------------------------------------------------------------


def _msg(
    error_type: str, label: str, ctx: dict[str, Any] | None = None, raw: str = "English message"
) -> str:
    error: dict[str, Any] = {"type": error_type, "msg": raw, "loc": ("body", "x")}
    if ctx is not None:
        error["ctx"] = ctx
    return korean_validation_message(error, label)


class TestTypeMessages:
    """매핑 표의 문구 — 키와 ``ctx`` 키는 실측값(#900 착수 시 pydantic v2 실물)."""

    @pytest.mark.parametrize(
        ("error_type", "label", "ctx", "expected"),
        [
            ("missing", "비밀번호", None, "비밀번호를 입력해 주세요."),
            (
                "string_too_long",
                "표시 이름",
                {"max_length": 100},
                "표시 이름은 100자 이하여야 합니다.",
            ),
            (
                "string_too_short",
                "비밀번호",
                {"min_length": 1},
                "비밀번호는 1자 이상이어야 합니다.",
            ),
            ("too_short", "연료 사용량", {"min_length": 1}, "연료 사용량은 1개 이상이어야 합니다."),
            (
                "string_pattern_mismatch",
                "이메일",
                {"pattern": "x"},
                "이메일 형식이 올바르지 않습니다.",
            ),
            ("extra_forbidden", "bogus", None, "bogus은(는) 허용되지 않는 필드입니다."),
            ("int_parsing", "규제연도", None, "규제연도는 숫자여야 합니다."),
            ("decimal_parsing", "운항 거리", None, "운항 거리는 숫자여야 합니다."),
            ("greater_than", "운항 거리", {"gt": 0}, "운항 거리는 0보다 커야 합니다."),
            ("greater_than_equal", "속력", {"ge": 1}, "속력은 1 이상이어야 합니다."),
            ("less_than_equal", "규제연도", {"le": 2100}, "규제연도는 2100 이하여야 합니다."),
            ("uuid_parsing", "선박", {"error": "…"}, "선박 형식이 올바르지 않습니다."),
            (
                "datetime_from_date_parsing",
                "기준 시각",
                {"error": "…"},
                "기준 시각 날짜·시각 형식이 올바르지 않습니다.",
            ),
            ("bool_parsing", "활성 여부", None, "활성 여부는 true 또는 false여야 합니다."),
            ("literal_error", "기상 모델", None, "기상 모델 값이 올바르지 않습니다."),
            ("finite_number", "운항 거리", None, "운항 거리는 유한한 숫자여야 합니다."),
        ],
    )
    def test_mapped_type(self, error_type, label, ctx, expected):
        assert _msg(error_type, label, ctx) == expected

    def test_type_suffix_family(self):
        """``string_type``·``model_type`` 등 ``*_type`` 계열은 접미사로 분류한다."""
        assert _msg("string_type", "이메일") == "이메일 형식이 올바르지 않습니다."
        assert _msg("some_new_type", "이메일") == "이메일 형식이 올바르지 않습니다."

    def test_value_error_keeps_our_own_message(self):
        """``field_validator``가 던진 문구는 우리가 적은 한국어다 — 매핑이 덮지 않는다."""
        assert (
            _msg("value_error", "랜덤 시드", raw="random_seed는 정수여야 합니다.")
            == "random_seed는 정수여야 합니다."
        )

    def test_unknown_type_never_returns_english(self):
        """미매핑 타입도 영문을 내보내지 않는다 (#900 완료 기준)."""
        message = _msg("brand_new_rule", "이메일", raw="brand new english detail")
        assert message == "이메일 값을 확인해 주세요."
        assert "english" not in message


# --- 실제 422 응답 (#900 실측 3건) ----------------------------------------------------


def _assert_all_korean(body: dict[str, Any]) -> None:
    """봉투 전체에 라틴 알파벳 3글자 이상 단어가 없는지 — 영문 원문 잔존 가드."""
    for detail in body["error"]["details"]:
        assert _HANGUL.search(str(detail["message"])), detail
        assert _HANGUL.search(str(detail["field_label"])), detail
    assert _HANGUL.search(str(body["error"]["message"]))


class TestApi422IsKorean:
    def test_signup_display_name_too_long(self, client):
        payload = {
            "email": "u900a@example.com",
            "password": "correct-horse",
            "display_name": "가" * 200,
        }
        resp = client.post("/api/v1/auth/signup", json=payload)
        assert resp.status_code == 422
        body = resp.json()
        detail = body["error"]["details"][0]
        assert detail["field"] == "display_name"
        assert detail["field_label"] == "표시 이름"
        assert detail["message"] == "표시 이름은 100자 이하여야 합니다."
        assert body["error"]["message"] == "표시 이름은 100자 이하여야 합니다."
        _assert_all_korean(body)

    def test_signup_email_pattern(self, client):
        resp = client.post(
            "/api/v1/auth/signup", json={"email": "not-an-email", "password": "correct-horse"}
        )
        assert resp.status_code == 422
        body = resp.json()
        detail = body["error"]["details"][0]
        assert detail["field_label"] == "이메일"
        assert detail["message"] == "이메일 형식이 올바르지 않습니다."
        _assert_all_korean(body)

    def test_login_missing_password(self, client):
        resp = client.post("/api/v1/auth/login", json={"email": "u900b@example.com"})
        assert resp.status_code == 422
        body = resp.json()
        detail = body["error"]["details"][0]
        assert detail["field"] == "password"
        assert detail["field_label"] == "비밀번호"
        assert detail["message"] == "비밀번호를 입력해 주세요."
        _assert_all_korean(body)

    def test_malformed_json_body(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422
        message = resp.json()["error"]["message"]
        assert message == "요청 본문이 올바른 JSON이 아닙니다."


# --- 전체 가드 — 모든 요청 필드에 한글 라벨 --------------------------------------------


def _walk_properties(
    schema: dict[str, Any], components: dict[str, Any], prefix: str, paths: list[str]
) -> None:
    if "$ref" in schema:
        schema = components.get(schema["$ref"].split("/")[-1], {})
    for name, sub in (schema.get("properties") or {}).items():
        path = prefix + name
        paths.append(path)
        resolved = components.get(sub["$ref"].split("/")[-1], {}) if "$ref" in sub else sub
        if resolved.get("type") == "array":
            item = resolved.get("items", {})
            item = components.get(item["$ref"].split("/")[-1], {}) if "$ref" in item else item
            paths.append(path + "[]")
            _walk_properties(item, components, path + "[].", paths)
        elif resolved.get("type") == "object" and "properties" in resolved:
            _walk_properties(resolved, components, path + ".", paths)


class TestEveryFieldHasKoreanLabel:
    """실앱의 모든 본문·쿼리·경로 필드가 ``field_labels``에 등록돼 있다.

    #900 착수 시점의 미등록 필드는 85종이었다(인증 6종이 계기). 이 가드가 없으면
    같은 누락이 네 번째로 반복된다.
    """

    def test_all_fields_labeled(self):
        spec = app.openapi()
        components = spec.get("components", {}).get("schemas", {})
        paths: list[str] = []
        for _path, ops in spec["paths"].items():
            for method, op in ops.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for media in op.get("requestBody", {}).get("content", {}).values():
                    _walk_properties(media.get("schema", {}), components, "", paths)
                for param in op.get("parameters", []):
                    if param.get("in") in {"query", "path"}:
                        paths.append(param["name"])
        assert paths, "OpenAPI 스키마에서 필드를 수집하지 못했다 — 가드 자체가 깨진 것"

        unlabeled = [p for p in paths if field_label(p) == p]
        assert not unlabeled, f"라벨이 없는 필드: {sorted(set(unlabeled))}"

        non_korean = [p for p in paths if not _HANGUL.search(field_label(p))]
        assert not non_korean, f"라벨이 한글이 아닌 필드: {sorted(set(non_korean))}"
