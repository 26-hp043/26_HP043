import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# src 레이아웃을 sys.path에 추가하여 editable 설치 없이도 cii_platform을 import할 수 있게 한다.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cii_platform.config import DATABASE_URL  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _to_async_url(url: str) -> str:
    """Alembic 마이그레이션은 비동기 엔진(asyncpg)으로 실행한다.

    프로젝트에 설치된 PostgreSQL 드라이버는 asyncpg뿐이므로, env로 주입된
    DATABASE_URL이 드라이버를 생략(``postgresql://``)했거나 다른 postgresql
    드라이버를 지정한 경우에도 asyncpg로 정규화하여 로컬/CI/docker에서 일관되게
    동작시킨다.
    """
    prefix = "postgresql+asyncpg://"
    if url.startswith(prefix):
        return url
    if url.startswith("postgresql://"):
        return prefix + url.split("://", 1)[1]
    if url.startswith("postgresql+"):
        return prefix + url.split("://", 1)[1]
    return url


# config 모듈의 DATABASE_URL을 단일 소스로 사용한다 (alembic.ini에 하드코딩 금지).
config.set_main_option("sqlalchemy.url", _to_async_url(DATABASE_URL))

# 모델(SQLAlchemy Base)이 아직 없으므로 autogenerate 미사용. 마이그레이션은 수기 작성한다.
# 향후 ORM 모델 도입 시 Base.metadata를 연결한다.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
