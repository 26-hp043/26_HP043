"""시연 기동 스크립트의 계약 (#637 · #616).

**CI가 이 스크립트를 실행하지 않는다.** `#616`이 그 대가를 보여 줬다 — `mktemp -t`의
템플릿 오류가 저장소에 들어와 있었고, 시연 당일에 처음 드러날 뻔했다.

전부를 돌릴 수는 없다(Docker·DB·백엔드가 필요하다). 대신 **실행 환경 없이 확인할 수
있는 것**을 잠근다.

* **문법** — `bash -n`. `#616`의 `mktemp` 오류는 문법이 아니라 런타임이었지만,
  문법 오류는 더 싸게 잡을 수 있다.
* **JSON 값 추출** — `#637`이 파이썬 파싱을 `sed`로 바꿨다. 그 한 줄이 이 스크립트에서
  가장 깨지기 쉬운 곳이라 **스크립트에서 그 줄을 그대로 꺼내** 검증한다.
* **`.venv` 가드가 `--check`를 막지 않는 것** — `#637`의 본체다.

케이스: 없음 (스크립트 계약이라 `TEST_PLAN §2`~`§7`의 케이스 체계 밖이다)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "demo_up.sh"


def test_script_is_syntactically_valid():
    """`bash -n`이 통과한다."""
    done = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr


def _field_line() -> str:
    """스크립트에서 ``_field`` 정의 줄을 그대로 꺼낸다.

    테스트에 같은 로직을 다시 적으면 **스크립트가 바뀌어도 테스트는 통과한다.**
    """
    for line in _SCRIPT.read_text(encoding="utf-8").splitlines():
        if line.startswith("_field()"):
            return line
    raise AssertionError("_field 정의를 찾지 못했다 — 스크립트가 바뀌었는지 확인할 것")


def _extract(key: str, payload: str) -> str:
    done = subprocess.run(
        ["bash", "-c", f'{_field_line()}\n_field "$1" "$2"', "_", key, payload],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


_OK = (
    '{"data":{"attained_cii":"4.982400","estimated_rating":"C",'
    '"warnings":["REFERENCE_ONLY"]},"meta":{"request_id":"abc"}}'
)
_ERR = '{"error":{"code":"PARAMETER_ERROR","message":"해당 연도의 규정 파라미터가 없습니다."}}'


@pytest.mark.parametrize(
    ("key", "payload", "expected"),
    [
        ("attained_cii", _OK, "4.982400"),
        ("estimated_rating", _OK, "C"),
        ("code", _ERR, "PARAMETER_ERROR"),
        # 없는 키는 **빈 값**이다 — 지어내지 않는다. 호출부가 원문을 보여 준다.
        ("nope", _OK, ""),
        # 따옴표 없는 수치도 집는다.
        ("count", '{"data":{"count":42}}', "42"),
    ],
)
def test_field_extracts_the_value(key: str, payload: str, expected: str):
    """`#637`이 파이썬 대신 넣은 `sed` 추출이 값을 옳게 집는다."""
    assert _extract(key, payload) == expected


def test_field_does_not_need_python():
    """추출 줄이 파이썬을 부르지 않는다.

    종전에는 `"$VENV/python" -c "import sys,json;…"`이었고, 그래서 **Docker만 있는
    환경에서는 계산 경로 확인 자체가 불가능**했다.
    """
    line = _field_line()

    assert "python" not in line
    assert "jq" not in line, "jq는 설치돼 있지 않을 수 있다"


def test_step_six_does_not_call_python_at_all():
    """6단계 **전체**가 파이썬 없이 돈다.

    ``_field`` 정의만 보면 부족하다 — 정의는 그대로 두고 **호출부만 파이썬으로**
    되돌려도 통과한다. 실제로 이 테스트를 쓰기 전에 그 갈래를 놓쳤다.

    6단계는 `curl` 응답에서 값을 집는 것뿐이라 실행 환경이 필요 없다. 여기에
    ``$VENV``가 다시 들어오면 **Docker만 있는 환경에서 계산 경로 확인이 막힌다.**
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    step_six = text.split('step "6. 계산 경로 확인"', 1)[1]
    # 안내 블록(GUIDE) 앞까지만 본다.
    step_six = step_six.split("GUIDE", 1)[0]

    # **주석은 뺀다.** 이 절의 주석이 「종전에는 `$VENV/python`으로 파싱했다」를
    # 설명하고 있어, 그대로 세면 고친 상태에서도 걸린다.
    offenders = [
        line.strip()
        for line in step_six.splitlines()
        if "$VENV" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, f"6단계가 아직 .venv를 부른다: {offenders}"


def test_check_mode_is_not_blocked_by_missing_venv():
    """`--check`는 `.venv`가 없어도 막히지 않는다 — `#637`의 본체.

    가드가 **두 갈래**여야 한다. 하나로 두면 점검까지 함께 막힌다.
    """
    text = _SCRIPT.read_text(encoding="utf-8")

    assert 'if [ "$HAVE_VENV" = "0" ] && [ "$CHECK_ONLY" = "--check" ]; then' in text
    assert 'if [ "$HAVE_VENV" = "0" ] && [ "$CHECK_ONLY" != "--check" ]; then' in text


def test_startup_still_requires_venv():
    """**기동은 그대로 막는다.** 점검을 열었다고 기동까지 열면 4·5단계가 죽는다."""
    text = _SCRIPT.read_text(encoding="utf-8")
    guard = text.split('if [ "$HAVE_VENV" = "0" ] && [ "$CHECK_ONLY" != "--check" ]; then', 1)[1]
    body = guard.split("fi", 1)[0]

    assert "exit 1" in body
    # 안내는 그대로 남는다 (#477).
    assert "docker compose run --rm app alembic upgrade head" in body


def test_step_seven_checks_the_korean_font():
    """7단계가 리포트 PDF의 한글 폰트를 점검한다 (`#689`).

    컨테이너(`Dockerfile`)와 CI(`ci.yml`)에는 `fonts-nanum`이 들어 있으나, **이
    스크립트만 호스트 `.venv`로 uvicorn을 띄워** 그 방어를 우회한다. 폰트가 없으면
    오류 없이 한글만 tofu(□)가 되므로 **점검이 없으면 아무도 모른다.**
    """
    text = _SCRIPT.read_text(encoding="utf-8")

    assert 'step "7. 리포트 PDF 한글 폰트"' in text
    # 판정은 /health 필드로 한다 — 파이썬 없이 확인된다 (#637).
    assert "pdf_korean_font" in text
    # 원인만 말하고 끝내지 않는다 — 무엇을 하면 되는지까지 낸다.
    assert "apt-get install -y fonts-nanum" in text


def test_font_check_does_not_call_python():
    """7단계도 `.venv` 없이 돈다 — Docker만 있는 환경에서 점검이 막히지 않는다 (`#637`)."""
    text = _SCRIPT.read_text(encoding="utf-8")
    step_seven = text.split('step "7. 리포트 PDF 한글 폰트"', 1)[1].split("GUIDE", 1)[0]

    offenders = [
        line.strip()
        for line in step_seven.splitlines()
        if "$VENV" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, f"7단계가 .venv를 부른다: {offenders}"


def test_font_check_does_not_block_the_demo():
    """폰트가 없어도 **기동을 세우지 않는다** (`#689`).

    막히는 것은 PDF 내려받기 하나이고 DB·계산·화면은 전부 정상이다. 시연 전체를
    세우는 것이 그 하나보다 비싸다 — 안내만 내고 계속한다.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    step_seven = text.split('step "7. 리포트 PDF 한글 폰트"', 1)[1].split("GUIDE", 1)[0]

    assert "exit 1" not in step_seven


# --- 시연 계정 (#692) ---------------------------------------------------------


def test_step_four_d_checks_the_demo_account():
    """4d 단계가 시연 계정 유무를 본다 (`#692`).

    계정이 없는 상태는 **오류가 아니라 로그인 실패로만 드러난다.** 시연 도중에
    처음 알면 늦다 — `#587`이 선박 제원에 대해 같은 자리에서 하는 검사다.
    """
    text = _SCRIPT.read_text(encoding="utf-8")

    assert 'step "4d. 시연 계정"' in text
    # 없을 때 무엇을 하면 되는지까지 낸다.
    assert "cii_platform.db.demo_seed" in text


def test_account_check_does_not_call_python():
    """4d도 `.venv` 없이 돈다 — psql로 직접 묻는다 (`#637`)."""
    text = _SCRIPT.read_text(encoding="utf-8")
    step = text.split('step "4d. 시연 계정"', 1)[1].split('step "5.', 1)[0]

    offenders = [
        line.strip()
        for line in step.splitlines()
        if "$VENV" in line and not line.lstrip().startswith("#") and "printf" not in line
    ]
    assert not offenders, f"4d가 .venv를 부른다: {offenders}"


def test_account_check_does_not_block_the_demo():
    """계정이 없어도 기동을 세우지 않는다 — 나머지 화면은 그대로 볼 수 있다."""
    text = _SCRIPT.read_text(encoding="utf-8")
    step = text.split('step "4d. 시연 계정"', 1)[1].split('step "5.', 1)[0]

    assert "exit 1" not in step


def test_script_credentials_match_the_seed():
    """**스크립트에 적힌 계정 정보가 시드 상수와 같다** (`#692`).

    스크립트는 점검(4d)과 안내문 두 곳에 이메일을 적고, 안내문에는 비밀번호도
    적는다. 시드 상수가 바뀌었는데 여기가 안 바뀌면 **점검이 거짓말을 하고 안내문이
    안 되는 비밀번호를 알려 준다** — 둘 다 시연 자리에서 드러난다.

    상수를 셸에서 읽어 올 수단이 없으므로(스크립트는 파이썬을 부르지 않는다),
    어긋남을 여기서 잡는다.
    """
    from cii_platform.db.demo_seed import DEMO_USER_EMAIL, DEMO_USER_PASSWORD

    text = _SCRIPT.read_text(encoding="utf-8")

    assert DEMO_USER_EMAIL in text, (
        f"스크립트가 시드와 다른 이메일을 쓴다 — 상수는 {DEMO_USER_EMAIL!r}이다"
    )
    assert DEMO_USER_PASSWORD in text, (
        "안내문의 비밀번호가 시드 상수와 다르다 — 그대로 치면 로그인에 실패한다"
    )


def test_guide_tells_how_to_log_in():
    """안내문이 **로그인 화면으로 들어가는 법**을 알려 준다.

    종전 안내는 브라우저 콘솔에 `dev-login`을 붙여넣는 길만 적었다. 그것은
    로그인 화면을 통과하지 않으므로 ⑴ 로그인 화면 자체를 시연할 수 없고
    ⑵ 개발자가 아닌 팀원은 쓰기 어렵다 (`#692`).
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    guide = text.split("cat <<'GUIDE'", 1)[1]

    assert "로그인" in guide
    assert "이메일" in guide
    assert "비밀번호" in guide
    # 프로덕션에서는 없는 계정이라는 것도 함께 말한다.
    assert "APP_ENV=production" in guide


# --- .env 적재 (#693) ---------------------------------------------------------
#
# `docker-compose.yml`에 대해 `tests/test_compose_env_wiring.py`가 고정한 세 계약을
# **이 스크립트에도** 건다. 종전에는 세 기동 경로 중 compose와 `uvicorn --env-file`만
# `.env`를 읽고 **이 스크립트만 빠져 있었다** — 그래서 `.env`에 8/17부터 있던
# `MAIL_BACKEND=smtp`가 서버에 닿지 않아 인증 메일이 나가지 않았다.


def test_backend_is_started_with_the_env_file():
    """uvicorn 기동에 ``--env-file``이 붙는다 (`#693`).

    이것이 없으면 `.env`의 `MAIL_BACKEND`·`APP_PUBLIC_URL`·`SMTP_*`가 **어느 것도
    서버에 닿지 않는다.** 회원가입은 201로 성공하고 메일만 안 온다.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    launch = text.split('step "5. 백엔드 API"', 1)[1].split('step "5b.', 1)[0]

    assert "--env-file" in launch
    assert "uvicorn" in launch


def test_env_file_is_optional():
    """`.env`가 없어도 기동한다.

    `.env`는 gitignore 대상이라 **새 클론에는 없다.** 없는 파일을 가리키면 uvicorn이
    그 자리에서 실패해, **메일 설정 하나 때문에 시연 전체가 서지 않는다.**
    compose가 `required: false`로 같은 것을 보장한다(`#508`).
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    launch = text.split('step "5. 백엔드 API"', 1)[1].split('step "5b.', 1)[0]

    # 파일이 있을 때만 인자를 만든다.
    assert '[ -f "$ROOT/.env" ]' in launch


def test_database_url_still_overrides_the_env_file():
    """스크립트가 정한 대상 DB가 `.env` 값보다 우선한다.

    uvicorn은 ``load_dotenv(override=False)``라 **이미 있는 환경변수가 이긴다.**
    그래서 ``env DATABASE_URL=...``를 그대로 두면 우선순위가 유지된다 — 이 줄이
    사라지면 `.env`의 DB가 이겨 **점검한 DB와 서버가 붙는 DB가 갈린다.**
    compose 쪽 같은 계약은 `test_compose_env_wiring.py`가 본다 (`#508`).
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    launch = text.split('step "5. 백엔드 API"', 1)[1].split('step "5b.', 1)[0]

    assert 'env DATABASE_URL="$DB_URL"' in launch


def test_env_file_is_not_sourced_by_the_shell():
    """셸이 `.env`를 직접 읽지 않는다.

    ``MAIL_FROM=BlueLog <26hp043@gmail.com>``의 ``<``·``>``를 셸이 리다이렉션으로
    해석해 **구문 오류가 난다**(실측: ``syntax error near unexpected token `newline'``).
    ``uvicorn --env-file``과 docker의 ``env_file``은 그 줄을 정상 처리하므로,
    읽는 주체를 그쪽에 맡긴다.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    assert "set -a" not in body
    assert ". ./.env" not in body
    assert "source .env" not in body


# --- 메일 발송 설정 점검 (#693) -------------------------------------------------


def test_step_five_b_checks_the_mail_backend():
    """5b 단계가 메일 백엔드를 알려 준다.

    ``console``이면 회원가입은 성공하고 메일은 로그에만 찍힌다 — **가입한 사람이
    「안 왔다」고 말하기 전까지 아무도 모른다.**
    """
    text = _SCRIPT.read_text(encoding="utf-8")

    assert 'step "5b. 메일 발송 설정"' in text
    assert "MAIL_BACKEND" in text
    # 인증 링크의 기준 주소도 함께 본다 (#429).
    assert "APP_PUBLIC_URL" in text


def test_mail_check_reads_the_server_log_not_the_env_file():
    """판정 근거가 **서버가 남긴 기록**이다 — 파일이 아니다.

    `.env` 파일을 읽어 판정하면 「파일에 뭐라고 적혀 있나」만 알 뿐 **그 값이 서버에
    닿았는지는 모른다.** 이 이슈의 결함이 바로 「설정은 되어 있고 읽는 경로가
    없다」였으므로, 파일을 보는 검사는 **같은 사고를 그대로 통과시킨다.**

    ``/proc/<pid>/environ``도 쓰지 않는다 — 그것은 **exec 시점의 사본**이라
    ``--env-file``로 나중에 실린 값이 나타나지 않는다.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    step = text.split('step "5b. 메일 발송 설정"', 1)[1].split('step "6.', 1)[0]

    assert "demo_api.log" in step, "판정이 서버 로그를 근거로 하지 않는다"
    assert "/proc/" not in step, "exec 시점 사본은 --env-file로 실린 값을 담지 않는다"


def test_script_never_prints_the_smtp_password():
    """비밀번호는 어디에도 출력하지 않는다."""
    text = _SCRIPT.read_text(encoding="utf-8")

    assert "SMTP_PASSWORD" not in text


def test_env_stays_out_of_git():
    """`.env`가 gitignore 대상이다 — 자격증명이 커밋되지 않는다 (`#693` 체크리스트).

    이 파일에는 Gmail 앱 비밀번호가 들어 있다. 한 번 커밋되면 이력에서 지우기
    어렵고, 그 사이 저장소를 clone한 사람에게는 남는다.
    """
    ignore = (_SCRIPT.resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    entries = {line.strip() for line in ignore.splitlines()}

    assert ".env" in entries, ".gitignore에 .env가 없다 — SMTP 자격증명이 커밋될 수 있다"
