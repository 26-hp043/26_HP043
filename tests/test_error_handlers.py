"""오류 처리 계약 테스트 (#100, #183).

이 이슈가 확정하는 "계약"을 CI가 지켜주도록 고정한다: base 예외 `AppError`의
HTTP status 매핑(TECH_SPEC §12.1), 오류 응답 포맷(API_SPEC §1.3.2), 그리고
`register_exception_handlers`로 등록된 핸들러의 end-to-end 동작. #183은
프레임워크 404·405와 명시적 `HTTPException`의 변환을 더한다.

DB에 의존하지 않는다(conftest의 `migrated_db`/`conn` 픽스처를 요청하지 않음).
"""

import re

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import (
    register_exception_handlers,
    to_error_response,
)
from cii_platform.api.middleware import RequestContextMiddleware
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


# --- #183: HTTPException → §1.3.2 변환 -------------------------------------------------

#: #183 테스트 전용 앱. main.py를 오염시키지 않고 프레임워크 404·405를 실제로
#: 만들어내기 위해 라우트 1개(GET 전용)만 둔다 — 405가 나오려면 "경로는 존재하나
#: 메서드가 다른" 요청이 필요하다(#183 이슈의 시뮬레이션 방식).
def _http_exception_app() -> FastAPI:
    router = APIRouter()

    @router.get("/only-get")
    async def only_get() -> dict[str, str]:
        return {"ok": "1"}

    @router.get("/boom-422")
    async def boom_422() -> dict[str, str]:
        raise HTTPException(status_code=422, detail="bad")

    @router.get("/boom-405")
    async def boom_405() -> dict[str, str]:
        raise HTTPException(status_code=405, detail="no")

    @router.get("/boom-400")
    async def boom_400() -> dict[str, str]:
        raise HTTPException(status_code=400, detail="x")

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)
    register_exception_handlers(app)
    return app


def test_framework_404_uses_standard_message_and_meta() -> None:
    """⑴ 경로 404 → NOT_FOUND + 표준 문구 + request_id/timestamp (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/no-such-path")
    assert resp.status_code == 404
    payload = resp.json()
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["message"] == "요청한 경로를 찾을 수 없습니다."
    assert "request_id" in payload["meta"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["meta"]["timestamp"])


def test_framework_405_preserves_allow_header() -> None:
    """⑵ 프레임워크 405 → METHOD_NOT_ALLOWED + Allow 헤더 보존 (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.post("/only-get")
    assert resp.status_code == 405
    assert "get" in resp.headers["allow"].lower()
    payload = resp.json()
    assert payload["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert payload["error"]["message"] == "허용되지 않은 HTTP 메서드입니다."


def test_explicit_422_uses_http_error_code_and_preserves_detail() -> None:
    """⑶ HTTPException(422, 'bad') → HTTP_ERROR + 'bad' (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/boom-422")
    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"]["code"] == "HTTP_ERROR"
    assert payload["error"]["message"] == "bad"
    assert "request_id" in payload["meta"]


def test_explicit_405_maps_to_method_not_allowed_and_preserves_detail() -> None:
    """⑷ HTTPException(405, 'no') → METHOD_NOT_ALLOWED + 'no' (#183, #182)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/boom-405")
    assert resp.status_code == 405
    payload = resp.json()
    assert payload["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert payload["error"]["message"] == "no"


def test_explicit_400_maps_to_bad_request_and_preserves_detail() -> None:
    """⑸ HTTPException(400, 'x') → BAD_REQUEST + 'x' (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/boom-400")
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["error"]["code"] == "BAD_REQUEST"
    assert payload["error"]["message"] == "x"


def test_normal_response_unaffected_by_http_exception_handler() -> None:
    """⑹ 정상 200 응답은 핸들러 등록 전과 동일하다 (#183)."""
    client = TestClient(_http_exception_app())
    resp = client.get("/only-get")
    assert resp.status_code == 200
    assert resp.json() == {"ok": "1"}
