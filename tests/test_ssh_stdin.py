"""실제 Bash→SSH argv/stdin→원격 Bash의 비밀 값 전송 계약 (#2117)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_HELPER = Path(__file__).resolve().parents[1] / "scripts" / "ssh_stdin.sh"
_VALUES = ("FAKE-2117-'\"$`\\ #\té\nline\n\n", "", "\n", "a\r\nb", "~fake", " lead trail ")


def _ssh_stub(tmp_path, *, status=0):
    shim = tmp_path / "ssh"
    record = tmp_path / "argv.json"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import json,sys,subprocess\n"
        f"open({str(record)!r},'w').write(json.dumps(sys.argv[1:]))\n"
        "payload=sys.stdin.buffer.read()\n"
        "result=subprocess.run(['bash','-s'],input=payload,capture_output=True)\n"
        "sys.stdout.buffer.write(result.stdout)\n"
        "sys.stderr.buffer.write(result.stderr)\n"
        f"sys.exit({status} or result.returncode)\n"
    )
    shim.chmod(0o700)
    return record


def _invoke(tmp_path, value, *, names="SECRET_ONE", trace=False, status=0):
    record = _ssh_stub(tmp_path, status=status)
    script = (
        f"source {shlex.quote(str(_HELPER))}\n"
        f"ssh_stdin fake@host {names} <<'ENDSSH'\n"
        "builtin printf '%s' \"${SECRET_ONE}\"\nENDSSH\n"
    )
    arguments = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]
    if trace:
        arguments.append("-x")
    result = subprocess.run(
        [*arguments, "-c", script],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "SECRET_ONE": value},
        capture_output=True,
        timeout=10,
    )
    return result, record


@pytest.mark.parametrize("value", _VALUES)
def test_secret_round_trips_only_over_stdin(tmp_path, value):
    result, record = _invoke(tmp_path, value)
    assert result.returncode == 0, result.stderr
    assert result.stdout == value.encode()
    argv = json.loads(record.read_text())
    assert argv[-3:] == ["fake@host", "bash", "-s"]
    assert all("SECRET_ONE=" not in argument for argument in argv)
    if len(value) > 3:
        assert all(value not in argument for argument in argv)


def test_shell_trace_does_not_print_secret(tmp_path):
    value = "FAKE-TRACE-2117-'$value\nend\n"
    result, _ = _invoke(tmp_path, value, trace=True)
    assert result.returncode == 0
    assert result.stdout == value.encode()
    assert b"FAKE-TRACE-2117" not in result.stderr


@pytest.mark.parametrize("names", ("MISSING_2117", "'BAD;touch injected'"))
def test_invalid_or_missing_variable_stops_before_ssh(tmp_path, names):
    result, record = _invoke(tmp_path, "FAKE-2117", names=names)
    assert result.returncode == 2
    assert not record.exists()
    assert b"FAKE-2117" not in result.stderr


def test_ssh_failure_is_not_reported_as_success(tmp_path):
    result, _ = _invoke(tmp_path, "FAKE-2117", status=23)
    assert result.returncode == 23


@pytest.mark.parametrize(
    ("workflow", "job"),
    (("deploy.yml", "deploy-db"), ("deploy.yml", "deploy-app"), ("ops.yml", "ops")),
)
def test_actual_workflow_call_sends_variable_values_over_stdin(tmp_path, workflow, job):
    """실제 호출문의 변수 누락/확장 오류를 검출한다. 원격의 작업 본문은 실행하지 않는다."""
    root = _HELPER.parents[1]
    jobs = yaml.safe_load((root / ".github" / "workflows" / workflow).read_text())["jobs"]
    steps = [step for step in jobs[job]["steps"] if "ssh_stdin " in step.get("run", "")]
    assert len(steps) == 1
    run = steps[0]["run"]
    assert "source scripts/ssh_stdin.sh" in run
    call = "ssh_stdin " + run.split("ssh_stdin ", 1)[1].split("<<'ENDSSH'", 1)[0]
    call = call.replace("${{ secrets.OCI_SSH_USER }}", "fake")
    call = call.replace("${{ secrets.OCI_DB_HOST }}", "host")
    call = call.replace("${{ secrets.OCI_APP_HOST }}", "host")
    names = shlex.split(call.replace("\\\n", " "))[2:]
    assert names
    values = {name: f"FAKE-2117-{name}-'\"$\nend\n" for name in names}
    record = _ssh_stub(tmp_path)
    # 원격 Bash의 변수들을 NUL로 구분한다. 비밀 값이 외부 명령 argv에 들어가지 않는다.
    script = (
        f"source {shlex.quote(str(_HELPER))}\n{call}<<'ENDSSH'\n"
        f"set -- {' '.join(names)}\n"
        'for variable in "$@"; do builtin printf "%s\\0" "${!variable}"; done\nENDSSH\n'
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=root,
        env={
            **os.environ,
            **values,
            "SSH_USER": "fake",
            "APP_HOST": "host",
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split(b"\0")[:-1] == [values[name].encode() for name in names]
    argv = json.loads(record.read_text())
    assert argv[-3:] == ["fake@host", "bash", "-s"]
    assert all(value not in " ".join(argv) for value in values.values())
