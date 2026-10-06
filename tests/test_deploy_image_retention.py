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

## 정리가 배포를 멈추지 않는가 (#2178)

정리 블록 머리주석이 「실패해도 배포를 실패시키지 않는다」고 적는데, 고정 경로 임시 파일
(`/tmp/bluelog-stale-images`)을 읽는 `wc`와 지우는 `rm`, 블록 끝의 `df` 줄은 실패를 삼키지
않았다. 그 시점엔 새 컨테이너가 이미 떠 있어, 스크립트가 죽으면 **배포는 됐는데 실패로
보고된다.** 블록을 `deploy.yml`에서 뽑아 가짜 `docker`를 깔고 `bash -euo pipefail`로 실제
실행해, 명령을 하나씩 실패시켜도 0으로 끝나는지 본다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

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


# ── 정리 블록을 실제로 실행한다 (#2178) ─────────────────────────────────────

_BASH = shutil.which("bash")
requires_bash = pytest.mark.skipif(_BASH is None, reason="bash가 없다")

#: 정리 블록이 부르는 외부 명령. `wc`·`rm`은 고정 경로 임시 파일을 쓰던 때의 두 줄이
#: 불렀다 — 그 줄이 돌아오면 여기서 걸리도록 남긴다.
_TOOLS = ("sort", "cut", "grep", "tail", "xargs", "awk", "wc", "rm")

_REPO = "ghcr.io/acme/bluelog-backend"
_RUNNING = f"{_REPO}:t4"

#: 가짜 `docker` — 받은 인자를 `DOCKER_LOG`에 남기고, `DOCKER_FAIL`이 가리키는 하위 명령만
#: 실패한다. 이미지 6개(순서를 섞었다)와 태그 없는 것 하나를 돌려준다.
_FAKE_DOCKER = f"""#!{_BASH}
echo "$*" >> "${{DOCKER_LOG}}"
if [ "$1" = "${{DOCKER_FAIL:-}}" ]; then
  echo "가짜 docker: $1 실패" >&2
  exit 1
fi
case "$1" in
  inspect) echo "{_RUNNING}" ;;
  images)
    printf '%s\\t%s\\n' \\
      "2026-10-03 00:00:00 +0000 UTC" "{_REPO}:t3" \\
      "2026-10-06 00:00:00 +0000 UTC" "{_REPO}:t6" \\
      "2026-10-01 00:00:00 +0000 UTC" "{_REPO}:t1" \\
      "2026-10-07 00:00:00 +0000 UTC" "{_REPO}:<none>" \\
      "2026-10-04 00:00:00 +0000 UTC" "{_REPO}:t4" \\
      "2026-10-05 00:00:00 +0000 UTC" "{_REPO}:t5" \\
      "2026-10-02 00:00:00 +0000 UTC" "{_REPO}:t2"
    ;;
esac
"""

_FAKE_DF = f"""#!{_BASH}
echo "Filesystem Size Used Avail Use% Mounted on"
echo "/dev/sda1 45G 14G 31G 31% /"
"""


def _cleanup_block() -> str:
    """`KEEP_IMAGES=`부터 `df` 줄까지 — 들여쓰기를 걷어 셸 원문으로."""
    lines = _app_script().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("KEEP_IMAGES="))
    end = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("df "))
    return textwrap.dedent("\n".join(lines[start : end + 1])) + "\n"


def _run_cleanup(
    tmp_path: Path, *, docker_fail: str = "", broken_tool: str = ""
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """블록을 `bash -euo pipefail`로 돌려 ``(결과, 가짜 docker가 받은 인자 줄)``을 돌려준다.

    `PATH`에는 이 디렉터리만 둔다 — 목록에 없는 명령을 블록이 새로 부르면 찾지 못한다.
    """
    assert _BASH is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {"docker": _FAKE_DOCKER, "df": _FAKE_DF}
    for tool in _TOOLS:
        real = shutil.which(tool)
        assert real, f"`{tool}`이 없다"
        (bin_dir / tool).symlink_to(real)
    if broken_tool:
        (bin_dir / broken_tool).unlink(missing_ok=True)
        fakes[broken_tool] = f"#!{_BASH}\nexit 1\n"
    for name, body in fakes.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    log = tmp_path / "docker.log"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        [_BASH, "-euo", "pipefail", "-c", _cleanup_block()],
        env={"PATH": str(bin_dir), "DOCKER_LOG": str(log), "DOCKER_FAIL": docker_fail},
        capture_output=True,
        text=True,
        check=False,
    )
    return result, log.read_text(encoding="utf-8").splitlines()


def test_cleanup_uses_no_fixed_temp_path():
    """지울 목록을 고정 경로 파일에 두지 않는다 — 쓰기만 실패하면 지난 실행의 목록을 읽는다."""
    block = "\n".join(
        line for line in _cleanup_block().splitlines() if not line.lstrip().startswith("#")
    )
    assert "/tmp/" not in block, "정리 블록이 `/tmp/` 고정 경로에 기댄다 (#2178)"


@requires_bash
def test_cleanup_removes_only_stale_images(tmp_path: Path):
    """이미지 6개 중 실행 중인 것과 최신 3개를 뺀 둘만 `docker rmi`에 넘어간다."""
    result, calls = _run_cleanup(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls[0].startswith("inspect cii-backend"), calls
    assert calls[1].startswith(f"images {_REPO} "), calls
    assert calls[2:] == [f"rmi {_REPO}:t2 {_REPO}:t1"], calls
    assert " 2개 " in result.stdout, result.stdout
    assert "루트 디스크 14G / 45G (31%)" in result.stdout, result.stdout


@requires_bash
@pytest.mark.parametrize("subcommand", ["inspect", "images", "rmi"])
def test_cleanup_survives_docker_failure(tmp_path: Path, subcommand: str):
    """`docker` 하위 명령이 실패해도 블록은 0으로 끝나고, 지우지 못한 것은 경고로 남는다."""
    result, calls = _run_cleanup(tmp_path, docker_fail=subcommand)
    assert result.returncode == 0, f"docker {subcommand} 실패가 배포를 멈춘다\n{result.stderr}"
    assert "루트 디스크" in result.stdout, "블록 끝까지 가지 못했다"
    if subcommand == "inspect":
        assert [c.split()[0] for c in calls] == ["inspect"], calls
        assert "::warning::" in result.stdout
    elif subcommand == "images":
        assert not any(c.startswith("rmi") for c in calls), calls
    else:
        assert "::warning::" in result.stdout, "지우지 못한 것을 알리지 않는다"


@requires_bash
@pytest.mark.parametrize("tool", [*_TOOLS, "df"])
def test_cleanup_survives_any_failing_command(tmp_path: Path, tool: str):
    """블록이 부르는 명령 어느 하나가 실패해도 0으로 끝난다 — 정리는 배포의 일부가 아니다."""
    result, calls = _run_cleanup(tmp_path, broken_tool=tool)
    assert result.returncode == 0, f"`{tool}` 실패가 배포를 멈춘다 (#2178)\n{result.stderr}"
    # 목록을 만드는 명령이 죽었으면 아무것도 지우지 않는다 — 걸러지지 않은 목록을 넘기지 않는다.
    if tool in ("sort", "cut", "grep", "tail"):
        assert not any(c.startswith("rmi") for c in calls), calls
