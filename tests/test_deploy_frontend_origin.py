"""이슈 #1322 · 클라우드 배포가 화면과 API를 **같은 오리진**에 두는지 고정한다.

## 무엇을 막는가

종전 배포는 화면이 ``https://bluelog-bx7.pages.dev``, API가 ``http://131.186.22.10:8001``
이었다. 세 겹으로 막혀 **로그인이 아예 성립하지 않았다.**

1. https 페이지에서 http로 가는 fetch는 **혼합 콘텐츠로 차단**된다 — 요청이 나가지 않는다
2. 설령 나가도 ``Secure`` 쿠키는 **http 응답의 ``Set-Cookie``에서 거부**된다
   (``auth/session.py``의 ``COOKIE_ATTRIBUTES``). ``localhost`` 예외는 IP에 없다
3. ``SameSite=Lax`` 쿠키는 ``pages.dev`` → ``131.186.22.10`` **교차 사이트 fetch에
   실리지 않는다**

## 왜 조용한가

**배포는 성공하고 화면도 뜬다.** ``/health``는 200이고 CORS preflight도 통과한다 —
``docs/OPERATIONS.md``의 「배포 검증 결과」가 실제로 그 셋만 확인했고 **로그인 성공을
확인한 항목이 없었다.** 로그인 버튼을 눌러 봐야 드러나고, 그 시점이 시연 당일이면 늦다.

## 왜 값 하나를 검사로 고정하는가

``VITE_API_BASE_URL``은 **빌드 시점에 코드에 굳는다.** 절대 주소로 한 글자만 되돌리면
세 겹이 전부 돌아오는데, 그 되돌림은 배포 로그 어디에도 실패로 남지 않는다.
`#1290`·`#1331`과 같은 종류의 조용한 배선 결함이다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
_WRANGLER = _ROOT / "frontend" / "wrangler.toml"
#: Pages Functions의 catch-all. 이 파일이 곧 `/api/*` 라우트다 — 별도 등록이 없다.
_PROXY_ROUTE = _ROOT / "frontend" / "functions" / "api" / "[[path]].ts"
_PROXY_LIB = _ROOT / "frontend" / "functions" / "_proxy.ts"


def _deploy_text() -> str:
    return _DEPLOY.read_text(encoding="utf-8")


def test_frontend_build_uses_a_relative_api_base_url():
    """``VITE_API_BASE_URL``이 **상대 경로**다 (#1322).

    절대 주소면 화면이 다른 오리진을 부르게 되고, 위 세 겹이 그대로 돌아온다.
    """
    values = re.findall(r"^\s*VITE_API_BASE_URL:\s*(\S+)", _deploy_text(), re.M)

    assert values, "deploy.yml에 VITE_API_BASE_URL이 없다 — 화면 빌드가 API 주소를 받지 못한다."
    for value in values:
        assert not value.startswith(("http://", "https://", "'http", '"http')), (
            f"VITE_API_BASE_URL이 절대 주소다: {value}. 화면과 API가 다른 오리진이 되면 "
            "혼합 콘텐츠·Secure 쿠키·SameSite 세 겹으로 로그인이 성립하지 않는다 (#1322). "
            "상대 경로(/api/v1)를 쓰고 functions/api/[[path]].ts가 넘기게 한다."
        )


def test_pages_function_proxies_api():
    """`/api/*` 프록시 라우트가 있다 (#1322).

    상대 경로만 두고 이 파일이 없으면 **화면이 자기 자신에게 API를 묻는다** — Pages가
    SPA 폴백으로 ``index.html``을 돌려주므로 요청은 200인데 본문이 HTML이다. JSON 파싱이
    깨지는 자리가 화면마다 달라 원인을 찾기 어렵다.
    """
    assert _PROXY_ROUTE.exists(), (
        f"{_PROXY_ROUTE.relative_to(_ROOT)}가 없다 — /api/* 를 넘길 곳이 없다 (#1322)."
    )
    assert _PROXY_LIB.exists(), f"{_PROXY_LIB.relative_to(_ROOT)}가 없다 (#1322)."

    route = _PROXY_ROUTE.read_text(encoding="utf-8")
    assert "onRequest" in route, (
        "Pages Functions가 부르는 이름은 onRequest다 — 라우트가 등록되지 않는다."
    )


def test_wrangler_config_carries_the_backend_origin():
    """``wrangler.toml``이 ``API_ORIGIN``을 들고 있다 (#1322).

    대시보드 환경변수에만 두면 **저장소에서 보이지 않는다** — 배포가 어디로 가는지
    아는 방법이 사람의 기억뿐이 되고, 값이 바뀌어도 커밋에 남지 않는다.
    """
    assert _WRANGLER.exists(), "frontend/wrangler.toml이 없다 (#1322)."
    text = _WRANGLER.read_text(encoding="utf-8")

    assert re.search(r"^\s*API_ORIGIN\s*=", text, re.M), (
        "wrangler.toml의 [vars]에 API_ORIGIN이 없다 — 프록시가 상류를 정하지 못한다 (#1322)."
    )
    assert re.search(r"^\s*pages_build_output_dir\s*=", text, re.M), (
        "pages_build_output_dir이 없다 — 배포 명령이 위치 인자 없이 도므로 "
        "출력 디렉터리를 찾지 못한다 (#1322)."
    )


def test_deploy_does_not_pass_a_positional_output_dir():
    """배포 명령이 ``dist``를 위치 인자로 주지 않는다 (#1322).

    ``pages_build_output_dir``이 설정된 상태에서 위치 인자를 함께 주면 wrangler가
    **충돌로 거부한다.** 둘 중 하나가 남아야 하고, 설정 파일 쪽을 정본으로 둔다.
    """
    match = re.search(r"^\s*run:\s*(npx\s.*wrangler@4\s+pages\s+deploy.*)$", _deploy_text(), re.M)

    assert match, "deploy.yml에서 wrangler pages deploy 명령을 찾지 못했다."
    command = match.group(1)
    assert " deploy dist" not in command, (
        f"배포 명령이 출력 디렉터리를 위치 인자로 준다: {command}. "
        "wrangler.toml의 pages_build_output_dir과 충돌한다 (#1322)."
    )
