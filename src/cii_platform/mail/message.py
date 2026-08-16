"""메일 메시지와 발송 실패 예외 (#407)."""

from __future__ import annotations

from dataclasses import dataclass


class MailDeliveryError(Exception):
    """메일을 보내지 못했다.

    ## 왜 별도 예외인가

    호출부가 **가입·재설정 트랜잭션과 분리해서** 처리할 수 있어야 한다. 메일 실패로
    계정 생성을 되돌리면 안 된다 — 계정은 만들어졌는데 메일만 실패한 상황이
    **정상 경로**이며, 사용자에게는 *"메일이 발송되지 않았습니다. 재발송해
    주세요"* 로 안내하는 것이 맞다.

    반대로 **삼키지도 않는다.** 조용히 무시하면 운영에서 아무도 메일이 안 가는 것을
    모른다.
    """

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


@dataclass(frozen=True)
class MailMessage:
    """보낼 메일 한 통.

    HTML 본문을 두지 않는다 — 인증 메일은 링크 하나가 본질이고, 평문이 스팸 판정과
    접근성 양쪽에서 유리하다. 필요해지면 그때 필드를 늘린다.
    """

    to: str
    subject: str
    body: str

    def __post_init__(self) -> None:
        """빈 값으로 보내지 않는다.

        수신자나 제목이 비면 SMTP 서버가 거부하거나 조용히 버린다. **호출 시점에
        막는 편이 발송 시점에 실패하는 것보다 원인을 찾기 쉽다.**
        """
        if not self.to.strip():
            raise ValueError("수신자가 비어 있습니다.")
        if not self.subject.strip():
            raise ValueError("제목이 비어 있습니다.")
