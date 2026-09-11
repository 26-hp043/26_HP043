"""서비스가 던지는 오류 문구에 영문 식별자·내부 예외가 섞이지 않는다 (``API_SPEC §1.3.2`` · #999).

``#900``이 Pydantic 422를 한국어로 옮겼으나 **서비스가 직접 던지는 문구**는 그 경로를 타지
않는다. 2026-09-12 전수 스캔에서 31곳이 나왔다 — 두 갈래다.

1. **필드명 원문이 문장에 섞인다** — 「``annual_inclusion_policy``가 ``EXCLUDE``가 아닌 항차에서
   ``regulation_year``를 지울 수 없습니다.」. 사용자는 필드명을 모른다. 라벨(``field_labels.py``)로
   부른다
2. **계산 엔진의 영문 예외를 문구 뒤에 붙인다** — ``f"선박 제원이 부족해 계산할 수 없습니다:
   {exc}"`` → 「… deadweight is required for ship_type 'BULK_CARRIER' (DWT 기준) but was None」.
   고칠 수 있는 원인은 한국어로 말하고, 진단은 서버 로그로 보낸다

## 무엇을 읽는가

``src/cii_platform``의 ``raise <앱 오류>(첫 인자, …)``를 **AST로** 읽는다(주석·docstring은 보지
않는다). ``api/schemas``·``api/routes``에서는 Pydantic 검증기가 던지는 ``ValueError``도 본다 —
그 문구는 ``#900``의 경로로 422 ``details[].message``에 그대로 실린다.

- 문자열 부분에 ``snake_case`` 식별자가 있으면 실패 — 끼워 넣는 **값**(``{fuel_type}``의
  ``HFO`` 등)은 보지 않는다. 값은 코드·식별자일 수 있으나 문장의 말이 아니다
- 끼워 넣는 값이 **예외 객체**(``exc``·``e``·``err``·``error``)면 실패

계산 엔진(``calc/``)의 ``ValueError``는 대상이 아니다 — 그것은 서비스가 받아 **옮기는** 원문이고,
엔진 검사(``test_cii_engine.py`` 등)가 그 영문을 단언한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "src" / "cii_platform"

#: 사용자에게 문구가 나가는 앱 오류 (``cii_platform.errors``).
_APP_ERRORS = frozenset(
    {
        "AppError",
        "ValidationError",
        "ParameterError",
        "CalculationError",
        "ConflictError",
        "NotFoundError",
        "StateTransitionError",
        "ForbiddenError",
        "UnauthorizedError",
    }
)
#: 여기서는 Pydantic 검증기의 ``ValueError``도 문구가 된다.
_VALIDATOR_DIRS = ("api/schemas", "api/routes")
#: 한글 조사가 바로 붙어도 잡는다 — 파이썬 ``\b``는 한글을 단어 문자로 본다.
_SNAKE = re.compile(r"(?<![A-Za-z0-9_])[a-z]+_[a-z0-9_]+(?![A-Za-z0-9_])")
_EXCEPTION_NAMES = frozenset({"exc", "e", "err", "error"})


def _parts(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.JoinedStr):
        return list(node.values)
    if isinstance(node, ast.BinOp):
        return _parts(node.left) + _parts(node.right)
    return [node]


def _findings(root: Path = _ROOT) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        validators = rel.startswith(_VALIDATOR_DIRS)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name not in _APP_ERRORS and not (validators and name == "ValueError"):
                continue
            if not node.exc.args:
                continue
            text = ""
            leaks_exception = False
            for part in _parts(node.exc.args[0]):
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    text += part.value
                elif isinstance(part, ast.FormattedValue):
                    value = part.value
                    if isinstance(value, ast.Name) and value.id in _EXCEPTION_NAMES:
                        leaks_exception = True
            identifiers = _SNAKE.findall(text)
            if identifiers:
                found.append(f"{rel}:{node.lineno} 필드명 원문 {identifiers} — {text[:60]}")
            if leaks_exception:
                found.append(f"{rel}:{node.lineno} 예외 객체를 문구에 끼워 넣는다 — {text[:60]}")
    return found


def test_scan_sees_raise_sites_at_all():
    """스캔이 빈손으로 통과하지 않게 — 앱 오류를 던지는 자리가 충분히 보여야 한다."""
    count = 0
    for path in _ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                func = node.exc.func
                if (getattr(func, "id", None) or getattr(func, "attr", None)) in _APP_ERRORS:
                    count += 1
    assert count > 100


def test_the_scanner_catches_both_shapes(tmp_path):
    """스캐너 자체의 검사 — 두 모양을 실제로 잡는가(한글 조사가 바로 붙은 경우 포함)."""
    fake = tmp_path / "services"
    fake.mkdir()
    (fake / "bad.py").write_text(
        "def f(exc):\n"
        "    raise ValidationError('direct_distance_nm을 입력하세요.')\n"
        "def g(exc):\n"
        "    raise ParameterError(f'기준선을 선택할 수 없습니다: {exc}')\n"
        "def h(fuel_type):\n"
        "    raise ValidationError(f'알 수 없는 연료 종류입니다: {fuel_type}')\n",
        encoding="utf-8",
    )
    found = _findings(tmp_path)
    assert len(found) == 2, found
    assert "direct_distance_nm" in found[0]
    assert "예외 객체" in found[1]


def test_service_error_messages_are_plain_korean():
    found = _findings()
    assert not found, (
        "사용자에게 나가는 오류 문구에 영문 식별자·내부 예외가 있습니다 (API_SPEC §1.3.2):\n"
        + "\n".join(f"  {line}" for line in found)
    )
