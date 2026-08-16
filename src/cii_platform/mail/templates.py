"""인증 메일 본문 (#407 자리 · 본문 확정은 #408).

## 여기 있는 것과 없는 것

**있는 것** — 제목·본문의 형태와 「무엇을 담아야 하는가」.
**없는 것** — 토큰을 만드는 방법, 링크의 유효기간을 정하는 규칙. `#408` 소관이다.

이 모듈은 **완성된 링크 문자열을 받아** 본문에 끼운다. 토큰을 여기서 만들면
발송 층이 인증 규칙을 알게 되고, 두 이슈의 경계가 무너진다.

## 문구 규칙

`PRD §6.3`이 확정한 화면 문구와 어긋나지 않게 쓴다. 특히 **계정 존재 여부를
드러내지 않는다** — 재설정 메일은 가입자에게만 가므로 본문에서는 문제가 없으나,
「요청하지 않았다면 무시하십시오」를 반드시 넣는다. 타인이 남의 주소로 요청했을 때
수신자가 상황을 알 수 있어야 한다.
"""

from __future__ import annotations

from cii_platform.mail.message import MailMessage

#: 서비스 표시명. 브랜드명은 `AppShell.tsx`와 같은 값이다.
SERVICE_NAME = "BlueLog"


def email_verification(*, to: str, verify_url: str) -> MailMessage:
    """가입 확인 메일.

    :param verify_url: 토큰이 포함된 완성 링크. 만드는 것은 `#408` 소관이다.
    """
    body = f"""{SERVICE_NAME} 가입을 확인해 주세요.

아래 링크를 눌러 이메일 인증을 완료하십시오.

{verify_url}

이 링크는 24시간 동안 유효합니다.
본인이 가입하지 않았다면 이 메일을 무시하셔도 됩니다.

— {SERVICE_NAME}
"""
    return MailMessage(
        to=to,
        subject=f"[{SERVICE_NAME}] 이메일 인증을 완료해 주세요",
        body=body,
    )


def password_reset(*, to: str, reset_url: str) -> MailMessage:
    """비밀번호 재설정 메일."""
    body = f"""{SERVICE_NAME} 비밀번호 재설정 안내입니다.

아래 링크를 눌러 새 비밀번호를 설정하십시오.

{reset_url}

이 링크는 1시간 동안 유효하며 한 번만 사용할 수 있습니다.
비밀번호를 재설정하면 기존에 로그인된 모든 기기에서 자동으로 로그아웃됩니다.

본인이 요청하지 않았다면 이 메일을 무시하셔도 됩니다.
비밀번호는 변경되지 않습니다.

— {SERVICE_NAME}
"""
    return MailMessage(
        to=to,
        subject=f"[{SERVICE_NAME}] 비밀번호 재설정",
        body=body,
    )
