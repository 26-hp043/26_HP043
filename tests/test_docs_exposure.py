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

케이스: AT-AUTH-014 (`TEST_PLAN §14.5`)
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
from cii_platform.auth.dependencies import _DOCS_PATHS, build_public_paths
from cii_platform.config import should_expose_api_docs

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
    closed = build_public_paths(expose_docs=False)
    open_ = build_public_paths(expose_docs=True)

    assert _DOCS_PATHS & closed == set()
    assert open_ >= _DOCS_PATHS
    # 문서 경로 말고는 달라지지 않는다 — 인증 플로우가 함께 닫히면 로그인이 막힌다.
    assert open_ - closed == _DOCS_PATHS


def test_health_and_login_stay_public_in_production():
    """프로덕션에서도 열려 있어야 하는 것 (`API_SPEC §1.2`)."""
    closed = build_public_paths(expose_docs=False)

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
    # 대조군 — 보호된 라우트는 그대로 401이어야 한다.
    out["/api/v1/vessels"] = client.get("/api/v1/vessels").status_code
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
