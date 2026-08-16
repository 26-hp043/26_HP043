"""메일 발송 설정 (#407).

`config.py`가 ``DATABASE_URL``에 적용한 것과 **같은 원칙**을 따른다 — 프로덕션에서
설정이 없으면 조용히 개발용 기본값으로 폴백하지 않고 **기동 시점에 실패한다**.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

_log = logging.getLogger(__name__)

#: 로그로만 출력하는 개발용 백엔드.
BACKEND_CONSOLE = "console"
#: 실제 SMTP 발송.
BACKEND_SMTP = "smtp"

_VALID_BACKENDS = frozenset({BACKEND_CONSOLE, BACKEND_SMTP})

#: 개발 기본 발신자. 실제로 나가지 않으므로 도달 가능한 주소일 필요가 없다.
_DEFAULT_FROM = "BlueLog <no-reply@localhost>"


@dataclass(frozen=True)
class MailSettings:
    backend: str
    mail_from: str
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True


def _as_bool(raw: str | None, *, default: bool) -> bool:
    """환경변수는 전부 문자열이라 ``bool("false")``가 ``True``가 되는 함정이 있다."""
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_mail_settings(env: dict[str, str] | None = None) -> MailSettings:
    """환경변수에서 설정을 읽는다.

    ``env``는 테스트 주입용이다 — 전역 ``os.environ``을 건드리지 않고 검증할 수 있게
    한다(`session.py`·`theme.ts`와 같은 주입 패턴).

    :raises RuntimeError: 프로덕션인데 설정이 개발용일 때. 아래 docstring 참조.
    """
    source = os.environ if env is None else env
    app_env = source.get("APP_ENV", "development")
    backend = source.get("MAIL_BACKEND", BACKEND_CONSOLE).strip().lower()

    if backend not in _VALID_BACKENDS:
        raise RuntimeError(
            f"MAIL_BACKEND 값이 올바르지 않습니다: {backend!r}. "
            f"허용: {', '.join(sorted(_VALID_BACKENDS))}"
        )

    #
    # 프로덕션에서 console이면 기동을 막는다.
    #
    # **가장 위험한 실패는 「운영인데 메일이 로그로만 나가고 아무도 모르는 것」이다.**
    # 비밀번호 재설정 메일이 안 가면 사용자가 계정을 잃는다. 그 실패는 조용해서
    # 사용자가 문의할 때까지 드러나지 않는다.
    #
    # DATABASE_URL이 프로덕션에서 폴백하지 않는 것과 같은 판단이다(config.py).
    #
    if app_env == "production" and backend == BACKEND_CONSOLE:
        raise RuntimeError(
            "MAIL_BACKEND=console은 프로덕션에서 사용할 수 없습니다 "
            "(APP_ENV=production). 콘솔 백엔드는 메일을 로그로만 출력하므로 "
            "비밀번호 재설정 메일이 사용자에게 도달하지 않습니다. "
            "MAIL_BACKEND=smtp와 SMTP_HOST를 설정하십시오."
        )

    mail_from = source.get("MAIL_FROM", "").strip() or _DEFAULT_FROM

    if backend == BACKEND_CONSOLE:
        if app_env != "production":
            _log.warning("MAIL_BACKEND=console — 메일을 실제로 보내지 않고 로그로 출력합니다.")
        return MailSettings(backend=backend, mail_from=mail_from)

    host = source.get("SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("MAIL_BACKEND=smtp인데 SMTP_HOST가 설정되지 않았습니다.")

    raw_port = source.get("SMTP_PORT", "587").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError(f"SMTP_PORT가 정수가 아닙니다: {raw_port!r}") from exc

    return MailSettings(
        backend=backend,
        mail_from=mail_from,
        smtp_host=host,
        smtp_port=port,
        smtp_user=source.get("SMTP_USER") or None,
        smtp_password=source.get("SMTP_PASSWORD") or None,
        smtp_use_tls=_as_bool(source.get("SMTP_USE_TLS"), default=True),
    )
