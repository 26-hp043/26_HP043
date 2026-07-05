import os

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cii:cii@localhost:5432/cii",
)
