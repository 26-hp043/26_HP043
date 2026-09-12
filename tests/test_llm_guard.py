"""챗봇 가드 둘 — 전송 화이트리스트와 수학 검증 (#120).

케이스: IT-CHAT-001 ~ IT-CHAT-009 · IT-CHAT-050~051 (`TEST_PLAN §3.17`)

``PRD §20 O-12`` 3대 봉쇄 원칙 중 둘을 코드가 실제로 막는지 본다.

* **No-Recall** — 선사 기밀이 외부 LLM으로 나가지 않는가
* **No-Compute** — LLM이 수치를 지어내거나 계산하지 않는가

⚠️ **정본과 코드가 어긋나는 것을 여기서 막는다.** `IT-CHAT-001`이 `PRD §16.3.1`
표를 읽어 코드 상수와 대조한다 — 한쪽만 고치면 여기서 걸린다. 그 가드가 없으면
「정본에는 있는데 코드가 안 거르는」 필드가 조용히 생긴다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cii_platform.services.llm_guard import (
    _DISPLAY_PLACES,
    OUTBOUND_FORBIDDEN_EXAMPLES,
    OUTBOUND_WHITELIST,
    NumberFabricationError,
    OutboundFieldError,
    extract_numbers,
    filter_outbound,
    verify_numbers,
)

_PRD = Path(__file__).resolve().parents[1] / "PRD.md"


def _whitelist_in_prd() -> set[str]:
    """``PRD §16.3.1`` 「보내도 되는 것」 표에서 백틱 코드값을 뽑는다."""
    text = _PRD.read_text(encoding="utf-8")
    start = text.index("#### 16.3.1")
    stop = text.index("**보내지 않는 것**", start)
    body = text[start:stop]
    return {token for token in re.findall(r"`([a-z_]+)`", body)}


def _forbidden_in_prd() -> set[str]:
    text = _PRD.read_text(encoding="utf-8")
    start = text.index("**보내지 않는 것**")
    stop = text.index("좁게 시작하는 이유", start)
    return set(re.findall(r"`([a-z_]+)`", text[start:stop]))


# --- No-Recall (전송 화이트리스트) -------------------------------------------------


def test_whitelist_matches_the_canonical_table():
    """IT-CHAT-001 — 코드 상수가 `PRD §16.3.1` 표와 같다.

    ⚠️ **이 검사가 이 파일의 중심이다.** 정본이 MUST로 목록을 정하는데 코드가 다른
    목록을 쓰면, 정본은 지켜졌다고 보이면서 실제로는 새어 나간다.
    """
    assert _whitelist_in_prd() == set(OUTBOUND_WHITELIST)


def test_forbidden_examples_match_the_canonical_table():
    """IT-CHAT-002 — 「보내지 않는 것」 예시도 정본과 같다.

    이 목록으로 거르지는 않는다(화이트리스트가 거른다). **문서와 코드가 서로를
    가리키게** 해 두는 것이 목적이다.
    """
    assert _forbidden_in_prd() == set(OUTBOUND_FORBIDDEN_EXAMPLES)


def test_allowed_fields_pass_through():
    """IT-CHAT-003 — 허용 필드는 그대로 나간다."""
    payload = {"attained_cii": "4.98", "required_cii": "5.05", "rating": "C"}

    assert filter_outbound(payload) == payload


def test_vessel_name_is_rejected():
    """IT-CHAT-004 — 선박명은 막힌다. `PRD §16.3` MUST의 실체다."""
    with pytest.raises(OutboundFieldError) as exc:
        filter_outbound({"attained_cii": "4.98", "vessel_name": "HANARO"})

    # 무엇이 막혔는지 말한다 — 「막혔다」만 알면 고칠 수 없다.
    assert "vessel_name" in str(exc.value)


def test_an_unknown_field_is_an_error_not_a_silent_drop():
    """IT-CHAT-005 — 목록에 **없는 새 필드**는 조용히 빠지지 않고 터진다.

    ⚠️ 떨어뜨리면 나중에 추가된 필드가 아무도 모르게 새어 나가고, **그 사실을
    알아챌 방법이 없다.** 화이트리스트 방식을 고른 이유가 이것이다.
    """
    with pytest.raises(OutboundFieldError):
        filter_outbound({"some_field_added_next_year": 1})


# --- No-Compute (수학 검증) --------------------------------------------------------


def test_numbers_from_tool_output_pass():
    """IT-CHAT-006 — 도구가 준 수치를 인용한 응답은 통과한다."""
    verify_numbers(
        "C등급입니다. attained 4.98이 required 5.05보다 낮습니다.",
        ['{"attained_cii": "4.98", "required_cii": "5.05", "rating": "C"}'],
    )


def test_a_derived_number_is_blocked():
    """IT-CHAT-007 — **파생 수치가 막힌다.** 빼기도 계산이다.

    도구가 `4.98`과 `5.05`를 줬을 때 모델이 차(`0.07`)를 쓰면 그것은 LLM이 한
    계산이다. 필요한 파생값은 **도구가 내려주어야 한다**(`next_boundary_gap`이
    응답 필드에 있는 이유다).
    """
    with pytest.raises(NumberFabricationError) as exc:
        verify_numbers(
            "여유는 0.07입니다.",
            ['{"attained_cii": "4.98", "required_cii": "5.05"}'],
        )

    assert "0.07" in str(exc.value)


def test_trailing_zeros_are_the_same_number():
    """IT-CHAT-008 — `4.980`과 `4.98`은 같은 값이다.

    표기 차이로 정상 응답을 막으면 가드가 기능을 깎는다. **막아야 하는 것은 표기가
    아니라 출처**다.
    """
    verify_numbers("attained 4.980입니다.", ['{"attained_cii": "4.98"}'])


def test_display_rounding_is_a_notation_difference_not_a_new_value():
    """IT-CHAT-050 — ⚠️ **화면 자릿수로 인용해도 통과한다** (2026-09-13 실측 결함).

    도구는 ``attained_cii``를 **6자리**로 내려주고 화면은 **3자리**로 보인다
    (`services/voyage_cii.SERIALIZATION_DIGITS` vs `DESIGN_SYSTEM §4.1` 🔒).
    종전에는 모델이 화면과 같게 ``4.982``라고 쓰면 **폐기됐다.**

    **면책이 「이 답변은 화면의 계산 결과를 풀어 쓴 것입니다」인데, 화면과 같은
    자릿수로 말할 수 없으면 그 면책이 거짓이 된다.**

    `IT-CHAT-008`이 이미 「막을 것은 표기가 아니라 **출처**」를 세웠다 — 끝자리 0만
    다루고 반올림은 다루지 않아 **같은 성질의 표기 차이 중 한쪽만** 허용하고 있었다.
    """
    tool = ['{"attained_cii": "4.982400", "required_cii": "5.045066"}']
    verify_numbers("attained CII는 4.982입니다.", tool)  # 화면 자릿수(3)
    verify_numbers("required CII는 5.045입니다.", tool)  # 화면 자릿수(3)
    verify_numbers("attained CII는 4.98입니다.", tool)  # 더 줄여도 같은 값


def test_display_rounding_does_not_open_derived_numbers():
    """IT-CHAT-051 — ⚠️ 표기를 넓혀도 **파생 계산은 그대로 막힌다**.

    `IT-CHAT-050`이 넓히는 것은 **같은 값의 다른 표기**뿐이다. 두 값의 차는 어느
    쪽의 반올림도 아니므로 여전히 걸린다 — **빼기도 계산이다.**

    이 검사가 없으면 「표기 허용」이 「계산 허용」으로 번져도 아무도 모른다.
    """
    tool = ['{"attained_cii": "4.982400", "required_cii": "5.045066"}']
    with pytest.raises(NumberFabricationError):
        verify_numbers("required보다 0.06 낮습니다.", tool)  # 차 — 파생
    with pytest.raises(NumberFabricationError):
        verify_numbers("attained CII는 7.31입니다.", tool)  # 지어낸 값
    with pytest.raises(NumberFabricationError):
        verify_numbers("1200해리 항해입니다.", tool)  # 도구가 주지 않은 수


def test_allowed_places_cover_every_display_precision_the_product_uses():
    """IT-CHAT-052 — 허용 자릿수가 **화면이 쓰는 자릿수를 전부 덮는다**.

    ⚠️ **화면 자릿수가 늘면 다시 폐기가 시작된다.** 누군가 CII 표시를 4자리로 바꾸면
    모델이 화면과 같게 말할 때마다 답이 버려지고, 증상은 「챗봇이 가끔 답을 안 준다」로
    나타나 **원인을 찾기 어렵다.**

    그래서 화면 쪽 정본(`frontend/src/display/format.ts` `DISPLAY_DIGITS` —
    `DESIGN_SYSTEM §4.2`가 소유)을 읽어 대조한다. 값을 옮겨 적지 않는다 — 옮겨 적으면
    한쪽만 바뀐다.
    """
    fmt = (
        Path(__file__).resolve().parents[1] / "frontend" / "src" / "display" / "format.ts"
    ).read_text(encoding="utf-8")
    block = fmt.split("export const DISPLAY_DIGITS = {", 1)[1].split("} as const", 1)[0]
    digits = [int(m) for m in re.findall(r"^\s*\w+:\s*(\d+),", block, re.M)]
    assert digits, "DISPLAY_DIGITS를 읽지 못했다 — 형식이 바뀌었는지 확인할 것"
    assert max(digits) <= max(_DISPLAY_PLACES), (
        f"화면 자릿수 최대 {max(digits)} > 허용 {max(_DISPLAY_PLACES)} — "
        "`llm_guard._DISPLAY_PLACES`를 함께 넓힐 것"
    )


def test_years_and_single_digits_do_not_trip_the_guard():
    """IT-CHAT-009 — 연도·한 자리 수는 대조에서 뺀다.

    「2026년」·「3가지」까지 도구 응답에 있어야 한다고 요구하면 **가드가 정상 문장을
    막는다.** ⚠️ 등급 경계·비율처럼 **판단에 쓰이는 수치는 전부 두 자리 이상**이라
    이 예외로 빠지지 않는다.
    """
    verify_numbers("2026년 기준 3가지를 봤습니다. attained는 4.98입니다.", ['{"v": "4.98"}'])

    # 예외가 너무 넓지 않은지 — 두 자리 수는 그대로 걸린다.
    with pytest.raises(NumberFabricationError):
        verify_numbers("12척입니다.", ['{"v": "4.98"}'])


def test_extract_normalizes_thousands_separator():
    """IT-CHAT-009 보조 — 천 단위 쉼표를 떼고 비교한다."""
    assert extract_numbers("12,345.60 톤") == ["12345.6"]


def test_api_key_env_constant_matches_the_literal_that_is_read():
    """IT-CHAT-005 보조 — 문서용 상수와 **실제로 읽는 리터럴**이 같다.

    ⚠️ `api_key()`가 상수 대신 리터럴을 쓰는 이유는 `test_compose_env_wiring`이
    소스에서 `environ.get("리터럴")`을 훑기 때문이다 — **상수를 넣으면 그 가드가
    이 변수를 못 보고**, `.env.example`에 없는 변수가 조용히 생긴다.

    대신 둘이 갈릴 수 있으므로 여기서 묶는다.
    """
    from pathlib import Path

    from cii_platform.llm.provider import API_KEY_ENV

    source = (Path(__file__).resolve().parents[1] / "src/cii_platform/llm/provider.py").read_text(
        encoding="utf-8"
    )

    assert f'os.environ.get("{API_KEY_ENV}"' in source
