"""커버리지 설정이 HTTP 테스트를 실제로 계측하는가 (#871).

## 무엇이 문제였나

`#871`이 **「테스트가 통과하는데 라우트 본문이 실행되지 않는다」**를 보고했다. 재현은
정확했다 — 409를 단언하는 검사 하나를 돌리면 그 409를 만드는 줄이 `Missing`에 있었다.

```
pytest tests/test_auth_api.py::TestSignup::test_duplicate_email_is_reported \\
    --cov=cii_platform.api.routes.auth --cov-report=term-missing
→ auth.py  41%  Missing 187-237       ← 409는 190행이다
```

**그러나 해석이 틀렸다. 본문은 실행되고 있었다.** 그 검사는 라우트가 만드는 문구
(``EMAIL_TAKEN_MESSAGE``)와 201·409를 단언하므로 실행은 필연이다. 문제는 **계측**이다.

## 왜 못 봤는가 — 두 겹이 겹쳐 있다

1. ``TestClient``는 ASGI 앱을 **워커 스레드**의 blocking portal에서 돌린다.
2. 그 안에서 SQLAlchemy asyncio가 **greenlet**으로 스택을 전환한다.

coverage는 둘을 각각 따라간다. 하나만 켜면 다른 하나에서 프레임을 잃는다. 같은 검사
한 건으로 실측한 값이다.

```
concurrency = thread            41%   Missing 187-237  (기본값과 같다)
concurrency = greenlet          31%   (스레드 추적을 잃어 더 나쁘다)
concurrency = thread,greenlet   50%   187-237이 Missing에서 빠진다
```

남는 ``229-230``은 메일 발송 실패 ``except`` 분기로 **진짜 미실행**이 맞다.

## 왜 90% 게이트가 못 잡았는가

게이트(`ci.yml`)는 **전체 합계**를 본다. 5,897문장 가운데 라우트 몇 파일이 40~70%로
집계돼도 합계는 93%라 통과한다. **합계 게이트는 파일별 구멍을 볼 수 없다** — 그것이
이 결함이 오래 남은 이유다.

## 왜 이 검사인가

설정 한 줄이라 **지워져도 아무 검사가 깨지지 않는다.** 깨지지 않으므로 지워진 사실은
**다음에 커버리지를 들여다볼 때까지** 드러나지 않고, 그때는 또 「본문이 안 돈다」로
읽힌다. `#478`(ruff 핀)·`#394`(테스트 인벤토리)와 같은 부류의 가드다.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

#: 둘 다 필요하다. 근거는 이 파일 머리말의 실측표.
REQUIRED_CONCURRENCY = {"thread", "greenlet"}


def _coverage_run() -> dict[str, object]:
    with _PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    return data.get("tool", {}).get("coverage", {}).get("run", {})


def test_커버리지_설정이_있다() -> None:
    """``[tool.coverage.run]``이 존재한다.

    종전에는 이 절이 **아예 없었다**(``.coveragerc``도 없었다). 그래서 기본값으로
    돌았고, 기본값은 greenlet 전환을 따라가지 않는다.
    """
    assert _coverage_run(), (
        "pyproject.toml에 [tool.coverage.run]이 없습니다.\n"
        "→ concurrency를 지정하지 않으면 HTTP 테스트가 지나간 라우트 본문이 "
        "미실행으로 집계됩니다 (#871)."
    )


def test_스레드와_greenlet을_모두_추적한다() -> None:
    """``concurrency``에 ``thread``·``greenlet``이 **둘 다** 있다.

    하나만 켜면 다른 하나에서 추적을 잃는다 — greenlet만 켜면 오히려 더 낮게(31%)
    나온다. 「greenlet만 있으면 되지 않나」로 줄이는 것을 막는 것이 이 단언이다.
    """
    concurrency = _coverage_run().get("concurrency")
    assert isinstance(concurrency, list), (
        f"concurrency가 목록이 아닙니다: {concurrency!r}\n"
        '→ concurrency = ["thread", "greenlet"] 형태여야 합니다 (#871).'
    )

    missing = REQUIRED_CONCURRENCY - set(concurrency)
    assert not missing, (
        f"concurrency에 {sorted(missing)}이(가) 없습니다: {concurrency}\n"
        "→ TestClient는 앱을 워커 스레드에서 돌리고 그 안에서 SQLAlchemy asyncio가 "
        "greenlet으로 전환합니다. 둘 다 없으면 라우트 본문이 미실행으로 집계되고, "
        "그 상태에서 「테스트가 있는데 안 돈다」로 오진하게 됩니다 (#871)."
    )
