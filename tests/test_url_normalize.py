"""``normalize_to_asyncpg`` 단위 테스트 (#234).

4곳(alembic · seed · pytest · 앱)이 공유하는 정규화 함수. 갈라진 분기가 다시
생기지 않도록 4가지 입력을 모두 잠근다.
"""

import pytest

from cii_platform.db.url import normalize_to_asyncpg


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # 1. 이미 asyncpg이면 그대로.
        (
            "postgresql+asyncpg://cii:cii@localhost:5432/cii",
            "postgresql+asyncpg://cii:cii@localhost:5432/cii",
        ),
        # 2. 드라이버 생략(postgresql://) → asyncpg 접두사로 교체.
        (
            "postgresql://cii:cii@localhost:5432/cii",
            "postgresql+asyncpg://cii:cii@localhost:5432/cii",
        ),
        # 3. 다른 드라이버(postgresql+psycopg://) → asyncpg으로 교체.
        #    배포 환경이 동기 드라이버 URL을 주는 경우 — 이슈 #234의 핵심.
        (
            "postgresql+psycopg://user:pass@db.example.com:5432/prod",
            "postgresql+asyncpg://user:pass@db.example.com:5432/prod",
        ),
        # 4. 다른 드라이버 + 쿼리 파라미터 유지.
        (
            "postgresql+psycopg://u:p@h:5432/db?sslmode=require",
            "postgresql+asyncpg://u:p@h:5432/db?sslmode=require",
        ),
    ],
)
def test_normalize_to_asyncpg_postgresql_variants(url: str, expected: str) -> None:
    """모든 PostgreSQL 스킴 변형을 ``postgresql+asyncpg://``로 통일 (#234)."""
    assert normalize_to_asyncpg(url) == expected


def test_normalize_to_asyncpg_passes_through_non_postgres_url() -> None:
    """비 PostgreSQL URL은 손대지 않는다 — 드라이버 mismatch 에러 가림 방지."""
    sqlite_url = "sqlite:///./test.db"
    assert normalize_to_asyncpg(sqlite_url) == sqlite_url


def test_normalize_to_asyncpg_is_idempotent() -> None:
    """이미 정규화된 URL을 다시 넣어도 변하지 않는다."""
    url = "postgresql+asyncpg://cii:cii@localhost:5432/cii"
    assert normalize_to_asyncpg(normalize_to_asyncpg(url)) == url
