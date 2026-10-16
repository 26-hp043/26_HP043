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
* 지우는 작업의 기본값 — `purge`는 `confirm=cii`가 없으면 세기만 한다(`--dry-run` · `#2116`).
* 호스트 밖 보관(`#788` 결정 ① · 정정 A) — 저장소가 공개라 **암호화한 파일만** 올린다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
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


def test_backup_artifact_is_encrypted_only() -> None:
    """저장소가 **공개**라 아티팩트는 누구나 받는다 — 암호화한 파일만 올린다(`#788` 정정 결정 A)."""
    enc = _step("덤프 받기 · 암호화 (db-01 → 러너)")
    script = enc["run"]
    assert enc["env"]["PASSPHRASE"] == "${{ secrets.BACKUP_ARTIFACT_PASSPHRASE }}"
    # 암호가 없으면 받지도 올리지도 않는다
    no_pass = r'if \[ -z "\$\{PASSPHRASE\}" \]; then.*?encrypted=false.*?exit 0'
    assert re.search(no_pass, script, re.S)
    assert "openssl enc -aes-256-cbc -pbkdf2 -iter 200000" in script
    assert "-pass env:PASSPHRASE" in script  # 명령줄에 암호를 싣지 않는다(ps·로그에 안 보이게)
    assert 'rm -rf "${plain}"' in script  # 평문은 올리기 전에 지운다
    upload = _step("덤프 올리기 (암호화 파일만 · Actions 아티팩트 · 14일)")
    assert upload["if"] == "steps.encrypt.outputs.encrypted == 'true'"
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["path"].endswith("/*.enc")
    assert upload["with"]["retention-days"] == 14


def test_decrypt_hint_matches_encrypt_iterations() -> None:
    """푸는 법 안내가 암호화와 같은 `-iter`를 적는다 — 다르면 안내대로 풀어도 실패한다."""
    ops_text = OPS.read_text(encoding="utf-8")
    runbook = (_ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    enc_iters = set(re.findall(r"openssl enc -aes-256-cbc -pbkdf2 -iter (\d+)", ops_text))
    assert enc_iters == {"200000"}
    for text in (ops_text, runbook):
        hints = re.findall(r"openssl enc -d -aes-256-cbc -pbkdf2 -iter (\d+)", text)
        assert hints and set(hints) == enc_iters
        assert "openssl enc -d -aes-256-cbc -pbkdf2 -in" not in text


def test_restore_swaps_the_rehearsed_dump() -> None:
    """교체는 방금 뜨고 리허설한 **바로 그 파일**로 한다 — 최신 파일을 다시 고르지 않는다."""
    assert _step("복구 리허설 (db-01)")["env"]["RESTORE_DUMP"] == "${{ steps.backup.outputs.dump }}"
    swap = _step("복구 교체 (db-01)")
    assert swap["env"]["RESTORE_DUMP"] == "${{ steps.backup.outputs.dump }}"
    assert "ls -t" not in swap["run"]
    # dump 입력은 rehearse 전용
    assert '[ "${TASK}" != "rehearse" ]' in _step("입력 검증")["run"]


def test_app_start_task_and_pipefail() -> None:
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True)
    assert "app-start" in triggers["workflow_dispatch"]["inputs"]["task"]["options"]
    assert "inputs.task == 'app-start'" in _step("앱 기동 · 헬스 (app-01)")["if"]
    # `ssh … | tee`의 실패가 tee의 성공으로 덮이지 않게
    assert wf["jobs"]["ops"]["defaults"]["run"]["shell"] == "bash"


def test_bench_runs_engine_only_at_low_priority() -> None:
    """`bench`가 패키지 모듈로 엔진만 재고, 우선순위를 낮춰 서비스에 양보한다 (`#790`).

    운영 이미지에는 ``tests/``·pytest가 없다 — 그래서 ``cii_platform.calc.bench``를
    ``exec``로 부른다. DB에 행을 쓰는 `PERF-002`·`PERF-005`는 이 경로에 없다.
    """
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True)
    assert "bench" in triggers["workflow_dispatch"]["inputs"]["task"]["options"]
    step = _step("계산 엔진 벤치마크 (app-01)")
    assert step["if"] == "inputs.task == 'bench'"
    run = step["run"]
    assert "exec -T backend nice -n 10 python -m cii_platform.calc.bench </dev/null" in run
    assert "pytest" not in run and "scenario" not in run


def test_backup_reclaims_root_owned_dir() -> None:
    # 2026-09-26 첫 백업이 root 소유 backups/에 막혔다 — 덤프 전에 되돌려야 한다
    run = _step("백업 (db-01)")["run"]
    assert "sudo -n chown" in run
    assert run.index("[ ! -w backups ]") < run.index("sudo -n chown")
    assert run.index("sudo -n chown") < run.index("db_backup.py backup")


def test_inspect_shows_db_container_health() -> None:
    # #1634 — db 헬스체크 상태는 compose ps의 STATUS 열에만 보인다
    assert "docker-compose.prod.db.yml ps" in _step("상태 보기 (db-01)")["run"]


def test_chat_audit_prints_no_content_or_identity() -> None:
    # 공개 저장소의 Actions 로그 — 본문 표(chat_message)·사용자·IP를 고르지 않고 해시는 지운다
    step = _step("챗봇 감사 흐름 (db-01)")
    assert step["if"] == "inputs.task == 'inspect'"
    run = step["run"]
    assert "chat_message" not in run
    assert "user_id" not in run and "ip_address" not in run
    assert "sha256" in run and "re.sub" in run


def test_inspect_picks_only_discard_lines_from_app_logs() -> None:
    """점검이 챗봇 폐기 줄과 공급자 실패 줄만 고른다 (`#1985` · `#2289`).

    컨테이너 로그를 통째로 내보내면 **질문·답이 공개 저장소의 Actions 로그로 나간다**
    (`PRD §16.3.1`). 고정 접두어로 그 줄만 고르고, 창을 최근 구간으로 좁히고, 줄 수도
    묶는다. 접두어가 코드와 같은지는 ``tests/test_chat_discard_log.py``가 본다.
    """
    step = _step("챗봇 폐기·공급자 실패 (app-01)")
    assert step["if"] == "inputs.task == 'inspect'"
    run = step["run"]
    # 통째로 내보내지 않는다 — grep으로 좁힌다.
    assert "grep -F" in run
    assert "--since" in run and "--no-color" in run
    assert "tail -" in run
    # 0건과 「못 찾았다」를 가른다.
    assert "폐기·공급자 실패 기록 없음" in run


def _run_purge_step(tmp_path: Path, confirm: str) -> list[str]:
    """`purge` 단계의 run 스크립트를 **실제로 실행**해, 서버에서 불린 인자를 돌려준다.

    `ssh`는 마지막 인자(원격 명령)를 stdin 스크립트와 함께 로컬 bash로 실행하는 스텁이고,
    `python3`는 받은 인자를 파일에 적는 스텁이다 — 운영 서버를 건드리지 않는다.
    """
    bin_dir, log = tmp_path / "bin", tmp_path / "calls.log"
    (tmp_path / "home" / "bluelog").mkdir(parents=True)
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text('#!/bin/bash\neval "${@: -1}"\n', encoding="utf-8")
    (bin_dir / "python3").write_text(
        f'#!/bin/bash\necho "args=$* svc=$DB_SERVICE" >> {log}\n', encoding="utf-8"
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "SSH_USER": "u",
        "DB_HOST": "h",
        "CONFIRM": confirm,
    }
    script = _step("만료 행 정리 (db-01)")["run"]
    subprocess.run(["bash", "-eo", "pipefail", "-c", script], env=env, check=True, text=True,
                   capture_output=True)  # fmt: skip
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_purge_defaults_to_dry_run_and_deletes_only_with_confirm() -> None:
    """`purge`는 기본이 세기만 하는 `--dry-run`이고 `confirm=cii`일 때만 지운다 (`#2116`).

    지운 행은 되돌릴 수 없다. 입력을 비우거나 빠뜨려도, 서버로 가는 값이 깨져도 지우는 쪽으로
    서지 않아야 한다 — 그래서 **러너와 서버 양쪽이** 기본을 `--dry-run`으로 둔다.
    """
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True)
    assert "purge" in triggers["workflow_dispatch"]["inputs"]["task"]["options"]

    # 입력 검증 — 비우면 세기만, `cii`면 지움, 그 밖의 값은 오타로 보고 거절한다
    validate = _step("입력 검증")["run"]
    assert re.search(
        r'"\$\{TASK\}" = "purge" \] && \[ -n "\$\{CONFIRM\}" \] && \[ "\$\{CONFIRM\}" != "cii" \]',
        validate,
    )

    step = _step("만료 행 정리 (db-01)")
    assert step["if"] == "inputs.task == 'purge'"
    run = step["run"]
    # 러너 쪽 — `confirm`이 정확히 `cii`일 때만 1을 서버로 보낸다
    assert re.search(r'if \[ "\$\{CONFIRM\}" = "cii" \]; then real=1; else real=0; fi', run)
    assert "PURGE_REAL='${real}'" in run
    # 서버 쪽 — `1`일 때만 지우고, 그 밖에는 `--dry-run`이다(값이 비거나 깨져도 지우지 않는다)
    remote = _REMOTE.findall(run)
    assert len(remote) == 1
    body = remote[0]
    assert re.search(r'if \[ "\$\{PURGE_REAL\}" = "1" \]; then', body)
    # `scripts/purge_expired.py`는 인자가 없으면 지운다 — 인자 없는 호출은 `then` 가지에만 있다
    then_branch, _, else_branch = body.partition("else")
    assert "python3 scripts/purge_expired.py </dev/null" in then_branch
    assert "python3 scripts/purge_expired.py --dry-run </dev/null" in else_branch
    assert "purge_expired.py </dev/null" not in else_branch
    # OCI 배포 값 — README 「만료 행 정리」의 OCI 주의와 같다
    assert 'COMPOSE="docker compose -f docker-compose.prod.db.yml"' in body
    assert "DB_SERVICE=cubrid" in body


@pytest.mark.parametrize("confirm", ["", "CII", "cii ", " cii", "x", "yes"])
def test_purge_runs_dry_unless_confirm_is_exactly_cii(tmp_path: Path, confirm: str) -> None:
    """문자열이 아니라 **실행**으로 본다 — `cii`가 아닌 값은 지우는 호출을 만들지 않는다 (`#2116`).

    러너 단계를 가짜 `ssh`·`python3` 위에서 돌려 서버에서 불린 인자를 받는다. 입력 검증이
    통과시킨 값(`""`)은 `--dry-run` 한 번만 부르고, 검증이 거절하는 값은 단계를 건너뛴다 — 그
    경우에도 단계만 따로 돌리면 `--dry-run`이다(검증이 빠져도 지우지 않는다).
    """
    calls = _run_purge_step(tmp_path, confirm)
    assert calls == ["args=scripts/purge_expired.py --dry-run svc=cubrid"]


def test_purge_deletes_with_no_flag_only_for_cii(tmp_path: Path) -> None:
    """`confirm=cii`일 때만 인자 없는 호출(= 지움) 한 번이 나간다 (`#2116`)."""
    assert _run_purge_step(tmp_path, "cii") == ["args=scripts/purge_expired.py svc=cubrid"]


@pytest.mark.parametrize("confirm", ["", "cii", "CII", "cii ", "x"])
def test_purge_confirm_validation_rejects_only_odd_values(tmp_path: Path, confirm: str) -> None:
    """입력 검증 — 비움과 `cii`는 통과, 그 밖의 값은 오타로 보고 거절한다 (`#2116`)."""
    env = {**os.environ, "TASK": "purge", "CONFIRM": confirm, "IMAGE_SHA": "", "DUMP": ""}
    done = subprocess.run(["bash", "-eo", "pipefail", "-c", _step("입력 검증")["run"]],
                          env=env, text=True, capture_output=True)  # fmt: skip
    assert (done.returncode == 0) == (confirm in ("", "cii"))


def test_purge_does_not_chain_to_other_tasks() -> None:
    """`purge`는 다른 작업에 이어 붙지 않는다 — 단독 수동 작업이다 (`#2116`).

    ⑴ 주기 실행은 백업이 수동인 채 삭제만 자동이 되어 「백업 → 삭제」 순서를 깬다. ⑵ `backup`에
    이어 붙이면 백업만 뜨고 싶을 때도 지워진다. 스크립트를 부르는 단계는 `purge`로만 켜지고,
    다른 단계의 조건에 `purge`가 끼지 않는다.
    """
    # 가짜 통과를 막는다 — 스크립트를 부르는 단계가 없으면 아래 반복이 공허하게 통과한다
    assert any("purge_expired.py" in (s.get("run") or "") for s in _steps())
    for step in _steps():
        condition = str(step.get("if", ""))
        run = step.get("run", "") or ""
        if "purge_expired.py" in run:
            assert condition == "inputs.task == 'purge'", step["name"]
        elif "'purge'" in condition:
            raise AssertionError(f"「{step['name']}」 조건에 purge가 끼어 있다")


def test_inspect_shows_last_expired_purge_row(tmp_path: Path) -> None:
    """`inspect`가 `audit_log`의 마지막 `EXPIRED_PURGE` 행을 보여 준다 (`#2116`).

    감사 행은 dry-run이 아닌 실행에서 감사 INSERT가 성공했을 때 남는다 — 그래서 행이 없다는 것은
    「한 번도 지우지 않았다」가 아니다(DELETE 출력을 못 읽었거나 INSERT가 실패한 실행은 지웠는데도
    행이 없다). 점검 단계의 Python을 **실제로 실행해** 성질을 본다 — 액션 이름은 코드의
    `PURGE_ACTION`과 같고, 가장 최근 한 줄만 묻고, 행이 있으면 그 행을 그대로 찍고, 행이 없으면
    다른 안내를 찍되 실패한 실행의 행방(Actions 실행 이력)을 말한다. 문구 원문이 아니라 성질이다.
    """
    source = (_ROOT / "scripts" / "purge_expired.py").read_text(encoding="utf-8")
    found = re.search(r'^PURGE_ACTION = "([A-Z_]+)"', source, re.M)
    assert found, "purge_expired.py에서 PURGE_ACTION을 읽지 못했다"

    step = _step("마지막 만료 행 정리 (db-01)")
    assert step["if"] == "inputs.task == 'inspect'"
    run = step["run"]
    # 공개 Actions 로그 — 사용자·IP 열은 고르지 않는다(감사 행에는 표별 행 수·실패·유예·시각뿐)
    assert "user_id" not in run and "ip_address" not in run

    inner = re.search(r"<<'PY'\n(.*?)\nPY\b", _REMOTE.findall(run)[0], re.S)
    assert inner, "점검 단계의 Python 본문을 찾지 못했다"
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "db_backup.py").write_text(
        "import os\n"
        "class Db:\n"
        "    def __init__(self, compose, service=None): pass\n"
        "    def query(self, sql):\n"
        "        open(os.environ['SQL_OUT'], 'w').write(sql)\n"
        "        return os.environ['ROWS']\n",
        encoding="utf-8",
    )
    env = {"COMPOSE": "docker compose", "SQL_OUT": str(tmp_path / "sql.txt")}

    def shown(rows: str) -> str:
        done = subprocess.run(
            [sys.executable, "-I", "-c", inner.group(1)],
            cwd=tmp_path, env={**env, "ROWS": rows}, text=True, capture_output=True, check=True,
        )  # fmt: skip
        return done.stdout.strip()

    row = "2026-10-07 03:47:00\t{counts}"
    assert shown(row) == row
    empty = shown("")
    assert empty and empty != row and "Actions" in empty
    sql = (tmp_path / "sql.txt").read_text(encoding="utf-8")
    assert f"'{found.group(1)}'" in sql and "DESC LIMIT 1" in sql


def test_no_destructive_commands() -> None:
    text = OPS.read_text(encoding="utf-8")
    for pattern in (r"down\s+-v", r"force_db_init", r"volume\s+rm", r"volume\s+prune", r"deletedb"):
        assert not re.search(pattern, text), f"파괴적 명령 {pattern}이 ops.yml에 있다"


# ---------------------------------------------------------------------------
# recalc-preview · recalc-apply — 저장 연간 실행의 낡음 표시 소급 (#2373)
# ---------------------------------------------------------------------------

_RECALC_STEPS = {
    "재계산 미리 보기 (app-01)": "inputs.task == 'recalc-preview'",
    "재계산 승인 목록 받기 (미리 보기 아티팩트 → 러너)": "inputs.task == 'recalc-apply'",
    "재계산 적용 (app-01)": "inputs.task == 'recalc-apply'",
}

#: 공개 Actions 로그에 나가면 안 되는 값 — 가짜 보고 JSON에 심는다.
_SECRET_VESSEL = "비밀호"
_SECRET_OTHER = "목록밖호"
_SECRET_NUMBER = "98765.4321"


def _recalc_report(*runs: tuple[str, str, str], mode: str = "dry-run", marked: int = 0) -> str:
    counts = {"TARGET": 0, "ALREADY_MARKED": 0, "CURRENT": 0, "UNCOMPARABLE": 0}
    for _, status, _ in runs:
        counts[status] += 1
    return json.dumps(
        {
            "format_version": 1,
            "generated_at": "2026-10-16T00:00:00+00:00",
            "mode": mode,
            "marked": marked,
            "counts": counts,
            "runs": [
                {
                    "simulation_id": sim,
                    "calculation_run_id": f"c-{sim}",
                    "vessel": vessel,
                    "status": status,
                    "differences": [f"항차 V1 planned_distance_nm: 1 → {_SECRET_NUMBER}"],
                }
                for sim, status, vessel in runs
            ],
        },
        ensure_ascii=False,
    )


def test_recalc_tasks_are_wired_to_their_own_steps() -> None:
    """두 작업이 선택지에 있고, 단계는 **정확히 그 작업**으로만 켜진다 (`#2373`)."""
    wf = _workflow()
    inputs = (wf.get("on") or wf.get(True))["workflow_dispatch"]["inputs"]
    assert {"recalc-preview", "recalc-apply"} <= set(inputs["task"]["options"])
    assert inputs["preview_run"]["default"] == ""
    for name, condition in _RECALC_STEPS.items():
        assert _step(name)["if"] == condition, name
    # 도구를 부르는 단계는 위 둘뿐이고, 다른 작업의 조건에 재계산이 끼지 않는다
    for step in _steps():
        run, condition = step.get("run") or "", str(step.get("if", ""))
        if "annual_needs_recalc" in run:
            assert step["name"] in _RECALC_STEPS, step["name"]
        elif "recalc" in condition:
            uploads = step.get("uses", "").startswith("actions/upload-artifact@")
            assert step["name"] in _RECALC_STEPS or uploads, step["name"]
    # 다른 실행의 아티팩트를 받는 데 필요한 권한 — 새 액션 핀 없이 `gh run download`
    assert wf["permissions"]["actions"] == "read"
    assert "gh run download" in _step("재계산 승인 목록 받기 (미리 보기 아티팩트 → 러너)")["run"]


def test_recalc_results_are_uploaded_encrypted_only() -> None:
    """선박명·운항 수치가 담긴 보고·복구 자료는 **암호화한 파일만** 올린다 (공개 저장소)."""
    backup_pin = _step("덤프 올리기 (암호화 파일만 · Actions 아티팩트 · 14일)")["uses"]
    uploads = {
        "재계산 미리 보기 올리기 (암호화 파일만 · Actions 아티팩트 · 14일)": (
            "steps.recalc_preview.outputs.encrypted == 'true'",
            "recalc-preview-${{ github.run_id }}",
        ),
        "재계산 적용 결과 올리기 (암호화 파일만 · Actions 아티팩트 · 14일)": (
            "always() && steps.recalc_apply.outputs.encrypted == 'true'",
            "recalc-apply-${{ github.run_id }}",
        ),
    }
    for name, (condition, artifact) in uploads.items():
        step = _step(name)
        assert step["if"] == condition
        assert step["uses"] == backup_pin  # 새 핀을 늘리지 않는다
        assert step["with"]["name"] == artifact
        assert step["with"]["path"].endswith("/*.enc")
        assert step["with"]["retention-days"] == 14
    # 평문을 올리는 단계가 없다 — 업로드는 위 셋(덤프·미리 보기·적용)뿐이다
    paths = [s["with"]["path"] for s in _steps() if "upload-artifact" in s.get("uses", "")]
    assert len(paths) == 3 and all(p.endswith("/*.enc") for p in paths)
    for name in ("재계산 미리 보기 (app-01)", "재계산 적용 (app-01)"):
        step = _step(name)
        assert step["env"]["PASSPHRASE"] == "${{ secrets.BACKUP_ARTIFACT_PASSPHRASE }}"
        assert "openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt" in step["run"]
        assert "-pass env:PASSPHRASE" in step["run"]


def test_recalc_tool_stdout_never_reaches_the_log() -> None:
    """도구의 표준출력(표 · 선박명)은 버리고, 보고 JSON은 ssh 출력을 **파일로만** 받는다."""
    calls = fetches = 0
    for name in ("재계산 미리 보기 (app-01)", "재계산 적용 (app-01)"):
        run = _step(name)["run"].replace("\\\n", " ")
        for line in run.splitlines():
            if "cii_platform.maintenance.annual_needs_recalc" in line:
                calls += 1
                assert line.rstrip().endswith(">/dev/null"), line
                assert "--json -" not in line
            # 원격 heredoc 밖에서 결과를 꺼내는 줄 — ssh 출력이 파일로 간다
            if 'app "cat ' in line:
                fetches += 1
                assert re.search(r'> "\$\{plain\}/', line), line
    assert calls == 2 and fetches == 2
    # 미리 보기는 원격 heredoc 안에서 꺼낸다 — 그 ssh 호출의 출력 전체가 파일로 간다
    preview = _step("재계산 미리 보기 (app-01)")["run"]
    assert "bash -s <<'ENDSSH' > \"${plain}/recalc_preview.json\"" in preview


@pytest.mark.parametrize(
    ("task", "confirm", "preview_run", "ok"),
    [
        ("recalc-apply", "cii", "18234567890", True),
        ("recalc-apply", "", "18234567890", False),
        ("recalc-apply", "CII", "18234567890", False),
        ("recalc-apply", "cii", "", False),
        ("recalc-apply", "cii", "123abc", False),
        ("recalc-apply", "cii", "1; rm x", False),
        ("recalc-apply", "cii", "0123", False),
        ("recalc-preview", "", "", True),
        ("recalc-preview", "", "123", False),
        ("purge", "", "123", False),
    ],
)
def test_recalc_apply_validation(task: str, confirm: str, preview_run: str, ok: bool) -> None:
    """입력 검증을 **실행으로** 본다 (`#2373`).

    `recalc-apply`는 `confirm=cii`와 숫자 실행 번호가 둘 다 있어야 시작하고, `preview_run`은
    `recalc-apply` 밖에서 받지 않는다.
    """
    env = {**os.environ, "TASK": task, "CONFIRM": confirm, "PREVIEW_RUN": preview_run,
           "IMAGE_SHA": "", "DUMP": ""}  # fmt: skip
    done = subprocess.run(["bash", "-eo", "pipefail", "-c", _step("입력 검증")["run"]],
                          env=env, text=True, capture_output=True)  # fmt: skip
    assert (done.returncode == 0) == ok, done.stdout + done.stderr


def _recalc_sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """가짜 `ssh`·`gh` 위에서 재계산 단계를 돌릴 환경 — 운영 서버를 건드리지 않는다.

    `ssh`는 원격 명령 모양으로 갈라 ⑴ `bash -s`면 스크립트를 삼키고 `stdout` 파일을 내보내고
    ⑵ 승인 목록 넣기는 받은 바이트를 `pushed.json`에 적고 ⑶ `cat`은 가짜 결과를 내보내고
    ⑷ 지우기는 기록만 한다. `FAKE_NO_RECOVERY=1`이면 복구 자료 `cat`이 실패한다.
    `gh`는 `artifact/`의 파일을 `-D` 디렉터리로 옮긴다. `openssl`은 진짜를 부르되
    `FAKE_ENC_FAIL=1`이면 복구 자료 암호화만 실패한다.
    """
    fake, bin_dir = tmp_path / "fake", tmp_path / "bin"
    (fake / "artifact").mkdir(parents=True)
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text(
        "#!/bin/bash\n"
        'cmd="$*"\n'
        'case "$cmd" in\n'
        '  *"cat > /tmp/recalc_approved.json"*) cat > "$FAKE/pushed.json" ;;\n'
        '  *"cat /tmp/recalc_apply.json"*) cat "$FAKE/apply.json" ;;\n'
        '  *"cat /app/logs/recalc_recovery_"*) echo "$cmd" >> "$FAKE/recovery_cat.log";'
        ' [ -z "$FAKE_NO_RECOVERY" ] && cat "$FAKE/recovery.json" ;;\n'
        '  *"rm -f "*) echo "$cmd" >> "$FAKE/rm.log" ;;\n'
        '  *"bash -s") echo "$cmd" >> "$FAKE/remote_cmd.log"; cat >> "$FAKE/remote.sh";'
        ' if [ -f "$FAKE/stdout" ]; then cat "$FAKE/stdout"; fi;'
        ' exit "${FAKE_RC:-0}" ;;\n'
        '  *) echo "unexpected ssh: $cmd" >&2; exit 99 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        'echo "$*" >> "$FAKE/gh.log"\n'
        'while [ $# -gt 0 ]; do [ "$1" = "-D" ] && dest="$2"; shift; done\n'
        'cp "$FAKE"/artifact/* "$dest"/\n',
        encoding="utf-8",
    )
    real_openssl = shutil.which("openssl")
    assert real_openssl, "openssl이 없다"
    (bin_dir / "openssl").write_text(
        "#!/bin/bash\n"
        'case "$*" in *recalc_recovery.json*) [ -n "$FAKE_ENC_FAIL" ] && exit 7 ;; esac\n'
        f'exec {real_openssl} "$@"\n',
        encoding="utf-8",
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    (tmp_path / "runner").mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE": str(fake),
        "RUNNER_TEMP": str(tmp_path / "runner"),
        "GITHUB_OUTPUT": str(tmp_path / "github_output"),
        "SSH_USER": "u",
        "APP_HOST": "h",
        "GITHUB_RUN_ID": "987",
        "PASSPHRASE": "pass-for-test",
        "PREVIEW_RUN": "123",
        "GH_TOKEN": "x",
        "GITHUB_REPOSITORY": "o/r",
    }
    return fake, env


def _run_step(name: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-eo", "pipefail", "-c", _step(name)["run"]],
                          env=env, text=True, capture_output=True)  # fmt: skip


def _decrypt(path: Path, env: dict[str, str]) -> str:
    done = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
         "-pass", "env:PASSPHRASE", "-in", str(path)],
        env=env, capture_output=True, check=True,
    )  # fmt: skip
    return done.stdout.decode("utf-8")


def test_recalc_preview_to_apply_logs_only_counts(tmp_path: Path) -> None:
    """미리 보기 → 승인 목록 받기 → 적용을 가짜 서버 위에서 **실제로 돌린다** (`#2373`).

    ⑴ 로그(표준출력·표준오류)에 선박명·운항 수치가 없고 건수만 있다 ⑵ 올릴 파일은 암호화본이고
    같은 `-iter`로 풀린다 ⑶ 허락한 미리 보기의 **바이트 그대로**가 승인 목록으로 들어간다
    ⑷ 승인 목록 밖 대상의 건수가 로그에 나온다 ⑸ 평문과 컨테이너 `/tmp` 파일을 지운다.
    """
    fake, env = _recalc_sandbox(tmp_path)
    runner = tmp_path / "runner"
    preview = _recalc_report(("s1", "TARGET", _SECRET_VESSEL), ("s2", "CURRENT", _SECRET_VESSEL))
    (fake / "stdout").write_text(preview, encoding="utf-8")

    done = _run_step("재계산 미리 보기 (app-01)", env)
    assert done.returncode == 0, done.stderr
    log = done.stdout + done.stderr
    assert _SECRET_VESSEL not in log and _SECRET_NUMBER not in log
    assert '"TARGET": 1' in log and "marked=0" in log
    enc = runner / "recalc-preview" / "recalc_preview.json.enc"
    assert _decrypt(enc, env) == preview
    assert not (runner / "recalc-plain").exists()
    assert "encrypted=true" in (tmp_path / "github_output").read_text(encoding="utf-8")

    # 승인 목록 받기 — 미리 보기 실행의 아티팩트를 그 번호로 받는다
    (fake / "artifact" / enc.name).write_bytes(enc.read_bytes())
    (fake / "stdout").unlink()
    done = _run_step("재계산 승인 목록 받기 (미리 보기 아티팩트 → 러너)", env)
    assert done.returncode == 0, done.stderr
    assert _SECRET_VESSEL not in done.stdout + done.stderr
    gh_args = (fake / "gh.log").read_text(encoding="utf-8")
    assert gh_args.startswith("run download 123 ") and "-n recalc-preview-123" in gh_args

    # 적용 — 승인한 s1 + 승인 목록 밖 s3(지금 새로 대상)
    applied = _recalc_report(
        ("s1", "TARGET", _SECRET_VESSEL), ("s3", "TARGET", _SECRET_OTHER), mode="apply", marked=1
    )
    recovery = json.dumps({"calculation_run_ids": ["c-s1"], "runs": [{"vessel": _SECRET_VESSEL}]})
    (fake / "apply.json").write_text(applied, encoding="utf-8")
    (fake / "recovery.json").write_text(recovery, encoding="utf-8")
    done = _run_step("재계산 적용 (app-01)", env)
    assert done.returncode == 0, done.stderr
    log = done.stdout + done.stderr
    for secret in (_SECRET_VESSEL, _SECRET_OTHER, _SECRET_NUMBER, "c-s1"):
        assert secret not in log, secret
    assert "marked=1" in log
    assert re.search(r"밖 1건 .* 바뀜 0건", log)
    assert (fake / "pushed.json").read_text(encoding="utf-8") == preview
    remote = (fake / "remote.sh").read_text(encoding="utf-8")
    assert "--approved /tmp/recalc_approved.json" in remote
    # 복구 자료는 지속 볼륨 /app/logs에 실행 번호로 남긴다
    assert '--recovery-file "${RECOVERY}"' in remote
    remote_cmd = (fake / "remote_cmd.log").read_text(encoding="utf-8")
    assert "RECOVERY='/app/logs/recalc_recovery_987.json' bash -s" in remote_cmd
    assert "/app/logs/recalc_recovery_987.json" in (fake / "recovery_cat.log").read_text(
        encoding="utf-8"
    )
    out = runner / "recalc-apply"
    assert _decrypt(out / "recalc_apply.json.enc", env) == applied
    assert _decrypt(out / "recalc_recovery.json.enc", env) == recovery
    assert sorted(p.name for p in out.iterdir()) == [
        "recalc_apply.json.enc",
        "recalc_recovery.json.enc",
    ]
    assert not (runner / "recalc-plain").exists()
    removed = (fake / "rm.log").read_text(encoding="utf-8")
    assert "/tmp/recalc_approved.json /tmp/recalc_apply.json" in removed
    assert "recovery" not in removed  # 복구 자료는 워크플로가 지우지 않는다


def test_recalc_apply_failure_still_keeps_recovery_file(tmp_path: Path) -> None:
    """도구가 실패해도 먼저 남은 복구 자료는 받아 암호화해 두고, 단계는 실패로 끝난다 (`#2373`)."""
    fake, env = _recalc_sandbox(tmp_path)
    plain = tmp_path / "runner" / "recalc-plain"
    plain.mkdir()
    (plain / "recalc_approved.json").write_text(
        _recalc_report(("s1", "TARGET", "x")), encoding="utf-8"
    )
    (fake / "recovery.json").write_text('{"calculation_run_ids": ["c-s1"]}', encoding="utf-8")
    done = _run_step("재계산 적용 (app-01)", {**env, "FAKE_RC": "3"})
    assert done.returncode == 3
    out = tmp_path / "runner" / "recalc-apply"
    assert [p.name for p in out.iterdir()] == ["recalc_recovery.json.enc"]
    assert "encrypted=true" in (tmp_path / "github_output").read_text(encoding="utf-8")
    assert (fake / "rm.log").exists() and not plain.exists()


def _apply_sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    fake, env = _recalc_sandbox(tmp_path)
    plain = tmp_path / "runner" / "recalc-plain"
    plain.mkdir()
    (plain / "recalc_approved.json").write_text(
        _recalc_report(("s1", "TARGET", "x")), encoding="utf-8"
    )
    (fake / "apply.json").write_text(
        _recalc_report(("s1", "TARGET", "x"), mode="apply", marked=1), encoding="utf-8"
    )
    (fake / "recovery.json").write_text('{"calculation_run_ids": ["c-s1"]}', encoding="utf-8")
    return fake, env


def test_recalc_apply_fails_when_recovery_file_not_received(tmp_path: Path) -> None:
    """도구가 성공해도 복구 자료를 러너로 받지 못하면 단계가 **실패**한다 (`#2373` 리뷰 HIGH).

    받지 못한 복구 자료는 지우지 않는다 — 컨테이너 `/app/logs`(지속 볼륨)에 남아 사람이 꺼낸다.
    받은 결과 JSON은 그대로 암호화해 올린다.
    """
    fake, env = _apply_sandbox(tmp_path)
    done = _run_step("재계산 적용 (app-01)", {**env, "FAKE_NO_RECOVERY": "1"})
    assert done.returncode != 0
    assert "::error::" in done.stdout + done.stderr
    assert "/app/logs/recalc_recovery_987.json" in (fake / "recovery_cat.log").read_text(
        encoding="utf-8"
    )
    removed = (fake / "rm.log").read_text(encoding="utf-8")
    assert "recovery" not in removed and "/app/logs" not in removed
    out = tmp_path / "runner" / "recalc-apply"
    assert [p.name for p in out.iterdir()] == ["recalc_apply.json.enc"]
    assert "encrypted=true" in (tmp_path / "github_output").read_text(encoding="utf-8")


def test_recalc_apply_fails_after_partial_encryption(tmp_path: Path) -> None:
    """두 번째 암호화가 실패해도 이미 만든 `.enc`는 올릴 수 있게 표시하고 실패로 끝난다."""
    _, env = _apply_sandbox(tmp_path)
    done = _run_step("재계산 적용 (app-01)", {**env, "FAKE_ENC_FAIL": "1"})
    assert done.returncode == 7
    out = tmp_path / "runner" / "recalc-apply"
    assert [p.name for p in out.iterdir()] == ["recalc_apply.json.enc"]
    assert "encrypted=true" in (tmp_path / "github_output").read_text(encoding="utf-8")


def test_recalc_preview_refuses_without_passphrase(tmp_path: Path) -> None:
    """암호 시크릿이 없으면 서버에 가기 **전에** 실패한다.

    결과를 볼 길이 없는 실행을 남기지 않는다 (`#2373`).
    """
    fake, env = _recalc_sandbox(tmp_path)
    for name in ("재계산 미리 보기 (app-01)", "재계산 승인 목록 받기 (미리 보기 아티팩트 → 러너)"):
        done = _run_step(name, {**env, "PASSPHRASE": ""})
        assert done.returncode != 0, name
    assert not (fake / "remote.sh").exists() and not (fake / "gh.log").exists()
