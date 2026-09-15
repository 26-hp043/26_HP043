import asyncio
import contextlib
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection, engine_from_config
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Register CUBRID Alembic DDL implementation (#1058).
with contextlib.suppress(ImportError):
    from sqlalchemy_cubrid.alembic_impl import CubridImpl as _CubridImpl  # noqa: F401

# src 레이아웃을 sys.path에 추가하여 editable 설치 없이도 cii_platform을 import할 수 있게 한다.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cii_platform.config import DATABASE_URL  # noqa: E402
from cii_platform.db.models import Base  # noqa: E402
from cii_platform.db.url import normalize_to_async, normalize_to_sync  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ORM 모델의 metadata를 연결하여 autogenerate를 활성화한다 (#101).
target_metadata = Base.metadata


def _is_async_url(url: str) -> bool:
    """URL이 비동기 드라이버를 가리키는지 판단한다."""
    scheme = url.split("://", 1)[0]
    return any(marker in scheme for marker in ("aio", "async"))


def run_migrations_offline() -> None:
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


def _run_migrations_sync() -> None:
    url = normalize_to_sync(DATABASE_URL)
    config.set_main_option("sqlalchemy.url", url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


async def _run_migrations_async() -> None:
    url = normalize_to_async(DATABASE_URL)
    config.set_main_option("sqlalchemy.url", url)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Dispatch to sync or async runner based on URL scheme."""
    url = DATABASE_URL
    if _is_async_url(url):
        asyncio.run(_run_migrations_async())
    else:
        _run_migrations_sync()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
