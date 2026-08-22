"""OpenAPI 문서 노출 범위 (#593).

**프로덕션에서 ``/docs``·``/redoc``·``/openapi.json``을 열지 않는다.** FastAPI 기본값이
「항상 켜짐」이라, 종전에는 세션 없이 API 전체 구조를 읽을 수 있었다 — 엔드포인트 50종,
요청 스키마, 필드명, 검증 규칙.

## 왜 하위 프로세스를 띄우는가

판정은 ``APP_ENV``를 **import 시점에** 읽는다(``config._ENV``). ``main.app``도, 공개 경로
목록도 그때 확정된다 — 그래서 같은 프로세스 안에서 환경을 바꿔 다시 만들 수 없다.
``importlib.reload``로는 부족하다: ``auth/middleware.py``가 ``is_public_path``를
``from ... import``로 **함수 객체째** 붙잡고 있어, 모듈을 다시 읽어도 미들웨어는 옛 함수를
계속 부른다.

순수 함수만 대조하면 *「함수가 옳은 값을 돌려준다」*까지만 증명되고 **「그 값이 실제 앱에
닿았다」**는 증명되지 않는다 — ``test_auth_wiring.py``가 `#318`에서 정확히 그 이유로 최소
앱을 거부했다. 그래서 프로덕션 환경변수로 **진짜 앱을 새 프로세스에서 기동**해 응답 코드를
확인한다.

케이스: AT-AUTH-014 · AT-AUTH-015 (`TEST_PLAN §14.5`)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import api_docs_kwargs, app
from cii_platform.api.rate_limit import RateLimiter
from cii_platform.auth.dependencies import _DEV_AUTH_PATHS, _DOCS_PATHS, build_public_paths
from cii_platform.config import should_expose_api_docs, should_expose_dev_auth

_REPO = Path(__file__).parents[1]


# ---------------------------------------------------------------------------
# 판정 — `should_register_dev_auth()`와 같은 형태다 (#276)
# ---------------------------------------------------------------------------


def test_docs_are_closed_in_production():
    """``APP_ENV=production`` → False."""
    import cii_platform.config as mod

    original = mod._ENV
    mod._ENV = "production"
    try:
        assert should_expose_api_docs() is False
    finally:
        mod._ENV = original


def test_docs_are_open_outside_production():
    """개발·스테이징에서는 연다. ``APP_ENV`` 미설정도 개발로 본다 (``config.py``)."""
    import cii_platform.config as mod

    original = mod._ENV
    try:
        for env in ("development", "staging", "test"):
            mod._ENV = env
            assert should_expose_api_docs() is True, env
    finally:
        mod._ENV = original


# ---------------------------------------------------------------------------
# 설정 조립
# ---------------------------------------------------------------------------


def test_production_turns_off_all_three():
    """**셋을 함께** 끈다.

    ``/docs``는 스펙 본문을 ``/openapi.json``에서 받아 그린다. 하나만 남기면 UI만
    사라지고 **구조 정보는 그대로 열린다.**
    """
    assert api_docs_kwargs(expose_docs=False) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_development_keeps_fastapi_defaults():
    """빈 dict을 돌려준다 — 기본 경로를 다시 적으면 FastAPI가 바꿨을 때 갈린다."""
    assert api_docs_kwargs(expose_docs=True) == {}


def test_public_paths_drop_the_docs_in_production():
    """공개 경로에서도 뺀다.

    라우트를 등록하지 않는 것만으로도 404지만, 그것만 하면 **``/docs``만 404이고 나머지
    미등록 경로는 401**이 된다 — 그 차이가 「여기에 무언가 있다」는 신호가 된다.
    """
    closed = build_public_paths(expose_docs=False, expose_dev_auth=False)
    open_ = build_public_paths(expose_docs=True, expose_dev_auth=True)

    assert _DOCS_PATHS & closed == set()
    assert open_ >= _DOCS_PATHS
    # 문서·dev-login 말고는 달라지지 않는다 — 인증 플로우가 함께 닫히면 로그인이 막힌다.
    assert open_ - closed == _DOCS_PATHS | _DEV_AUTH_PATHS


def test_health_and_login_stay_public_in_production():
    """프로덕션에서도 열려 있어야 하는 것 (`API_SPEC §1.2`)."""
    closed = build_public_paths(expose_docs=False, expose_dev_auth=False)

    for path in ("/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/signup"):
        assert path in closed, path


# ---------------------------------------------------------------------------
# 배선 — 실제 `main.app` (#307 · #318)
# ---------------------------------------------------------------------------


def test_the_running_app_matches_the_decision():
    """설정이 ``FastAPI()``에 실제로 닿았는지 본다.

    ``api_docs_kwargs()``만 검사하면 함수가 옳은 값을 돌려준다는 것까지만 증명된다.
    """
    expected = "/docs" if should_expose_api_docs() else None

    assert app.docs_url == expected
    assert app.redoc_url == ("/redoc" if should_expose_api_docs() else None)
    assert app.openapi_url == ("/openapi.json" if should_expose_api_docs() else None)


@pytest.fixture
def spare_rate_limiter():
    """이 테스트의 요청을 **공용 분당 한도에서 빼 둔다**.

    ``main.app``은 모듈 레벨 객체라 ``app.state.rate_limiter``(300/분)를 **pytest
    프로세스 전체가 공유**한다 — 그 앱을 ``TestClient``로 때리는 테스트 파일이 22개다.
    로컬은 전체 실행이 3분 46초라 요청이 여러 윈도에 흩어지지만, **CI는 1분 4초**라
    같은 윈도에 몰린다. 실제로 이 파일을 더한 뒤 CI에서 무관한
    ``test_voyage_cii_api.py``가 429로 떨어졌다.

    그래서 이 테스트 동안만 **별도 카운터**를 끼우고 끝나면 원래 것을 되돌린다 —
    다른 테스트가 쌓아 둔 카운트를 지우지 않으면서, 이 파일이 예산을 **0** 쓰게 한다.

    ⚠️ **한도 자체가 아슬아슬한 것은 그대로 남는다.** 공용 리미터를 매 테스트마다
    리셋하는 것이 근본 해법이지만 ``conftest.py``(공용 인프라) 소관이라 이 이슈에서
    다루지 않는다.
    """
    original = app.state.rate_limiter
    app.state.rate_limiter = RateLimiter(original.limit)
    try:
        yield
    finally:
        app.state.rate_limiter = original


def test_docs_answer_in_the_current_environment(spare_rate_limiter):
    """개발 환경(테스트가 도는 곳)에서는 지금까지처럼 열린다 — 회귀 방지."""
    assert should_expose_api_docs() is True, "이 테스트는 APP_ENV 미설정을 전제한다"

    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


# ---------------------------------------------------------------------------
# 프로덕션 기동 — 새 프로세스
# ---------------------------------------------------------------------------

_PROBE = """
import json
from fastapi.testclient import TestClient
from cii_platform.api.main import app

out = {}
with TestClient(app, base_url="https://testserver") as client:
    for path in ("/docs", "/redoc", "/openapi.json"):
        out[path] = client.get(path).status_code
    # 라우트가 등록되지 않는 경로도 다른 미등록 경로와 같은 응답이어야 한다 (#648).
    out["/api/v1/auth/dev-login"] = client.post("/api/v1/auth/dev-login").status_code
    # 대조군 — 보호된 라우트는 그대로 401, 없는 경로도 401이어야 한다.
    out["/api/v1/vessels"] = client.get("/api/v1/vessels").status_code
    out["/nonexistent"] = client.get("/nonexistent").status_code
print("RESULT " + json.dumps(out))
"""


def _run_in_production() -> dict[str, int]:
    env = {
        **os.environ,
        "APP_ENV": "production",
        # 프로덕션은 DATABASE_URL이 없으면 기동을 거부한다 (#118). 연결하지는 않는다.
        "DATABASE_URL": "postgresql+asyncpg://cii:cii@localhost:5432/cii",
        # 프로덕션 + console 메일 백엔드 조합은 기동이 실패한다 (`.env.example`).
        "MAIL_BACKEND": "smtp",
        "SMTP_HOST": "smtp.example.test",
        "PYTHONPATH": str(_REPO / "src"),
    }
    done = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=env,
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert done.returncode == 0, f"기동 실패:\n{done.stdout}\n{done.stderr}"

    line = next(x for x in done.stdout.splitlines() if x.startswith("RESULT "))
    return json.loads(line.removeprefix("RESULT "))


def test_production_app_hides_the_docs():
    """**이 테스트가 이 이슈의 완료 기준이다.**

    ``APP_ENV=production``으로 진짜 앱을 띄워 세 경로의 응답을 본다. 셋 다 401이어야
    한다 — 라우트가 없어서 404가 아니라, **다른 미등록 경로와 똑같이** 인증 미들웨어가
    먼저 끊기 때문이다. 404가 나오면 그 경로만 특별하다는 신호가 남는다.
    """
    codes = _run_in_production()

    assert codes["/docs"] == 401, codes
    assert codes["/redoc"] == 401, codes
    assert codes["/openapi.json"] == 401, codes
    # 대조군 — 보호 경로의 동작이 바뀌지 않았다.
    assert codes["/api/v1/vessels"] == 401, codes


# ---------------------------------------------------------------------------
# 공개 경로의 불변식 (#648)
#
# `#593`이 문서 경로에 대해 세운 원칙 — **미등록 경로는 전부 같은 응답을 낸다** —
# 이 한 곳에서만 깨져 있었다. 프로덕션에서 `POST /api/v1/auth/dev-login`이 **404**였다:
# `#276`이 라우트를 등록하지 않는데 공개 경로 목록에는 그대로 남아 있어, 미들웨어를
# 통과하고 라우팅에서 404가 됐다. 다른 미등록 경로는 라우팅 전에 401로 끊긴다.
#
# 개별 수정으로 끝내지 않고 **「목록의 모든 경로에 라우트가 실재한다」**를 잠근다 —
# 그 성질이 깨지는 순간이 곧 응답이 갈리는 순간이다.
# ---------------------------------------------------------------------------


def _registered_paths() -> set[str]:
    """앱에 실제로 등록된 경로.

    ``app.routes``는 ``include_router``한 것을 ``_IncludedRouter`` 하나로 감싸 두므로
    **원본 라우터를 펼쳐야** 실제 경로가 나온다. 펼치지 않으면 4개(문서 라우트)만
    보이고, 그 상태로 대조하면 이 테스트가 **언제나 통과한다.**
    """
    paths: set[str] = set()
    for route in app.routes:
        direct = getattr(route, "path", None)
        if direct:
            paths.add(direct)
            continue
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        prefix = getattr(context, "prefix", "") if context is not None else ""
        if original is not None:
            for sub in getattr(original, "routes", []):
                sub_path = getattr(sub, "path", None)
                if sub_path:
                    paths.add(prefix + sub_path)
    return paths


def test_the_helper_actually_finds_the_routes():
    """펼치기가 동작하는지 먼저 본다 — 이 확인이 없으면 아래 단언이 공허해진다."""
    paths = _registered_paths()

    assert len(paths) > 30, f"라우트를 제대로 펼치지 못했다: {len(paths)}개"
    assert "/api/v1/vessels" in paths
    assert "/api/v1/auth/login" in paths


def test_every_public_path_has_a_route():
    """공개 경로에 라우트가 없으면 **그 경로만 404**가 된다.

    다른 미등록 경로는 전부 401이므로, 그 차이가 「여기에 무언가 있다」는 신호가 된다.
    """
    orphans = sorted(
        build_public_paths(expose_docs=True, expose_dev_auth=True) - _registered_paths()
    )

    assert not orphans, (
        f"라우트가 없는 공개 경로 {len(orphans)}개: {orphans}\n"
        "→ 목록에서 빼거나, 환경에 따라 갈린다면 build_public_paths()에 조건을 더하세요."
    )


def test_public_paths_all_carry_the_api_prefix():
    """접두사 없는 사본은 **영원히 매치되지 않는다** — `is_public_path()`가 그 이유를 적고 있다.

    > 실제 요청 경로는 항상 ``/api/v1`` prefix를 달고 나오므로 접두사가 실효 없었고 …

    종전에는 그런 항목이 8개 있었다(``/health``·``/auth/login`` 등). 허용 목록만 넓히고
    아무 일도 하지 않는다. 문서 경로(``/docs``)는 FastAPI가 루트에 등록하므로 예외다.
    """
    everything = build_public_paths(expose_docs=True, expose_dev_auth=True)
    bare = sorted(p for p in everything - _DOCS_PATHS if not p.startswith("/api/v1/"))

    assert not bare, f"`/api/v1` 접두사가 없는 공개 경로: {bare}"


def test_the_two_dev_auth_judgements_agree():
    """같은 판정이 두 곳에 있다 — 갈리면 dev-login이 다시 404가 된다.

    ``auth/dependencies.py``가 ``routes/auth_dev.py``를 import하면 ``TECH_SPEC §16``
    계층 규칙을 어기므로(auth는 routes보다 아래층) ``config.py``에 따로 두었다.
    **여기서 대조하는 것이 그 대가다.**
    """
    import cii_platform.api.routes.auth_dev as auth_dev
    import cii_platform.config as config

    original_config, original_route = config._ENV, auth_dev._ENV
    try:
        for env in ("production", "development", "staging"):
            config._ENV = auth_dev._ENV = env
            assert should_expose_dev_auth() is auth_dev.should_register_dev_auth(), env
    finally:
        config._ENV, auth_dev._ENV = original_config, original_route


def test_production_hides_the_dev_login_the_same_way():
    """프로덕션에서 dev-login이 **401**이다 — 404가 아니다.

    404는 「그 경로만 다르다」를 말한다. 다른 미등록 경로와 같은 응답이어야 신호가
    남지 않는다.
    """
    codes = _run_in_production()

    assert codes["/api/v1/auth/dev-login"] == 401, codes
