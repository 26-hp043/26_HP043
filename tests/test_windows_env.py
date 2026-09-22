"""Windows 새 환경에서만 깨지던 것 셋 (`#1664` · `#1665` · `#1670`).

CI는 Linux라 **셋 다 드러나지 않았다** — Linux 이미지에는 OS 시간대 데이터가 있고, 로캘이
UTF-8이다. Windows는 둘 다 아니다(시간대 데이터 없음 · 기본 콘솔 CP949).

## UTF-8이 아닌 로캘을 Linux에서 만든다

``LC_ALL=C`` + ``PYTHONCOERCECLOCALE=0`` + ``PYTHONUTF8=0``이면 자식 파이썬의 기본 인코딩이
ASCII가 된다. CP949보다 **더 좁은** 인코딩이라, 여기서 통과하면 「플랫폼 기본 인코딩에
기대지 않는다」가 성립한다. 로캘을 바꿀 수 없는 환경이면 건너뛴다.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_NARROW = {
    **os.environ,
    "LC_ALL": "C",
    "LANG": "C",
    "PYTHONCOERCECLOCALE": "0",
    "PYTHONUTF8": "0",
    "PYTHONIOENCODING": "",
}


def _narrow_encoding() -> str:
    out = subprocess.run(
        [sys.executable, "-c", "import locale,sys;print(locale.getpreferredencoding(False))"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_NARROW,
        check=True,
    )
    return out.stdout.strip().lower()


@pytest.fixture(scope="module")
def narrow_env() -> dict[str, str]:
    encoding = _narrow_encoding()
    if "utf" in encoding:
        pytest.skip(f"UTF-8이 아닌 로캘을 만들 수 없다 ({encoding})")
    return _NARROW


def test_fixture_generator_finishes_on_a_narrow_console(narrow_env):
    """`#1670` — 콘솔이 ✓를 못 그려도 생성기는 **성공으로 끝난다**."""
    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "gen_fixtures.py")],
        capture_output=True,
        cwd=_ROOT,
        env=narrow_env,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def test_changelog_script_reads_korean_git_output_on_a_narrow_locale(narrow_env, tmp_path):
    """`#1665` — Git 출력의 한국어를 **플랫폼 기본 인코딩이 아니라 UTF-8로** 읽는다."""

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    (tmp_path / "DOC.md").write_text("| 2026-09-23 | `#1` | 한국어 행 |\n", encoding="utf-8")
    git("add", "DOC.md")
    git("commit", "-qm", "init")

    probe = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]);"
        "import check_changelog_rows as m;"
        "text = m._show(Path(sys.argv[2]), 'HEAD', 'DOC.md');"
        # 자식의 명령줄도 ASCII 로캘로 풀리므로 **한글을 이스케이프로** 싣는다.
        f"sys.exit(0 if {ascii('한국어 행')} in text else 3)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(_ROOT / "scripts"), str(tmp_path)],
        capture_output=True,
        env=narrow_env,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


#: 텍스트 I/O 호출의 시작 — 괄호 짝은 아래 :func:`_bare_text_io`가 맞춘다.
_TEXT_IO = re.compile(r"\.(?:write_text|read_text)\(")


def _bare_text_io(source: str) -> list[str]:
    """인코딩을 적지 않은 ``write_text``·``read_text`` 호출 — 플랫폼 기본 인코딩에 기댄다.

    인자 안에 괄호가 겹치므로(``_table(...)``) 정규식 하나로는 끝을 못 찾는다. 짝을 센다.
    """
    found = []
    for match in _TEXT_IO.finditer(source):
        depth, end = 1, match.end()
        while depth and end < len(source):
            depth += {"(": 1, ")": -1}.get(source[end], 0)
            end += 1
        call = source[match.start() : end]
        if "encoding=" not in call:
            found.append(call)
    return found


@pytest.mark.parametrize(
    "relative",
    ["scripts/check_changelog_rows.py", "tests/test_changelog_rows_script.py"],
)
def test_changelog_files_name_their_text_encoding(relative):
    """`#1665` — 변경 이력 검사와 그 테스트는 파일을 읽고 쓸 때 **UTF-8을 적는다**."""
    source = (_ROOT / relative).read_text(encoding="utf-8")
    assert _bare_text_io(source) == []


def test_zoneinfo_users_get_tzdata_as_an_install_dependency():
    """`#1664` — `ZoneInfo`를 쓰는 코드가 있으면 `tzdata`가 **설치 의존성**이다.

    Windows에는 OS 시간대 데이터가 없어, 새 가상환경에서 `ZoneInfo("Asia/Seoul")`이
    `ZoneInfoNotFoundError`로 끝난다. 개발자가 따로 설치해야 통과하는 상태를 막는다.
    """
    users = [
        path
        for path in (_ROOT / "src").rglob("*.py")
        if "ZoneInfo(" in path.read_text(encoding="utf-8")
    ]
    assert users, "ZoneInfo를 쓰는 코드가 없어졌다면 이 검사와 의존성을 함께 걷는다"
    deps = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]
    assert any(re.match(r"tzdata\b", dep) for dep in deps), deps


def test_seoul_resolves_from_the_tzdata_package():
    """`#1664` — OS 데이터 없이도 `tzdata` 패키지만으로 `Asia/Seoul`이 풀린다."""
    from importlib.resources import files

    assert files("tzdata.zoneinfo").joinpath("Asia", "Seoul").is_file()
