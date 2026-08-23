"""마이그레이션 테스트용 pytest fixture.

실행 중인 PostgreSQL(docker-compose의 db 서비스, 기본 localhost:5432)에 대해
`alembic upgrade head`로 스키마를 구성한 뒤, async 엔진으로 제약을 검증한다.

DATABASE_URL 환경변수로 대상 DB를 바꿀 수 있으며, 미설정 시 config 기본값을 사용한다.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_ROOT / "src"))
from db_target import is_disposable, refusal_reason  # noqa: E402

from cii_platform.config import DATABASE_URL  # noqa: E402
from cii_platform.db.url import normalize_to_asyncpg  # noqa: E402

# config/환경변수의 원본 URL. run_alembic은 이 raw 값을 그대로 넘긴다(아래 참조).
_RAW_DATABASE_URL = os.environ.get("DATABASE_URL", DATABASE_URL)
# async 엔진(conn fixture)용: asyncpg 드라이버로 정규화한 URL.
# 4곳(alembic/seed/pytest/앱) 공유 정책 — db.url.normalize_to_asyncpg (#234).
TEST_DATABASE_URL = normalize_to_asyncpg(_RAW_DATABASE_URL)


def require_disposable_target() -> None:
    """DB를 건드리기 전에 대상이 버려도 되는 곳인지 확인한다 (`#691`).

    ## 왜 파일이 아니라 여기인가

    `#507`이 같은 판정을 만들었으나 ``test_zz_roundtrip.py`` **한 파일에만** 걸었다.
    계정·세션·토큰을 지우는 나머지 **12개 파일**은 아무 제약 없이 시연 DB에 붙었고,
    2026-08-23에 가입 계정이 실제로 사라졌다. **스키마 드롭은 막혔는데 행 삭제는
    안 막혀 있었다.**

    파일마다 붙이는 방식은 **다음에 만드는 테스트를 놓친다.** 그래서 DB를 여는
    자리(:func:`run_alembic` · :func:`migrated_db` · :func:`app_fresh_engine`)로
    올린다 — 앞으로 추가되는 테스트도 자동으로 같은 규칙을 받는다.

    ## 왜 skip이 아니라 fail인가

    skip은 조용하다. **돌지 않은 것을 돌았다고 착각할 여지**를 남기는데, 이 사고의
    본체가 바로 「아무 신호 없이 지나갔다」였다. CI는 이미 ``cii_test``를 쓰므로
    (``.github/workflows/ci.yml``) fail로 두어도 **CI 동작은 달라지지 않는다.**

    ## 무엇을 막지 않는가

    **DB를 쓰지 않는 테스트는 그대로 돈다.** 세션 전체를 중단하면 `cii_test` 없이
    돌리던 순수 단위 테스트까지 함께 잃는다 — 막아야 할 것은 「DB에 쓰는 것」이지
    「테스트를 돌리는 것」이 아니다.
    """
    if not is_disposable(TEST_DATABASE_URL):
        pytest.fail(refusal_reason(TEST_DATABASE_URL), pytrace=False)


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    """매 테스트마다 ``main.app``의 분당 카운터를 새것으로 바꾼다 (#651).

    ## 왜 필요한가

    ``main.app``은 **모듈 레벨 객체**라 ``app.state.rate_limiter``(300/분)를
    **pytest 프로세스 전체가 공유**한다. 그 앱을 ``TestClient``로 때리는 테스트
    파일이 20개가 넘고, ``RateLimiter``는 **고정 윈도**라 60초가 지나야 리셋된다.

    그래서 실패 여부가 **전체 실행 속도에 달려 있었다.**

    .. code-block:: text

        로컬  전체 3분대 → 요청이 여러 윈도에 흩어짐 → 통과
        CI    전체 1분대 → 같은 윈도에 몰림         → 429

    테스트를 몇 개만 더해도 **자기 변경과 무관한 파일**이 떨어진다. 실제로 `#593`과
    `#648`이 각각 한 번씩 이것으로 CI가 막혔고, 두 번 다 해당 파일에서만 우회했다.

    ## 왜 카운터를 비우지 않고 통째로 바꾸는가

    ``_counts``는 내부 상태다. 테스트가 그것을 직접 만지면 구현이 바뀔 때 함께
    깨진다. 같은 한도의 **새 인스턴스**를 끼우면 공개된 생성자만 쓴다 — 미들웨어가
    요청마다 ``request.app.state.rate_limiter``를 다시 읽으므로 교체가 그대로 든다.

    ## 무엇을 무력화하지 않는가

    **한도 자체는 그대로 살아 있다.** 한 테스트 안에서 300건을 넘기면 여전히 429가
    되고, ``test_rate_limit.py``는 자기 앱을 따로 만들어 쓰므로 영향이 없다.
    `#275`가 배선으로 고정한 「rate limit이 auth보다 바깥」도 그대로다 — 한도를 0으로
    꺼 버리면 그 순서가 깨져도 아무도 모른다.
    """
    from cii_platform.api.main import app
    from cii_platform.api.rate_limit import RateLimiter

    previous = getattr(app.state, "rate_limiter", None)
    if previous is not None:
        app.state.rate_limiter = RateLimiter(previous.limit)
    try:
        yield
    finally:
        if previous is not None:
            app.state.rate_limiter = previous


def run_alembic(*alembic_args: str) -> subprocess.CompletedProcess:
    """프로젝트 루트에서 alembic CLI를 실행한다.

    PATH에 alembic 스크립트가 없어도(예: `python -m pytest` 직접 실행, CI) 동작하도록
    현재 인터프리터로 `python -m alembic`을 호출한다.
    """
    # 드라이버 정규화는 alembic/env.py의 _to_async_url()이 담당하므로, 여기서는
    # 원본 URL을 그대로 전달한다. asyncpg form을 미리 넘겨 이중 변환하지 않음으로써,
    # 향후 config.py가 raw postgresql:// 형식을 검증하더라도 깨지지 않게 한다. (#86)
    require_disposable_target()
    env = {**os.environ, "DATABASE_URL": _RAW_DATABASE_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *alembic_args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def load_fixture():
    """JSON 픽스처 로더 (`TEST_PLAN §1.6`).

    구현은 `tests/fixture_loader.py`에 있다. 이 모듈은 PostgreSQL 연결을
    전제하므로, DB 없이 성립해야 하는 픽스처 비교를 여기에 두지 않는다.

    `tests/`에 `__init__.py`가 없어 pytest가 이 디렉터리를 `sys.path`에 넣는다.
    따라서 `tests.` 접두 없이 모듈 이름으로 import한다 — `tests.fixture_loader`로
    적으면 저장소 루트가 `sys.path`에 있는 환경(로컬 `cwd`)에서만 동작하고
    CI에서는 `ModuleNotFoundError`가 난다.
    """
    from fixture_loader import load_fixture as _load

    return _load


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """세션 시작 시 head까지 upgrade하고 **데모 데이터를 적재**한다.

    데모 데이터가 마이그레이션에서 분리되면서(`#451`) 스키마만으로는 데모 선박이 없다.
    그 선박의 고정 UUID를 전제하는 테스트가 여럿이라 여기서 함께 넣는다 — 각 테스트가
    따로 넣으면 같은 데이터를 여러 벌 관리하게 된다.

    적재는 **멱등**이라(``ON CONFLICT DO NOTHING``) 매 세션 반복해도 행이 늘지 않는다.

    대상 DB 판정을 먼저 한다 (`#691`) — :func:`run_alembic`이 같은 확인을 하지만,
    **여기서 막아야 실패 지점이 「DB를 쓰는 fixture」로 읽힌다.**
    """
    require_disposable_target()
    result = run_alembic("upgrade", "head")
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head 실패:\n{result.stdout}\n{result.stderr}")

    import asyncio

    from cii_platform.db.demo_seed import seed_demo

    async def _seed() -> None:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
        try:
            async with engine.begin() as conn:
                await seed_demo(conn)
        finally:
            await engine.dispose()

    asyncio.run(_seed())


@pytest_asyncio.fixture
async def conn(migrated_db):
    """함수 단위 트랜잭션. 테스트 종료 시 롤백하여 DB를 오염시키지 않는다."""
    # env.py와 동일하게 NullPool 사용: 함수마다 엔진을 새로 만들고 dispose하므로
    # 커넥션을 풀에 남기지 않아 누수를 방지한다. (#86)
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    connection = await engine.connect()
    trans = await connection.begin()
    try:
        yield connection
    finally:
        await trans.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def app_fresh_engine(monkeypatch: pytest.MonkeyPatch):
    """TestClient(포털 루프) DB 접근용 NullPool 엔진으로 교체한다.

    앱의 ``get_engine``은 lru_cache로 프로세스에 하나다. TestClient는 컨텍스트마다
    새 이벤트 루프(포털)를 만들므로, 풀에 남은 연결이 이전 루프에 묶여
    ``attached to a different loop``로 실패한다 (#308 테스트). DB를 실제로 쓰는
    TestClient 테스트는 이 fixture로 요청마다 연결을 만드는 NullPool 엔진으로
    갈아끼운다 — 테스트 루프에서 검증·정리할 때도 같은 세션팩토리를 쓴다.

    **``migrated_db``에 의존하지 않는다.** 그래서 대상 DB 판정을 여기서 따로 한다
    (`#691`) — 이 fixture만 받아 DB에 쓰는 테스트가 생기면 위 판정을 통째로
    비켜 간다.
    """
    require_disposable_target()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from cii_platform.db import session as db_session_mod

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=pool.NullPool)
    patched_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session_mod, "get_engine", lambda: engine)
    monkeypatch.setattr(db_session_mod, "get_sessionmaker", lambda: patched_maker)
    yield engine
