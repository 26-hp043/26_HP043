"""테스트 대상 DB가 파괴해도 되는 곳인지 판정한다 (#507).

## 무엇을 막는가

``tests/test_zz_roundtrip.py``는 ``alembic downgrade base``로 **스키마를 통째로
드롭**한다. 그 검사 자체는 정당하다 — ``DB_SCHEMA §8.1`` 롤백 안전성을 지키며,
실제로 `#451`이 「데모 선박으로 계산을 한 번 돌리면 018 롤백이 막힌다」는 결함을
이 테스트로 잡았다.

**문제는 그 검사가 개발용 DB에서 돈다는 것이다.** ``conftest.py``가 ``DATABASE_URL``을
그대로 대상으로 쓰므로 개발 DB와 테스트 DB가 같은 데이터베이스였고, ``pytest``를
한 번 돌릴 때마다 ``app_user``·``user_session``·``user_token``이 사라졌다.
마이그레이션이 되살리는 것은 규정 파라미터뿐이고, 데모 데이터는 테스트가 다시
넣지만, **사람이 가입한 계정은 아무도 되살리지 않는다.**

## 왜 지금까지 안 드러났나

계정이 ``dev-login`` 스텁뿐일 때는 사라져도 다음 호출이 같은 고정 UUID로 다시
만들었다(``auth_dev.py``). **사람이 가입한 계정이 생긴 뒤에야** 손실이 보인다.

## 판정 방법 — 데이터베이스 **이름**으로 본다

호스트나 포트로는 가를 수 없다. 개발 DB와 테스트 DB가 같은 서버에 있는 것이
정상이기 때문이다. 가를 수 있는 것은 이름뿐이다.

CI는 이미 ``cii_test``를 쓴다(``.github/workflows/ci.yml``의 postgres 서비스
``POSTGRES_DB``). 그래서 이 규칙은 **CI를 그대로 통과시키고 로컬 개발 DB만 막는다.**

로컬에서 롤백 테스트를 돌리려면 대상만 바꾸면 된다.

.. code-block:: bash

    createdb -h localhost -U cii cii_test
    DATABASE_URL=postgresql://cii:cii@localhost:5432/cii_test uv run pytest

## 범위 — 파괴적 테스트만이 아니다 (`#691`)

위 판정은 처음에 ``test_zz_roundtrip.py`` **한 파일에만** 걸렸다. 그 사이 계정·세션·
토큰을 지우는 다른 테스트 **12개 파일**은 아무 제약 없이 개발 DB에 붙었고,
**이 독스트링이 예고한 그대로 2026-08-23에 가입 계정이 사라졌다.**

스키마 드롭은 막혔는데 행 삭제는 안 막혀 있었다 — **막은 것이 위험의 한 종류뿐이었다.**
그래서 판정을 ``conftest.py``의 DB fixture로 올려 **DB를 건드리는 모든 테스트**가
같은 규칙을 받게 했다. 파일마다 붙이는 방식은 다음에 만드는 테스트를 놓친다.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

#: 파괴적 테스트를 허용하는 데이터베이스 이름의 접미.
TEST_DB_SUFFIX = "_test"


def database_name(url: str) -> str:
    """접속 URL에서 데이터베이스 이름을 꺼낸다.

    드라이버 표기(``postgresql+asyncpg://``)와 쿼리스트링(``?sslmode=…``)이 섞여도
    같은 값을 돌려줘야 한다 — 판정이 표기 방식에 따라 갈리면 가드가 아니다.
    """
    path = urlsplit(url).path
    return path.lstrip("/") if path else ""


def is_disposable(url: str) -> bool:
    """이 DB를 드롭·재생성해도 되는가.

    이름이 ``_test``로 끝나는 것만 허용한다. **모르면 허용하지 않는다** — 잘못
    허용하면 되돌릴 수 없고(백업이 없다), 잘못 막으면 테스트가 skip될 뿐이다.
    """
    name = database_name(url)
    return name.endswith(TEST_DB_SUFFIX) and name != TEST_DB_SUFFIX


def skip_reason(url: str) -> str:
    """왜 건너뛰는지 사람이 읽을 문장. **조용히 넘어가지 않는다.**"""
    name = database_name(url) or "(이름 없음)"
    return (
        f"대상 DB '{name}'은(는) 파괴적 테스트 대상이 아닙니다 (#507). "
        f"이 테스트는 `alembic downgrade base`로 스키마를 드롭하므로 "
        f"이름이 '{TEST_DB_SUFFIX}'로 끝나는 DB에서만 실행합니다. "
        f"예: DATABASE_URL=postgresql://cii:cii@localhost:5432/cii_test uv run pytest"
    )


def refusal_reason(url: str) -> str:
    """왜 막았는지와 어떻게 하면 되는지. **막을 때 조용히 넘어가지 않는다** (`#691`).

    :func:`skip_reason`과 나눠 둔다. 그쪽은 「이 테스트는 안 돌린다」이고 이쪽은
    **「이 실행 전체를 받지 않는다」**이며, 읽는 사람이 해야 할 일이 다르다.

    문장에 **대상 이름·이유·해결 명령**을 함께 넣는다. 셋 중 하나라도 빠지면
    사람은 가드를 우회할 방법부터 찾는다 — 그 우회가 곧 이 사고의 재발이다.
    """
    name = database_name(url) or "(이름 없음)"
    return (
        f"대상 DB '{name}'은(는) 테스트 대상이 아닙니다 (#691).\n"
        "\n"
        "테스트는 app_user·user_session·user_token 행을 지웁니다. 마이그레이션이 "
        "되살리는 것은 규정 파라미터뿐이고 데모 데이터는 테스트가 다시 넣지만, "
        "**사람이 가입한 계정은 아무도 되살리지 않습니다.**\n"
        "\n"
        f"이름이 '{TEST_DB_SUFFIX}'로 끝나는 DB에서만 실행합니다. 한 번만 만들면 됩니다.\n"
        "\n"
        "    docker compose exec -T db createdb -U cii cii_test\n"
        "    DATABASE_URL=postgresql+asyncpg://cii:cii@localhost:5432/cii_test pytest\n"
        "\n"
        "CI는 이미 cii_test를 씁니다 (.github/workflows/ci.yml)."
    )


def running_in_ci(env: dict[str, str] | None = None) -> bool:
    """CI 환경인가.

    GitHub Actions는 ``CI=true``를 넣는다. 이 값을 보는 이유는 **CI에서 롤백
    테스트가 조용히 skip되는 것을 막기 위해서**다 — 가드가 생긴 뒤 CI의 DB 이름이
    바뀌면 회귀 검사가 사라지는데, 그 손실은 아무 신호 없이 일어난다.
    """
    source = os.environ if env is None else env
    return source.get("CI", "").strip().lower() in {"1", "true", "yes", "on"}
