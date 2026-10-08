"""Pydantic 검증 실패 → 한국어 문구 (``API_SPEC §1.3.2`` 언어 규정 · §11 · #900).

``API_SPEC §1.3.2``가 정한다 — *「``error.message``·``details[].message``는 ``field_label``과
동일하게 **한국어**로 작성한다(§1.4의 프레임워크 발생 오류 포함).」* 종전에는 Pydantic 원문이
그대로 나갔다(``String should have at most 100 characters``). 화면이 문구를 조립하면 그
규정을 화면 아홉 곳이 각자 지키게 되므로, **서버 한 곳에서** 옮긴다.

## 어떻게 옮기는가

Pydantic v2는 오류마다 **기계가 읽는 ``type``**과 한계값 ``ctx``를 준다(``string_too_long`` ·
``{"max_length": 100}``). 원문 문장을 번역하지 않고 ``type``에서 문장을 **새로 만든다** — 원문은
Pydantic 판이 바뀌면 문장이 바뀌지만 ``type``은 공개 계약이다.

- 문장 틀은 ``API_SPEC §11``의 것을 따른다 — VAL-001 「``{field_label}``을/를 입력하세요.」 ·
  VAL-002 「``{field_label}``는 0보다 커야 합니다.」
- 조사는 라벨의 **마지막 글자 받침**으로 고른다(「선명을」 · 「이메일을」 · 「비밀번호를」).
  괄호 설명은 건너뛰고 앞 낱말로 고른다(「총톤수(GT)는」). 한글로 끝나지 않아 판단할 수 없는
  라벨은 「을(를)」 꼴로 둘 다 적는다
- **직접 만든 검증기의 한국어 문구는 그대로 쓴다** — ``ValueError("종료 시각은 시작 시각보다
  뒤여야 합니다.")``는 이미 규정을 지킨다. Pydantic이 앞에 붙이는 ``Value error, ``만 뗀다
- **모르는 ``type``은 영문으로 새지 않는다** — 「``{label}`` 값이 올바르지 않습니다.」로 떨어진다.
  원문을 버리는 대신 무엇이 틀렸는지(어느 필드)는 ``field``·``field_label``이 계속 말한다
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

_HANGUL = re.compile(r"[가-힣]")
#: 끝의 괄호 설명 — 「총톤수(GT)」의 「(GT)」. 조사는 그 앞 낱말을 따른다.
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def _has_batchim(word: str) -> bool | None:
    """마지막 글자에 받침이 있는가. 한글 음절로 끝나지 않으면 ``None``(모름)."""
    stripped = _TRAILING_PAREN.sub("", word).rstrip()
    if not stripped:
        return None
    last = stripped[-1]
    if not "가" <= last <= "힣":
        return None
    return (ord(last) - ord("가")) % 28 != 0


def josa(word: str, with_batchim: str, without: str) -> str:
    """``word`` 뒤에 맞는 조사를 붙인다. 판단할 수 없으면 「을(를)」 꼴로 둘 다 적는다."""
    has = _has_batchim(word)
    if has is None:
        return f"{word}{with_batchim}({without})"
    return f"{word}{with_batchim if has else without}"


def _eul(label: str) -> str:
    return josa(label, "을", "를")


def _eun(label: str) -> str:
    return josa(label, "은", "는")


def _num(value: object) -> str:
    """한계값 표기. ``Decimal('0')`` · ``0.0``은 「0」으로 — 끝의 0을 보이지 않는다."""
    text = str(value)
    if "." in text and "e" not in text.lower():
        text = text.rstrip("0").rstrip(".")
    return text


def _expected(ctx: Mapping[str, object]) -> str:
    """``enum``·``literal_error``의 허용값. Pydantic은 ``'A', 'B' or 'C'``로 준다."""
    raw = str(ctx.get("expected", ""))
    parts = [p.strip().strip("'\"") for p in re.split(r",| or ", raw) if p.strip()]
    return ", ".join(parts)


_Builder = Callable[[str, Mapping[str, object]], str]

#: 시각 입력의 예. 서버는 시간대가 붙은 ISO 8601을 받는다(``API_SPEC §1.7``).
_DATETIME_EXAMPLE = "2026-09-12T09:00:00+09:00"

#: Pydantic ``type`` → 문장. 인자는 (한글 라벨, ctx).
_MESSAGES: dict[str, _Builder] = {
    # 필수값 — API_SPEC §11 VAL-001
    "missing": lambda lb, c: f"{_eul(lb)} 입력하세요.",
    # 문자열
    "string_type": lambda lb, c: f"{_eun(lb)} 문자열이어야 합니다.",
    "string_too_short": lambda lb, c: f"{_eun(lb)} {c.get('min_length')}자 이상이어야 합니다.",
    "string_too_long": lambda lb, c: f"{_eun(lb)} {c.get('max_length')}자 이하여야 합니다.",
    "string_pattern_mismatch": lambda lb, c: f"{lb} 형식이 올바르지 않습니다.",
    # 숫자
    "int_type": lambda lb, c: f"{_eun(lb)} 정수여야 합니다.",
    "int_parsing": lambda lb, c: f"{_eun(lb)} 정수여야 합니다.",
    "int_from_float": lambda lb, c: f"{_eun(lb)} 정수여야 합니다.",
    "float_type": lambda lb, c: f"{_eun(lb)} 숫자여야 합니다.",
    "float_parsing": lambda lb, c: f"{_eun(lb)} 숫자여야 합니다.",
    "decimal_type": lambda lb, c: f"{_eun(lb)} 숫자여야 합니다.",
    "decimal_parsing": lambda lb, c: f"{_eun(lb)} 숫자여야 합니다.",
    "finite_number": lambda lb, c: f"{_eun(lb)} 유한한 숫자여야 합니다.",
    "decimal_max_digits": lambda lb, c: (
        f"{_eun(lb)} 최대 {c.get('max_digits')}자리까지 입력할 수 있습니다."
    ),
    "decimal_max_places": lambda lb, c: (
        f"{_eun(lb)} 소수점 아래 {c.get('decimal_places')}자리까지 입력할 수 있습니다."
    ),
    "decimal_whole_digits": lambda lb, c: (
        f"{_eun(lb)} 정수부 {c.get('whole_digits')}자리까지 입력할 수 있습니다."
    ),
    # 범위 — API_SPEC §11 VAL-002 「…는 0보다 커야 합니다.」
    "greater_than": lambda lb, c: f"{_eun(lb)} {_num(c.get('gt'))}보다 커야 합니다.",
    "greater_than_equal": lambda lb, c: f"{_eun(lb)} {_num(c.get('ge'))} 이상이어야 합니다.",
    "less_than": lambda lb, c: f"{_eun(lb)} {_num(c.get('lt'))}보다 작아야 합니다.",
    "less_than_equal": lambda lb, c: f"{_eun(lb)} {_num(c.get('le'))} 이하여야 합니다.",
    "multiple_of": lambda lb, c: f"{_eun(lb)} {_num(c.get('multiple_of'))}의 배수여야 합니다.",
    # 참·거짓
    "bool_type": lambda lb, c: f"{_eun(lb)} 참 또는 거짓이어야 합니다.",
    "bool_parsing": lambda lb, c: f"{_eun(lb)} 참 또는 거짓이어야 합니다.",
    # 선택지
    "enum": lambda lb, c: f"{_eun(lb)} 다음 중 하나여야 합니다: {_expected(c)}.",
    "literal_error": lambda lb, c: f"{_eun(lb)} 다음 중 하나여야 합니다: {_expected(c)}.",
    # 식별자·날짜·시각
    "uuid_type": lambda lb, c: f"{lb} 형식이 올바르지 않습니다.",
    "uuid_parsing": lambda lb, c: f"{lb} 형식이 올바르지 않습니다.",
    "date_type": lambda lb, c: f"{lb} 형식이 올바르지 않습니다(예: 2026-09-12).",
    "date_parsing": lambda lb, c: f"{lb} 형식이 올바르지 않습니다(예: 2026-09-12).",
    "date_from_datetime_parsing": lambda lb, c: f"{lb} 형식이 올바르지 않습니다(예: 2026-09-12).",
    "date_from_datetime_inexact": lambda lb, c: f"{lb}에는 날짜만 입력하세요.",
    "datetime_type": lambda lb, c: f"{lb} 형식이 올바르지 않습니다(예: {_DATETIME_EXAMPLE}).",
    "datetime_parsing": lambda lb, c: f"{lb} 형식이 올바르지 않습니다(예: {_DATETIME_EXAMPLE}).",
    "datetime_from_date_parsing": lambda lb, c: (
        f"{lb} 형식이 올바르지 않습니다(예: {_DATETIME_EXAMPLE})."
    ),
    "timezone_aware": lambda lb, c: f"{lb}에는 시간대(예: +09:00)가 필요합니다.",
    "timezone_naive": lambda lb, c: f"{lb}에는 시간대를 넣지 마세요.",
    # 목록·객체
    "list_type": lambda lb, c: f"{_eun(lb)} 목록이어야 합니다.",
    "too_short": lambda lb, c: f"{_eun(lb)} 최소 {c.get('min_length')}개가 필요합니다.",
    "too_long": lambda lb, c: f"{_eun(lb)} 최대 {c.get('max_length')}개까지 입력할 수 있습니다.",
    "dict_type": lambda lb, c: f"{lb} 형식이 올바르지 않습니다.",
    "model_type": lambda lb, c: f"{lb} 형식이 올바르지 않습니다.",
    "model_attributes_type": lambda lb, c: f"{lb} 형식이 올바르지 않습니다.",
    "extra_forbidden": lambda lb, c: f"{_eun(lb)} 받지 않는 항목입니다.",
    "json_invalid": lambda lb, c: "요청 본문이 올바른 JSON이 아닙니다.",
    "json_type": lambda lb, c: "요청 본문이 올바른 JSON이 아닙니다.",
    # 파일(업로드)
    "bytes_type": lambda lb, c: f"{lb} 파일을 읽을 수 없습니다.",
}

#: 모르는 ``type``의 문장. 영문 원문을 내보내지 않는다(모듈 docstring).
FALLBACK = "{label} 값이 올바르지 않습니다."

_CUSTOM_PREFIXES = ("Value error, ", "Assertion failed, ")


def _custom_message(error: Mapping[str, object]) -> str | None:
    """직접 만든 검증기(``ValueError``)의 문구. 한국어일 때만 쓴다."""
    msg = str(error.get("msg", ""))
    for prefix in _CUSTOM_PREFIXES:
        if msg.startswith(prefix):
            msg = msg[len(prefix) :]
            break
    return msg if _HANGUL.search(msg) else None


def korean_message(error: Mapping[str, object], label: str) -> str:
    """Pydantic 오류 하나를 한국어 문장으로.

    ``label``은 ``field_label()``이 준 한글 라벨이다. 필드가 없는 오류(본문 전체가 JSON이
    아닌 경우 등)는 ``label``이 빈 문자열일 수 있어 「입력값」으로 채운다.
    """
    kind = str(error.get("type", ""))
    label = label or "입력값"
    if kind in ("value_error", "assertion_error"):
        custom = _custom_message(error)
        if custom:
            return custom
    ctx = error.get("ctx") or {}
    builder = _MESSAGES.get(kind)
    if builder is None:
        return FALLBACK.format(label=label)
    return builder(label, ctx if isinstance(ctx, Mapping) else {})


def is_korean(text: str) -> bool:
    """문장에 한글이 있는가 — 가드가 「영문 원문이 새지 않았다」를 볼 때 쓴다."""
    return bool(_HANGUL.search(text))
