"""서비스가 던지는 오류 문구에 영문 식별자·내부 예외가 섞이지 않는다 (``API_SPEC §1.3.2`` · #999).

``#900``이 Pydantic 422를 한국어로 옮겼으나 **서비스가 직접 던지는 문구**는 그 경로를 타지
않는다. 2026-09-12 전수 스캔에서 31곳이 나왔다 — 두 갈래다.

1. **필드명 원문이 문장에 섞인다** — 「``annual_inclusion_policy``가 ``EXCLUDE``가 아닌 항차에서
   ``regulation_year``를 지울 수 없습니다.」. 사용자는 필드명을 모른다. 라벨(``field_labels.py``)로
   부른다
2. **계산 엔진의 영문 예외를 문구 뒤에 붙인다** — ``f"선박 제원이 부족해 계산할 수 없습니다:
   {exc}"`` → 「… deadweight is required for ship_type 'BULK_CARRIER' (DWT 기준) but was None」.
   고칠 수 있는 원인은 한국어로 말하고, 진단은 서버 로그로 보낸다

`#2112`가 셋째 갈래를 더했다 — **내부 값이 문구에 실린다.** PDF 렌더러의 import 예외 원문
(「(원인: libpango-1.0-0 not found)」), 외부 모델의 HTTP 상태 코드(「(HTTP 529)」), 내부 이슈
번호(「저장하기 전(#443)에」). 셋 다 사용자가 읽을 말이 아니고, ``api/error_handlers.py``가
잡히지 않은 예외에 대해 지키는 「예외 내용을 응답에 넣지 않는다」와 같은 원칙이다.

## 무엇을 읽는가

``src/cii_platform``의 ``raise <앱 오류>(첫 인자, …)``를 **AST로** 읽는다(주석·docstring은 보지
않는다). ``api/schemas``·``api/routes``에서는 Pydantic 검증기가 던지는 ``ValueError``도 본다 —
그 문구는 ``#900``의 경로로 422 ``details[].message``에 그대로 실린다.

- 문자열 부분에 ``snake_case`` 식별자가 있으면 실패 — 끼워 넣는 **값**(``{fuel_type}``의
  ``HFO`` 등)은 보지 않는다. 값은 코드·식별자일 수 있으나 문장의 말이 아니다
- **소문자 영단어**가 있으면 실패 (`#1329`). ``snake_case``만 보던 동안 ``from``·``to``·
  ``sort``·``got``·``cursor``·``limit``·``seed``가 **밑줄이 없다는 이유로** 전부 빠져나갔다 —
  「``from``은 2019 이상이어야 합니다: got 2000」이 그렇게 살아 있었다. 대문자 약어
  (``IMO``·``DWT``·``CII``)와 열거값(``EXCLUDE``)은 문장의 말이므로 걸리지 않는다
- 끼워 넣는 값이 **예외 객체**(``exc``·``e``·``err``·``error``)면 실패 — f-string의 ``{exc}``만이
  아니라 ``str(exc)``·``repr(exc)``·``exc.args`` 꼴과 **문구 자체가 ``str(exc)``인** 경우도
  (`#2112`)
- 문구에 **이슈 번호**(``#443``)나 **HTTP 상태 코드**(``HTTP 529`` · ``HTTP {status}``)가 있으면
  실패 (`#2112`)

### 어디까지 보는가 (`#2112`)

종전 스캔은 ``raise X("…")``의 **리터럴 첫 인자**만 읽었다. 세 모양이 빠져나갔다.

- **변수로 넘긴 문구** — ``message = f"… {exc}"`` 뒤 ``raise X(message)``. 같은 함수(없으면
  모듈)의 단순 대입을 따라가 그 값을 읽는다
- **키워드로 넘긴 문구** — ``raise X(message="…")``
- **`errors.py` 밖에서 정의한 하위 클래스** — ``reports/pdf.py``의 ``PdfUnavailableError``처럼
  ``AppError``를 상속해 ``super().__init__("INTERNAL_ERROR", f"… {detail}")``로 문구를 만드는
  것. 파일 안의 상속 선언을 읽어 그 이름도 앱 오류로 치고, ``super().__init__`` 호출의 문구
  인자도 읽는다. 앱 오류 목록 자체도 손으로 적지 않고 ``errors.py``에서 읽는다

챗봇의 ``LLMError``도 본다 — ``services/chat.py``가 그것을 받아 답으로 바꾸는 경로가 있다.

계산 엔진(``calc/``)의 ``ValueError``는 대상이 아니다 — 그것은 서비스가 받아 **옮기는** 원문이고,
엔진 검사(``test_cii_engine.py`` 등)가 그 영문을 단언한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "src" / "cii_platform"


def _app_error_names(root: Path = _ROOT) -> frozenset[str]:
    """사용자에게 문구가 나가는 앱 오류 — ``cii_platform.errors``의 ``AppError`` 계열 전부.

    손으로 적은 목록은 낡는다 — 종전 목록에는 없는 이름(``ForbiddenError``)이 있고 있는 이름
    (``RateLimitError``·``ChatUnavailableError``)이 빠져 있었다. 챗봇 공급자의 ``LLMError``는
    ``errors.py`` 밖에 있으나 ``services/chat.py``가 그 문구를 답으로 쓸 수 있어 함께 본다.
    """
    names = {"AppError", "LLMError", "LLMUnavailableError"}
    errors_py = root / "errors.py"
    if errors_py.exists():
        for node in ast.parse(errors_py.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and any(
                getattr(base, "id", None) in names for base in node.bases
            ):
                names.add(node.name)
    return frozenset(names)


_APP_ERRORS = _app_error_names()
#: 여기서는 Pydantic 검증기의 ``ValueError``도 문구가 된다.
_VALIDATOR_DIRS = ("api/schemas", "api/routes")
#: 한글 조사가 바로 붙어도 잡는다 — 파이썬 ``\b``는 한글을 단어 문자로 본다.
_SNAKE = re.compile(r"(?<![A-Za-z0-9_])[a-z]+_[a-z0-9_]+(?![A-Za-z0-9_])")
#: 소문자 영단어 (`#1329`). 밑줄이 없어 :data:`_SNAKE`를 빠져나가던 필드명들이다.
#: 대문자 약어·열거값은 문장의 말이라 잡지 않는다.
_LOWER_WORD = re.compile(r"(?<![A-Za-z0-9_])[a-z]{2,}(?![A-Za-z0-9_])")
#: 내부 이슈 번호 (`#2112`). ``#``에 숫자가 바로 붙은 것 — 「전(#443)에」.
_ISSUE_NUMBER = re.compile(r"#\d+")
#: HTTP 상태 코드 (`#2112`). 리터럴 숫자든 끼워 넣는 값(``{}`` 자리)이든.
_HTTP_STATUS = re.compile(r"HTTP\s*(\d{3}|\{\})")


def _label_words() -> frozenset[str]:
    """정본 라벨이 이미 쓰는 소문자 영단어 (`#1329`).

    **손으로 적은 예외 목록을 두지 않는다.** 라벨(``field_labels._FIELD_LABELS``)이
    `난수 시드(seed)`처럼 영문을 **병기하기로 정한** 것은 그 자체가 정본의 결정이고,
    그 결정을 여기 한 번 더 적으면 **두 곳이 갈린다.**

    실측상 지금 해당하는 것은 ``seed`` 하나다 — 라벨이 늘면 자동으로 따라간다.
    """
    from cii_platform.api.field_labels import _FIELD_LABELS

    words: set[str] = set()
    for label in _FIELD_LABELS.values():
        words.update(_LOWER_WORD.findall(label))
    return frozenset(words)


_EXCEPTION_NAMES = frozenset({"exc", "e", "err", "error"})
#: 문구를 키워드로 넘길 때의 이름.
_MESSAGE_KEYWORDS = ("message", "detail")


def _parts(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.JoinedStr):
        return list(node.values)
    if isinstance(node, ast.BinOp):
        # ``"…" + x``와 ``"원인: %s" % exc`` — 오른쪽이 튜플이면 그 원소까지 본다.
        right = node.right
        tail = list(right.elts) if isinstance(right, ast.Tuple) else _parts(right)
        return _parts(node.left) + tail
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        # ``"원인: {}".format(exc)`` — 틀 문자열과 인자를 함께 본다.
        return _parts(node.func.value) + list(node.args) + [k.value for k in node.keywords]
    return [node]


def _mentions_exception(node: ast.AST) -> bool:
    """``exc`` · ``str(exc)`` · ``repr(exc)`` · ``exc.args[0]`` — 예외 객체가 값으로 들어가는 꼴."""
    if isinstance(node, ast.Name):
        return node.id in _EXCEPTION_NAMES
    if isinstance(node, ast.Attribute | ast.Subscript):
        return _mentions_exception(node.value)
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) in {"str", "repr"}:
        return any(_mentions_exception(arg) for arg in node.args)
    return False


def _callee(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "__init__":
        inner = func.value
        if isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "super":
            return "super().__init__"
        return None
    return getattr(func, "id", None) or getattr(func, "attr", None)


def _message_arg(call: ast.Call, *, base_signature: bool) -> ast.AST | None:
    """호출에서 문구 인자를 고른다.

    ``AppError``와 ``super().__init__``는 ``(code, message)``라 둘째 인자, 그 밖의 하위 클래스는
    첫째 인자다. 위치 인자가 없으면 ``message=``·``detail=`` 키워드를 본다.
    """
    index = 1 if base_signature else 0
    if len(call.args) > index:
        return call.args[index]
    for keyword in call.keywords:
        if keyword.arg in _MESSAGE_KEYWORDS:
            return keyword.value
    return None


def _scope_nodes(body: list[ast.stmt]):
    """한 스코프의 노드 전부 — 안쪽 함수·클래스는 **그 선언 노드까지만** 내고 들어가지 않는다."""
    stack: list[ast.AST] = list(reversed(body))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _assignments(body: list[ast.stmt]) -> dict[str, ast.AST]:
    """한 스코프의 ``이름 = 값`` 단순 대입 — 변수로 넘긴 문구를 따라가는 재료."""
    found: dict[str, ast.AST] = {}
    for node in _scope_nodes(body):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name):
                found[node.targets[0].id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            found[node.target.id] = node.value
    return found


def _local_subclasses(tree: ast.Module, names: frozenset[str]) -> frozenset[str]:
    """이 파일이 ``errors.py`` 밖에서 선언한 앱 오류 하위 클래스."""
    local = set(names)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            getattr(base, "id", None) in local for base in node.bases
        ):
            local.add(node.name)
    return frozenset(local)


def _message_sites(tree: ast.Module, *, validators: bool) -> list[tuple[int, ast.AST]]:
    """문구가 사용자에게 나가는 호출 자리 — ``(줄, 문구 노드)``.

    앱 오류의 **생성 호출**을 본다 — ``raise`` 아래든 ``return ValidationError(…)``처럼 만들어
    돌려주는 것이든. 변수로 넘긴 문구는 같은 함수의 대입, 없으면 모듈 대입에서 값을 찾는다.
    """
    names = _local_subclasses(tree, _APP_ERRORS)
    module_scope = _assignments(tree.body)
    sites: list[tuple[int, ast.AST]] = []

    def visit(body: list[ast.stmt], scope: dict[str, ast.AST], in_app_error_class: bool) -> None:
        for node in _scope_nodes(body):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                # 안쪽 함수는 바깥 함수의 대입도 본다 — 바깥에서 만든 문구를 안에서 던지는 꼴.
                visit(node.body, {**scope, **_assignments(node.body)}, in_app_error_class)
                continue
            if isinstance(node, ast.ClassDef):
                inherits = any(getattr(base, "id", None) in names for base in node.bases)
                visit(node.body, {}, inherits)
                continue
            if isinstance(node, ast.Raise):
                # 검증기의 `ValueError`는 던질 때만 문구가 된다. 앱 오류는 아래 Call로 잡힌다.
                call = node.exc
                if not (validators and isinstance(call, ast.Call)):
                    continue
                if _callee(call) != "ValueError":
                    continue
                base_signature = False
            elif isinstance(node, ast.Call):
                call = node
                name = _callee(call)
                if name == "super().__init__":
                    if not in_app_error_class:
                        continue
                    base_signature = True
                elif name in names:
                    base_signature = name == "AppError"
                else:
                    continue
            else:
                continue
            message = _message_arg(call, base_signature=base_signature)
            if message is None:
                continue
            if isinstance(message, ast.Name) and not _mentions_exception(message):
                message = scope.get(message.id) or module_scope.get(message.id)
                if message is None:
                    continue
            sites.append((node.lineno, message))

    visit(tree.body, module_scope, False)
    return sites


def _findings(root: Path = _ROOT) -> list[str]:
    allowed = _label_words()
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        validators = rel.startswith(_VALIDATOR_DIRS)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, message in _message_sites(tree, validators=validators):
            text = ""
            rendered = ""
            leaks_exception = _mentions_exception(message)
            for part in _parts(message):
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    text += part.value
                    rendered += part.value
                elif isinstance(part, ast.FormattedValue):
                    rendered += "{}"
                    if _mentions_exception(part.value):
                        leaks_exception = True
                elif _mentions_exception(part):
                    # ``%`` · ``.format()``로 끼운 예외 객체.
                    leaks_exception = True
            identifiers = _SNAKE.findall(text)
            if identifiers:
                found.append(f"{rel}:{lineno} 필드명 원문 {identifiers} — {text[:60]}")
            words = [
                w for w in _LOWER_WORD.findall(text) if w not in allowed and not _SNAKE.search(w)
            ]
            # `_SNAKE`가 이미 보고한 자리는 두 번 세지 않는다.
            words = [w for w in words if not any(w in i for i in identifiers)]
            if words:
                found.append(f"{rel}:{lineno} 소문자 영단어 {words} — {text[:60]}")
            if leaks_exception:
                found.append(f"{rel}:{lineno} 예외 객체를 문구에 끼워 넣는다 — {text[:60]}")
            if _ISSUE_NUMBER.search(rendered):
                found.append(f"{rel}:{lineno} 이슈 번호가 문구에 있다 — {text[:60]}")
            if _HTTP_STATUS.search(rendered):
                found.append(f"{rel}:{lineno} HTTP 상태 코드가 문구에 있다 — {text[:60]}")
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
        "    raise ValidationError(f'알 수 없는 연료 종류입니다: {fuel_type}')\n"
        "def i():\n"
        "    raise ValidationError('from은 2019 이상이어야 합니다: got 2000')\n"
        "def j():\n"
        "    raise ValidationError('IMO 번호는 7자리여야 합니다. DWT는 EXCLUDE가 아닙니다.')\n",
        encoding="utf-8",
    )
    found = _findings(tmp_path)
    assert len(found) == 3, found
    assert "direct_distance_nm" in found[0]
    assert "예외 객체" in found[1]
    # `#1329` — 밑줄 없는 영단어. 대문자 약어·열거값만 있는 `j`는 걸리지 않는다.
    assert "소문자 영단어" in found[2]
    assert "from" in found[2] and "got" in found[2]


def test_the_scanner_follows_variables_subclasses_and_internals(tmp_path):
    """`#2112` — 변수·키워드로 넘긴 문구 · 파일 안 하위 클래스 · 내부 값(이슈 번호·HTTP·예외 원문).

    각 줄이 **정확히 하나의** 사유로 잡히고, 깨끗한 `clean`은 잡히지 않는다. 이슈 본문의 세
    경로를 그대로 옮겼다 — PDF 렌더러(`super().__init__` + 변수), 외부 모델(`HTTP {status}`),
    404 두 문구(`#443` · `#493`).
    """
    fake = tmp_path / "services"
    fake.mkdir()
    (fake / "bad.py").write_text(
        "class PdfUnavailableError(AppError):\n"
        "    def __init__(self, detail):\n"
        "        super().__init__('INTERNAL_ERROR', f'PDF 생성기를 쓸 수 없습니다 ({detail})')\n"
        "def pdf(exc):\n"
        "    raise PdfUnavailableError(str(exc))\n"
        "def http(status):\n"
        "    raise LLMError(f'챗봇 응답을 받지 못했습니다 (HTTP {status}).')\n"
        "def literal():\n"
        "    raise LLMError('챗봇 응답을 받지 못했습니다 (HTTP 503).')\n"
        "def issue():\n"
        "    raise NotFoundError('이 실행은 결과 본문을 저장하기 전(#443)에 만들어졌습니다.')\n"
        "def variable(exc):\n"
        "    message = f'재현할 수 없습니다: {exc}'\n"
        "    raise NotFoundError(message)\n"
        "def keyword():\n"
        "    raise ConflictError(message='스냅샷하기 전(#493)에 만들어졌습니다.')\n"
        "def attribute(exc):\n"
        "    raise CalculationError(f'계산 실패: {exc.args[0]}')\n"
        "def clean(label):\n"
        "    message = f'{label}는 0보다 커야 합니다.'\n"
        "    raise ValidationError(message)\n"
        "MODULE_MESSAGE = '모듈 상수 문구 (HTTP 500)'\n"
        "def module_level():\n"
        "    raise AppError('INTERNAL_ERROR', MODULE_MESSAGE)\n"
        # 검토가 찾은 미탐 셋 — `.format` · `%` · 바깥 함수의 변수.
        "def formatted(exc):\n"
        "    raise CalculationError('계산 실패: {}'.format(exc))\n"
        "def percent(exc):\n"
        "    raise CalculationError('계산 실패: %s' % exc)\n"
        "def outer(exc):\n"
        "    message = f'계산 실패: {exc}'\n"
        "    def inner():\n"
        "        raise CalculationError(message)\n"
        "    inner()\n",
        encoding="utf-8",
    )
    found = _findings(tmp_path)
    by_line = {int(line.split(":")[1].split(" ")[0]): line for line in found}
    assert len(found) == len(by_line) == 11, found
    # `super().__init__`의 `{detail}`은 예외 이름이 아니라 그 줄은 조용하다 — 대신
    # `str(exc)`를 넘기는 **던지는 자리**가 잡힌다.
    assert 3 not in by_line
    assert "예외 객체" in by_line[5]
    assert "HTTP 상태 코드" in by_line[7]
    assert "HTTP 상태 코드" in by_line[9]
    assert "이슈 번호" in by_line[11]
    assert "예외 객체" in by_line[14]
    assert "이슈 번호" in by_line[16]
    assert "예외 객체" in by_line[18]
    assert "HTTP 상태 코드" in by_line[24]
    assert 21 not in by_line  # `clean`
    assert "예외 객체" in by_line[26]  # `.format(exc)`
    assert "예외 객체" in by_line[28]  # `% exc`
    assert "예외 객체" in by_line[32]  # 바깥 함수의 `message`


def test_service_error_messages_are_plain_korean():
    found = _findings()
    assert not found, (
        "사용자에게 나가는 오류 문구에 영문 식별자·내부 예외가 있습니다 (API_SPEC §1.3.2):\n"
        + "\n".join(f"  {line}" for line in found)
    )
