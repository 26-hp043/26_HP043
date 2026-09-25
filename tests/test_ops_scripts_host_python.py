"""이슈 #1915 · 운영 호스트에서 돌리라고 적은 스크립트가 **그 호스트에서 돈다.**

## 무엇이 깨져 있었나

``docs/OPERATIONS.md §9.2.1``이 DB 이전의 **1단계**로 적은 백업 명령이 그대로는 실패했다::

    $ ssh db-01
    $ python3 scripts/db_backup.py backup
    ImportError: cannot import name 'UTC' from 'datetime' (/usr/lib/python3.10/datetime.py)

``datetime.UTC``는 **3.11+**이고 운영 호스트는 Ubuntu 22.04 · **3.10.12**다(app-01 · db-01
둘 다 실측 2026-09-25). 같은 덫이 ``scripts/purge_expired.py``에도 있었는데, 그쪽은
``README``가 **crontab 한 줄**로 돌리라고 적는 자리다 — 실패해도 사람이 보지 않는다.

## 왜 조용했나

``pyproject.toml``의 ``requires-python = ">=3.12"``는 **패키지**의 요구사항이고 이 스크립트들은
패키지에 들어가지 않는다(``purge_expired.py`` 머리주석: 「프로덕션 이미지는 wheel만 설치해
``scripts/``가 없고, 호스트에…」). **실행 환경이 CI·이미지와 다른데 그 차이를 보는 검사가
없었다.** CI도 개발 PC도 3.12라 어디서도 빨개지지 않는다.

## 무엇을 보는가

호스트에서 도는 스크립트마다 셋을 본다.

⑴ **3.10 문법으로 파싱된다** — ``ast.parse(feature_version=(3, 10))``가 ``except*``·PEP 695처럼
   새 문법을 잡는다.
⑵ **3.11+ 표준 라이브러리 이름을 쓰지 않는다** — 문법은 3.10인데 이름만 새것인 경우가
   이번 사고였다. 아래 목록은 **실제로 손이 가는 것들**이며, 새 이름이 필요해지면 여기 더하는
   것이 아니라 **그 스크립트를 호스트에서 돌리지 않기로** 정해야 한다.
⑶ **프로젝트 모듈을 import하지 않는다** — 호스트에는 ``cii_platform``이 설치돼 있지 않다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: 운영 호스트의 ``python3``. Ubuntu 22.04가 담는 버전이다 — 올리려면 **호스트를 먼저** 올린다.
HOST_PYTHON = (3, 10)

#: 호스트에서 ``python3 scripts/…``로 돌리라고 문서가 적는 스크립트.
#: 여기 더할 때는 그 문서 줄도 함께 가리킨다.
HOST_SCRIPTS = {
    "db_backup.py": "docs/OPERATIONS.md §3.6.6 · §9.2.1 (DB 백업·복구)",
    "purge_expired.py": "README.md (보존 기간 청소 · crontab)",
}

#: 3.11+에서 생긴 표준 라이브러리 이름 중 **손이 가기 쉬운 것들**.
#: ``모듈 이름``은 import 자체를, ``모듈.이름``은 ``from 모듈 import 이름``을 막는다.
TOO_NEW = {
    "tomllib": "3.11 — 호스트에는 없다. `configparser`나 `json`을 쓴다",
    "datetime.UTC": "3.11 — `timezone.utc`를 쓴다 (이번 사고)",
    "enum.StrEnum": "3.11 — `class X(str, Enum)`을 쓴다",
    "typing.Self": "3.11 — 클래스 이름을 문자열로 적는다",
    "typing.Never": "3.11",
    "typing.assert_never": "3.11",
    "typing.override": "3.12",
    "typing.TypeAliasType": "3.12",
    "asyncio.TaskGroup": "3.11",
    "asyncio.timeout": "3.11",
    "itertools.batched": "3.12",
    "hashlib.file_digest": "3.11",
    "pathlib.Path.walk": "3.12",
}


def _source(name: str) -> str:
    return (_ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_the_scripts_documents_point_at_still_exist():
    """목록이 실제 파일을 가리킨다 — 이름이 바뀌면 이 검사가 조용히 비어 버린다."""
    for name in HOST_SCRIPTS:
        assert (_ROOT / "scripts" / name).is_file(), f"scripts/{name} 이 없다"


def test_host_scripts_parse_on_the_host_python():
    """호스트 파이썬 문법으로 파싱된다 (#1915 ⑴).

    ``feature_version``은 **문법**만 본다 — 이름은 아래 검사가 맡는다.
    """
    for name, where in HOST_SCRIPTS.items():
        try:
            ast.parse(_source(name), filename=name, feature_version=HOST_PYTHON)
        except SyntaxError as error:  # pragma: no cover - 실패 시 메시지가 본체다
            version = ".".join(str(part) for part in HOST_PYTHON)
            raise AssertionError(
                f"scripts/{name} 이 Python {version}에서 파싱되지 않는다 — {where}에서 "
                f"호스트 python3로 돌리라고 적는 파일이다: {error}"
            ) from error


def test_host_scripts_do_not_use_newer_stdlib_names():
    """3.11+ 표준 라이브러리 이름을 쓰지 않는다 (#1915 ⑵).

    문법은 3.10인데 **이름만 새것**인 경우가 이번 사고였다 — ``from datetime import UTC``.
    """
    for name, where in HOST_SCRIPTS.items():
        tree = ast.parse(_source(name), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    reason = TOO_NEW.get(alias.name)
                    assert reason is None, (
                        f"scripts/{name}: `import {alias.name}` 은 {reason}. {where}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    reason = TOO_NEW.get(f"{node.module}.{alias.name}")
                    assert reason is None, (
                        f"scripts/{name}: `from {node.module} import {alias.name}` 은 "
                        f"{reason}. {where}"
                    )


def test_host_scripts_do_not_import_the_project_package():
    """프로젝트 모듈을 부르지 않는다 (#1915 ⑶).

    호스트에는 ``cii_platform``이 설치돼 있지 않다 — 프로덕션 이미지는 wheel만 담고
    ``scripts/``를 넣지 않으므로, 이 스크립트들은 **저장소 체크아웃 + 표준 라이브러리**만으로
    서야 한다.
    """
    for name, where in HOST_SCRIPTS.items():
        tree = ast.parse(_source(name), filename=name)
        for node in ast.walk(tree):
            imported = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in imported:
                assert not module.startswith("cii_platform"), (
                    f"scripts/{name}: `{module}` 은 호스트에 설치돼 있지 않다. {where}"
                )


def test_the_guard_would_catch_the_bug_it_was_written_for():
    """가드가 **이번 사고를 실제로 잡는다** — 되돌려 확인한다.

    검사가 스스로 통과하는지만 보면, 규칙이 틀려도 초록으로 남는다.
    """
    broken = "from datetime import UTC, datetime\n"
    tree = ast.parse(broken)
    node = tree.body[0]
    assert isinstance(node, ast.ImportFrom) and node.module == "datetime"
    assert any(f"{node.module}.{alias.name}" in TOO_NEW for alias in node.names)

    # 문법 쪽도 같은 방식으로 확인한다 — `except*`는 3.11 문법이다.
    try:
        ast.parse("try:\n    pass\nexcept* ValueError:\n    pass\n", feature_version=HOST_PYTHON)
    except SyntaxError:
        pass
    else:  # pragma: no cover - 여기 오면 feature_version이 동작하지 않는 것이다
        raise AssertionError("feature_version이 새 문법을 걸러 내지 못한다")
