"""가입 게이트 (#808 · `API_SPEC §1.2` 「가입 제한」 · `PRD §6.3`).

사내 도구로 확정되어(2026-09-11) 가입을 **허용 도메인 또는 초대 코드**로 제한한다.
권한 분리·데이터 격리가 없으므로(`PRD §5.2`) 들어오는 문이 곧 유일한 경계다.

잠그는 것:

* 둘 중 **하나만** 맞으면 통과 — 도메인이 맞으면 코드가 없어도, 코드가 맞으면 도메인이 달라도
* 도메인 비교는 대소문자·``@`` 앞머리를 무시하되 **정확히 일치**만 — 하위 도메인·접미사 흉내 불가
* 설정이 비면 개발·테스트에서는 열려 있고, **프로덕션에서는 기동 거부**
* 거절 문구가 `PRD §6.3` 표와 문자 단위로 같다

케이스: AT-AUTH-016 (`TEST_PLAN §4.7`)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cii_platform import config
from cii_platform.auth.signup_gate import (
    REJECTED_MESSAGE,
    SignupGate,
    load_signup_gate,
    validate_signup_gate,
)

_PRD = Path(__file__).resolve().parents[1] / "PRD.md"


def _gate(domains: str | None = None, code: str | None = None) -> SignupGate:
    env = {}
    if domains is not None:
        env["SIGNUP_ALLOWED_DOMAINS"] = domains
    if code is not None:
        env["SIGNUP_INVITE_CODE"] = code
    return load_signup_gate(env)


def test_allowed_domain_passes_without_code():
    gate = _gate(domains="bluelog.kr")
    assert gate.allows("captain@bluelog.kr", None)
    assert not gate.allows("captain@gmail.com", None)


def test_invite_code_passes_any_domain():
    gate = _gate(code="harbour-2026-xyz")
    assert gate.allows("guest@gmail.com", "harbour-2026-xyz")
    # 앞뒤 공백은 복사·붙여넣기 실수라 무시한다
    assert gate.allows("guest@gmail.com", "  harbour-2026-xyz ")
    assert not gate.allows("guest@gmail.com", "harbour-2026-xy")
    assert not gate.allows("guest@gmail.com", None)
    assert not gate.allows("guest@gmail.com", "")


def test_either_condition_is_enough_when_both_are_configured():
    gate = _gate(domains="bluelog.kr", code="harbour-2026-xyz")
    assert gate.allows("captain@bluelog.kr", None)
    assert gate.allows("guest@gmail.com", "harbour-2026-xyz")
    assert not gate.allows("guest@gmail.com", "wrong")


def test_domain_list_is_normalised_but_matched_exactly():
    """쉼표 목록 · 공백 · ``@`` 앞머리 · 대소문자를 정리한다. 매칭은 정확히 일치만.

    ``endswith``로 비교하면 ``evilbluelog.kr``·``bluelog.kr.attacker.io``가 통과한다.
    """
    gate = _gate(domains=" @BlueLog.kr , partner.co.kr ,, ")
    assert gate.domains == frozenset({"bluelog.kr", "partner.co.kr"})
    assert gate.allows("a@partner.co.kr", None)
    assert not gate.allows("a@evilbluelog.kr", None)
    assert not gate.allows("a@bluelog.kr.attacker.io", None)
    assert not gate.allows("a@sub.bluelog.kr", None)


def test_unset_gate_is_open():
    """개발·테스트 기본값 — 게이트가 개발 흐름을 막으면 우회 설정이 생긴다."""
    gate = _gate()
    assert gate.is_open
    assert gate.allows("anyone@example.com", None)
    # 공백만 있는 설정은 설정이 없는 것이다
    assert _gate(domains=" , ", code="   ").is_open


def test_production_refuses_to_start_with_an_open_gate(monkeypatch: pytest.MonkeyPatch):
    """조용히 열린 가입문은 `#809`·`#524`와 같은 부류다 — 기동 시점에 끊는다."""
    monkeypatch.setattr(config, "_ENV", "production")
    with pytest.raises(RuntimeError, match="SIGNUP_ALLOWED_DOMAINS"):
        validate_signup_gate({})
    validate_signup_gate({"SIGNUP_INVITE_CODE": "harbour-2026-xyz"})
    validate_signup_gate({"SIGNUP_ALLOWED_DOMAINS": "bluelog.kr"})


def test_real_app_lifespan_runs_the_gate_check(monkeypatch: pytest.MonkeyPatch):
    """배선 — 실제 앱을 기동하면 게이트 검사가 돈다.

    위 검사는 **함수의 규칙**만 본다. ``lifespan``에서 호출을 빠뜨려도 그쪽은 통과한다
    (`test_mail_startup_guard.py`가 메일 가드에 대해 같은 이유로 둔 검사다).
    """
    from fastapi.testclient import TestClient

    from cii_platform.api.main import app

    monkeypatch.setattr(config, "_ENV", "production")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://bluelog.example")
    monkeypatch.delenv("SIGNUP_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("SIGNUP_INVITE_CODE", raising=False)
    with pytest.raises(RuntimeError, match="SIGNUP_ALLOWED_DOMAINS"), TestClient(app):
        pass  # pragma: no cover - 진입 자체가 실패한다

    monkeypatch.setenv("SIGNUP_ALLOWED_DOMAINS", "bluelog.kr")
    with TestClient(app) as client:
        assert client is not None


def test_development_starts_with_an_open_gate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "_ENV", "development")
    validate_signup_gate({})


def test_rejected_message_matches_prd_table():
    """`PRD §6.3` 「회원가입 — 가입 제한」 행과 문자 단위로 같다."""
    text = _PRD.read_text(encoding="utf-8")
    row = re.search(r"^\|\s*회원가입 — 가입 제한\s*\|\s*`([^`]+)`\s*\|", text, re.MULTILINE)
    assert row, "PRD §6.3 표에서 「회원가입 — 가입 제한」 행을 찾지 못했다"
    assert row.group(1) == REJECTED_MESSAGE
