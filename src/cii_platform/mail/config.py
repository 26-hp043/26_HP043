"""메일 발송 설정 (#407).

`config.py`가 ``DATABASE_URL``에 적용한 것과 **같은 원칙**을 따른다 — 프로덕션에서
설정이 없으면 조용히 개발용 기본값으로 폴백하지 않고 **기동 시점에 실패한다**.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from cii_platform.config import is_production_env, normalize_app_env

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


#: ``_as_bool``이 참·거짓으로 읽는 값. **이 밖의 값은 거부한다** (#868).
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _as_bool(raw: str | None, *, name: str, default: bool) -> bool:
    """환경변수는 전부 문자열이라 ``bool("false")``가 ``True``가 되는 함정이 있다.

    **모르는 값은 기본값으로 폴백하지 않고 거부한다** (#868). 종전에는 참으로
    읽는 목록에 없으면 전부 거짓이었다 — ``SMTP_USE_TLS=enabled``·``Y``·``TLS``가
    **오류도 경고도 없이 「끔」**이 됐다. 그 스위치가 꺼지면 SMTP 자격증명과
    비밀번호 재설정·이메일 인증 토큰 링크가 평문으로 나가는데, **메일은 정상
    도착하므로 배포 후에도 드러나지 않는다.**

    같은 파일의 ``MAIL_BACKEND``·``SMTP_PORT``는 이미 모르는 값을 ``RuntimeError``로
    막는다. 이 함수만 fail-open이었다 — 모듈 docstring이 선언한 「프로덕션에서
    설정이 없으면 조용히 개발용 기본값으로 폴백하지 않고 기동 시점에 실패한다」를
    보안 스위치 하나가 깨고 있었다.

    ``False``는 **정당한 선택**이다(465 포트 implicit TLS 등). 그래서 「거짓으로
    읽는 값」을 따로 두고, 그 목록에도 없는 것만 거부한다.
    """
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise RuntimeError(
        f"{name} 값이 올바르지 않습니다: {raw!r}. "
        f"참: {', '.join(sorted(_TRUE_VALUES))} · "
        f"거짓: {', '.join(sorted(_FALSE_VALUES))}"
    )


def load_mail_settings(env: dict[str, str] | None = None) -> MailSettings:
    """환경변수에서 설정을 읽는다.

    ``env``는 테스트 주입용이다 — 전역 ``os.environ``을 건드리지 않고 검증할 수 있게
    한다(`session.py`·`theme.ts`와 같은 주입 패턴).

    :raises RuntimeError: 프로덕션인데 설정이 개발용일 때. 아래 docstring 참조.
    :raises RuntimeError: ``APP_ENV``가 허용값이 아닐 때 (#810).
    """
    source = os.environ if env is None else env
    # `APP_ENV`를 여기서 다시 해석하지 않는다 (#810). 종전에는 원문을 그대로 받아
    # 아래에서 `== "production"`으로 비교했고, 그래서 `APP_ENV=Production`이면
    # **프로덕션인데 console 백엔드 가드가 발동하지 않았다** — 재설정 메일이 로그로만
    # 나가고 사용자는 계정을 잃는다. `config.py`가 `os.environ`을 읽는 반면 이 함수는
    # 주입 dict를 받으므로 `config._ENV`를 쓸 수 없어, 해석 함수 쪽을 공유한다.
    app_env = normalize_app_env(source.get("APP_ENV"))
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
    if is_production_env(app_env) and backend == BACKEND_CONSOLE:
        raise RuntimeError(
            "MAIL_BACKEND=console은 프로덕션에서 사용할 수 없습니다 "
            "(APP_ENV=production). 콘솔 백엔드는 메일을 로그로만 출력하므로 "
            "비밀번호 재설정 메일이 사용자에게 도달하지 않습니다. "
            "MAIL_BACKEND=smtp와 SMTP_HOST를 설정하십시오."
        )

    mail_from = source.get("MAIL_FROM", "").strip() or _DEFAULT_FROM

    if backend == BACKEND_CONSOLE:
        if not is_production_env(app_env):
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
        smtp_use_tls=_as_bool(source.get("SMTP_USE_TLS"), name="SMTP_USE_TLS", default=True),
    )
