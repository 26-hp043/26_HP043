"""최초 사무직 — 누가 처음 사무직이 되는가 (#672).

## 왜 필요한가

역할을 나누면(`PRD §20 O-14` · `API_SPEC §1.2`) 새 계정은 **현장직**으로 시작하고, 사무직은
**사무직만** 지정할 수 있다. 그 규칙만 있으면 새 DB에서는 **아무도 사무직이 아닌 채로
배포된다** — `#672` 본문이 경고한 「관리자 0명」 상태이고, 파라미터·리포트·계정 관리가 전원에게
막힌다. 기존 DB는 마이그레이션 044가 전원을 사무직으로 채우므로 이 문제가 없다.

## 설정

``INITIAL_OFFICE_EMAILS`` — 쉼표로 나눈 이메일 목록. 여기 든 이메일은 **가입할 때와 로그인할
때** 사무직으로 올린다(``routes/auth.py``). 부팅 시점에 DB를 고치지 않는 이유 — 앱 기동이 DB
쓰기에 묶이면 DB 없이 뜨는 검사·헬스 체크 경로가 전부 그 쓰기에 걸린다. 로그인은 어차피 DB를
읽는 자리다.

**목록에 있는 동안은 강등해도 다음 로그인에서 되돌아온다.** 그 계정을 현장직으로 두려면 먼저
목록에서 뺀다 — 목록은 「항상 사무직인 사람」이지 「처음 한 번」이 아니다. 처음 한 번으로 만들면
그 한 번을 누가 기록했는지가 필요해지고, 그 기록이 사라지면 잠긴다.

## 설정이 없으면

* **프로덕션에서는 기동을 거부한다** (:func:`validate_initial_office`) — ``SIGNUP_ALLOWED_DOMAINS``
  (`#808`)와 같은 자리, 같은 이유다. 조용히 사무직 0명으로 뜨면 첫 사용자가 리포트를 열 때에야
  드러난다.
* 개발·테스트에서는 비워 둔다. 개발 계정(``dev-login`` · 시연 계정)은 코드가 사무직으로 만든다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from cii_platform.config import is_production

ENV_NAME = "INITIAL_OFFICE_EMAILS"

_REQUIRED = (
    "최초 사무직이 설정되지 않았습니다 (APP_ENV=production). "
    f"{ENV_NAME}에 사무직으로 시작할 이메일을 쉼표로 적으세요. "
    "비어 있으면 새 DB에서 아무도 사무직이 아니라 리포트·계정 관리를 아무도 못 씁니다 (#672)."
)


def parse_initial_office_emails(raw: str | None) -> frozenset[str]:
    """``" A@BlueLog.kr, b@x.io ,, "`` → ``{"a@bluelog.kr", "b@x.io"}``.

    이메일은 가입·로그인이 소문자로 정규화하므로(``routes/auth._normalize_email``) 여기서도
    같은 규칙으로 맞춘다 — 대소문자 하나로 최초 사무직이 안 되는 일이 없게.
    """
    if not raw:
        return frozenset()
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def load_initial_office_emails(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """환경변수에서 읽는다. 호출할 때마다 읽는다 — 테스트가 값을 바꿀 수 있게."""
    env = os.environ if environ is None else environ
    return parse_initial_office_emails(env.get(ENV_NAME))


def is_initial_office(email: str, environ: Mapping[str, str] | None = None) -> bool:
    """이 이메일(소문자 정규화된 값)이 최초 사무직 목록에 있는가."""
    return email.strip().lower() in load_initial_office_emails(environ)


def validate_initial_office(environ: Mapping[str, str] | None = None) -> None:
    """기동 시점 검증 — 프로덕션인데 목록이 비어 있으면 기동을 거부한다 (#672).

    :raises RuntimeError: ``APP_ENV=production``이고 목록이 비었을 때.
    """
    if not is_production():
        return
    if not load_initial_office_emails(environ):
        raise RuntimeError(_REQUIRED)
