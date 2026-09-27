"""시연 동결 — 당일 구간과 ``DEPLOY_FROZEN``이면 push 자동 배포만 건너뛴다 (`#789` · 결정 E-2).

## 무엇을 막는가

동결을 공지로만 지키면 머지하는 사람 넷 중 한 사람이 몰랐을 때 깨지고, 깨진 사실은
시연장에서 화면이 다를 때에야 드러난다. 그래서 워크플로가 막는다 — 시연 당일
**2026-10-10 00:00 ~ 20:00 KST**(09-28 사용자 결정)는 사람이 켜지 않아도 걸린다.

## 어떻게 보는가

동결을 실제로 켜 보려면 운영 배포를 돌려야 한다. 대신 두 가지를 본다.

* **판정 셸을 그대로 실행한다** — `freeze` 잡의 ``run:`` 블록을 꺼내 `bash`로 돌리고,
  검사 전용 주입점 ``FREEZE_NOW``에 경계 시각을 넣는다. 구간 앞 · 시작 · 끝 직전 · 끝 ·
  뒤, 수동 스위치, 수동 실행 예외를 실제 출력(``$GITHUB_OUTPUT``)으로 확인한다.
* **잡의 연결을 파일에서 본다** — 입구 잡 둘이 판정 출력을 보는지, 백엔드 뒤 잡이
  `preflight`에 걸려 함께 건너뛰는지(`test_deploy_host_key_pinning.py`와 같은 판단).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"
OPERATIONS = _ROOT / "docs" / "OPERATIONS.md"

#: 입구 잡 둘의 조건 — 판정이 동결이 아니라고 했을 때만 돈다.
ENTRY_GUARD = "needs.freeze.outputs.frozen != 'true'"
#: 배포의 두 입구. 백엔드 쪽 나머지는 preflight에 needs로 걸린다.
ENTRY_JOBS = ("preflight", "deploy-frontend")

#: 09-28 사용자 결정 — 워크플로 상수와 같아야 한다(아래 검사가 대조한다).
START = "2026-10-10T00:00:00+09:00"
END = "2026-10-10T20:00:00+09:00"

_BASH = shutil.which("bash")


def _text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _job(name: str) -> str:
    """`jobs:` 아래 들여쓰기 2칸의 잡 블록 하나를 잘라 낸다."""
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", _text(), re.S | re.M)
    assert match, f"잡 `{name}`을 찾지 못했다"
    return match.group(1)


def _if(block: str) -> str | None:
    match = re.search(r"^    if: (.+)$", block, re.M)
    return match.group(1).strip() if match else None


def _judge_script() -> str:
    """`freeze` 잡 판정 단계의 ``run: |`` 블록 — 들여쓰기를 걷어 셸 원문으로."""
    block = _job("freeze")
    match = re.search(r"^        run: \|\n((?:^ {10}.*\n|^\s*\n)+)", block, re.M)
    assert match, "`freeze` 잡의 run 블록을 찾지 못했다"
    return "".join(line[10:] if line.strip() else "\n" for line in match.group(1).splitlines(True))


def _env_constant(name: str) -> str:
    match = re.search(rf'^          {name}: "([^"]+)"$', _job("freeze"), re.M)
    assert match, f"`freeze` 잡에 상수 {name}이 없다"
    return match.group(1)


def _epoch(iso: str, delta: int = 0) -> str:
    return str(int(datetime.fromisoformat(iso).timestamp()) + delta)


def _run(tmp_path: Path, *, event: str, now: str | None, switch: str = "") -> tuple[str, str]:
    """판정 셸을 실행해 ``(frozen 출력, 표준 출력)``을 돌려준다 — ``now=None``이면 주입 없음."""
    out = tmp_path / "github_output"
    out.write_text("", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "EVENT_NAME": event,
        "FROZEN_SWITCH": switch,
        "FREEZE_START": _env_constant("FREEZE_START"),
        "FREEZE_END": _env_constant("FREEZE_END"),
        "GITHUB_OUTPUT": str(out),
    }
    if now is not None:
        env["FREEZE_NOW"] = now
    result = subprocess.run(
        [_BASH, "-c", _judge_script()],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"출력이 한 줄이어야 한다: {lines!r}"
    return lines[0], result.stdout


requires_bash = pytest.mark.skipif(_BASH is None, reason="bash가 없다")


def test_window_constants_match_the_decision():
    """구간 상수가 09-28 결정(10/10 00:00 ~ 20:00 KST)과 같다 — 워크플로 파일에 상수로 둔다."""
    assert _env_constant("FREEZE_START") == START
    assert _env_constant("FREEZE_END") == END


@requires_bash
def test_judge_script_parses():
    """판정 셸이 문법상 읽힌다 — heredoc·따옴표 하나로 운영 배포가 멈춘 적이 있다."""
    subprocess.run([_BASH, "-n", "-c", _judge_script()], check=True)


@requires_bash
@pytest.mark.parametrize(
    ("label", "now", "frozen"),
    [
        ("구간 1초 전", _epoch(START, -1), "false"),
        ("구간 시작", _epoch(START), "true"),
        ("구간 끝 1초 전", _epoch(END, -1), "true"),
        ("구간 끝(포함하지 않는다)", _epoch(END), "false"),
        ("구간 하루 뒤", _epoch(END, 86400), "false"),
    ],
)
def test_push_is_frozen_only_inside_the_window(tmp_path, label, now, frozen):
    """push 자동 배포는 구간 안에서만 동결 — 끝 시각은 포함하지 않는다."""
    value, stdout = _run(tmp_path, event="push", now=now)
    assert value == f"frozen={frozen}", label
    assert ("::notice::" in stdout) is (frozen == "true"), label


@requires_bash
def test_real_clock_path_runs_without_injection(tmp_path):
    """운영에서 도는 경로 — ``FREEZE_NOW`` 없이 ``date -u``로 판정해도 죽지 않고 한 줄을 낸다.

    주입점만 검사하면 ``${FREEZE_NOW:-…}``를 ``${FREEZE_NOW}``로 「정리」했을 때
    ``set -u``가 운영에서만 죽는다. 오늘 날짜에 묶이지 않게 값은 둘 중 하나로만 본다.
    """
    value, _ = _run(tmp_path, event="push", now=None)
    assert value in {"frozen=true", "frozen=false"}


@requires_bash
def test_manual_switch_freezes_pushes_outside_the_window(tmp_path):
    """구간 밖에서도 ``DEPLOY_FROZEN == 'true'``면 push를 건너뛴다 — 정확히 'true'만."""
    outside = _epoch(START, -86400)
    assert _run(tmp_path, event="push", now=outside, switch="true")[0] == "frozen=true"
    for loose in ("True", "1", "false", ""):
        assert _run(tmp_path, event="push", now=outside, switch=loose)[0] == "frozen=false"


@requires_bash
@pytest.mark.parametrize("switch", ["", "true"])
def test_manual_dispatch_is_never_frozen(tmp_path, switch):
    """수동 실행(예외 배포)은 구간 안이든 스위치가 켜져 있든 돈다."""
    inside = _epoch(START, 3600)
    value, stdout = _run(tmp_path, event="workflow_dispatch", now=inside, switch=switch)
    assert value == "frozen=false"
    assert "::notice::" not in stdout
    assert "workflow_dispatch:" in _text()


@pytest.mark.parametrize("job", ENTRY_JOBS)
def test_entry_jobs_follow_the_judgement(job: str):
    """배포 입구 둘이 판정 잡에 걸려 있고 그 출력으로만 건너뛴다."""
    block = _job(job)
    assert re.search(r"^    needs: freeze$", block, re.M)
    assert _if(block) == ENTRY_GUARD


def test_judgement_runs_on_every_trigger():
    """판정 잡 자체에는 조건이 없다 — 수동 실행에서도 돌아 입구 잡이 건너뛰지 않게 한다."""
    block = _job("freeze")
    assert _if(block) is None
    assert "frozen: ${{ steps.judge.outputs.frozen }}" in block
    assert "timeout-minutes:" in block
    assert "vars.DEPLOY_FROZEN" in block


def test_backend_jobs_hang_off_preflight():
    """build · deploy-db · deploy-app은 preflight를 거쳐야 돈다 — 동결을 물려받는다."""
    assert re.search(r"^    needs: preflight$", _job("build"), re.M)
    assert re.search(r"^    needs: build$", _job("deploy-db"), re.M)
    assert re.search(r"^    needs: \[build, deploy-db\]$", _job("deploy-app"), re.M)


def test_old_variable_only_guard_is_gone():
    """변수만 보던 종전 조건·잡이 남지 않는다 — 두 판정이 갈리면 어느 쪽이 이기는지 모른다."""
    text = _text()
    assert "\n  frozen:\n" not in text
    assert "github.event_name != 'push' || vars.DEPLOY_FROZEN != 'true'" not in text


def test_operations_documents_the_window_and_switch():
    """구간 · 켜고 끄는 자리 · 예외 배포 방법이 운영 문서에 있다."""
    text = OPERATIONS.read_text(encoding="utf-8")
    assert "#### 3.1.1 시연 동결" in text
    assert "2026-10-10(토) 00:00 ~ 20:00 KST" in text
    assert "`DEPLOY_FROZEN` = `true`" in text
    assert "Run workflow" in text
