"""오류 처리 계약 테스트 (#100).

이 이슈가 확정하는 "계약"을 CI가 지켜주도록 고정한다: base 예외 `AppError`의
HTTP status 매핑(TECH_SPEC §12.1), 오류 응답 포맷(API_SPEC §1.3.2), 그리고
`register_exception_handlers`로 등록된 핸들러의 end-to-end 동작.

DB에 의존하지 않는다(conftest의 `migrated_db`/`conn` 픽스처를 요청하지 않음).
"""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import (
    register_exception_handlers,
    to_error_response,
)
from cii_platform.errors import DEFAULT_HTTP_STATUS, AppError


def test_http_status_mapping_from_tech_spec_12_1() -> None:
    # TECH_SPEC §12.1 / API_SPEC §1.4 매핑값과 일치해야 한다.
    assert AppError("VALIDATION_ERROR", "x").http_status == 422
    assert AppError("PARAMETER_ERROR", "x").http_status == 409
    assert AppError("REPRODUCIBILITY_ERROR", "x").http_status == 500


def test_unknown_code_falls_back_to_default_status() -> None:
    # 매핑에 없는 코드는 DEFAULT_HTTP_STATUS(500)로 떨어진다.
    assert AppError("NO_SUCH_CODE", "x").http_status == DEFAULT_HTTP_STATUS
    assert DEFAULT_HTTP_STATUS == 500


def test_to_error_response_matches_api_spec_1_3_2() -> None:
    # API_SPEC §1.3.2: {"error": {"code","message","details"?}, "meta": {...}}
    body = to_error_response(
        "VALIDATION_ERROR",
        "운항 거리는 0보다 커야 합니다.",
        details=[{"field": "distance_nm", "rule": "VAL-002"}],
        request_id="req-1",
        timestamp="2026-07-18T00:00:00Z",
    )
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "운항 거리는 0보다 커야 합니다."
    assert body["error"]["details"] == [{"field": "distance_nm", "rule": "VAL-002"}]
    assert body["meta"] == {"request_id": "req-1", "timestamp": "2026-07-18T00:00:00Z"}


def test_to_error_response_omits_details_when_none() -> None:
    body = to_error_response("PARAMETER_ERROR", "해당 연도의 규정 파라미터가 없습니다.")
    assert "details" not in body["error"]


def test_to_error_response_omits_none_meta_keys() -> None:
    # API_SPEC §1.3.2는 meta 값을 문자열로 전제 → 값 없는 키는 null 대신 생략.
    body = to_error_response("PARAMETER_ERROR", "해당 연도의 규정 파라미터가 없습니다.")
    assert body["meta"] == {}


def test_registered_handler_converts_app_error_end_to_end() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise AppError("PARAMETER_ERROR", "해당 연도의 규정 파라미터가 없습니다.")

    resp = TestClient(app).get("/boom")
    assert resp.status_code == 409
    payload = resp.json()
    assert payload["error"]["code"] == "PARAMETER_ERROR"
    assert payload["error"]["message"] == "해당 연도의 규정 파라미터가 없습니다."
    assert "details" not in payload["error"]
    # timestamp는 미들웨어 미주입 시에도 핸들러가 UTC ISO8601로 채운다.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["meta"]["timestamp"])
    # request_id는 미들웨어(#49) 도입 전이므로 null 대신 생략된다.
    assert "request_id" not in payload["meta"]
