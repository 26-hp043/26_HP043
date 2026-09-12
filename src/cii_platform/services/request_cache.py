"""한 요청 안에서 **같은 규제 파라미터를 다시 읽지 않는다** (`#989` ⑴).

선대 요약(`GET /fleet/summary`)은 선박마다 :func:`~cii_platform.services.ytd_cii.compute_ytd_cii`
를 최대 네 번 부르고(올해 · 직전 2개 연도 · 최근 30일 창), **그 네 번이 각각 규정연도 ·
기준선 · 등급 경계 · 선박을 처음부터 다시 읽는다.** 200척에서 호출당 8,402 쿼리 · 10.7초가
나온 실측(`#772` 코멘트)에서 **같은 값을 다시 읽는 몫이 약 45%**였다.

## 왜 캐시를 켜는 쪽이 정하는가

이 모듈은 **기본으로 아무것도 캐시하지 않는다.** :func:`enable`을 부른 요청에서만 값을 모으고,
부르지 않은 경로는 종전과 같이 매번 읽는다. 규제 파라미터는 요청 하나가 도는 동안 바뀌지
않지만 **선박·파라미터를 고치는 요청도 같은 함수를 지나가기** 때문이다 — 그런 경로에서 캐시가
켜져 있으면 **자기가 방금 고친 값을 못 보는** 상태가 된다. 그래서 켜는 것은 **읽기 전용
요청**이 스스로 정한다(지금은 선대 요약 하나).

## 무엇을 담는가

값은 **저장소가 준 것 그대로**(ORM 행·행 목록·``None``)를 담는다. 선택·판정 결과는 담지
않는다 — 같은 기준선 목록이라도 선박마다 고르는 행이 다르므로, 캐시가 그 판정까지 기억하면
**다른 선박의 답을 돌려주는** 종류의 결함이 된다.

수명은 ``session.info``다. 세션이 끝나면 함께 사라지므로 **요청 밖으로 새지 않는다** —
프로세스 전역 캐시와 달리 규제 파라미터 개정이 다음 요청부터 바로 보인다(`PRD §8.4`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from sqlalchemy.ext.asyncio import AsyncSession

#: ``session.info``에 두는 자리. 다른 확장과 겹치지 않게 모듈 이름을 그대로 쓴다.
_KEY = "cii_platform.request_cache"


def enable(session: AsyncSession) -> None:
    """이 세션에서 :func:`cached`가 값을 모으게 한다. 두 번 불러도 안전하다."""
    session.info.setdefault(_KEY, {})


def is_enabled(session: AsyncSession) -> bool:
    return _KEY in session.info


async def cached[T](session: AsyncSession, key: object, load: Callable[[], Awaitable[T]]) -> T:
    """``key``의 값을 한 번만 읽는다. 켜지지 않은 세션에서는 **그냥 읽는다**.

    ``load``가 예외를 던지면 아무것도 담지 않는다 — 실패를 기억하면 같은 요청의 뒤쪽
    호출이 **이유를 모른 채** 같은 실패를 받는다.
    """
    store = session.info.get(_KEY)
    if store is None:
        return await load()
    if key in store:
        return store[key]
    value = await load()
    store[key] = value
    return value


def put(session: AsyncSession, key: object, value: object) -> None:
    """이미 읽어 둔 값을 캐시에 넣는다. 켜지지 않은 세션에서는 아무 일도 하지 않는다.

    선대 요약이 선박 목록을 한 번에 읽어 두고도 **선박마다 다시 한 건씩 읽던** 자리를
    없앤다 — 목록과 개별 조회가 같은 행을 준다.
    """
    store = session.info.get(_KEY)
    if store is not None:
        store[key] = value
