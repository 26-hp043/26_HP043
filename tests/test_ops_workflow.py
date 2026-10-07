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


def test_purge_does_not_chain_to_other_tasks() -> None:
    """`purge`는 다른 작업에 이어 붙지 않는다 — 단독 수동 작업이다 (`#2116`).

    백업이 수동이라 `backup`·주기 실행에 얹으면 백업 없는 삭제가 생기거나 지우는 작업이 묻지도
    않고 돈다. 스크립트를 부르는 단계는 `purge`로만 켜지고, 다른 단계의 조건에 `purge`가 끼지
    않는다.
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


def test_inspect_shows_last_expired_purge_row() -> None:
    """`inspect`가 `audit_log`의 마지막 `EXPIRED_PURGE` 행을 보여 준다 (`#2116`).

    스크립트는 실제로 지웠을 때만 감사 행을 남긴다(`PURGE_ACTION`). 그 행이 「마지막으로 언제
    무엇을 지웠나」의 유일한 기록이라 점검에서 볼 수 있어야 한다. 값은 코드와 같은 문자열이어야
    한다 — 어긋나면 이 단계가 조용히 「기록 없음」을 찍는다.
    """
    source = (_ROOT / "scripts" / "purge_expired.py").read_text(encoding="utf-8")
    found = re.search(r'^PURGE_ACTION = "([A-Z_]+)"', source, re.M)
    assert found, "purge_expired.py에서 PURGE_ACTION을 읽지 못했다"
    action = found.group(1)

    step = _step("마지막 만료 행 정리 (db-01)")
    assert step["if"] == "inputs.task == 'inspect'"
    run = step["run"]
    assert f"'{action}'" in run
    # 가장 최근 한 줄 — 시각 내림차순 하나
    assert 'ORDER BY \\"timestamp\\" DESC LIMIT 1' in run
    # 0건과 못 읽은 것을 가른다
    assert "기록 없음" in run
    # 공개 Actions 로그 — 사용자·IP 열은 고르지 않는다(감사 행에는 표별 행 수·실패·유예·시각뿐)
    assert "user_id" not in run and "ip_address" not in run


def test_no_destructive_commands() -> None:
    text = OPS.read_text(encoding="utf-8")
    for pattern in (r"down\s+-v", r"force_db_init", r"volume\s+rm", r"volume\s+prune", r"deletedb"):
        assert not re.search(pattern, text), f"파괴적 명령 {pattern}이 ops.yml에 있다"
