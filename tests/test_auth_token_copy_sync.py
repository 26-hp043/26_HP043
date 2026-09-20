"""토큰 경로의 문구·상태 코드 ↔ 정본 (`#1326`).

## 왜 필요한가

두 가지가 조용히 어긋나 있었다.

* **문구** — 인증 메일 재발송이 **비밀번호 재설정 문구**를 돌려 썼다. 화면은 서버가
  준 문구를 그대로 띄우므로(`VerifyBanner.tsx`), 「인증 메일 다시 받기」를 누르면
  **「재설정 안내를 보냈습니다」**가 떴다 — 사용자는 **다른 메일이 온다고 믿는다.**
* **상태 코드** — `VALIDATION_ERROR`에 **400**(`API_SPEC §1.4`는 422), 메일 실패에
  **502**(표에 502 행이 없고 `INTERNAL_ERROR`는 500). 같은 코드에 다른 상태가 붙는
  자리가 이 파일 하나뿐이었고, **검사가 그 값을 그대로 잠그고 있었다.**

## 무엇을 단언하는가

문구는 `PRD §6.3` 표에서 **읽어서** 대조한다 — 검사에 문장을 또 적으면 정본이 바뀔 때
**두 곳을 고쳐야 하고, 한 곳만 고치면 검사가 낡은 문장을 지킨다.**
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cii_platform.api.routes.auth_tokens import (
    RESET_REQUESTED_MESSAGE,
    TOKEN_INVALID_MESSAGE,
    VERIFY_REQUESTED_MESSAGE,
)
from cii_platform.errors import ERROR_HTTP_STATUS

PRD = Path(__file__).resolve().parents[1] / "PRD.md"


def _copy_row(label: str) -> str:
    """`PRD §6.3` 표에서 한 행의 문구를 읽는다."""
    text = PRD.read_text(encoding="utf-8")
    start = text.index("### 6.3 공통 UX 문구")
    section = text[start : text.index("\n### ", start + 10)]
    for line in section.splitlines():
        if line.startswith(f"| {label}"):
            match = re.search(r"\|\s*`([^`]+)`\s*\|", line)
            assert match, f"문구를 읽지 못했다: {line}"
            return match.group(1)
    raise AssertionError(f"§6.3에 「{label}」 행이 없다")


@pytest.mark.parametrize(
    ("label", "constant"),
    [
        ("인증 메일 재발송 결과", VERIFY_REQUESTED_MESSAGE),
        ("비밀번호 재설정 요청 결과", RESET_REQUESTED_MESSAGE),
        ("토큰 만료·사용됨", TOKEN_INVALID_MESSAGE),
    ],
)
def test_the_constant_matches_the_canon_row(label: str, constant: str) -> None:
    assert _copy_row(label) == constant


def test_resend_does_not_reuse_the_reset_sentence() -> None:
    """⚠️ **두 흐름은 오는 메일이 다르다** (`#1326`).

    같은 상수를 가리키면 위 대조는 **두 행이 같은 문장일 때** 통과한다 — 그 상태가
    바로 종전의 결함이었다.
    """
    assert VERIFY_REQUESTED_MESSAGE != RESET_REQUESTED_MESSAGE


def test_the_two_messages_stay_the_same_shape() -> None:
    """뒷문장(스팸함 확인)은 **사용자가 할 일이 같다** — 거기까지 달라질 이유가 없다."""
    tail = "메일이 오지 않으면 스팸함을 확인해 주세요."

    assert VERIFY_REQUESTED_MESSAGE.endswith(tail)
    assert RESET_REQUESTED_MESSAGE.endswith(tail)


@pytest.mark.parametrize(("code", "status"), [("VALIDATION_ERROR", 422), ("INTERNAL_ERROR", 500)])
def test_the_status_comes_from_the_error_code(code: str, status: int) -> None:
    """상태는 **코드가 정한다** (`API_SPEC §1.4`).

    종전에는 라우트가 상태를 인자로 적어 400·502가 나갔다. 인자를 없앴으므로 이
    표가 곧 응답 상태다 — 값이 바뀌면 여기서 먼저 드러난다.
    """
    assert ERROR_HTTP_STATUS[code] == status


def test_the_helper_cannot_be_handed_a_status_at_all() -> None:
    """**갈릴 자리 자체를 지웠는지** 본다 (`#1326`).

    상태를 인자로 받는 한, 어느 호출부가 다시 다른 값을 적어도 위 검사는 통과한다.

    ⚠️ 호출 **모양**(`_error(request, 502, …`)을 찾는 것으로는 부족하다 — 상태를
    뒤쪽 인자로 넘기면 그대로 빠져나간다(실측). **시그니처**를 본다.
    """
    import inspect

    from cii_platform.api.routes import auth_tokens

    parameters = set(inspect.signature(auth_tokens._error).parameters)

    assert parameters == {"request", "code", "message"}, parameters
