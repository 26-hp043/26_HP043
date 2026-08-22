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
