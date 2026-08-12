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
from cii_platform.db.models import Base  # noqa: E402
from cii_platform.db.url import normalize_to_asyncpg  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# config 모듈의 DATABASE_URL을 단일 소스로 사용한다 (alembic.ini에 하드코딩 금지).
# URL 정규화는 db.url.normalize_to_asyncpg으로 통일 (#234) — alembic/seed/pytest/앱이
# 같은 정책을 공유한다. 사본을 두면 앱만 분기가 빠져 기동 실패하는 조합이 생긴다.
config.set_main_option("sqlalchemy.url", normalize_to_asyncpg(DATABASE_URL))

# ORM 모델(cii_platform.db.models)의 metadata를 연결하여 autogenerate를 활성화한다 (#101).
# 모델↔DB 일치(zero drift)는 tests/test_orm_schema_sync.py가 CI에서 검증한다.
target_metadata = Base.metadata


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
