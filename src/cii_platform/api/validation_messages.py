"""Pydantic 검증 오류 타입 → 한국어 문구 (#900 · ``API_SPEC`` 언어 규정).

``API_SPEC`` §1.3.2 언어 규정은 ``error.message``·``details[].message``를
``field_label``과 같은 한국어로 적고, 프레임워크 영문 원문(``'Not Found'``뿐 아니라
Pydantic의 ``'String should have at most 100 characters'``까지)을 그대로 내보내지
않는다고 못박았다. 서비스 계층이 직접 던지는 검증 문구는 처음부터 한국어였지만,
Pydantic 422를 옮기는 :func:`~cii_platform.api.error_handlers._validation_details`는
원문을 ``str(error["msg"])``으로 실어 보내 그 규정을 지키지 않았다.

## 왜 타입별 매핑인가

Pydantic v2는 오류를 ``type``(``missing``·``string_too_long``…)으로 분류하고 문구는
영어로 만든다. 문구를 문장 단위로 번역하면 같은 타입이 상황마다 다르게 번역되고,
타입은 **유한한 목록**이라 표로 덮는 쪽이 결정적이다. 실측 근거는 테스트
``tests/test_korean_validation_422.py``의 타입 실측 케이스다 — 이 표의 키가 실제
Pydantic이 내는 타입인지 매 테스트 실행마다 확인된다.

## ``value_error``는 원문을 지킨다

``field_validator``가 직접 던지는 ``value_error``의 ``msg``는 **우리 코드가 적은
문구**다(예: ``random_seed는 정수여야 합니다``). 서비스 계층 문구와 같은 성격이므로
매핑 표를 타지 않고 그대로 흘린다 — 우리 문구를 다시 우리 문구로 바꾸는 계층은
없어도 된다.

## 미매핑 타입의 폴백

모르는 타입이 와도 **영문을 내보내지 않는다**(이슈 #900 완료 기준). 한국어 폴백
문구로 내리고, 서버 로그에 원문 타입과 문구를 남겨 개발자가 표를 확장할 수 있게
한다. 조용히 폴백만 쓰면 새 타입이 생겨도 아무도 모른다 — 폴백은 알림과 함께다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: 폴백 문구. 라벨이 비어 있으면(JSON 파싱 실패처럼 필드를 특정할 수 없으면)
#: 라벨 자리를 비운다 — "값을 확인해 주세요"만으로도 무엇을 고쳐야 하는지는
#: 알 수 없지만, 영문 원문보다는 낫고 잘못된 안내는 아니다.
FALLBACK_MESSAGE = "{label} 값을 확인해 주세요."


def _has_final_consonant(char: str) -> bool | None:
    """한글 글자 하나가 받침을 가지는지. 한글이 아니면 ``None``.

    유니코드 한글 음절(U+AC00~)의 배열은 (초성, 중성, 종성) 순이고, 코드값에서
    받침 여부는 28로 나눈 나머지로 가린다. 한글이 아닌 글자(라틴·숫자)는 조사를
    기계적으로 고를 수 없어 ``None`` — 호출자가 병기형(「은(는)」)으로 갈린다.
    """
    code = ord(char) - 0xAC00
    if not 0 <= code < 11172:
        return None
    return code % 28 > 0


def josa(word: str, pair: tuple[str, str]) -> str:
    """단어 끝에 맞는 조사를 고른다. ``josa("비밀번호", ("을", "를"))`` → ``"를"``.

    받침 있음 → 앞 원소(을/은/이), 받침 없음 → 뒤 원소(를/는/가). 한글이 아닌
    글자로 끝나면 어느 쪽이 맞는지 정할 수 없으므로 병기형 ``"을(를)"``을 쓴다 —
    프론트엔드 필드명(``bogus``)이 그대로 라벨로 내려오는 ``extra_forbidden``이
    실제로 그렇다.
    """
    if not word:
        return f"{pair[0]}({pair[1]})"
    final = _has_final_consonant(word[-1])
    if final is None:
        return f"{pair[0]}({pair[1]})"
    return pair[0] if final else pair[1]


def _subject(label: str) -> str:
    """「라벨 + 은/는」 형태. 조사 선택이 문장의 첫 걸음이라 별도 함수로 둔다."""
    return f"{label}{josa(label, ('은', '는'))}"


def _number(value: Any) -> str:
    """``ctx``의 수치를 문구에 싣는 표기. ``Decimal('1.0')`` → ``'1.0'``.

    ``str()``과 같지만 값의 종류(Decimal·int)를 여기서만 의식하게 하려고 문턱을
    둔다. 천단위 구분자는 붙이지 않는다 — 한계값 안내는 형식보다 정확값이 먼저다.
    """
    return str(value)


def _numeric_message(label: str, ctx: dict[str, Any]) -> str:
    return f"{_subject(label)} 숫자여야 합니다."


def _format_message(label: str, ctx: dict[str, Any]) -> str:
    return f"{label} 형식이 올바르지 않습니다."


def _datetime_message(label: str, ctx: dict[str, Any]) -> str:
    return f"{label} 날짜·시각 형식이 올바르지 않습니다."


def _at_least(label: str, ctx: dict[str, Any], key: str, unit: str) -> str:
    return f"{_subject(label)} {_number(ctx[key])}{unit} 이상이어야 합니다."


def _at_most(label: str, ctx: dict[str, Any], key: str, unit: str) -> str:
    return f"{_subject(label)} {_number(ctx[key])}{unit} 이하여야 합니다."


def _more_than(label: str, ctx: dict[str, Any], key: str) -> str:
    return f"{_subject(label)} {_number(ctx[key])}보다 커야 합니다."


def _less_than(label: str, ctx: dict[str, Any], key: str) -> str:
    return f"{_subject(label)} {_number(ctx[key])}보다 작아야 합니다."


#: 타입 → 문구 생성기. 시그니처는 (라벨, ``ctx``)로 통일한다.
#:
#: ``ctx`` 키(``max_length`` 등)는 Pydantic v2가 정하는 이름이며, 실측 테스트가
#: 키 이름의 드리프트를 잡는다.
_TYPE_MESSAGES: dict[str, Callable[[str, dict[str, Any]], str]] = {
    "missing": lambda label, ctx: f"{label}{josa(label, ('을', '를'))} 입력해 주세요.",
    "string_too_long": lambda label, ctx: _at_most(label, ctx, "max_length", "자"),
    "string_too_short": lambda label, ctx: _at_least(label, ctx, "min_length", "자"),
    "too_short": lambda label, ctx: _at_least(label, ctx, "min_length", "개"),
    "too_long": lambda label, ctx: _at_most(label, ctx, "max_length", "개"),
    "string_pattern_mismatch": _format_message,
    "extra_forbidden": lambda label, ctx: f"{_subject(label)} 허용되지 않는 필드입니다.",
    "json_invalid": lambda label, ctx: "요청 본문이 올바른 JSON이 아닙니다.",
    "int_parsing": _numeric_message,
    "float_parsing": _numeric_message,
    "decimal_parsing": _numeric_message,
    "uuid_parsing": _format_message,
    "datetime_parsing": _datetime_message,
    "datetime_from_date_parsing": _datetime_message,
    "bool_parsing": lambda label, ctx: f"{_subject(label)} true 또는 false여야 합니다.",
    "greater_than": lambda label, ctx: _more_than(label, ctx, "gt"),
    "greater_than_equal": lambda label, ctx: _at_least(label, ctx, "ge", ""),
    "less_than": lambda label, ctx: _less_than(label, ctx, "lt"),
    "less_than_equal": lambda label, ctx: _at_most(label, ctx, "le", ""),
    "literal_error": lambda label, ctx: f"{label} 값이 올바르지 않습니다.",
    "enum": lambda label, ctx: f"{label} 값이 올바르지 않습니다.",
    "finite_number": lambda label, ctx: f"{_subject(label)} 유한한 숫자여야 합니다.",
    "multiple_of": lambda label, ctx: _multiple_of(label, ctx),
}


def _multiple_of(label: str, ctx: dict[str, Any]) -> str:
    return f"{_subject(label)} {_number(ctx['multiple_of'])}의 배수여야 합니다."

#: ``*_type`` 계열(``string_type``·``int_type``·``model_type``…)은 끝 접미사로
#: 분류한다 — 종류가 늘어나도 목록을 다시 적지 않게. 전부 같은 문구다.
_TYPE_SUFFIX = "_type"

#: 우리 코드가 직접 적은 문구를 가진 타입. 매핑 표를 타지 않고 원문을 쓴다.
_CUSTOM_MESSAGE_TYPES = frozenset({"value_error"})


def korean_validation_message(error: dict[str, Any], label: str) -> str:
    """Pydantic 오류 하나를 한국어 문구로 바꾼다.

    Args:
        error: ``exc.errors()``의 한 항목(``type``·``msg``·``ctx`` 포함).
        label: 이미 한국어로 확보한 ``field_label``. 문구의 주어로 쓴다.

    미매핑 타입은 영문을 내보내지 않고 폴백 문구로 내린다(#900 완료 기준).
    그리고 로그를 남긴다 — 폴백에 도달한 타입은 매핑 표의 구멍이고, 조용히
    지나가면 새 타입이 생겨도 아무도 표를 확장하지 않는다.
    """
    error_type = str(error.get("type", ""))
    if error_type in _CUSTOM_MESSAGE_TYPES:
        return str(error.get("msg", "")) or FALLBACK_MESSAGE.format(label=label)

    factory = _TYPE_MESSAGES.get(error_type)
    if factory is not None:
        return factory(label, dict(error.get("ctx") or {}))
    if error_type.endswith(_TYPE_SUFFIX):
        return _format_message(label, {})
    logger.warning(
        "Pydantic 오류 타입 '%s'에 한국어 문구가 없어 폴백을 썼습니다 (원문: %s)",
        error_type,
        error.get("msg"),
    )
    return FALLBACK_MESSAGE.format(label=label)
