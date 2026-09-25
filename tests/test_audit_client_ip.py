"""감사 로그·세션의 IP는 요청 한도와 **같은 판정**을 쓴다 (`#1889` · `#1483` 후속).

클라우드에서는 요청이 프록시 → 터널 → ``localhost``로 들어와 ``request.client.host``가
전원 터널 주소다. 감사 기록이 그 값을 그대로 적으면 누가 어디서 로그인·변경했는지
구분되지 않는다. 판정은 :func:`rate_limit.client_ip` 하나이고, 감사용
:func:`rate_limit.audit_client_ip`는 「알 수 없음」을 ``None``으로 바꾸기만 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import cii_platform.api.rate_limit as rl

_SRC = Path(__file__).resolve().parents[1] / "src" / "cii_platform"
_SECRET = "s3cret-for-tests"


class _Client:
    def __init__(self, host: str) -> None:
        self.host = host


class _Req:
    def __init__(self, headers: dict[str, str], client_host: str | None = "127.0.0.1") -> None:
        self.headers = headers
        self.client = _Client(client_host) if client_host is not None else None


def _signed(ip: str, secret: str = _SECRET) -> dict[str, str]:
    return {"x-bluelog-client-ip": ip, "x-bluelog-proxy-secret": secret}


def test_signed_header_gives_the_original_ip(monkeypatch) -> None:
    """비밀 값이 맞으면 터널 주소가 아니라 프록시가 실은 원 IP를 적는다."""
    monkeypatch.setattr(rl, "_PROXY_CLIENT_IP_SECRET", _SECRET)
    assert rl.audit_client_ip(_Req(_signed("203.0.113.7"))) == "203.0.113.7"


def test_wrong_secret_falls_back_to_the_socket_peer(monkeypatch) -> None:
    """비밀 값이 틀리면 헤더를 무시하고 소켓 상대를 적는다 — `:8001` 직접 위조를 막는다."""
    monkeypatch.setattr(rl, "_PROXY_CLIENT_IP_SECRET", _SECRET)
    assert rl.audit_client_ip(_Req(_signed("203.0.113.7", "wrong"))) == "127.0.0.1"


def test_no_client_is_null_not_the_word_unknown(monkeypatch) -> None:
    """컬럼이 NULL 허용이다 — 「unknown」이라는 글자를 IP 칸에 적지 않는다."""
    monkeypatch.setattr(rl, "_PROXY_CLIENT_IP_SECRET", "")
    monkeypatch.setattr(rl, "_USE_FORWARDED_FOR", False)
    assert rl.audit_client_ip(_Req({}, client_host=None)) is None


def test_no_route_reads_the_socket_peer_directly() -> None:
    """``request.client.host`` 직접 참조는 판정 함수와 접근 로그의 ``peer`` 두 곳뿐이다.

    다른 자리가 소켓 상대를 직접 읽으면 그 자리의 감사 기록만 다시 터널 주소가 된다.
    """
    allowed = {
        _SRC / "api" / "rate_limit.py",  # 판정 함수 본체
        _SRC / "api" / "middleware.py",  # 접근 로그의 `peer` — 소켓 상대를 따로 남기는 칸
    }
    offenders = [
        f"{path.relative_to(_SRC)}:{number}"
        for path in _SRC.rglob("*.py")
        if path not in allowed
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\.client\.host|getattr\(\s*request\s*,\s*[\"']client", line)
    ]
    assert offenders == []


def test_no_private_copy_of_the_rule_remains() -> None:
    """파일별 ``_client_ip`` 사본이 없다 — 규칙이 한 곳에서만 바뀐다."""
    copies = [
        str(path.relative_to(_SRC))
        for path in (_SRC / "api").rglob("*.py")
        if re.search(r"^def _client_ip\(", path.read_text(encoding="utf-8"), re.M)
    ]
    assert copies == []


def test_forwarded_for_must_be_an_ip_before_it_is_recorded(monkeypatch) -> None:
    """``USE_FORWARDED_FOR=true``여도 첫 항이 IP가 아니면 쓰지 않는다 — 45자 칸을 넘는 값이
    감사 INSERT를 실패시키지 않게, 서명 헤더와 같은 규칙으로 소켓 상대로 내려간다."""
    monkeypatch.setattr(rl, "_PROXY_CLIENT_IP_SECRET", "")
    monkeypatch.setattr(rl, "_USE_FORWARDED_FOR", True)
    assert rl.audit_client_ip(_Req({"x-forwarded-for": "198.51.100.4, 10.0.0.1"})) == "198.51.100.4"
    assert rl.audit_client_ip(_Req({"x-forwarded-for": "x" * 80})) == "127.0.0.1"
    assert rl.audit_client_ip(_Req({"x-forwarded-for": "2001:DB8::1"})) == "2001:db8::1"
