"""최초 관리자 — 누가 처음 관리자가 되는가 (#672 · #1301).

## 왜 필요한가

역할을 나누면(`PRD §20 O-14` · `API_SPEC §1.2`) 새 계정은 **현장직**으로 시작하고, 역할을
바꾸는 일은 **관리자만** 할 수 있다(`#1301`). 그 규칙만 있으면 새 DB에서는 **아무도 관리자가
아닌 채로 배포된다** — `#672` 본문이 경고한 「관리자 0명」 상태이고, 그때는 계정 관리 화면으로
아무도 역할을 올릴 수 없다. 기존 DB는 마이그레이션 044가 전원을 사무직으로 채웠지만,
**사무직은 이제 역할을 바꾸지 못하므로 그것만으로는 풀리지 않는다.**

## 설정

``INITIAL_ADMIN_EMAILS`` — 쉼표로 나눈 이메일 목록. 여기 든 이메일은 **가입할 때와 로그인할
때** 관리자로 올린다(``routes/auth.py``). 부팅 시점에 DB를 고치지 않는 이유 — 앱 기동이 DB
쓰기에 묶이면 DB 없이 뜨는 검사·헬스 체크 경로가 전부 그 쓰기에 걸린다. 로그인은 어차피 DB를
읽는 자리다.

**목록에 있는 동안은 강등해도 다음 로그인에서 되돌아온다.** 그 계정을 관리자에서 빼려면 먼저
목록에서 뺀다 — 목록은 「항상 관리자인 사람」이지 「처음 한 번」이 아니다. 처음 한 번으로
만들면 그 한 번을 누가 기록했는지가 필요해지고, 그 기록이 사라지면 잠긴다.

## 옛 이름은 거부한다

`#1301` 이전 이름은 ``INITIAL_OFFICE_EMAILS``였고 부여하던 역할도 사무직이었다. 그 이름이
설정된 채로 뜨면 **아무 일도 일어나지 않는다** — 그리고 「적어 뒀는데 아무 일도 없다」가 정확히
`#1290`이 겪은 실패 방식이다. 그래서 **조용히 무시하지 않고 기동을 거부한다**
(:func:`validate_initial_admin`). 이름이 바뀐 것을 그 자리에서 알려 주는 편이, 첫 사용자가
계정 관리 화면을 열 때 알게 되는 것보다 싸다.

## 설정이 없으면

* **프로덕션에서는 기동을 거부한다** (:func:`validate_initial_admin`) — ``SIGNUP_ALLOWED_DOMAINS``
  (`#808`)와 같은 자리, 같은 이유다. 조용히 관리자 0명으로 뜨면 첫 사용자가 계정 관리를
  열 때에야 드러난다.
  ⚠️ **``staging``에는 이 가드가 없다** — SMTP 준비 전 배포가 고르는 자리이고(`#524` ·
  `docs/OPERATIONS.md §4.5`), 그래서 그 환경에서는 사람이 값을 채웠는지 직접 봐야 한다.
* 개발·테스트에서는 비워 둔다. 개발 계정(``dev-login`` · 시연 계정)은 코드가 사무직으로 만든다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from cii_platform.config import is_production

ENV_NAME = "INITIAL_ADMIN_EMAILS"

#: `#1301` 이전 이름. 설정돼 있으면 기동을 거부한다 — 모듈 독스트링 「옛 이름은 거부한다」.
LEGACY_ENV_NAME = "INITIAL_OFFICE_EMAILS"

_REQUIRED = (
    "최초 관리자가 설정되지 않았습니다 (APP_ENV=production). "
    f"{ENV_NAME}에 관리자로 시작할 이메일을 쉼표로 적으세요. "
    "비어 있으면 새 DB에서 아무도 관리자가 아니라 계정 관리를 아무도 못 씁니다 (#672 · #1301)."
)

_LEGACY_SET = (
    f"{LEGACY_ENV_NAME}는 {ENV_NAME}로 이름이 바뀌었습니다 (#1301). "
    f"역할을 지정하는 권한이 사무직에서 관리자로 넘어갔기 때문입니다. "
    f"{LEGACY_ENV_NAME} 줄을 {ENV_NAME}로 고치십시오 — "
    "옛 이름은 읽히지 않으므로 그대로 두면 관리자가 0명인 채로 뜹니다."
)


def parse_initial_admin_emails(raw: str | None) -> frozenset[str]:
    """``" A@BlueLog.kr, b@x.io ,, "`` → ``{"a@bluelog.kr", "b@x.io"}``.

    이메일은 가입·로그인이 소문자로 정규화하므로(``routes/auth._normalize_email``) 여기서도
    같은 규칙으로 맞춘다 — 대소문자 하나로 최초 관리자가 안 되는 일이 없게.
    """
    if not raw:
        return frozenset()
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def load_initial_admin_emails(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """환경변수에서 읽는다. 호출할 때마다 읽는다 — 테스트가 값을 바꿀 수 있게."""
    env = os.environ if environ is None else environ
    return parse_initial_admin_emails(env.get(ENV_NAME))


def is_initial_admin(email: str, environ: Mapping[str, str] | None = None) -> bool:
    """이 이메일(소문자 정규화된 값)이 최초 관리자 목록에 있는가."""
    return email.strip().lower() in load_initial_admin_emails(environ)


def validate_initial_admin(environ: Mapping[str, str] | None = None) -> None:
    """기동 시점 검증 (#672 · #1301).

    둘을 본다.

    * **옛 이름이 설정돼 있으면** 환경과 무관하게 거부한다 — 그 값은 읽히지 않는데 적은
      사람은 적용됐다고 믿는다. 개발에서도 막는 이유는 거기서 먼저 걸려야 배포 전에
      고치기 때문이다.
    * **프로덕션인데 목록이 비어 있으면** 거부한다.

    :raises RuntimeError: 위 둘 중 하나.
    """
    env = os.environ if environ is None else environ
    if (env.get(LEGACY_ENV_NAME) or "").strip():
        raise RuntimeError(_LEGACY_SET)
    if not is_production():
        return
    if not load_initial_admin_emails(env):
        raise RuntimeError(_REQUIRED)
