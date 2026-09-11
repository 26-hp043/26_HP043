"""가입 게이트 — 누가 계정을 만들 수 있는가 (#808).

## 왜 필요한가

이 제품은 **사내 도구**다(`#808` · 2026-09-11 결정). 권한 분리도 데이터 격리도 없어
(`API_SPEC §1.2` · `PRD §5.2`) 로그인한 사용자는 **모든 선박·항차를 읽고 고칠 수 있다.**
그런데 가입문은 공개였다 — 이메일 인증 전에도 로그인이 허용되므로(`PRD §7.10`),
주소만 알면 누구나 계정을 만들어 **남의 선박 이름과 위치를 바꿀 수 있었다**(`#808` 실측).

데이터를 회사별로 가르는 대신(다중 선사 — 수 주 규모) **들어오는 문을 좁힌다.** 문이
좁으면 안에서 모두가 같은 권한을 가져도 된다 — 그것이 정본이 이미 적어 둔 모델이다.

## 두 가지 통로

* ``SIGNUP_ALLOWED_DOMAINS`` — 쉼표로 나눈 이메일 도메인 목록. 회사 메일로 가입하는
  평상시 경로다. ``@`` 앞머리와 대소문자는 무시한다.
* ``SIGNUP_INVITE_CODE`` — 회사 메일이 아닌 사람(외부 협력사·시연 참석자)을 들이는 경로다.
  **둘 중 하나만 맞으면 된다.**

## 설정이 없으면

* **프로덕션에서는 기동을 거부한다** (:func:`validate_signup_gate`). 조용히 열린 가입문은
  `#809`(Host 헤더)·`#524`(메일 백엔드)와 같은 부류다 — 틀렸다는 신호 없이 성공한다.
* 개발·테스트에서는 열어 둔다. 게이트가 개발 흐름을 막으면 사람들이 우회 설정을 만든다.

## 무엇을 하지 않는가

**관리자 승인은 두지 않는다.** 승인하려면 「누가 관리자인가」가 있어야 하는데, 역할은
정본이 제외했다(`PRD §20 O-14` · 재개 지점 `#672`). 역할 없이 승인 흐름만 만들면
승인할 사람이 없는 대기열이 생긴다.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass

from cii_platform.config import is_production

#: 거절 문구 (`PRD §6.3`). 어느 조건에서 떨어졌는지는 말하지 않는다 — 「도메인이 틀렸다」와
#: 「코드가 틀렸다」를 가르면 허용 도메인을 한 번에 하나씩 캐낼 수 있다.
REJECTED_MESSAGE = (
    "가입이 허용되지 않았습니다. "
    "회사 이메일로 가입하거나, 관리자에게 받은 초대 코드를 입력해 주세요."
)

_GATE_REQUIRED = (
    "가입 게이트가 설정되지 않았습니다 (APP_ENV=production). "
    "SIGNUP_ALLOWED_DOMAINS 또는 SIGNUP_INVITE_CODE 중 하나 이상을 설정하세요. "
    "미설정이면 누구나 가입해 모든 선박·항차를 고칠 수 있습니다 (#808)."
)


@dataclass(frozen=True)
class SignupGate:
    """설정에서 읽은 가입 조건."""

    domains: frozenset[str]
    invite_code: str | None

    @property
    def is_open(self) -> bool:
        """조건이 하나도 없는가 — 개발·테스트에서만 허용되는 상태."""
        return not self.domains and not self.invite_code

    def allows(self, email: str, invite_code: str | None) -> bool:
        """이 이메일·초대 코드로 가입할 수 있는가.

        ``email``은 호출부가 이미 소문자로 정규화한 값이다(`routes/auth._normalize_email`).
        초대 코드는 :func:`hmac.compare_digest`로 비교한다 — 문자열 ``==``은 첫 불일치에서
        멈춰 응답 시간이 앞에서부터 맞은 글자 수를 흘린다.
        """
        if self.is_open:
            return True
        domain = email.rsplit("@", 1)[-1]
        if domain in self.domains:
            return True
        if self.invite_code and invite_code:
            return hmac.compare_digest(
                invite_code.strip().encode("utf-8"), self.invite_code.encode("utf-8")
            )
        return False


def _parse_domains(raw: str | None) -> frozenset[str]:
    """``"bluelog.kr, @Partner.co.kr"`` → ``{"bluelog.kr", "partner.co.kr"}``."""
    if not raw:
        return frozenset()
    return frozenset(
        part.strip().lstrip("@").lower() for part in raw.split(",") if part.strip().lstrip("@")
    )


def load_signup_gate(environ: Mapping[str, str] | None = None) -> SignupGate:
    """환경변수에서 가입 조건을 읽는다. 호출할 때마다 읽는다 — 테스트가 값을 바꿀 수 있게."""
    env = os.environ if environ is None else environ
    code = (env.get("SIGNUP_INVITE_CODE") or "").strip()
    return SignupGate(
        domains=_parse_domains(env.get("SIGNUP_ALLOWED_DOMAINS")),
        invite_code=code or None,
    )


def validate_signup_gate(environ: Mapping[str, str] | None = None) -> None:
    """기동 시점 검증 — 프로덕션인데 가입문이 열려 있으면 기동을 거부한다 (#808).

    ``validate_public_base_url``(`#809`)과 같은 자리에서 같은 이유로 돈다. 첫 가입
    요청에서 막으면 **이미 누군가 들어온 뒤**에야 드러난다.

    :raises RuntimeError: ``APP_ENV=production``이고 두 설정이 모두 비었을 때.
    """
    if not is_production():
        return
    if load_signup_gate(environ).is_open:
        raise RuntimeError(_GATE_REQUIRED)
