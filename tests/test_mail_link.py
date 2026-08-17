"""메일 링크의 기준 주소 (#429).

인증 메일 링크가 **프론트엔드가 아니라 API 서버**를 가리켜 개발 환경에서 항상 죽던
결함의 회귀 방지다.

이 결함이 오래 숨어 있던 이유는 개발 환경이 콘솔 백엔드라 **로그에서 토큰만 꺼내 쓰면
플로우가 통과**했기 때문이다 — 링크를 실제로 누르는 경로를 아무도 밟지 않았다.
그래서 여기서는 토큰이 아니라 **링크 문자열 자체**를 본다.
"""

from __future__ import annotations

import pytest

from cii_platform.config import public_base_url

API_ORIGIN = "http://localhost:8000/"
FRONTEND = "http://localhost:5173"


def test_configured_url_wins(monkeypatch: pytest.MonkeyPatch):
    """설정이 있으면 요청 주소를 무시한다 — 개발은 두 origin이 다르다."""
    monkeypatch.setenv("APP_PUBLIC_URL", FRONTEND)
    assert public_base_url(API_ORIGIN) == FRONTEND


def test_falls_back_to_request_origin(monkeypatch: pytest.MonkeyPatch):
    """미설정이면 요청 주소다.

    운영은 nginx 뒤에서 프론트와 API가 같은 origin이라 이 값이 정확하다 — 설정을
    강제하면 그 값이 실제 서비스 주소와 어긋났을 때 **링크가 조용히 죽는다.**
    """
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    assert public_base_url(API_ORIGIN) == "http://localhost:8000"


def test_blank_setting_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch):
    """빈 문자열은 「설정했다」가 아니다 — `.env`에 키만 남기는 경우가 실제로 있다."""
    monkeypatch.setenv("APP_PUBLIC_URL", "   ")
    assert public_base_url(API_ORIGIN) == "http://localhost:8000"


def test_trailing_slash_is_stripped(monkeypatch: pytest.MonkeyPatch):
    """`//verify-email`이 되면 라우터가 못 찾는다."""
    monkeypatch.setenv("APP_PUBLIC_URL", "https://bluelog.example/")
    assert public_base_url(API_ORIGIN) == "https://bluelog.example"


def test_link_points_at_the_frontend_route(monkeypatch: pytest.MonkeyPatch):
    """**이 이슈의 본체**다 — 링크가 화면이 있는 곳을 가리켜야 한다.

    8000번(API)에는 `/verify-email`이 없어 401이 난다.
    """
    monkeypatch.setenv("APP_PUBLIC_URL", FRONTEND)
    link = f"{public_base_url(API_ORIGIN)}/verify-email?token=abc"

    assert link == "http://localhost:5173/verify-email?token=abc"
    assert ":8000" not in link
