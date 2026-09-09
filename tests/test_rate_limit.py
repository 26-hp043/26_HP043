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
    RateLimits,
    rate_limit_middleware,
)
from cii_platform.api.routes.health import router as health_router


def _app_with_limit(limit: int) -> FastAPI:
    """한도를 작게 세팅한 테스트 전용 app.

    세 버킷을 **같은 값**으로 둔다 (`RateLimits.uniform`) — 이 아래 검사들은 버킷
    경계가 아니라 **카운터 자체**(윈도·IP 분리·0 비활성)를 재기 때문이다. 버킷별
    값을 따로 주면 무엇을 재는 검사인지 흐려진다. 버킷 경계는 `#811` 절이 따로 본다.
    """
    app = FastAPI()
    app.state.rate_limiter = RateLimiter(RateLimits.uniform(limit))
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

    limiter = RateLimiter(RateLimits.uniform(1))
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

    limiter = RateLimiter(RateLimits.uniform(1))
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
    app.state.rate_limiter = RateLimiter(RateLimits.uniform(1))
    app.middleware("http")(rate_limit_middleware)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/api/v1")

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        resp = client.get("/api/v1/health")
        assert resp.status_code == 429
        assert resp.json()["meta"]["request_id"]


# ---------------------------------------------------------------------------
# 공용 카운터 격리 (#651)
#
# `main.app`은 모듈 레벨 객체라 분당 카운터를 pytest 프로세스 전체가 공유했다.
# 그 앱을 `TestClient`로 때리는 파일이 20개가 넘고, 고정 윈도라 60초가 지나야
# 리셋되므로 **실패 여부가 전체 실행 속도에 달려 있었다** — 로컬 3분대는 통과하고
# CI 1분대는 429가 났다. `#593`·`#648`이 각각 한 번씩 이것으로 막혔다.
#
# `conftest.py`의 `_fresh_rate_limiter`가 매 테스트마다 같은 한도의 새 인스턴스를
# 끼운다. 아래 두 테스트는 **순서에 의존한다** — 앞이 카운터를 올리고, 뒤가 그것이
# 넘어오지 않았음을 본다. pytest는 파일 안 정의 순서를 지킨다.
# ---------------------------------------------------------------------------


def test_shared_counter_starts_empty_and_records() -> None:
    """테스트 시작 시 카운터가 비어 있고, 요청을 보내면 올라간다."""
    from cii_platform.api.main import app

    limiter = app.state.rate_limiter
    assert limiter._counts == {}, "앞선 테스트의 카운트가 넘어왔다 — 픽스처가 동작하지 않는다"

    with TestClient(app) as client:
        for _ in range(3):
            client.get("/api/v1/health")

    assert sum(limiter._counts.values()) == 3


def test_shared_counter_does_not_leak_into_the_next_test() -> None:
    """**바로 앞 테스트가 3건을 썼는데** 여기서는 다시 0이다.

    이 단언이 이 이슈의 본체다. 넘어오면 테스트를 몇 개 더할 때마다 **무관한 파일**이
    429로 떨어진다.
    """
    from cii_platform.api.main import app

    assert app.state.rate_limiter._counts == {}


def test_the_limit_itself_still_applies() -> None:
    """리셋이 **한도를 무력화하지 않는다.**

    한도를 0으로 꺼 버리면 `#275`가 배선으로 고정한 「rate limit이 auth보다 바깥」이
    깨져도 아무도 모른다. 한 테스트 안에서 한도를 넘기면 여전히 429다.
    """
    app = _app_with_limit(2)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 429


# ---------------------------------------------------------------------------
# 경로 버킷 (#811)
#
# 종전에는 전역 한도 하나(300)뿐이었다. `API_SPEC §13.2`가 **두 행**을 규정하는데
# 아래 행만 인용해 계산 경로에도 300이 걸렸고, 인증 경로에는 별도 한도가 없어
# **로그인 무차별 대입에 분당 300회**가 허용됐다.
# ---------------------------------------------------------------------------

from cii_platform.api.rate_limit import (  # noqa: E402
    AUTH_PATHS,
    BUCKET_AUTH,
    BUCKET_CALCULATION,
    BUCKET_DEFAULT,
    CALCULATION_ROUTES,
    resolve_bucket,
)


@pytest.mark.parametrize("path", sorted(AUTH_PATHS))
def test_auth_paths_resolve_to_the_auth_bucket(path: str) -> None:
    """인증 경로 다섯이 전부 인증 버킷이다 (#811)."""
    assert resolve_bucket("POST", path) == BUCKET_AUTH


@pytest.mark.parametrize(("method", "path"), sorted(CALCULATION_ROUTES))
def test_calculation_routes_resolve_to_the_calculation_bucket(method: str, path: str) -> None:
    """`API_SPEC §13.2` 「계산 API」 셋이 계산 버킷이다 (#811)."""
    assert resolve_bucket(method, path) == BUCKET_CALCULATION


def test_reproduce_resolves_to_the_calculation_bucket() -> None:
    """`POST /annual-simulations/{id}/reproduce`도 계산이다 (#811).

    경로에 UUID가 들어 있어 완전 일치로 잡을 수 없다. 재현은 같은 Monte Carlo
    엔진을 다시 도는 요청이므로 조회가 아니다.
    """
    path = "/api/v1/annual-simulations/1b2f0d0e-0000-4000-8000-000000000001/reproduce"
    assert resolve_bucket("POST", path) == BUCKET_CALCULATION


@pytest.mark.parametrize(
    ("method", "path"),
    [
        # 조회는 계산이 아니다 — `API_SPEC §13.2`의 CRUD 행이다.
        ("GET", "/api/v1/calculations"),
        ("GET", "/api/v1/annual-simulations/1b2f0d0e-0000-4000-8000-000000000001"),
        # 채택은 「이 시나리오를 쓴다」는 선언이다 (`API_SPEC §5.2`).
        ("POST", "/api/v1/scenarios/1b2f0d0e-0000-4000-8000-000000000001/adopt"),
        # 인증 경로라도 로그아웃·조회는 무차별 대입 표면이 아니다.
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/auth/me"),
        # 토큰이 256비트 난수라 추측이 불가능하다 (services/auth_token.py).
        ("POST", "/api/v1/auth/password-reset/confirm"),
        ("POST", "/api/v1/auth/verify-email/confirm"),
        # 평범한 CRUD.
        ("GET", "/api/v1/vessels"),
        ("GET", "/api/v1/health"),
    ],
)
def test_these_paths_stay_in_the_default_bucket(method: str, path: str) -> None:
    """버킷 경계가 넓어지지 않았는지 본다 (#811).

    접두사 매칭으로 바꾸면 `/auth/logout`·`/auth/me`까지 10회/분에 걸려 **정상
    사용이 막힌다.** `GET /calculations`를 계산으로 세면 목록 화면이 60회/분에
    걸린다. 이 검사는 그 방향의 실수를 잡는다.
    """
    assert resolve_bucket(method, path) == BUCKET_DEFAULT


def test_bucket_paths_all_exist_in_the_app() -> None:
    """버킷 경로 목록의 모든 경로가 **실제 라우트로 존재한다** (#811).

    ## 왜 필요한가

    ``resolve_bucket``은 문자열 상수를 본다. 라우트 경로가 바뀌면 상수는 그대로
    남고 **한도만 조용히 풀린다** — 오류도, 로그도, 응답 변화도 없다. 로그인이
    다시 300회/분이 되어도 아무도 모른다.

    ``#591``이 ``API_SPEC §12`` ↔ 실제 라우트에서 같은 종류의 어긋남을 **양방향
    6종** 찾아낸 뒤로 이 저장소가 반복해 쓰는 방식이다.

    ## 무엇을 보지 않는가

    **반대 방향(「이 라우트도 버킷에 넣어야 하지 않나」)은 보지 않는다.** 새 계산
    엔드포인트가 생겼는데 목록에 없는 것은 사람이 판단할 문제이고, 자동으로 정하면
    조회 엔드포인트까지 60회/분에 걸린다.

    ## ``app.routes``가 아니라 OpenAPI를 읽는 이유

    ``app.routes``에는 ``include_router``한 것이 ``_IncludedRouter`` 항목으로만
    들어 있고 **개별 경로는 펼쳐져 있지 않다.** 그대로 세면 인증·계산 라우트가
    **0개로 보이고**, 그러면 이 검사가 「없는 것끼리 비교해」 조용히 통과한다.
    ``test_api_spec_endpoints_sync.py``가 `#634`에서 같은 함정에 걸릴 뻔해 이미
    OpenAPI를 읽는다.
    """
    from cii_platform.api.main import app

    registered = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    paths = {path for _, path in registered}

    assert paths, "OpenAPI에서 경로를 하나도 읽지 못했다 — 이 검사가 무력해진다"

    missing_auth = sorted(p for p in AUTH_PATHS if p not in paths)
    assert not missing_auth, (
        f"AUTH_PATHS에 있는데 앱에 없는 경로: {missing_auth}. "
        "라우트가 바뀌면 그 경로의 요청 한도가 조용히 풀린다 (#811)."
    )

    missing_calc = sorted(r for r in CALCULATION_ROUTES if r not in registered)
    assert not missing_calc, f"CALCULATION_ROUTES에 있는데 앱에 없는 라우트: {missing_calc} (#811)."


def test_login_eleventh_attempt_is_rate_limited() -> None:
    """로그인 11회째가 429다 — `#811` 완료 기준.

    ``main.app``이 아니라 인증 라우트를 붙인 전용 앱을 쓴다. 한도만 보면 되므로
    DB는 필요 없다 — 로그인 요청은 세션 의존성에서 막히지만, **레이트 리밋
    미들웨어는 그보다 바깥**이라(`#307`) 카운터는 이미 올라간 뒤다. 429가 그
    실패보다 **먼저** 나오는지가 이 검사의 대상이다.
    """
    from cii_platform.api.rate_limit import RateLimits

    app = FastAPI()
    app.state.rate_limiter = RateLimiter(RateLimits(default=300, auth=10, calculation=60))
    app.middleware("http")(rate_limit_middleware)
    register_exception_handlers(app)

    with TestClient(app) as client:
        codes = [
            client.post("/api/v1/auth/login", json={"email": "a@b.c", "password": "x"}).status_code
            for _ in range(11)
        ]

    assert codes[-1] == 429, codes
    assert 429 not in codes[:10], codes


def test_calculation_sixty_first_request_is_rate_limited() -> None:
    """계산 61회째가 429다 — `API_SPEC §13.2` 「계산 API 분당 60회」 (#811)."""
    from cii_platform.api.rate_limit import RateLimits

    app = FastAPI()
    app.state.rate_limiter = RateLimiter(RateLimits(default=300, auth=10, calculation=60))
    app.middleware("http")(rate_limit_middleware)
    register_exception_handlers(app)

    with TestClient(app) as client:
        codes = [
            client.post("/api/v1/calculations/voyage-cii", json={}).status_code for _ in range(61)
        ]

    assert codes[-1] == 429, codes[-3:]
    assert 429 not in codes[:60]


def test_buckets_do_not_share_a_counter() -> None:
    """버킷이 서로 독립이다 (#811).

    인증 한도(2)를 다 써도 계산·CRUD는 그대로 통과해야 한다. 카운터를 ``IP``만으로
    잡으면 이 검사가 깨진다 — 그러면 로그인 10회에 대시보드가 함께 막힌다.
    """
    from cii_platform.api.rate_limit import RateLimits

    app = FastAPI()
    app.state.rate_limiter = RateLimiter(RateLimits(default=5, auth=2, calculation=5))
    app.middleware("http")(rate_limit_middleware)
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/api/v1")

    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={}).status_code != 429
        assert client.post("/api/v1/auth/login", json={}).status_code != 429
        assert client.post("/api/v1/auth/login", json={}).status_code == 429
        # 인증 버킷이 막혀도 나머지는 살아 있다.
        assert client.get("/api/v1/health").status_code == 200
        assert client.post("/api/v1/calculations/voyage-cii", json={}).status_code != 429


def test_main_app_uses_the_documented_default_limits() -> None:
    """``main.app``의 기본 한도가 `API_SPEC §13.2` + `#811`의 값이다.

    환경변수가 비어 있는 상태를 전제한다 — CI·로컬 모두 이 셋을 설정하지 않는다.
    자기참조를 피하려고 **리터럴로** 대조한다.
    """
    from cii_platform.api.main import app

    limits = app.state.rate_limiter.limits
    assert limits.default == 300
    assert limits.auth == 10
    assert limits.calculation == 60
