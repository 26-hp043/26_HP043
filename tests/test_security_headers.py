"""TECH_SPEC §20의 헤더·실제 앱 배선·오류/스트림 보존 (#2111)."""

import base64
import hashlib
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
_BASE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
# API·Function 응답은 문서가 아니다 — 아무것도 불러오지 않는 정책 (#2368).
_API_CSP = "default-src 'none'; frame-ancestors 'none'"
_EXPECTED = {**_BASE, "Content-Security-Policy": _API_CSP}
_ROOT = Path(__file__).resolve().parents[1]
# 화면 정책 (TECH_SPEC §20 · #2368). 해시 자리는 index.html에서 계산해 채운다 —
# 값 자체를 상수로 두면 스크립트를 고쳤을 때 이 검사가 함께 낡는다.
_HTML_CSP_TEMPLATE = (
    "default-src 'self'; script-src 'self' '{hash}'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; "
    "connect-src 'self' https://open.er-api.com https://api.frankfurter.dev; "
    "worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)


def _theme_script_hash() -> str:
    """index.html의 인라인 스크립트(`src` 없는 것) 본문의 CSP 해시 표기."""
    html = (_ROOT / "frontend/index.html").read_text(encoding="utf-8")
    bodies = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    # 인라인 스크립트가 둘이 되면 정책에 둘 다 적어야 한다 — 조용히 하나만 허용하지 않는다.
    assert len(bodies) == 1, "인라인 스크립트는 테마 스크립트 하나여야 한다"
    return "sha256-" + base64.b64encode(hashlib.sha256(bodies[0].encode()).digest()).decode()


def _html_csp() -> str:
    return _HTML_CSP_TEMPLATE.format(hash=_theme_script_hash())


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
    assert static_headers == {**_BASE, "Content-Security-Policy": _html_csp()}
    function = (_ROOT / "frontend/functions/_securityHeaders.ts").read_text()
    # helper에서 onRequest를 내보내면 별도 공개 경로가 생긴다 (Wrangler 실제 번들 확인).
    assert "export async function onRequest" not in function
    for name, value in _EXPECTED.items():
        assert f"'{name}': '{value}'" in function or f"'{name}': \"{value}\"" in function
    for area in ("api", "basemap"):
        assert (
            "export { attachSecurityHeaders as onRequest } from '../_securityHeaders'"
            in (_ROOT / f"frontend/functions/{area}/_middleware.ts").read_text()
        )


def test_csp_hash_matches_inline_theme_script_in_all_frontend_places():
    """스크립트를 고치고 해시를 안 고치면 첫 화면 테마가 막힌다 — 그 어긋남을 막는다 (#2368)."""
    expected = _html_csp()
    headers = (_ROOT / "frontend/public/_headers").read_text()
    nginx = (_ROOT / "frontend/nginx.conf").read_text()
    assert f"Content-Security-Policy: {expected}\n" in headers
    # 서버·/assets/·= /index.html 세 곳이 같은 화면 정책을 낸다. /api/는 API 정책이다.
    assert nginx.count(f'add_header Content-Security-Policy "{expected}" always;') == 3
    assert nginx.count(f'add_header Content-Security-Policy "{_API_CSP}" always;') == 1
    # 네 자리가 서로 다른 해시를 갖지 않는다.
    found = set(re.findall(r"sha256-[A-Za-z0-9+/=]+", headers + nginx))
    assert found == {_theme_script_hash()}


def test_csp_is_enforcing_and_has_no_unsafe_script_sources():
    policy = _html_csp()
    directives = dict(d.strip().split(" ", 1) for d in policy.split(";"))
    assert "unsafe-inline" not in directives["script-src"]
    assert "unsafe-eval" not in policy
    assert directives["object-src"] == "'none'"
    assert directives["frame-ancestors"] == "'none'"
    assert "*" not in policy.replace("'self'", "")


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
        for name, value in _BASE.items():
            assert len(re.findall(rf'add_header {name} "{value}" always;', block)) == 1
        assert len(re.findall(r'add_header Content-Security-Policy "[^"]+" always;', block)) == 1
    api = dict(locations)["/api/"]
    for name in _EXPECTED:
        assert f"proxy_hide_header {name};" in api
    # /api/는 add_header가 있어 server 것을 상속하지 않는다 — API 정책을 직접 적는다.
    assert f'add_header Content-Security-Policy "{_API_CSP}" always;' in api


def test_swagger_docs_paths_are_exempt_from_csp_only():
    """개발 환경 Swagger UI가 깨지지 않는다 — CSP만 빼고 나머지 헤더는 그대로다 (#2368)."""
    app = FastAPI()

    @app.get("/docs")
    async def docs():
        return Response("<html></html>", media_type="text/html")

    app.add_middleware(SecurityHeadersMiddleware)
    response = TestClient(app).get("/docs")
    assert "content-security-policy" not in response.headers
    for name, value in _BASE.items():
        assert response.headers.get_list(name) == [value]
