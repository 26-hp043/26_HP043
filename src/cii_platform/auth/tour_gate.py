"""둘러보기 접근 코드 — 로그인 없이 열람 세션을 여는 문 (#1486).

## 무엇을 위한 것인가

인터뷰·설문 대상자에게 **가입·로그인 없이** 서비스를 보여 준다. 링크에 실린 코드
(`/login?tour=<코드>`)를 확인하면 ``POST /auth/tour-login``이 관리자 세션을 발급한다.

## 왜 ``dev-login``을 쓰지 않는가

``routes/auth_dev.py``의 스텁 인증이 이미 *「로그인 화면을 건너뛰기 위한 것」*이다.
그러나 그 라우트는 ``development``·``test``에서만 등록된다
(:data:`~cii_platform.config._DEV_SURFACE_ENVS`). 배포는 ``staging``이므로
**교수님 링크에서는 401이 난다.**

그 목록에 ``staging``을 더하는 쪽은 선택지가 아니다. 상수 하나에 dev-login·``/docs``·
시연 계정 시드 셋이 묶여 있고, `#1058`이 실측을 근거로 닫은 결정이다 — *「2026-09-15
OCI 배포에서 실제로 ``POST /auth/dev-login``이 200을 냈다 — 누구나 미인증 세션을 받는
상태였다」*.

그래서 이 문은 **환경과 무관하게 항상 열려 있고, 코드로만 잠긴다.**

## fail-closed — 이 모듈에서 가장 중요한 성질

``SIGNUP_INVITE_CODE``를 다루는 :class:`~cii_platform.auth.signup_gate.SignupGate`는
조건이 **하나도 없으면 통과**시킨다(``is_open``). 가입 게이트는 그것이 맞다 — 개발에서
아무 설정 없이 가입할 수 있어야 한다.

**여기서는 정반대여야 한다.** 코드가 설정되지 않은 배포에서 통과시키면 **누구나
관리자 세션을 받는다.** `#1058`·`#810`이 세운 *「부정형은 여는 쪽으로, 긍정형은 닫는
쪽으로 틀린다」*와 같은 판단이며, 그래서 :func:`verify_tour_code`는 **설정이 없으면
언제나 False**다.

## 왜 ``SIGNUP_INVITE_CODE``를 겸용하지 않는가

그 값은 **가입**(현장직 계정 생성)을 여는 것이고 이 값은 **관리자 세션**을 연다 —
위력이 다르다. 하나를 공유하면 인터뷰가 끝나 코드를 비울 때 가입문까지 함께 닫히거나,
반대로 가입 코드를 아는 사람이 관리자가 된다.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

#: 접근 코드를 담는 환경변수. 비어 있으면 둘러보기는 **닫힌다.**
ENV_NAME = "TOUR_ACCESS_CODE"

#: 거절 문구 (`PRD §6.3`).
#:
#: **「꺼져 있다」와 「코드가 틀렸다」를 구분하지 않는다.** 구분하면 기능의 존재 여부가
#: 새고, 코드를 맞히는 사람에게 「거의 맞았다」는 신호를 준다 — ``signup_gate``의
#: :data:`~cii_platform.auth.signup_gate.REJECTED_MESSAGE`와 같은 원칙이다.
REJECTED_MESSAGE = "둘러보기 링크가 올바르지 않습니다. 받으신 링크를 다시 확인해 주세요."


def load_tour_code(environ: Mapping[str, str] | None = None) -> str | None:
    """설정된 접근 코드를 돌려준다. 미설정·빈 값이면 ``None``.

    **호출할 때마다 읽는다** — 검사가 값을 바꿀 수 있게 하고, 운영에서 코드를 비우면
    다음 요청부터 곧바로 닫히게 하기 위해서다(``signup_gate.load_signup_gate``와 같다).
    """
    source = os.environ if environ is None else environ
    return (source.get(ENV_NAME) or "").strip() or None


def tour_is_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """둘러보기가 열려 있는가 — 코드가 설정돼 있을 때만 True.

    화면에 버튼을 보일지 정하는 데 쓰지 **않는다.** 그 판단은 링크에 코드가 실려 있는지로
    프런트가 하고, 서버는 :func:`verify_tour_code` 하나로만 답한다 — 「열려 있는가」를
    묻는 공개 경로를 만들면 그 자체가 기능의 존재를 알리는 신호가 된다.
    """
    return load_tour_code(environ) is not None


def verify_tour_code(provided: str | None, environ: Mapping[str, str] | None = None) -> bool:
    """제시된 코드가 맞는가. **설정이 없으면 언제나 False다.**

    비교는 :func:`hmac.compare_digest`로 한다 — 문자열 ``==``는 첫 불일치에서 멈춰
    **응답 시간이 앞에서부터 맞은 글자 수를 흘린다.** 공개 주소에 놓이는 문이라
    그 누출이 곧 추측 비용을 깎아 준다(``signup_gate.SignupGate.allows``와 같은 판단).

    :param provided: 요청이 실어 온 코드. ``None``·빈 문자열이면 False.
    """
    expected = load_tour_code(environ)
    if expected is None:
        # ⚠️ **여기를 「통과」로 바꾸지 않는다.** 코드가 설정되지 않은 배포에서
        # 누구나 관리자 세션을 받게 된다 — 모듈 독스트링 「fail-closed」.
        return False
    if not provided:
        return False
    return hmac.compare_digest(provided.strip().encode("utf-8"), expected.encode("utf-8"))
