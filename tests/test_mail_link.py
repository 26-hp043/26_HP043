"""메일 링크의 기준 주소 (#429).

인증 메일 링크가 **프론트엔드가 아니라 API 서버**를 가리켜 개발 환경에서 항상 죽던
결함의 회귀 방지다.

이 결함이 오래 숨어 있던 이유는 개발 환경이 콘솔 백엔드라 **로그에서 토큰만 꺼내 쓰면
플로우가 통과**했기 때문이다 — 링크를 실제로 누르는 경로를 아무도 밟지 않았다.
그래서 여기서는 토큰이 아니라 **링크 문자열 자체**를 본다.
"""

from __future__ import annotations

import pytest

from cii_platform import config
from cii_platform.config import public_base_url, validate_public_base_url

API_ORIGIN = "http://localhost:8000/"
FRONTEND = "http://localhost:5173"


def test_configured_url_wins(monkeypatch: pytest.MonkeyPatch):
    """설정이 있으면 요청 주소를 무시한다 — 개발은 두 origin이 다르다."""
    monkeypatch.setenv("APP_PUBLIC_URL", FRONTEND)
    assert public_base_url(API_ORIGIN) == FRONTEND


def test_falls_back_to_request_origin_in_development(monkeypatch: pytest.MonkeyPatch):
    """**개발에서만** 미설정이 요청 주소로 폴백한다.

    `#809` 정정 — 종전 docstring은 *"운영은 nginx 뒤에서 같은 origin이라 이 값이
    정확하다"* 였다. 그 전제가 성립하려면 **`Host` 헤더를 믿을 수 있어야** 하는데,
    믿을 수 없다는 것이 `#809`의 내용이다.
    """
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    monkeypatch.setattr(config, "_ENV", "development")

    assert public_base_url(API_ORIGIN) == "http://localhost:8000"


def test_blank_setting_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch):
    """빈 문자열은 「설정했다」가 아니다 — `.env`에 키만 남기는 경우가 실제로 있다."""
    monkeypatch.setenv("APP_PUBLIC_URL", "   ")
    monkeypatch.setattr(config, "_ENV", "development")

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


# ─────────────────────────────────────────────────────────────────────────────
# Host 헤더 주입 (#809)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "attacker_origin",
    [
        "http://attacker.example/",
        "https://bluelog.example.attacker.test/",
        "http://127.0.0.1:8000/",
    ],
)
def test_host_header_cannot_steer_the_link_in_production(
    monkeypatch: pytest.MonkeyPatch, attacker_origin: str
):
    """**이 이슈의 본체** — 요청 `Host`가 링크를 바꾸지 못한다 (#809).

    종전에는 `APP_PUBLIC_URL`이 없으면 `request.base_url`을 그대로 썼다. 공격자가
    ``Host: attacker.example``로 재설정을 요청하면 피해자는 **정상 발신지에서 온
    정상 문구의 메일**을 받는데 링크만 공격자 도메인이다 — 클릭 한 번에 유효한
    재설정 토큰(1시간)이 넘어간다.

    설정이 있으면 폴백 자체를 보지 않으므로 어떤 `Host`가 와도 결과가 같다.
    """
    monkeypatch.setenv("APP_PUBLIC_URL", "https://bluelog.example")
    monkeypatch.setattr(config, "_ENV", "production")

    assert public_base_url(attacker_origin) == "https://bluelog.example"


def test_production_without_the_setting_refuses_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    """프로덕션 미설정은 **폴백이 아니라 거부**다 (#809).

    폴백이 곧 취약점이었다. 「없으면 요청 주소를 쓴다」가 그대로 「공격자가 정하는
    주소를 쓴다」가 된다.
    """
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    monkeypatch.setattr(config, "_ENV", "production")

    with pytest.raises(RuntimeError, match="APP_PUBLIC_URL"):
        public_base_url("http://attacker.example/")


def test_startup_validation_fails_fast_in_production(monkeypatch: pytest.MonkeyPatch):
    """기동 시점에 끊는다 (#809 · `#524` 선례).

    호출 시점 방어만 두면 드러나는 시점이 「배포 직후」가 아니라 **「첫 사용자가
    비밀번호를 잊은 순간」**이 된다. 그때는 이미 메일이 나간 뒤일 수 있다.
    """
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    monkeypatch.setattr(config, "_ENV", "production")

    with pytest.raises(RuntimeError, match="APP_PUBLIC_URL"):
        validate_public_base_url()


def test_startup_validation_is_silent_in_development(monkeypatch: pytest.MonkeyPatch):
    """개발에서는 막지 않는다 — 개발자가 매번 설정하게 만들 이유가 없다 (#809)."""
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    monkeypatch.setattr(config, "_ENV", "development")

    validate_public_base_url()  # 예외가 나지 않아야 한다


def test_startup_validation_passes_when_configured(monkeypatch: pytest.MonkeyPatch):
    """설정이 있으면 프로덕션에서도 통과한다 — 가드가 늘 막지는 않는다 (#809)."""
    monkeypatch.setenv("APP_PUBLIC_URL", "https://bluelog.example")
    monkeypatch.setattr(config, "_ENV", "production")

    validate_public_base_url()
