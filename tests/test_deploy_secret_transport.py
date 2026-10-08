"""이슈 #1634 · 배포 시크릿이 원격 셸과 `.env`를 **바이트 그대로** 건너는지 고정한다.

## 무엇이 깨져 있었나

`deploy.yml`은 시크릿을 ssh 명령줄에 `'${SECRET}'`로 이어 붙이고, 원격이
`cat > .env <<EOF`로 **따옴표 없이** 적었다. 그래서 두 자리에서 값이 바뀌었다.

| 자리 | 값에 이것이 있으면 | 결과 |
|---|---|---|
| ssh 명령줄 | `'` | 인용이 끊겨 **배포가 선다** |
| compose가 읽는 `.env` | `$` · ` #` · 개행 | `${…}` 치환 · ` #` 뒤 잘림 — **조용히** 바뀐다 |

`OPERATIONS.md §5.2`가 `TOUR_ACCESS_CODE` 행에 「`'`가 들어가면 ssh 인용이 끊긴다」를
주의로 적어 두고 있었다(`#1495`). 문서로 막던 것을 절차로 막는다.

## 지금의 방식

러너가 `emit KEY "값"`으로 `.env`를 만들고(compose dotenv의 큰따옴표 규칙 — `\\` `"` `$`
개행 넷만 이스케이프) **base64로 싸서** 넘긴다. 원격은 `base64 -d > .env`로 풀 뿐이다.
base64 문자(`A-Za-z0-9+/=`)에는 인용 문자가 없어 ssh 인용이 끊기지 않는다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY = _ROOT / ".github" / "workflows" / "deploy.yml"

#: 가짜 값 — 실제 시크릿을 쓰지 않는다. 종전 방식에서 값을 바꾸거나 배포를 세우던 문자를
#: 전부 넣었다: 작은·큰따옴표, `$(…)`, `${…}`, ` #`(주석 시작), 역슬래시, 탭, 개행, 비ASCII.
_FAKE_VALUES: tuple[str, ...] = (
    'a$(echo X)b ${HOME} "q" \'s #c \\ back\tTAB é\nline2',
    "p@ss:w/rd?&=+%",
    "'",
    '"',
    "$",
    "\\",
    "trailing\\",
    " lead and trail ",
    "",
)


def _workflow() -> str:
    return _DEPLOY.read_text(encoding="utf-8")


def _emit_definitions() -> list[str]:
    return [
        line.strip() for line in _workflow().splitlines() if line.strip().startswith("emit() {")
    ]


def _run_emit(key: str, value: str) -> str:
    """`deploy.yml`에 적힌 `emit`을 **그대로** bash로 돌려 한 줄을 받는다."""
    definition = _emit_definitions()[0]
    script = f'{definition}\nemit "$1" "$2"\n'
    out = subprocess.run(
        ["bash", "-c", script, "emit", key, value],
        capture_output=True,
        check=True,
    )
    return out.stdout.decode("utf-8")


def _compose_unquote(line: str) -> tuple[str, str]:
    """compose dotenv의 큰따옴표 값을 원문으로 되돌린다 (`\\` `"` `$` `n`)."""
    m = re.fullmatch(r'([A-Z][A-Z0-9_]*)="(.*)"\n', line, re.S)
    assert m, f'emit 출력이 KEY="…" 한 줄이 아니다: {line!r}'
    out, it = [], iter(m.group(2))
    for ch in it:
        if ch == "\\":
            nxt = next(it)
            out.append({"n": "\n"}.get(nxt, nxt))
        else:
            assert ch not in '"$', f"이스케이프되지 않은 {ch!r}가 남았다: {line!r}"
            out.append(ch)
    return m.group(1), "".join(out)


def test_both_hosts_render_with_the_same_emit():
    """🔴 db-01과 app-01이 **같은 `emit`**으로 `.env`를 만든다 (#1634).

    한쪽만 고쳐지면 두 호스트가 같은 비밀번호를 다르게 받는다.
    """
    definitions = _emit_definitions()
    assert len(definitions) == 2, (
        f"deploy.yml에서 `emit` 정의를 {len(definitions)}개 찾았다 — db-01·app-01 두 곳이어야 한다."
    )
    assert definitions[0] == definitions[1], "db-01과 app-01의 `emit` 정의가 다르다."


@pytest.mark.parametrize("value", _FAKE_VALUES)
def test_emit_then_base64_round_trips_byte_exact(value: str):
    """🔴 가짜 값이 `emit` → base64 → 해독 → compose 규칙 역변환에서 **바이트 그대로** 돌아온다."""
    line = _run_emit("SECRET_UNDER_TEST", value)
    wire = base64.b64encode(line.encode("utf-8")).decode("ascii")
    assert re.fullmatch(r"[A-Za-z0-9+/=]*", wire), "base64 출력에 인용 문자가 섞였다."

    key, decoded = _compose_unquote(base64.b64decode(wire).decode("utf-8"))

    assert key == "SECRET_UNDER_TEST"
    assert decoded.encode("utf-8") == value.encode("utf-8")


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker가 없다")
def test_real_compose_reads_the_rendered_env_byte_exact(tmp_path: Path):
    """🔴 **실제 compose**가 `emit`으로 만든 `.env`를 읽어 컨테이너에 원문을 넘긴다.

    역변환을 우리가 짠 함수로만 확인하면 compose의 실제 규칙과 어긋나도 모른다.
    `docker compose config` 출력은 `$`를 `$$`로 다시 이스케이프하므로 대조에 쓰지 않고,
    컨테이너 안에서 값을 그대로 찍어 비교한다.
    """
    values = {f"V{i}": v for i, v in enumerate(_FAKE_VALUES)}
    compose = "services:\n  t:\n    image: busybox:latest\n    environment:\n" + "".join(
        f"      {k}: ${{{k}:-}}\n" for k in values
    )

    def run(cwd: Path, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", "compose", "run", "--rm", "-T", "t", "sh", "-c", command],
            cwd=cwd,
            capture_output=True,
            timeout=120,
        )

    # 환경 문제와 대상 실패를 가른다 (`#2143`). **`.env` 없이** 같은 compose 파일을 먼저
    # 돌려 본다 — 여기서 안 되면 데몬·이미지 쪽 사정이라 건너뛴다. 그 뒤 `.env`를 둔
    # 실행이 실패하면 그것은 `emit`이 만든 `.env`를 compose가 읽지 못한 것이므로 실패다.
    # 종전에는 두 경우를 가리지 않고 skip해, compose가 거부하는 줄을 `emit`이 내도 통과했다.
    bare = tmp_path / "emit-probe"
    bare.mkdir()
    (bare / "compose.yml").write_text(compose, encoding="utf-8")
    probe = run(bare, "true")
    if probe.returncode != 0:
        pytest.skip(
            f"compose 실행 불가(`.env` 없이도): {probe.stderr.decode('utf-8', 'replace')[:200]}"
        )

    rendered = tmp_path / "emit-env"
    rendered.mkdir()
    (rendered / "compose.yml").write_text(compose, encoding="utf-8")
    (rendered / ".env").write_text(
        "".join(_run_emit(k, v) for k, v in values.items()), encoding="utf-8"
    )
    for key, value in values.items():
        got = run(rendered, f'printf %s "${key}"')
        assert got.returncode == 0, (
            f"{key}: `.env` 없이는 되던 compose가 `emit`이 만든 `.env`에서 실패했다: "
            f"{got.stderr.decode('utf-8', 'replace')[:400]}"
        )
        assert got.stdout == value.encode("utf-8"), f"{key}: {got.stdout!r} != {value!r}"


def _password_lines() -> tuple[str, list[str]]:
    """러너가 `CUBRID_PASSWORD_B64`를 만드는 줄과, db-01 원격이 그것을 푸는 줄들."""
    lines = [line.strip() for line in _workflow().splitlines()]
    make = [line for line in lines if line.startswith('CUBRID_PASSWORD_B64="$(')]
    decode = [
        line
        for line in lines
        if line.startswith('CUBRID_PASSWORD="$(') or line.startswith('CUBRID_PASSWORD="${')
    ]
    assert len(make) == 1, f"러너의 `CUBRID_PASSWORD_B64` 할당을 {len(make)}곳 찾았다."
    return make[0], decode


@pytest.mark.parametrize("value", ["pw\n", "pw\n\n", "pw", "a b'c\"$d\\"])
def test_remote_password_keeps_trailing_newline(value: str):
    """🔴 db-01 원격이 푼 `CUBRID_PASSWORD`가 시크릿과 **바이트 그대로** 같다 — 끝 줄바꿈 포함.

    운영 `CUBRID_PASSWORD`는 끝에 줄바꿈이 1개 있고(`#1944` 진단 · 2026-09-26) DB 비밀번호도
    그 값이다. PR #1798은 원격에서 `"$(… | base64 -d)"`로 풀었는데 **명령 치환이 끝 줄바꿈을
    지워** 브로커 대기 60회가 전부 실패했다(#1876으로 되돌림). 러너의 할당과 원격의 해독을
    워크플로에 적힌 그대로 bash로 돌려 본다.
    """
    make, decode = _password_lines()
    assert decode, "원격의 `CUBRID_PASSWORD` 해독 줄이 없다."
    script = "\n".join([make, *decode, 'printf %s "${CUBRID_PASSWORD}"']) + "\n"
    got = subprocess.run(
        ["bash", "-c", script],
        env={"CUBRID_PASSWORD": value, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=True,
    )
    assert got.stdout == value.encode("utf-8"), f"{got.stdout!r} != {value!r}"


def test_ssh_command_line_carries_no_raw_secret():
    """실제 SSH argv에는 base64를 포함한 인증 값이 없어야 한다 (#2117)."""
    workflow = _workflow()
    assert workflow.count("ssh_stdin ") == 2
    helper = (_ROOT / "scripts" / "ssh_stdin.sh").read_text()
    assert '"$destination" bash -s' in helper
    assert re.search(r"printf .+%q", helper)
    for call in workflow.split("ssh_stdin ")[1:]:
        arguments = call.split("<<'ENDSSH'", 1)[0]
        assert "=" not in arguments
        assert "${CUBRID_PASSWORD_B64}" not in arguments
        assert "${DOTENV_B64}" not in arguments
        assert "${GHCR_TOKEN}" not in arguments
    assert "x-access-token" not in workflow
    assert 'csql -u dba -p "${CUBRID_PASSWORD}"' not in workflow


def test_every_base64_payload_is_masked():
    """🔴 러너가 만든 base64 값은 **전부** `::add-mask::`로 가린다.

    GitHub는 시크릿 원문만 자동으로 가리고 base64형은 모른다 — 가리지 않으면 로그에서
    누구나 풀 수 있다.
    """
    # 두 호스트가 같은 이름(`DOTENV_B64`)을 쓰므로 파일 전체에서 한 번 찾는 것으로는 한쪽이
    # 빠져도 모른다 — **할당마다** 바로 다음 줄이 그 값을 가리는지 본다.
    lines = _workflow().splitlines()
    assignments = [
        (i, m.group(1))
        for i, line in enumerate(lines)
        # 러너의 명령 치환 할당만 — ssh 문자열의 `DOTENV_B64='…'`는 할당이 아니라 전달이다.
        if (m := re.match(r'\s*([A-Z][A-Z0-9_]*_(?:B64|ENC))="\$\(', line))
    ]
    names = [name for _, name in assignments]
    assert names.count("DOTENV_B64") == 2, "두 호스트 각각에서 `DOTENV_B64`를 만들어야 한다."
    assert {"CUBRID_PASSWORD_B64", "CUBRID_PASSWORD_ENC"} <= set(names)
    unmasked = [
        f"{i + 1}행 {name}"
        for i, name in assignments
        if lines[i + 1].strip() != f'echo "::add-mask::${{{name}}}"'
    ]
    assert not unmasked, f"바로 뒤에 `::add-mask::`가 없는 값: {', '.join(unmasked)}"


def test_remote_writes_env_only_by_decoding_under_umask_077():
    """🔴 원격은 `.env`를 **해독해서만** 쓰고, 그 전에 `umask 077`을 건다.

    `cat > .env <<EOF`가 되살아나면 따옴표 없는 heredoc으로 돌아간 것이다.
    """
    lines = _workflow().splitlines()
    code = [line for line in lines if not line.lstrip().startswith("#")]
    assert not any("cat > .env" in line for line in code), "`cat > .env` heredoc이 남아 있다."
    writes = [i for i, line in enumerate(lines) if "base64 -d > .env" in line]
    assert len(writes) == 2, f"`base64 -d > .env`를 {len(writes)}곳 찾았다 — 두 호스트여야 한다."
    for i in writes:
        assert lines[i - 1].strip() == "umask 077", f"{i + 1}행 앞에 `umask 077`이 없다."


def test_no_shell_tracing_that_would_print_secrets():
    """🔴 `set -x`가 없다 — 켜지면 해독한 값과 `.env` 내용이 로그에 찍힌다."""
    assert not re.search(r"^\s*set -[a-z]*x", _workflow(), re.M)
