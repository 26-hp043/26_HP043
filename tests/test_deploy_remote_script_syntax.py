"""배포 워크플로가 원격에 보내는 셸 스크립트의 문법을 검사한다 (`#1794`).

`deploy.yml`은 두 호스트에 `ssh … bash -s` 로 heredoc 본문을 보낸다. 그 본문은
**원격 bash가 읽는 스크립트**인데, 저장소 어느 검사도 그것을 셸로 읽어 보지 않았다.

2026-09-23에 `#1633`(PR `#1762`)이 넣은 한 줄에서 **닫는 큰따옴표가 빠졌다.**

    echo "[deploy] 실행 커밋 ${got}

열린 문자열이 세 줄 뒤의 `"` 까지 삼켜 파싱이 어긋났고, 한참 뒤 괄호가 있는 줄에서
`syntax error near unexpected token '('` 로 터졌다. **운영 배포가 멈췄다**(`deploy-db`
실패 → `deploy-app` skipped). `tests/test_deploy_sha_pinning.py`는 SHA 고정 패턴이
있는지만 보므로 잡지 못했다.

`bash -n` 은 실행하지 않고 문법만 본다 — 원격 명령이 돌지 않는다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"

#: `<<'ENDSSH'` 부터 그 짝인 `ENDSSH` 줄까지. YAML `run: |` 안이라 들여쓰기가 붙어 있다.
_OPEN = re.compile(r"<<'ENDSSH'\s*$")
_CLOSE = re.compile(r"^\s*ENDSSH\s*$")


def _remote_scripts() -> list[tuple[int, str]]:
    """heredoc 본문을 (시작 줄 번호, 본문) 으로 뽑는다."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    out: list[tuple[int, str]] = []
    start: int | None = None
    body: list[str] = []
    for i, line in enumerate(lines, start=1):
        if start is None:
            if _OPEN.search(line):
                start, body = i + 1, []
            continue
        if _CLOSE.match(line):
            # 공통 들여쓰기를 걷어낸다 — 원격 bash가 보는 것과 같게.
            indent = min(
                (len(b) - len(b.lstrip()) for b in body if b.strip()),
                default=0,
            )
            out.append((start, "\n".join(b[indent:] for b in body) + "\n"))
            start = None
            continue
        body.append(line)
    return out


def test_원격_스크립트를_두_개_찾는다() -> None:
    """블록이 사라지거나 이름이 바뀌면 이 검사가 조용히 통과하지 않게 한다."""
    scripts = _remote_scripts()
    assert len(scripts) == 2, f"ENDSSH 블록이 2개가 아니다: {len(scripts)}개"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash 없음")
def test_원격_스크립트의_셸_문법이_유효하다() -> None:
    for start, body in _remote_scripts():
        proc = subprocess.run(  # noqa: S603
            ["bash", "-n"],  # noqa: S607 - 문법 검사만, 실행하지 않는다
            input=body,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, (
            f"deploy.yml {start}행부터의 원격 스크립트에 셸 문법 오류가 있다.\n"
            f"{proc.stderr.strip()}"
        )


def test_따옴표가_짝을_이룬다() -> None:
    """`bash -n` 이 우연히 통과하는 경우까지 잡는다 — 한 줄 안에서 큰따옴표는 짝이다.

    여러 줄에 걸친 문자열을 쓰는 줄이 생기면 이 검사를 고쳐야 한다. 지금은 없다.
    """
    나쁜: list[str] = []
    for start, body in _remote_scripts():
        for offset, line in enumerate(body.splitlines()):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if line.count('"') % 2 == 1:
                나쁜.append(f"deploy.yml:{start + offset} {stripped}")
    assert not 나쁜, "큰따옴표가 홀수인 줄:\n" + "\n".join(나쁜)
