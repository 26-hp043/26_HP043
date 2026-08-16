"""메일 발송 (#407).

자체 ID/PW 인증 전환(`PRD §20 O-14`)으로 **가입 확인 메일과 비밀번호 재설정
메일을 보낼 수단**이 필요해졌다. 이 패키지는 **보내는 층만** 담당한다 — 토큰
발급·검증은 `#408`, 화면은 `#415` 소관이다.

## 왜 인증 플로우와 분리하는가

SMTP는 자격증명·네트워크·수신 거부 등 **우리 코드 밖에서 깨진다.** 그 실패가
회원가입 트랜잭션을 통째로 되돌리면, 사용자는 계정이 만들어졌는지도 알 수 없다.

경계를 나눠 두면 *"메일이 안 갔다"*와 *"가입이 안 됐다"*를 구분할 수 있고,
호출부가 커밋 뒤에 보내고 실패를 따로 처리할 수 있다.

## 사용

```python
from cii_platform.mail import MailMessage, get_mailer

await get_mailer().send(
    MailMessage(to="user@example.com", subject="...", body="...")
)
```
"""

from cii_platform.mail.backends import ConsoleMailer, Mailer, SmtpMailer, get_mailer
from cii_platform.mail.config import MailSettings, load_mail_settings
from cii_platform.mail.message import MailDeliveryError, MailMessage

__all__ = [
    "ConsoleMailer",
    "MailDeliveryError",
    "MailMessage",
    "MailSettings",
    "Mailer",
    "SmtpMailer",
    "get_mailer",
    "load_mail_settings",
]
