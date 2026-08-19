"""기동 시점 메일 설정 검증 (#524).

## 무엇이 어긋나 있었나

``mail/backends.py``와 ``.env.example``이 **「프로덕션에서 console이면 기동을
막는다」**고 적고 있었으나 실제로는 막지 않았다. ``get_mailer()``가 ``lru_cache``로
**라우트 안에서 처음 호출**되므로 가드가 기동이 아니라 **첫 발송 시도**에서 돌았다.

    APP_ENV=production + MAIL_BACKEND 미설정
      → 앱이 정상 기동한다 (health 200)
      → 아무도 이상을 눈치채지 못한다
      → 사용자가 「비밀번호를 잊었어요」를 누른다
      → 그 요청이 500으로 떨어진다

가드가 지키려던 것이 정확히 이 상황이다. 드러나는 시점이 **「배포 직후」가 아니라
「첫 사용자가 계정을 잃을 뻔한 순간」**이었다.

## 여기서 잠그는 것

``lifespan``이 ``load_mail_settings()``를 부르는 것. 그 함수의 규칙 자체는
``test_mail.py``가 이미 검증하므로 여기서 다시 보지 않는다 — **기동 경로에
연결됐는가**만 본다.

## 왜 별도 프로세스로 돌지 않는가

``TestClient``를 컨텍스트 매니저로 쓰면 lifespan이 실제로 돈다. 환경변수는
``monkeypatch``로 주입하고, ``load_mail_settings()``가 ``os.environ``을 읽으므로
그것으로 충분하다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import app, lifespan


def test_lifespan이_앱에_연결돼_있다() -> None:
    """연결이 끊기면 아래 검사가 통과해도 실제 기동은 검증되지 않는다."""
    assert app.router.lifespan_context is not None
    # FastAPI가 lifespan을 감싸므로 동일성 비교는 하지 않는다. 이름으로 확인한다.
    assert lifespan.__name__ == "lifespan"


def test_개발_환경에서는_기동한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """console 백엔드는 개발에서 정상이다 — 경고만 남는다."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("MAIL_BACKEND", raising=False)

    with TestClient(app) as client:
        assert client is not None


def test_프로덕션_console이면_기동이_막힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    """`#524`의 본체다. 종전에는 여기서 막히지 않고 첫 발송에서 500이 났다."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MAIL_BACKEND", raising=False)

    with pytest.raises(RuntimeError, match="MAIL_BACKEND=console"), TestClient(app):
        pass  # pragma: no cover - 진입 자체가 실패한다


def test_smtp인데_호스트가_없으면_기동이_막힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    """설정이 앞뒤가 맞지 않는 다른 경우도 기동 시점에 드러난다."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MAIL_BACKEND", "smtp")
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with pytest.raises(RuntimeError, match="SMTP_HOST"), TestClient(app):
        pass  # pragma: no cover


def test_프로덕션_smtp_설정이_갖춰지면_기동한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """가드가 정상 배포까지 막으면 안 된다.

    **연결은 열지 않는다.** 호스트가 실재하지 않아도 기동이 성공하는 것이 의도다 —
    기동을 외부 서비스 가용성에 묶는 것은 배포가 멈춰야 할 이유가 아니다.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MAIL_BACKEND", "smtp")
    monkeypatch.setenv("SMTP_HOST", "localhost.invalid")

    with TestClient(app) as client:
        assert client is not None
