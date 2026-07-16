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
from cii_platform.config import DATABASE_URL  # noqa: E402


def _async_url(url: str) -> str:
    """asyncpg 드라이버 URL로 정규화한다 (env.py와 동일 정책)."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    if url.startswith("postgresql+"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


# config/환경변수의 원본 URL. run_alembic은 이 raw 값을 그대로 넘긴다(아래 참조).
_RAW_DATABASE_URL = os.environ.get("DATABASE_URL", DATABASE_URL)
# async 엔진(conn fixture)용: asyncpg 드라이버로 정규화한 URL.
TEST_DATABASE_URL = _async_url(_RAW_DATABASE_URL)


def run_alembic(*alembic_args: str) -> subprocess.CompletedProcess:
    """프로젝트 루트에서 alembic CLI를 실행한다.

    PATH에 alembic 스크립트가 없어도(예: `python -m pytest` 직접 실행, CI) 동작하도록
    현재 인터프리터로 `python -m alembic`을 호출한다.
    """
    # 드라이버 정규화는 alembic/env.py의 _to_async_url()이 담당하므로, 여기서는
    # 원본 URL을 그대로 전달한다. asyncpg form을 미리 넘겨 이중 변환하지 않음으로써,
    # 향후 config.py가 raw postgresql:// 형식을 검증하더라도 깨지지 않게 한다. (#86)
    env = {**os.environ, "DATABASE_URL": _RAW_DATABASE_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *alembic_args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """세션 시작 시 head까지 upgrade하여 스키마를 보장한다."""
    result = run_alembic("upgrade", "head")
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head 실패:\n{result.stdout}\n{result.stderr}")


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
