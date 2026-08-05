"""요청 컨텍스트 미들웨어 계약 테스트 (#49).

RequestContextMiddleware가 request.state에 request_id/timestamp를 주입하고,
오류 핸들러(#100)가 그 값을 API_SPEC §1.3.2 meta로 노출하는 end-to-end 동작을
고정한다. DB에 의존하지 않는다.
"""

import re
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.errors import AppError

_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise AppError("VALIDATION_ERROR", "테스트 오류")

    return app


def test_middleware_injects_request_id_and_timestamp_into_meta() -> None:
    client = TestClient(_build_app())
    meta = client.get("/boom").json()["meta"]
    # request_id는 UUID4 문자열이어야 한다(형식이 틀리면 예외).
    uuid.UUID(meta["request_id"])
    # timestamp는 API_SPEC §1.3 포맷(…Z)이어야 한다.
    assert _TIMESTAMP_RE.fullmatch(meta["timestamp"])


def test_request_id_differs_per_request() -> None:
    client = TestClient(_build_app())
    first = client.get("/boom").json()["meta"]["request_id"]
    second = client.get("/boom").json()["meta"]["request_id"]
    assert first != second


def test_no_x_request_id_response_header() -> None:
    # D2 범위: state 주입까지만. 응답 헤더는 정본 근거가 없어 추가하지 않는다.
    client = TestClient(_build_app())
    resp = client.get("/boom")
    assert "X-Request-ID" not in resp.headers
