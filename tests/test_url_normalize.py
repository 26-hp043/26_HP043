"""``normalize_to_async`` / ``normalize_to_sync`` 단위 테스트 (#234 -> #1058 CUBRID 전환).

4곳(alembic · seed · pytest · 앱)이 공유하는 정규화 함수. 갈라진 분기가 다시
생기지 않도록 입력 변형을 잠근다.
"""

import pytest

from cii_platform.db.url import normalize_to_async, normalize_to_sync


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # 1. 이미 aiopycubrid이면 그대로.
        (
            "cubrid+aiopycubrid://dba:@localhost:33000/cii",
            "cubrid+aiopycubrid://dba:@localhost:33000/cii",
        ),
        # 2. 드라이버 생략(cubrid://) → aiopycubrid 접두사로 교체.
        (
            "cubrid://dba:@localhost:33000/cii",
            "cubrid+aiopycubrid://dba:@localhost:33000/cii",
        ),
        # 3. 동기 드라이버(cubrid+pycubrid://) → aiopycubrid로 교체.
        (
            "cubrid+pycubrid://dba:pass@db.example.com:33000/prod",
            "cubrid+aiopycubrid://dba:pass@db.example.com:33000/prod",
        ),
    ],
)
def test_normalize_to_async_cubrid_variants(url: str, expected: str) -> None:
    """모든 CUBRID 스킴 변형을 ``cubrid+aiopycubrid://``로 통일."""
    assert normalize_to_async(url) == expected


def test_normalize_to_async_passes_through_non_cubrid_url() -> None:
    """비 CUBRID URL은 손대지 않는다."""
    sqlite_url = "sqlite:///./test.db"
    assert normalize_to_async(sqlite_url) == sqlite_url


def test_normalize_to_async_is_idempotent() -> None:
    """이미 정규화된 URL을 다시 넣어도 변하지 않는다."""
    url = "cubrid+aiopycubrid://dba:@localhost:33000/cii"
    assert normalize_to_async(normalize_to_async(url)) == url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "cubrid+aiopycubrid://dba:@localhost:33000/cii",
            "cubrid+pycubrid://dba:@localhost:33000/cii",
        ),
        (
            "cubrid://dba:@localhost:33000/cii",
            "cubrid+pycubrid://dba:@localhost:33000/cii",
        ),
        (
            "cubrid+pycubrid://dba:@localhost:33000/cii",
            "cubrid+pycubrid://dba:@localhost:33000/cii",
        ),
    ],
)
def test_normalize_to_sync_cubrid_variants(url: str, expected: str) -> None:
    """동기 컨텍스트용 ``cubrid+pycubrid://``로 통일."""
    assert normalize_to_sync(url) == expected
