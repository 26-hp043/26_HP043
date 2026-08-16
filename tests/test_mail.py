"""메일 발송 층 검증 (#407).

이 이슈의 위험은 발송 자체가 아니라 **설정 실수**에 있다. 가장 비싼 실패는
「운영인데 메일이 로그로만 나가고 아무도 모르는 것」이므로, 그 조합에서 기동이
막히는지를 가장 먼저 고정한다.

DB도 네트워크도 쓰지 않는다 — 설정은 주입하고 SMTP는 대역으로 바꾼다.
"""

from __future__ import annotations

import logging

import pytest

from cii_platform.mail.backends import ConsoleMailer, SmtpMailer, create_mailer
from cii_platform.mail.config import (
    BACKEND_CONSOLE,
    BACKEND_SMTP,
    MailSettings,
    load_mail_settings,
)
from cii_platform.mail.message import MailDeliveryError, MailMessage
from cii_platform.mail.templates import email_verification, password_reset

# ─────────────────────────────────────────────────────────────────────────────
# 설정 — 프로덕션 가드
# ─────────────────────────────────────────────────────────────────────────────


def test_default_backend_is_console():
    """개발자가 SMTP 자격증명 없이도 전체 플로우를 돌릴 수 있어야 한다."""
    settings = load_mail_settings({})
    assert settings.backend == BACKEND_CONSOLE


def test_production_with_console_backend_fails_to_start():
    """가장 위험한 조합이다.

    운영인데 콘솔이면 비밀번호 재설정 메일이 로그로만 나가고, 사용자는 계정을
    잃는다. 그 실패는 조용해서 문의가 올 때까지 드러나지 않는다.
    `DATABASE_URL`이 프로덕션에서 폴백하지 않는 것과 같은 판단이다.
    """
    with pytest.raises(RuntimeError, match="프로덕션에서 사용할 수 없습니다"):
        load_mail_settings({"APP_ENV": "production"})


def test_production_with_smtp_backend_is_allowed():
    settings = load_mail_settings(
        {
            "APP_ENV": "production",
            "MAIL_BACKEND": "smtp",
            "SMTP_HOST": "smtp.example.com",
            "MAIL_FROM": "BlueLog <no-reply@example.com>",
        }
    )
    assert settings.backend == BACKEND_SMTP
    assert settings.smtp_host == "smtp.example.com"


def test_smtp_backend_requires_host():
    """호스트 없이 smtp를 켜면 발송 시점이 아니라 기동 시점에 막는다."""
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        load_mail_settings({"MAIL_BACKEND": "smtp"})


def test_unknown_backend_is_rejected():
    with pytest.raises(RuntimeError, match="MAIL_BACKEND"):
        load_mail_settings({"MAIL_BACKEND": "carrier-pigeon"})


def test_port_must_be_an_integer():
    with pytest.raises(RuntimeError, match="SMTP_PORT"):
        load_mail_settings({"MAIL_BACKEND": "smtp", "SMTP_HOST": "h", "SMTP_PORT": "오백팔십칠"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("1", True), ("on", True), ("false", False), ("0", False)],
)
def test_use_tls_parses_strings_not_truthiness(raw: str, expected: bool):
    """환경변수는 전부 문자열이라 ``bool("false")``가 ``True``가 되는 함정이 있다."""
    settings = load_mail_settings({"MAIL_BACKEND": "smtp", "SMTP_HOST": "h", "SMTP_USE_TLS": raw})
    assert settings.smtp_use_tls is expected


def test_backend_selection(monkeypatch: pytest.MonkeyPatch):
    console = create_mailer(MailSettings(backend=BACKEND_CONSOLE, mail_from="a@b"))
    smtp = create_mailer(MailSettings(backend=BACKEND_SMTP, mail_from="a@b", smtp_host="h"))
    assert isinstance(console, ConsoleMailer)
    assert isinstance(smtp, SmtpMailer)


# ─────────────────────────────────────────────────────────────────────────────
# 메시지
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_recipient_is_rejected_at_construction():
    """발송 시점이 아니라 호출 시점에 막는 편이 원인을 찾기 쉽다."""
    with pytest.raises(ValueError, match="수신자"):
        MailMessage(to="  ", subject="s", body="b")


def test_empty_subject_is_rejected():
    with pytest.raises(ValueError, match="제목"):
        MailMessage(to="a@b", subject="", body="b")


# ─────────────────────────────────────────────────────────────────────────────
# 백엔드 동작
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_console_mailer_logs_and_does_not_raise(caplog: pytest.LogCaptureFixture):
    mailer = ConsoleMailer(MailSettings(backend=BACKEND_CONSOLE, mail_from="from@x"))
    with caplog.at_level(logging.WARNING):
        await mailer.send(MailMessage(to="to@x", subject="제목", body="본문 링크"))

    text = caplog.text
    # 개발자가 로그에서 인증 링크를 복사해 쓸 수 있어야 한다.
    assert "to@x" in text
    assert "제목" in text
    assert "본문 링크" in text


@pytest.mark.asyncio
async def test_smtp_failure_is_wrapped(monkeypatch: pytest.MonkeyPatch):
    """라이브러리 예외 계층을 호출부에 노출하지 않는다.

    노출하면 백엔드를 바꿀 때 호출부가 함께 바뀌고, 인터페이스를 나눈 의미가 없다.
    """
    import aiosmtplib

    async def boom(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("연결 거부")

    monkeypatch.setattr(aiosmtplib, "send", boom)

    mailer = SmtpMailer(
        MailSettings(backend=BACKEND_SMTP, mail_from="f@x", smtp_host="h", smtp_port=25)
    )
    with pytest.raises(MailDeliveryError) as exc:
        await mailer.send(MailMessage(to="t@x", subject="s", body="b"))

    # 원인을 버리지 않는다 — 무엇이 끊겼는지 알 수 없게 된다.
    assert isinstance(exc.value.__cause__, ConnectionRefusedError)


@pytest.mark.asyncio
async def test_smtp_sends_expected_payload(monkeypatch: pytest.MonkeyPatch):
    import aiosmtplib

    captured: dict[str, object] = {}

    async def capture(payload: object, **kwargs: object) -> None:
        captured["payload"] = payload
        captured.update(kwargs)

    monkeypatch.setattr(aiosmtplib, "send", capture)

    mailer = SmtpMailer(
        MailSettings(
            backend=BACKEND_SMTP,
            mail_from="BlueLog <no-reply@x>",
            smtp_host="smtp.x",
            smtp_port=587,
            smtp_user="u",
            smtp_password="p",
        )
    )
    await mailer.send(MailMessage(to="t@x", subject="제목", body="본문"))

    payload = captured["payload"]
    assert payload["To"] == "t@x"  # type: ignore[index]
    assert payload["From"] == "BlueLog <no-reply@x>"  # type: ignore[index]
    assert captured["hostname"] == "smtp.x"
    assert captured["port"] == 587


# ─────────────────────────────────────────────────────────────────────────────
# 템플릿
# ─────────────────────────────────────────────────────────────────────────────


def test_verification_mail_carries_the_link_and_expiry():
    message = email_verification(to="u@x", verify_url="https://app/verify?t=abc")
    assert "https://app/verify?t=abc" in message.body
    assert "24시간" in message.body


def test_reset_mail_warns_about_session_invalidation():
    """재설정하면 기존 세션이 모두 끊긴다는 사실을 미리 알린다."""
    message = password_reset(to="u@x", reset_url="https://app/reset?t=abc")
    assert "https://app/reset?t=abc" in message.body
    assert "1시간" in message.body
    assert "로그아웃" in message.body


@pytest.mark.parametrize(
    ("factory", "url_kwarg"),
    [(email_verification, "verify_url"), (password_reset, "reset_url")],
)
def test_both_mails_tell_the_recipient_what_to_do_if_they_did_not_request_it(
    factory, url_kwarg: str
):
    """타인이 남의 주소로 요청했을 때 수신자가 상황을 알 수 있어야 한다."""
    message = factory(to="u@x", **{url_kwarg: "https://app/x"})
    assert "무시" in message.body
