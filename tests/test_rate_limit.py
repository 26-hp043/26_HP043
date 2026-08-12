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
from cii_platform.api.rate_limit import (
    RateLimiter,
    _client_ip,
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
    """IP별로 카운터가 독립이다 — 다른 IP는 다시 0부터 (#238)."""
    app = _app_with_limit(limit=1)
    fwd_ip1 = {"X-Forwarded-For": "1.1.1.1"}
    fwd_ip2 = {"X-Forwarded-For": "2.2.2.2"}
    with TestClient(app) as client:
        # IP 1: 1회 OK, 2회 차 429
        assert client.get("/api/v1/health", headers=fwd_ip1).status_code == 200
        assert client.get("/api/v1/health", headers=fwd_ip1).status_code == 429
        # IP 2: 별도 카운터 — 1회 OK
        assert client.get("/api/v1/health", headers=fwd_ip2).status_code == 200


def test_client_ip_prefers_x_forwarded_for() -> None:
    """``X-Forwarded-For`` 첫 값을 클라이언트 IP로 본다 (#238)."""

    class _FakeClient:
        def __init__(self, host: str | None):
            self.host = host if host is not None else ""

    class _FakeRequest:
        def __init__(self, headers: dict[str, str], client_host: str | None):
            self.headers = headers
            self.client = _FakeClient(client_host) if client_host is not None else None

    # X-Forwarded-For 우선.
    req = _FakeRequest({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, "127.0.0.1")
    assert _client_ip(req) == "9.9.9.9"
    # 없으면 client.host.
    req = _FakeRequest({}, "127.0.0.1")
    assert _client_ip(req) == "127.0.0.1"
    # 둘 다 없으면 "unknown".
    req = _FakeRequest({}, None)
    assert _client_ip(req) == "unknown"


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
