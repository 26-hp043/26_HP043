"""메일 발송 백엔드 (#407).

두 구현이 같은 인터페이스를 만족한다. 호출부는 어느 쪽인지 알지 않는다 —
프론트엔드가 demo/api provider를 갈아 끼우는 것과 같은 구조다.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from cii_platform.mail.config import (
    BACKEND_CONSOLE,
    MailSettings,
    load_mail_settings,
)
from cii_platform.mail.message import MailDeliveryError, MailMessage

_log = logging.getLogger(__name__)


class Mailer(Protocol):
    """메일 발송 인터페이스."""

    async def send(self, message: MailMessage) -> None:
        """한 통을 보낸다.

        :raises MailDeliveryError: 보내지 못했을 때.
        """
        ...


class ConsoleMailer:
    """메일을 **로그로만 출력**한다 — 개발·테스트용.

    ## 왜 필요한가

    개발자가 SMTP 자격증명 없이도 **가입 → 인증 메일 → 링크 클릭** 전체 플로우를
    돌릴 수 있어야 한다. 인증 링크를 로그에서 복사해 붙이면 된다.

    `should_register_dev_auth()`가 `APP_ENV != production`에서 개발 편의를 여는 것과
    같은 패턴이며, **프로덕션에서는 `load_mail_settings()`가 기동을 막는다.**
    그 검증은 `api/main.py`의 `lifespan`이 기동 시점에 부른다 — 종전에는
    `get_mailer()`가 라우트 안에서 처음 불려 **첫 발송 시도에서야** 돌았다 (`#524`).
    """

    def __init__(self, settings: MailSettings) -> None:
        self._settings = settings

    async def send(self, message: MailMessage) -> None:
        # 인증 링크가 본문에 들어가므로 본문을 그대로 남긴다. 개발 환경 전용이고,
        # 프로덕션에서는 이 백엔드 자체가 기동을 막으므로 자격증명 유출 경로가 아니다.
        _log.warning(
            "[MAIL:console] 실제로 보내지 않았습니다\n"
            "  From    : %s\n"
            "  To      : %s\n"
            "  Subject : %s\n"
            "  ---\n%s",
            self._settings.mail_from,
            message.to,
            message.subject,
            message.body,
        )


class SmtpMailer:
    """SMTP로 실제 발송한다.

    ## 예외를 `MailDeliveryError`로 옮긴다

    호출부가 `aiosmtplib`의 예외 계층을 알 필요가 없다. 알게 두면 백엔드를 바꿀 때
    호출부가 함께 바뀐다 — 그러면 인터페이스를 나눈 의미가 없다.

    **원인 예외는 `__cause__`로 보존한다.** 버리면 무엇이 끊겼는지(자격증명·네트워크·
    수신 거부) 알 수 없다.
    """

    def __init__(self, settings: MailSettings) -> None:
        self._settings = settings

    async def send(self, message: MailMessage) -> None:
        # import를 함수 안에 둔다 — console 백엔드만 쓰는 환경(테스트·개발)에서
        # aiosmtplib이 없어도 모듈 import가 실패하지 않게 한다.
        try:
            import aiosmtplib
        except ImportError as exc:  # pragma: no cover - 의존성 누락은 배포 문제다
            raise MailDeliveryError(
                "aiosmtplib이 설치되지 않아 SMTP 발송을 할 수 없습니다.", cause=exc
            ) from exc

        settings = self._settings
        payload = EmailMessage()
        payload["From"] = settings.mail_from
        payload["To"] = message.to
        payload["Subject"] = message.subject
        payload.set_content(message.body)

        try:
            await aiosmtplib.send(
                payload,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=settings.smtp_use_tls,
            )
        except Exception as exc:  # noqa: BLE001 — 라이브러리 예외 계층을 노출하지 않는다
            raise MailDeliveryError(
                f"메일을 보내지 못했습니다: {settings.smtp_host}:{settings.smtp_port}",
                cause=exc,
            ) from exc


def create_mailer(settings: MailSettings) -> Mailer:
    """설정에 맞는 백엔드를 만든다."""
    if settings.backend == BACKEND_CONSOLE:
        return ConsoleMailer(settings)
    return SmtpMailer(settings)


@lru_cache(maxsize=1)
def get_mailer() -> Mailer:
    """프로세스 공용 mailer.

    설정은 환경변수에서 오고 프로세스 수명 동안 바뀌지 않으므로 매번 만들 이유가
    없다. `health.py`의 `_app_version()`이 같은 방식을 쓴다.

    **설정 오류는 여기서 즉시 드러난다** — `load_mail_settings()`가 프로덕션 +
    console 조합에서 `RuntimeError`를 던진다.
    """
    return create_mailer(load_mail_settings())
