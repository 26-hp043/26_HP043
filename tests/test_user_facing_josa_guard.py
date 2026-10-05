"""사용자에게 나가는 문구에 조사 괄호 병기가 없다 (#2123).

「은(는)」·「을(를)」 같은 병기는 받침을 몰라서 둘 다 적은 것이다. 화면에는 괄호가 그대로
보이고, 같은 오류를 경로(JSON · CSV)마다 다르게 말하게 된다. 조사는
``api/validation_messages.josa``가 라벨의 받침으로 **하나만** 고른다.

## 무엇을 스캔하는가

``src/`` 아래 모든 ``.py``의 **문자열 상수**(f-string의 고정 조각 포함)다. 제외는 둘이다.

- **주석** — AST에 없으므로 자연히 빠진다. 사용자에게 나가지 않는다.
- **docstring** — 규칙을 설명하며 병기를 인용한다(``validation_messages``). 이것도 나가지 않는다.

``josa()``가 한글로 끝나지 않는 낱말에 내는 「을(를)」 꼴은 리터럴이 아니라 **실행 시점에
조립**되므로 이 스캔의 대상이 아니다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from cii_platform.services.not_underway_import import RowError, _decimal, _optional_decimal

SRC = Path(__file__).resolve().parents[1] / "src"
PAREN_JOSA = re.compile(r"은\(는\)|을\(를\)|이\(가\)|와\(과\)|\(으\)로")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _offenders(source: str, name: str) -> list[str]:
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    return [
        f"{name}:{node.lineno}: {node.value.strip()[:60]}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and PAREN_JOSA.search(node.value)
    ]


def test_src_문자열에_조사_괄호_병기가_없다() -> None:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        found += _offenders(path.read_text(encoding="utf-8"), str(path.relative_to(SRC)))
    assert found == []


def test_가드가_문자열은_잡고_주석과_docstring은_넘긴다() -> None:
    sample = '"""설명 은(는)."""\n# 주석 을(를)\nx = f"{a}은(는) 틀렸다"\ny = "ok"\n'
    hits = _offenders(sample, "s.py")
    assert len(hits) == 1
    assert hits[0].startswith("s.py:3")


def _message(call: object) -> str:
    with pytest.raises(RowError) as info:
        call()  # type: ignore[operator]
    return info.value.message


def test_정박_CSV_오류문구에_괄호가_없다() -> None:
    messages = [
        _message(lambda: _decimal({"d": ""}, "d", label="연료량")),
        _message(lambda: _decimal({"d": "x"}, "d", label="연료량")),
        _message(lambda: _decimal({"d": "0"}, "d", label="연료량", positive=True)),
        _message(lambda: _decimal({"d": "-1"}, "d", label="이동 거리")),
        _message(lambda: _decimal({"d": "9" * 12}, "d", label="이동 거리")),
        _message(lambda: _optional_decimal({"lat": "x"}, "lat", label="위도")),
        _message(lambda: _optional_decimal({"lat": "91"}, "lat", label="위도")),
    ]
    assert all("(" not in m and ")" not in m for m in messages), messages


def test_정박_CSV_조사는_라벨_받침을_따른다() -> None:
    # 받침 없는 「위도」는 「는」, 받침 있는 「시작 시각」은 「은」이어야 한다.
    assert _message(lambda: _optional_decimal({"lon": "x"}, "lon", label="위도")).startswith(
        "위도는"
    )
    assert _message(lambda: _optional_decimal({"lon": "x"}, "lon", label="시작 시각")).startswith(
        "시작 시각은"
    )
    assert _message(lambda: _decimal({"d": ""}, "d", label="연료량")).startswith("연료량을")
    assert _message(lambda: _decimal({"d": ""}, "d", label="이동 거리")).startswith("이동 거리를")
