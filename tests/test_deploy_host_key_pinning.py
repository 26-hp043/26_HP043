"""배포 SSH는 **사전에 대조한 호스트 키**만 믿는다 (`#1637` · `F-11`).

## 무엇을 막는가

종전 워크플로는 배포 직전에 `ssh-keyscan`으로 원격 호스트의 공개키를 받아
`known_hosts`에 넣었다. 네트워크 경로에서 잘못된 키가 주입돼도 **같은 연결 흐름이
그 키를 신뢰**하므로, 호스트 신원 검증이 있으나 마나였다.

이제 사람이 두 경로(서버 콘솔 · 다른 경로의 `ssh-keyscan`)에서 얻은 지문을 대조해
`ops/host/known_hosts`에 커밋하고, 워크플로는 그 파일을 `~/.ssh/known_hosts`로 복사한 뒤
`-o StrictHostKeyChecking=yes`로 접속한다. 파일에 호스트가 없으면 `SSH 설정` 단계가
멈추고, 키가 다르면 ssh가 접속을 거부한다 — 어느 쪽이든 **원격 명령은 돌지 않는다.**

## 왜 파일 검사인가

배포는 실행해야 재현되는데 그 실행이 **운영 서버를 건드린다.** 재현 대신 워크플로가
**무엇을 믿는지**를 파일에서 본다 — 실행 중 수집이 사라졌는가 · 접속이 엄격 검사인가 ·
없으면 멈추는가 · 파일의 줄이 ssh가 읽을 수 있는 모양인가.

`PyYAML`을 들이지 않는 판단은 `test_workflow_timeouts.py`와 같다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
KNOWN_HOSTS = _ROOT / "ops" / "host" / "known_hosts"

#: 배포 워크플로에서 원격 호스트에 접속하는 잡. 둘 다 같은 `SSH 설정` 단계를 갖는다.
SSH_JOBS = ("deploy-db", "deploy-app")


def _text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _job(name: str) -> str:
    """`jobs:` 아래 들여쓰기 2칸의 잡 블록 하나를 잘라 낸다."""
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", _text(), re.S | re.M)
    assert match, f"잡 `{name}`을 찾지 못했다"
    return match.group(1)


def _key_lines() -> list[str]:
    """`known_hosts`에서 주석·빈 줄을 뺀 실제 항목."""
    return [
        line.strip()
        for line in KNOWN_HOSTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_workflow_is_read_at_all():
    """파일을 못 읽으면 아래 검사가 **빈 문자열을 훑어 통과**한다."""
    body = _text()
    assert all(f"  {job}:" in body for job in SSH_JOBS), "배포 워크플로의 잡 이름을 찾지 못했다"


def test_no_host_key_is_collected_during_the_run():
    """`ssh-keyscan`이 사라졌다 — 실행 중 받은 키는 검증이 아니다."""
    offending = [line.strip() for line in _text().splitlines() if "ssh-keyscan" in line]
    assert offending == [], "실행 중 호스트 키를 받아 간다:\n  " + "\n  ".join(offending)


def test_every_ssh_connection_checks_the_host_key_strictly():
    """`ssh` 호출마다 `-o StrictHostKeyChecking=yes`가 붙는다 — 두 호스트 모두."""
    calls = [line.strip() for line in _text().splitlines() if line.strip().startswith("ssh -i ")]
    assert len(calls) == 2, f"ssh 호출이 둘이 아니다: {calls}"
    lax = [c for c in calls if "-o StrictHostKeyChecking=yes" not in c]
    assert lax == [], "엄격 검사 없이 접속한다:\n  " + "\n  ".join(lax)


@pytest.mark.parametrize("job", SSH_JOBS)
def test_the_pinned_file_is_what_ssh_reads(job: str):
    """저장소 파일을 `~/.ssh/known_hosts`로 **덮어쓴다**(이어 붙이지 않는다).

    러너의 기존 `known_hosts`에 무엇이 있든, ssh가 읽는 것은 사람이 대조한 줄뿐이어야 한다.
    """
    block = _job(job)
    assert "actions/checkout@" in block, f"`{job}`이 저장소를 받지 않아 파일을 읽을 수 없다"
    assert "cp ops/host/known_hosts ~/.ssh/known_hosts" in block
    assert ">> ~/.ssh/known_hosts" not in block, "이어 붙이면 러너에 남은 키가 함께 신뢰된다"


@pytest.mark.parametrize("job", SSH_JOBS)
def test_a_missing_host_stops_the_deploy_before_any_remote_command(job: str):
    """파일에 그 호스트가 없으면 **`SSH 설정`에서 멈춘다** — 원격 명령 전이다.

    `ssh-keygen -F`는 항목이 없으면 1로 끝난다(실측). 그 뒤 `exit 1`이 있어야 하고,
    이 검사가 `ssh` 호출보다 **앞**에 있어야 한다.
    """
    block = _job(job)
    gate = re.search(r'if ! ssh-keygen -F "\$\{OCI_(DB|APP)_HOST\}" -f ops/host/known_hosts', block)
    assert gate, f"`{job}`에 호스트 키 존재 검사가 없다"
    after_gate = block[gate.end() :]
    assert "exit 1" in after_gate.split("cp ops/host/known_hosts")[0], "없어도 멈추지 않는다"
    assert gate.start() < block.index("ssh -i "), "검사가 ssh 호출보다 뒤에 있다"


@pytest.mark.parametrize("job", SSH_JOBS)
def test_the_failure_path_prints_no_secret(job: str):
    """멈출 때 찍는 메시지에 시크릿 값이 실리지 않는다 — 이름만 적는다."""
    block = _job(job)
    step = block.split("- name: SSH 설정", 1)[1].split("- name:", 1)[0]
    echoes = [line.strip() for line in step.splitlines() if "echo" in line]
    assert echoes, "실패 메시지가 없다"
    for line in echoes:
        assert "secrets." not in line and "${OCI_" not in line and "$OCI_" not in line, line


def test_known_hosts_lines_are_in_a_shape_ssh_can_read():
    """항목은 `<호스트> ssh-ed25519 <키>` 모양이다 — 해시하지 않고, 유형은 ed25519 하나."""
    for line in _key_lines():
        fields = line.split()
        assert len(fields) >= 3, f"필드가 셋 미만이다: {line!r}"
        assert not fields[0].startswith("|1|"), f"해시된 호스트는 리뷰에서 대조할 수 없다: {line!r}"
        assert fields[1] == "ssh-ed25519", f"키 유형이 ed25519가 아니다: {line!r}"


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen 없음")
def test_known_hosts_keys_decode_to_fingerprints():
    """`ssh-keygen -lf`가 모든 항목의 지문을 낸다 — 한 글자만 깨져도 여기서 실패한다."""
    if not _key_lines():
        pytest.skip("아직 항목이 없다 — 개수는 아래 검사가 본다")
    proc = subprocess.run(  # noqa: S603
        ["ssh-keygen", "-lf", str(KNOWN_HOSTS)],  # noqa: S607 - 파일을 읽어 지문만 계산한다
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr.strip()
    assert len(proc.stdout.strip().splitlines()) == len(_key_lines())


def test_known_hosts_pins_both_deploy_hosts():
    """db-01·app-01 **두 줄이 있어야 머지할 수 있다.**

    비어 있는 채 머지되면 머지 즉시 도는 배포가 `SSH 설정`에서 선다. 서비스는 살아
    있지만(이전 컨테이너가 남는다) 그 실패는 사람이 지문을 넣을 때까지 반복된다.
    지문을 넣는 절차는 `docs/OPERATIONS.md §4.7`이다.
    """
    hosts = {line.split()[0] for line in _key_lines()}
    assert len(hosts) >= 2, (
        f"`ops/host/known_hosts`에 고정된 호스트가 {len(hosts)}개다 — db-01·app-01 두 줄이 필요하다"
    )
