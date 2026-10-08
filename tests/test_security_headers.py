"""TECH_SPEC §20의 헤더·실제 앱 배선·오류/스트림 보존 (#2111)."""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response, StreamingResponse

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.rate_limit import RateLimiter, RateLimits
from cii_platform.api.security_headers import SECURITY_HEADERS, SecurityHeadersMiddleware

# 정본 정책 (TECH_SPEC §20). 구현 상수에서 기대값을 만들면 값 오기를 놓친다.
_EXPECTED = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
_ROOT = Path(__file__).resolve().parents[1]


def _assert_headers(response):
    for name, value in _EXPECTED.items():
        assert response.headers.get_list(name) == [value]


def _app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/value")
    async def value(value: int):
        return {"value": value}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("검사용 오류")

    @app.get("/download")
    async def download():
        async def chunks():
            yield b"voyage,fuel\n"
            yield b"V001,HFO\n"

        response = StreamingResponse(chunks(), media_type="text/csv")
        response.headers["Content-Disposition"] = 'attachment; filename="voyages.csv"'
        response.set_cookie("sid", "test-session", httponly=True)
        response.set_cookie("csrf", "test-csrf")
        return response

    @app.get("/old-header")
    async def old_header():
        return Response("ok", headers={"X-Frame-Options": "SAMEORIGIN"})

    app.add_middleware(
        CORSMiddleware, allow_origins=["https://pages.example"], allow_methods=["GET"]
    )
    app.add_middleware(SecurityHeadersMiddleware)
    return app


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/value?value=1", 200),
        ("GET", "/missing", 404),
        ("HEAD", "/value?value=1", 405),
        ("GET", "/value?value=bad", 422),
        ("GET", "/boom", 500),
    ],
)
def test_security_headers_include_framework_and_outer_500_errors(method, path, status):
    response = TestClient(_app(), raise_server_exceptions=False).request(method, path)
    assert response.status_code == status
    _assert_headers(response)
    assert response.headers["content-type"].startswith("application/json")
    if status == 500:
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "검사용 오류" not in response.text


def test_security_headers_include_cors_preflight():
    response = TestClient(_app()).options(
        "/value",
        headers={
            "Origin": "https://pages.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://pages.example"
    _assert_headers(response)


def test_security_headers_preserve_download_and_both_cookies():
    response = TestClient(_app()).get("/download")
    _assert_headers(response)
    assert response.content == b"voyage,fuel\nV001,HFO\n"
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="voyages.csv"'
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert cookies[0].startswith("sid=") and cookies[1].startswith("csrf=")


def test_security_headers_replace_conflicting_value_without_duplicates():
    response = TestClient(_app()).get("/old-header")
    _assert_headers(response)
    assert response.text == "ok"


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/api/v1/health", 200),
        ("HEAD", "/api/v1/health", 405),
        ("GET", "/api/v1/vessels", 401),
    ],
)
def test_main_app_actually_covers_health_and_auth_early_response(monkeypatch, method, path, status):
    from cii_platform.api.main import app

    monkeypatch.setattr(app.state, "rate_limiter", RateLimiter(RateLimits.uniform(100)))
    response = TestClient(app).request(method, path)
    assert response.status_code == status
    _assert_headers(response)


def test_main_app_actually_covers_rate_limit_early_response(monkeypatch):
    from cii_platform.api.main import app

    monkeypatch.setattr(app.state, "rate_limiter", RateLimiter(RateLimits.uniform(1)))
    client = TestClient(app)
    assert client.get("/api/v1/vessels").status_code == 401
    response = client.get("/api/v1/vessels")
    assert response.status_code == 429
    _assert_headers(response)
    assert response.json()["meta"]["request_id"]


@pytest.mark.asyncio
async def test_non_http_scope_is_passed_through_unchanged():
    received = []

    async def app(scope, receive, send):
        received.append((scope, receive, send))

    scope = {"type": "lifespan"}
    receive, send = object(), object()
    await SecurityHeadersMiddleware(app)(scope, receive, send)
    assert received == [(scope, receive, send)]


def test_static_and_function_policies_match_canonical_values():
    assert SECURITY_HEADERS == _EXPECTED
    text = (_ROOT / "frontend/public/_headers").read_text()
    global_rule = re.search(r"(?m)^/\*\n((?:[ \t]+[^\n]+\n)+)", text)
    assert global_rule
    static_headers = dict(re.findall(r"^\s+([^:]+): (.+)$", global_rule[1], re.M))
    assert static_headers == _EXPECTED
    function = (_ROOT / "frontend/functions/_securityHeaders.ts").read_text()
    for name, value in _EXPECTED.items():
        assert f"'{name}': '{value}'" in function
    for area in ("api", "basemap"):
        assert (
            "export { onRequest } from '../_securityHeaders'"
            in (_ROOT / f"frontend/functions/{area}/_middleware.ts").read_text()
        )


def test_nginx_retains_headers_in_cache_locations_and_avoids_proxy_duplicates():
    conf = (_ROOT / "frontend/nginx.conf").read_text()
    server = conf.split("location ", 1)[0]
    locations = re.findall(r"(?m)^    location ([^\n]+) \{\n(.*?)^    }", conf, re.S)
    assert {name for name, _ in locations} >= {
        "/api/",
        "/assets/",
        "= /index.html",
        "/",
        "/basemap/",
    }
    for block in [server] + [body for _, body in locations if "add_header " in body]:
        for name, value in _EXPECTED.items():
            assert len(re.findall(rf'add_header {name} "{value}" always;', block)) == 1
    api = dict(locations)["/api/"]
    for name in _EXPECTED:
        assert f"proxy_hide_header {name};" in api
