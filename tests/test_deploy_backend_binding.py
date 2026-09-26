"""백엔드는 루프백에만 게시하고 외부 요청은 터널로만 받는다 (`#786`).

## 무엇을 막는가

종전 ``docker-compose.prod.app.yml``의 ``"8001:8000"``은 **모든 인터페이스**에 게시되어,
공인 IP ``:8001``로 터널을 거치지 않고 백엔드에 닿는 길이 열려 있었다. 그 길로 들어온
요청은 Cloudflare도 Pages Function의 프록시 서명 헤더(`#1483`)도 거치지 않는다.

## 왜 세 자리를 함께 보는가

* compose 게시 주소 — ``127.0.0.1:`` 한 토막이 빠지면 조용히 다시 열린다.
* 배포 헬스체크 — 게시를 좁히고 헬스체크가 여전히 공인 IP ``:8001``을 부르면 **모든 배포가
  헬스체크에서 실패한다.** 둘은 한 몸이다.
* 배포마다 공인 ``:8001``이 닫혀 있는지 확인하는 단계 — 컨테이너는 배포마다 다시 만들어지므로
  열린 채로 돌아가면 그때 드러나야 한다.

배포는 실행하면 운영 서버를 건드리므로 파일에서 본다(`test_deploy_freeze.py`와 같은 판단).

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = _ROOT / "docker-compose.prod.app.yml"
DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"

TUNNEL_HEALTH = "https://bluelog-api.kpubdata.com/api/v1/health"


def _deploy_app_steps() -> list[dict]:
    workflow = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    return workflow["jobs"]["deploy-app"]["steps"]


def _step(name: str) -> dict:
    for step in _deploy_app_steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"deploy-app에 「{name}」 단계가 없다")


def test_backend_published_on_loopback_only() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    ports = compose["services"]["backend"]["ports"]
    assert ports, "backend 게시 포트가 없다 — 터널 커넥터가 localhost:8001로 닿지 못한다"
    for entry in ports:
        assert str(entry).startswith("127.0.0.1:"), (
            f"backend가 루프백 밖에 게시된다: {entry!r} — 터널을 우회하는 길이 열린다 (#786)"
        )


def test_health_check_goes_through_tunnel() -> None:
    script = _step("헬스 체크")["run"]
    assert TUNNEL_HEALTH in script
    # 공인 IP `:8001`로 묻는 줄이 남으면 게시를 좁힌 뒤 모든 배포가 실패한다
    assert not re.search(r"OCI_APP_HOST\s*}}:8001", script)


def test_public_port_closed_check_fails_when_open() -> None:
    script = _step("공인 :8001 닫힘 확인")["run"]
    assert re.search(r"OCI_APP_HOST\s*}}:8001", script)
    # 응답이 오면(= 열려 있으면) 실패로 끝나야 한다
    assert re.search(r"if curl [^\n]*; then\n(?:[^\n]*\n)*?\s*exit 1", script)
