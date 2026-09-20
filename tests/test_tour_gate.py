"""둘러보기 접근 코드 게이트 단위 검사 (#1486).

대상은 ``src/cii_platform/auth/tour_gate.py`` 하나다 — DB도 라우트도 거치지 않는다.
라우트 실동작(성공·거절·중복 방지·감사 로그)은 ``test_tour_login_db.py``가 잠근다.

잠그는 것:

1. **fail-closed** — ``TOUR_ACCESS_CODE``가 없거나 빈 값·공백뿐이면
   ``verify_tour_code``는 무엇을 제시해도(빈 코드를 포함해) 언제나 ``False``다. 이것이
   모듈 독스트링이 「이 모듈에서 가장 중요한 성질」로 적은 것이다 — 반대(설정 없으면
   통과)로 바뀌면 배포마다 누구나 관리자 세션을 받는다.
2. 코드가 정확히 맞으면 ``True``. 앞뒤 공백은 strip 후 비교한다(복사·붙여넣기 실수는
   허용).
3. 한 글자만 달라도·대소문자가 달라도·접두사만 맞아도(``"abc"`` vs ``"abcdef"``)
   ``False`` — ``hmac.compare_digest``가 **전체 일치**만 본다는 것을 실측한다.
4. ``provided``가 ``None``·빈 문자열이면, 코드가 설정돼 있어도 ``False``.
5. ``load_tour_code``/``tour_is_enabled``가 미설정·공백·정상값에서 돌려주는 값.

세 함수 모두 ``environ`` 인자로 주입한 딕셔너리만 읽는다 — ``os.environ``은 건드리지
않는다. 실제 프로세스 환경을 바꾸면 그 값이 이 파일 밖의 다른 테스트로 샌다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 둘러보기 접근 코드는 #1486에서 신설된 기능이다)
"""

from __future__ import annotations

import os

from cii_platform.auth.tour_gate import (
    ENV_NAME,
    load_tour_code,
    tour_is_enabled,
    verify_tour_code,
)

_CODE = "harbour-tour-9x"


# --- load_tour_code ----------------------------------------------------------------------


def test_load_tour_code_returns_none_when_env_missing():
    assert load_tour_code({}) is None


def test_load_tour_code_returns_none_when_blank_or_whitespace_only():
    """빈 문자열·공백만 있는 값은 「설정 없음」과 같다."""
    assert load_tour_code({ENV_NAME: ""}) is None
    assert load_tour_code({ENV_NAME: "   "}) is None


def test_load_tour_code_strips_surrounding_whitespace():
    assert load_tour_code({ENV_NAME: f"  {_CODE}  "}) == _CODE


# --- tour_is_enabled -----------------------------------------------------------------------


def test_tour_is_enabled_false_when_unset_or_blank():
    assert tour_is_enabled({}) is False
    assert tour_is_enabled({ENV_NAME: "   "}) is False


def test_tour_is_enabled_true_only_when_code_is_set():
    assert tour_is_enabled({ENV_NAME: _CODE}) is True


# --- verify_tour_code — fail-closed ---------------------------------------------------------


def test_verify_tour_code_rejects_everything_when_env_missing():
    """🔴 fail-closed — 설정 자체가 없으면 무엇을 보내도 거절한다."""
    assert verify_tour_code(_CODE, {}) is False
    assert verify_tour_code("", {}) is False
    assert verify_tour_code(None, {}) is False


def test_verify_tour_code_rejects_everything_when_env_is_blank():
    """🔴 fail-closed — 빈 문자열·공백뿐인 설정도 「설정 없음」과 같이 거절한다.

    ``load_tour_code``가 이 값을 ``None``으로 접기 때문에 일어나는 일이며, 직접
    확인해 둔다 — 언젠가 ``verify_tour_code``가 ``load_tour_code``를 거치지 않고
    환경을 직접 읽도록 바뀌면 이 검사가 먼저 깨진다.
    """
    env = {ENV_NAME: "   "}
    assert verify_tour_code(_CODE, env) is False
    assert verify_tour_code("", env) is False
    assert verify_tour_code(None, env) is False


def test_verify_tour_code_rejects_empty_code_even_when_configured():
    """빈 코드를 제시하는 것은, 설정이 있어도 통과가 아니다."""
    env = {ENV_NAME: _CODE}
    assert verify_tour_code("", env) is False
    assert verify_tour_code(None, env) is False


# --- verify_tour_code — 정상 경로 -----------------------------------------------------------


def test_verify_tour_code_accepts_exact_match():
    env = {ENV_NAME: _CODE}
    assert verify_tour_code(_CODE, env) is True


def test_verify_tour_code_strips_surrounding_whitespace_on_provided_value():
    """복사·붙여넣기로 제시된 값 쪽에 앞뒤 공백·개행이 붙어도 통과한다."""
    env = {ENV_NAME: _CODE}
    assert verify_tour_code(f"  {_CODE}  ", env) is True
    assert verify_tour_code(f"\t{_CODE}\n", env) is True


# --- verify_tour_code — 불일치 --------------------------------------------------------------


def test_verify_tour_code_rejects_single_character_difference():
    env = {ENV_NAME: _CODE}
    assert verify_tour_code(_CODE[:-1] + "y", env) is False


def test_verify_tour_code_is_case_sensitive():
    env = {ENV_NAME: _CODE}
    assert verify_tour_code(_CODE.upper(), env) is False


def test_verify_tour_code_rejects_prefix_match_in_either_direction():
    """접두사만 맞는 것으로는 통과하지 않는다 — 짧은 쪽이 설정이든 제시든 마찬가지다."""
    assert verify_tour_code("abc", {ENV_NAME: "abcdef"}) is False
    assert verify_tour_code("abcdef", {ENV_NAME: "abc"}) is False


# --- 환경 격리 --------------------------------------------------------------------------------


def test_functions_never_touch_the_real_process_environment():
    """세 함수 모두 주입된 ``environ``만 읽는다 — ``os.environ``은 그대로 남는다.

    이 검사가 ``os.environ``을 직접 건드리지 않는 것 자체가 지시 사항이다(다른 검사로
    샐 수 있으므로). 여기서는 실행 전후 값이 그대로인지만 확인해 위 전제를 지킨다.
    """
    sentinel = object()
    before = os.environ.get(ENV_NAME, sentinel)
    verify_tour_code("whatever", {ENV_NAME: _CODE})
    load_tour_code({ENV_NAME: _CODE})
    tour_is_enabled({ENV_NAME: _CODE})
    after = os.environ.get(ENV_NAME, sentinel)
    assert before == after
