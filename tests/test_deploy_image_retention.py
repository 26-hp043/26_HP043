"""이슈 #2041 · 배포가 app-01의 옛 백엔드 이미지를 정리하는지 고정한다.

## 무엇을 막는가

배포마다 `ghcr.io/<owner>/bluelog-backend:<sha>` 가 새로 받아지는데 지우는 단계가 없어,
2026-09-29에 app-01 루트 디스크가 **100%(45G 중 여유 139M)** 까지 찼다 —
`bluelog-backend` 이미지 253개 · `/var/lib/containerd` 36G.

## 왜 조용한가

정리 단계를 지워도 배포는 성공하고 `/health`도 200이다. 디스크는 배포 수십 번에 걸쳐
천천히 차고, 드러나는 것은 **운영 앱이 쓰기에 실패할 때**다.

## 무엇을 지우면 안 되는가

- **실행 중 이미지** — 지우면 컨테이너 재생성이 레지스트리에 기대게 된다.
- **같은 VM의 our-tax 이미지** — `docker image prune -a` 는 사용 중이 아닌 이미지를 저장소와
  무관하게 지운다(OPERATIONS §9.5가 그 명령을 권하고 있었다).
- **볼륨** — `--volumes` 는 §9.2의 고아 볼륨 복구 가능성을 없앤다(비가역).

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
from pathlib import Path

_DEPLOY = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"


def _app_script() -> str:
    """`deploy-app` 잡이 app-01에 보내는 heredoc 본문."""
    text = _DEPLOY.read_text(encoding="utf-8")
    job = text[text.index("\n  deploy-app:") :]
    job = job[: job.index("\n  deploy-frontend:")]
    start = job.index("<<'ENDSSH'")
    return job[start : job.index("ENDSSH", start + len("<<'ENDSSH'"))]


def test_deploy_removes_stale_backend_images():
    """app-01 배포가 옛 이미지를 `docker rmi` 로 지운다 (#2041)."""
    script = _app_script()
    assert re.search(r"docker rmi", script), (
        "deploy-app 원격 스크립트에 옛 이미지 정리가 없다 — 배포마다 이미지가 쌓여 "
        "app-01 디스크가 다시 찬다 (#2041)"
    )


def test_cleanup_runs_after_backend_restart():
    """정리는 새 컨테이너가 뜬 **뒤**에 돈다 — 실행 중 이미지를 새 것으로 판정해야 한다."""
    script = _app_script()
    up = script.index("up -d backend")
    rmi = script.index("docker rmi")
    assert up < rmi, "옛 이미지 정리가 backend 재시작보다 먼저 돈다 — 보존 기준이 옛 이미지가 된다"


def test_cleanup_keeps_running_image():
    """실행 중 이미지를 목록에서 빼고, 최근 몇 개를 남긴다."""
    script = _app_script()
    assert "docker inspect cii-backend" in script, "실행 중 이미지를 확인하지 않고 지운다"
    assert re.search(r'grep -vxF "\$\{running_image\}"', script), (
        "실행 중 이미지를 삭제 대상에서 빼지 않는다"
    )
    keep = re.search(r"^\s*KEEP_IMAGES=(\d+)\s*$", script, re.MULTILINE)
    assert keep and int(keep.group(1)) >= 1, "보존 개수(KEEP_IMAGES)가 없거나 0이다"


def test_cleanup_is_scoped_to_backend_repo():
    """저장소를 가리지 않는 정리 명령을 쓰지 않는다 — 같은 VM의 our-tax 이미지·볼륨을 지운다."""
    # 주석은 뺀다 — 쓰지 않는 이유를 적은 주석이 그 명령 이름을 담고 있다.
    script = "\n".join(
        line for line in _app_script().splitlines() if not line.lstrip().startswith("#")
    )
    for banned in ("image prune -a", "image prune --all", "system prune", "volume prune"):
        assert banned not in script, f"`docker {banned}` 는 같은 VM의 다른 프로젝트까지 지운다"
    assert re.search(r'docker images "\$\{image_repo\}"', script), (
        "정리 대상을 백엔드 이미지 저장소로 한정하지 않는다"
    )


def test_cleanup_failure_does_not_fail_deploy():
    """`set -e` 아래에서 정리 실패가 배포를 멈추지 않는다."""
    script = _app_script()
    rmi_line = next(line for line in script.splitlines() if "docker rmi" in line)
    assert "||" in rmi_line, "docker rmi 실패가 set -e로 배포를 실패시킨다"
