"""이메일별 로그인 실패 지수 백오프 (#1203 · `#853`에서 분리 · v9 E-4).

## 왜 IP 한도만으로는 부족한가

요청 한도(`api/rate_limit.py`)는 **IP당**이다 — 한 IP에서 여러 계정을 노리는 것은
막지만, **여러 IP에서 한 계정을 노리는 것은 못 막는다**(자격 증명 스터핑). 이 모듈이
그 **이메일 축**을 막는다. 두 축은 함께 걸린다 — IP 한도는 미들웨어에서 먼저 429를
내고, 백오프는 라우트 안에서 지연 뒤 401을 낸다.

## 정책 (PRD §16.3 「로그인 실패 백오프」 행)

- 연속 실패 **5회까지는 즉시 응답** — 정당한 사용자의 오타는 벌하지 않는다
- 6회째부터 **지수 지연**: ``0.4 × 2^(n-6)`` 초 — 0.4·0.8·1.6·3.2·**6.4 상한**
- 지연은 **응답 형태를 바꾸지 않는다** — 같은 401·같은 문구로 **늦게** 답한다.
  429나 ``Retry-After``를 내면 「이 계정은 존재한다」는 신호가 된다(아래)
- **성공하면 즉시 초기화**, 마지막 실패 후 **15분**이 지나면 잊는다(시간 경과가
  유일한 구제 경로 — 비밀번호 재설정 링크로 들어가면 새 비밀번호로 로그인한다)

## 🔒 계정 존재를 노출하지 않는다 (PRD §6.3)

카운터의 키는 **이메일 문자열뿐**이다. 계정이 있든 없든 같은 이메일이면 같은
지연을 걸고, ``verify_dummy``가 없는 계정의 Argon2 비용까지 맞춘 종전 규율
(`routes/auth.py`) 위에서 **시간으로도 구분되지 않는다**. 없는 계정만 즉시
응답하면 그 자체가 존재 오라클이다.

## 저장 — 프로세스 메모리 (워커 1 전제)

``uvicorn --workers 1``(``Dockerfile``)이라 프로세스 안 dict로 충분하다. 재시작하면
카운터가 비지만 공격자가 얻는 것도 잠깐의 초기화뿐이다. ⚠️ 워커를 늘리면
(`#986`) 카운터가 워커별로 갈라 효과가 그만큼 나뉜다 — 늘리는 날 공유 저장소로
옮겨야 한다.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

#: 연속 실패 이 횟수까지는 즉시 응답한다 (정당한 사용자의 오타 허용).
THRESHOLD = 5

#: 지연 곡선 — 6번째 실패 뒤 0.4초, 이후 2배씩. 상한 ``MAX_DELAY_SECONDS``.
BASE_DELAY_SECONDS = 0.4
MAX_DELAY_SECONDS = 6.4

#: 마지막 실패 후 이 시간이 지나면 잊는다 — 유일한 구제 경로(시간 경과).
WINDOW = timedelta(minutes=15)


def _delay_for_failures(failures: int) -> float:
    """실패 횟수 → 지연 초. 임계 전 0, 이후 지수·상한 6.4초.

    순수 함수 — 검사가 곡선 자체를 잠근다(지연이 있으면 안 되는 구간이 0임을 포함).
    """
    if failures < THRESHOLD:
        return 0.0
    return min(
        BASE_DELAY_SECONDS * (2 ** (failures - THRESHOLD)),
        MAX_DELAY_SECONDS,
    )


class LoginBackoff:
    """이메일별 연속 실패 카운터 — 단일 이벤트 루프 전제(위 모듈 docstring)."""

    def __init__(self) -> None:
        self._failures: dict[str, tuple[int, float]] = {}  # email → (연속 실패, 마지막 시각)

    def _current(self, email: str) -> tuple[int, float]:
        entry = self._failures.get(email)
        if entry is None:
            return 0, 0.0
        failures, last = entry
        if time.monotonic() - last > WINDOW.total_seconds():
            # 창을 넘은 실패는 잊는다 — 구제 경로(시간 경과)가 이것이다.
            self._failures.pop(email, None)
            return 0, 0.0
        return failures, last

    def delay_seconds(self, email: str) -> float:
        """**이번 시도 전에** 걸어야 할 지연 — 지난 실패가 쌓은 만큼."""
        failures, _ = self._current(email)
        return _delay_for_failures(failures)

    async def wait(self, email: str) -> None:
        """지연을 기다린다 — 응답 형태는 바꾸지 않는다(같은 401, 늦게).

        검사가 지연 시간을 재지 않고 **부름의 인자**를 재도 되게 ``_sleep``으로
        갈라 둔다 — 시간 재기는 CI에서 흔들린다.
        """
        delay = self.delay_seconds(email)
        if delay > 0:
            await _sleep(delay)

    def record_failure(self, email: str) -> None:
        failures, _ = self._current(email)
        self._failures[email] = (failures + 1, time.monotonic())

    def record_success(self, email: str) -> None:
        """성공은 즉시 초기화 — 정당한 사용자는 벌을 이어받지 않는다."""
        self._failures.pop(email, None)


#: 검사가 인자 기록용으로 갈아끼우는 주입점.
_sleep = asyncio.sleep

#: 라우트가 쓰는 프로세스 전역 인스턴스. 검사는 새 인스턴스로 곡선을 본다.
backoff = LoginBackoff()
