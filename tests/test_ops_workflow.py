"""운영 워크플로(`ops.yml`)가 서버에서 무엇을 하고 무엇을 하지 않는지 고정한다
(`#788` · `#789` · `#1635`).

## 왜 파일 검사인가

이 워크플로는 실행하면 **운영 서버**(db-01 · app-01)에서 백업·복구 교체·롤백을 한다. 재현하려고
돌리면 그것이 곧 운영 작업이다. 그래서 `test_deploy_remote_script_syntax.py`·
`test_deploy_freeze.py`와 같은 판단으로 파일에서 본다.

* 원격 스크립트가 셸 문법상 유효한가 — `deploy.yml`의 따옴표 한 개가 09-23 운영 배포를
  멈췄다(`#1794`).
* 되돌릴 수 없는 일에 걸린 잠금이 있는가 — `restore`의 `confirm` · 롤백 실습의 `trap` 복귀.
* 배포와 **같은 동시 실행 그룹**인가 — 배포 도중에 백업·교체가 끼면 무엇이 무엇을
  깨뜨렸는지 가릴 수 없다.
* 파괴적 명령이 없는가 — 볼륨을 지우는 길은 `deploy.yml`의 `force_db_init` 하나로 둔다.
* 호스트 밖 보관(`#788` 결정 ①)의 보존 기간.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
OPS = _ROOT / ".github" / "workflows" / "ops.yml"
DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"

_REMOTE = re.compile(r"<<'ENDSSH'[^\n]*\n(.*?)\n\s*ENDSSH", re.S)


def _workflow() -> dict:
    return yaml.safe_load(OPS.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["ops"]["steps"]


def _step(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"ops.yml에 「{name}」 단계가 없다")


def test_remote_scripts_parse() -> None:
    scripts = [body for s in _steps() if s.get("run") for body in _REMOTE.findall(s["run"])]
    # 가짜 통과를 막는다 — 블록을 하나도 못 찾으면 아래 반복이 공허하게 통과한다
    assert len(scripts) >= 9, f"원격 스크립트를 {len(scripts)}개만 찾았다"
    for body in scripts:
        done = subprocess.run(["bash", "-n"], input=body, text=True, capture_output=True)
        assert done.returncode == 0, done.stderr


def test_step_scripts_parse() -> None:
    for step in _steps():
        if step.get("run"):
            done = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
            assert done.returncode == 0, f"{step['name']}: {done.stderr}"


def test_restore_requires_confirm() -> None:
    script = _step("입력 검증")["run"]
    assert re.search(r'"\$\{TASK\}" = "restore" \] && \[ "\$\{CONFIRM\}" != "cii" \]', script)
    # 교체 명령도 운영 DB 이름을 명시하고, 앱을 멈췄다고 적는다(OPERATIONS §3.6.6)
    swap = _step("복구 교체 (db-01)")["run"]
    assert "--confirm cii --app-stopped" in swap
    # 교체가 실패하면 앱을 켜지 않는다
    assert "steps.swap.outcome == 'success'" in _step("앱 기동 · 헬스 (app-01)")["if"]


def test_rollback_drill_always_returns() -> None:
    script = _step("롤백 실습 (app-01)")["run"]
    assert "trap restore EXIT" in script
    assert 'wait_commit "${CURRENT_SHA}"' in script
    # 마이그레이션이 섞인 되돌림은 시작하지 않는다(OPERATIONS §3.6.3)
    assert "-- alembic/" in _step("롤백 실습 사전 검사")["run"]


def test_shares_concurrency_with_deploy() -> None:
    deploy = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    ops = _workflow()
    assert ops["concurrency"]["group"] == deploy["concurrency"]["group"]
    assert ops["concurrency"]["cancel-in-progress"] is False


def test_manual_trigger_only() -> None:
    # PyYAML은 키 `on`을 참(True)으로 읽는다
    triggers = _workflow().get("on") or _workflow().get(True)
    assert set(triggers) == {"workflow_dispatch"}


def test_backup_artifact_retention() -> None:
    upload = _step("덤프 올리기 (Actions 아티팩트 · 14일)")
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["retention-days"] == 14
    assert upload["with"]["if-no-files-found"] == "error"


def test_no_destructive_commands() -> None:
    text = OPS.read_text(encoding="utf-8")
    for pattern in (r"down\s+-v", r"force_db_init", r"volume\s+rm", r"volume\s+prune", r"deletedb"):
        assert not re.search(pattern, text), f"파괴적 명령 {pattern}이 ops.yml에 있다"
