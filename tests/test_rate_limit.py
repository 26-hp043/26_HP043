"""요청 한도 미들웨어 테스트 (#238).

API_SPEC §13.2 (분당 300회/사용자) 계약 — IP별 fixed window 카운터가 한도 초과 시
429 ``RATE_LIMIT_EXCEEDED``를 낸다. main.py의 app을 직접 쓰면 한도 300을 초과하기
어려워, 테스트 전용 app에 낮은 한도의 RateLimiter를 주입해 검증한다.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cii_platform.api.error_handlers import register_exception_handlers
from cii_platform.api.middleware import RequestContextMiddleware
from cii_platform.api.rate_limit import (
    RateLimiter,
    rate_limit_middleware,
)
from cii_platform.api.routes.health import router as health_router


def _app_with_limit(limit: int) -> FastAPI:
    """한도를 작게 세팅한 테스트 전용 app."""
    app = FastAPI()
    app.state.rate_limiter = RateLimiter(limit)
    app.middleware("http")(rate_limit_middleware)
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    return app


def test_under_limit_passes() -> None:
    """한도 내는 정상 응답 (#238)."""
    app = _app_with_limit(limit=5)
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/api/v1/health").status_code == 200


def test_over_limit_returns_429() -> None:
    """한도 초과 시 429 RATE_LIMIT_EXCEEDED (#238)."""
    app = _app_with_limit(limit=2)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        third = client.get("/api/v1/health")
        assert third.status_code == 429
        body = third.json()
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "한도" in body["error"]["message"]


def test_zero_limit_disables_middleware() -> None:
    """``limit <= 0``이면 미들웨어가 통과만 한다 (#238)."""
    app = _app_with_limit(limit=0)
    with TestClient(app) as client:
        for _ in range(100):
            assert client.get("/api/v1/health").status_code == 200


def test_counts_are_per_ip() -> None:
    """IP별로 카운터가 독립이다 — 다른 client.host는 다시 0부터 (#238).

    X-Forwarded-For는 기본적으로 무시되므로, rate_limiter를 직접 테스트한다.
    """
    from cii_platform.errors import RateLimitError

    limiter = RateLimiter(limit_per_minute=1)
    limiter.consume("1.1.1.1")
    with pytest.raises(RateLimitError):
        limiter.consume("1.1.1.1")
    # 다른 IP는 별도 카운터 — OK
    limiter.consume("2.2.2.2")


def test_client_ip_ignores_forwarded_by_default() -> None:
    """기본적으로 X-Forwarded-For를 무시한다 — 한도 우회 방어 (#rate-limit-security)."""
    import cii_platform.api.rate_limit as rl

    class _FakeClient:
        def __init__(self, host: str):
            self.host = host

    class _FakeRequest:
        def __init__(self, headers: dict[str, str], client_host: str):
            self.headers = headers
            self.client = _FakeClient(client_host)

    # XFF가 있어도 client.host를 쓴다 (기본).
    req = _FakeRequest({"x-forwarded-for": "9.9.9.9"}, "127.0.0.1")
    assert rl._client_ip(req) == "127.0.0.1"


def test_client_ip_uses_forwarded_when_enabled(monkeypatch) -> None:
    """USE_FORWARDED_FOR=true일 때만 X-Forwarded-For를 신뢰한다 (#rate-limit-security)."""
    import cii_platform.api.rate_limit as rl

    monkeypatch.setattr(rl, "_USE_FORWARDED_FOR", True)

    class _FakeClient:
        def __init__(self, host: str):
            self.host = host

    class _FakeRequest:
        def __init__(self, headers: dict[str, str], client_host: str):
            self.headers = headers
            self.client = _FakeClient(client_host)

    # XFF 우선.
    req = _FakeRequest({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, "127.0.0.1")
    assert rl._client_ip(req) == "9.9.9.9"
    # 없으면 client.host.
    req = _FakeRequest({}, "127.0.0.1")
    assert rl._client_ip(req) == "127.0.0.1"


def test_limiter_window_resets_after_expiry() -> None:
    """윈도(60s)가 지나면 카운터가 리셋된다 — 시간을 흉내내 검증 (#238)."""
    from cii_platform.errors import RateLimitError

    limiter = RateLimiter(limit_per_minute=1)
    # 첫 consume OK.
    limiter.consume("x")
    # 두 번째는 한도 초과.
    with pytest.raises(RateLimitError):
        limiter.consume("x")
    # 윈도 시작 시간을 과거로 돌린다 — 다음 consume이 리셋을 트리거.
    limiter._window_start -= 100  # type: ignore[attr-defined]
    limiter.consume("x")  # 리셋 후 OK
    with pytest.raises(RateLimitError):  # 다시 한도 초과
        limiter.consume("x")


# --- #309: RequestContextMiddleware 중복 등록 제거 검증 ------------------------------------
# 중복 등록 시 요청마다 request_id가 두 번 생성되고, 429 응답의 meta.request_id가
# 채워지는 순서 계약이 지켜지는지를 main.app 기준으로 고정한다.


def test_main_app_registers_request_context_once() -> None:
    """main.app에 RequestContextMiddleware가 정확히 1건만 등록돼 있다 (#309).

    중복 등록(2회)이 다시 들어오면 이 테스트가 잡는다.
    """
    from cii_platform.api.main import app

    registered = [m for m in app.user_middleware if m.cls is RequestContextMiddleware]
    assert len(registered) == 1


def test_429_response_meta_has_request_id() -> None:
    """429 응답의 meta.request_id가 채워진다 — rate_limit이 RequestContext 안쪽 (#309).

    main.py와 같은 순서(RequestContext를 **나중에** 등록 → 바깥에서 실행)로
    조립한 앱에서 429가 request_id를 담는지 검증한다. 중복 등록을 없앤 뒤에도
    순서 계약이 유지되는지가 이 테스트의 대상이다.
    """
    app = FastAPI()
    app.state.rate_limiter = RateLimiter(1)
    app.middleware("http")(rate_limit_middleware)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/api/v1")

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        resp = client.get("/api/v1/health")
        assert resp.status_code == 429
        assert resp.json()["meta"]["request_id"]
