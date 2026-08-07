"""#116 — ``RequestValidationError``·catch-all 핸들러 검증.

기존 ``tests/test_error_handlers.py``는 #100이 만든 ``AppError`` 경로를 본다.
이 파일은 **#116이 추가한 두 경로**만 다룬다.

두 핸들러가 없으면 이렇게 깨진다.

- FastAPI 기본 422는 ``{"detail": [...]}``라 API_SPEC §1.3.2와 구조가 다르고,
  화면(#135)이 필드별 메시지를 꺼내지 못한다.
- 잡히지 않은 예외는 Starlette 기본 500 **HTML**을 낸다. JSON 파서가 실패하고
  traceback이 응답에 실릴 수 있다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from cii_platform.api.error_handlers import (
    INTERNAL_ERROR_MESSAGE,
    _field_path,
    register_exception_handlers,
)
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.errors import AppError


class _Item(BaseModel):
    value: int


class _Payload(BaseModel):
    name: str
    items: list[_Item]


@pytest.fixture
def client() -> Iterator[TestClient]:
    """#116 경로만 자극하는 최소 앱.

    실제 ``main.app``을 쓰지 않는 이유: catch-all을 확인하려면 **반드시 터지는
    엔드포인트**가 필요한데, 그런 라우트를 운영 앱에 둘 수 없다.
    """
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.post("/echo")
    async def echo(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("내부 상세: /secret/path/db.sqlite 접근 실패")

    @app.get("/domain")
    async def domain() -> dict[str, str]:
        raise AppError("NOT_FOUND", "없습니다.")

    # raise_server_exceptions=False 여야 핸들러가 만든 500 응답을 받아 볼 수 있다.
    # True(기본)면 TestClient가 예외를 그대로 다시 던진다.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# --- 필드 경로 ----------------------------------------------------------------------


class TestFieldPath:
    """Pydantic ``loc`` → 요청 본문 기준 경로."""

    @pytest.mark.parametrize(
        ("loc", "expected"),
        [
            (("body", "distance_nm"), "distance_nm"),
            (("body", "fuel_uses", 0, "fuel_ton"), "fuel_uses[0].fuel_ton"),
            (("body", "items", 12, "value"), "items[12].value"),
            (("query", "limit"), "limit"),
            (("path", "vessel_id"), "vessel_id"),
            # 출처 표시가 없으면 그대로 쓴다.
            (("distance_nm",), "distance_nm"),
            ((), ""),
        ],
    )
    def test_path(self, loc, expected):
        assert _field_path(loc) == expected

    def test_uses_bracket_notation_for_indices(self):
        """**점 표기가 아니라 대괄호다.**

        화면이 이 경로를 그대로 입력창에 매핑한다(#135 ``VoyageCiiError.field``).
        ``fuel_uses.0.fuel_ton``으로 내려보내면 화면 쪽에 변환 규칙이 하나 더 생긴다.
        """
        assert _field_path(("body", "fuel_uses", 0, "fuel_ton")) == "fuel_uses[0].fuel_ton"


# --- 검증 실패 ----------------------------------------------------------------------


class TestValidationHandler:
    def test_status_is_422(self, client):
        assert client.post("/echo", json={"items": []}).status_code == 422

    def test_envelope_is_api_spec_shape(self, client):
        """``{"error": {...}, "meta": {...}}`` — FastAPI 기본 ``{"detail": [...]}``가 아니다."""
        body = client.post("/echo", json={"items": []}).json()
        assert set(body) == {"error", "meta"}
        assert "detail" not in body
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_details_have_field_and_label(self, client):
        body = client.post("/echo", json={"items": []}).json()
        detail = body["error"]["details"][0]
        assert set(detail) == {"field", "field_label", "message"}
        assert detail["field"] == "name"

    def test_nested_array_field_path(self, client):
        body = client.post("/echo", json={"name": "x", "items": [{"value": "글자"}]}).json()
        fields = [d["field"] for d in body["error"]["details"]]
        assert "items[0].value" in fields

    def test_multiple_errors_are_all_reported(self, client):
        """여러 필드가 동시에 틀리면 **전부** 담는다.

        하나만 내려보내면 화면이 오류를 하나씩 고치는 왕복을 만든다.
        """
        body = client.post("/echo", json={"items": [{"value": "글자"}]}).json()
        fields = {d["field"] for d in body["error"]["details"]}
        assert {"name", "items[0].value"} <= fields

    def test_message_is_first_detail(self, client):
        body = client.post("/echo", json={"items": []}).json()
        assert body["error"]["message"] == body["error"]["details"][0]["message"]

    def test_rule_is_not_invented(self, client):
        """``rule``(VAL 번호)을 임의로 붙이지 않는다.

        §1.3.2 예시에는 있으나 **Pydantic 오류에서 VAL 번호를 유도할 수 없다.**
        근거 없는 규칙 번호가 응답에 실리면 그것이 사실로 읽힌다.
        """
        body = client.post("/echo", json={"items": []}).json()
        assert all("rule" not in d for d in body["error"]["details"])

    def test_meta_has_request_context(self, client):
        body = client.post("/echo", json={"items": []}).json()
        assert isinstance(body["meta"]["request_id"], str)
        assert body["meta"]["timestamp"].endswith("Z")

    def test_malformed_json_body(self, client):
        """JSON 자체가 깨져도 500이 아니라 검증 오류로 나간다."""
        resp = client.post(
            "/echo", content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# --- catch-all ----------------------------------------------------------------------


class TestUnhandledHandler:
    def test_status_is_500(self, client):
        assert client.get("/boom").status_code == 500

    def test_response_is_json_not_html(self, client):
        """Starlette 기본 500은 HTML이다. JSON을 기대하는 클라이언트가 파싱에 실패한다."""
        resp = client.get("/boom")
        assert resp.headers["content-type"].startswith("application/json")

    def test_code_is_internal_error(self, client):
        assert client.get("/boom").json()["error"]["code"] == "INTERNAL_ERROR"

    def test_internal_details_are_not_leaked(self, client):
        """**예외 메시지를 응답에 넣지 않는다.**

        파일 경로·SQL·값이 섞여 있을 수 있고 그대로 나가면 정보 노출이 된다.
        """
        body = client.get("/boom").json()
        serialized = str(body)
        assert body["error"]["message"] == INTERNAL_ERROR_MESSAGE
        assert "/secret/path" not in serialized
        assert "RuntimeError" not in serialized
        assert "Traceback" not in serialized

    def test_request_id_is_kept_for_tracing(self, client):
        """응답에서 내용을 감추는 대신 ``request_id``로 로그와 잇는다."""
        assert isinstance(client.get("/boom").json()["meta"]["request_id"], str)

    def test_exception_is_logged(self, client, caplog):
        import logging

        with caplog.at_level(logging.ERROR, logger="cii_platform.api.error_handlers"):
            client.get("/boom")
        assert any("unhandled error" in record.message for record in caplog.records)


# --- 핸들러 우선순위 -----------------------------------------------------------------


class TestHandlerPrecedence:
    def test_app_error_is_not_swallowed_by_catch_all(self, client):
        """``AppError``가 catch-all보다 앞선다.

        Starlette는 예외의 MRO에서 가장 먼저 일치하는 핸들러를 고르므로 등록 순서와
        무관하다. 이 단언이 깨지면 **모든 도메인 오류가 500이 된다** — 404·409·422가
        전부 사라지는 심각한 회귀다.
        """
        resp = client.get("/domain")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"
