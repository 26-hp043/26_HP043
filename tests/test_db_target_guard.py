"""이슈 #507 · 파괴적 테스트가 개발 DB를 치지 않게 한다.

**막으려는 것은 실수가 아니라 조용한 손실이다.**

`tests/test_zz_roundtrip.py`는 `alembic downgrade base`로 스키마를 통째로 드롭한다.
그 검사는 정당하지만(`DB_SCHEMA §8.1` 롤백 안전성), `conftest.py`가 `DATABASE_URL`을
그대로 대상으로 써서 **개발 DB와 테스트 DB가 같은 데이터베이스**였다. `pytest`를 한 번
돌릴 때마다 `app_user`가 사라졌고, 실제로 가입 계정이 그렇게 없어졌다.

여기서 고정하는 것은 둘이다.

1. **이름이 `_test`로 끝나는 DB에서만 파괴적 테스트가 돈다**
2. **CI에서는 그 테스트가 skip되지 않는다** — 가드가 생긴 뒤 CI의 DB 이름이 바뀌면
   회귀 검사가 사라지는데, 그 손실은 아무 신호 없이 일어난다

두 번째가 이 파일의 핵심이다. 가드는 안전을 얻는 대신 **검사를 잃을 위험**을 만든다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 테스트 인프라 가드)
"""

from __future__ import annotations

import pytest
from conftest import TEST_DATABASE_URL
from db_target import (
    TEST_DB_SUFFIX,
    database_name,
    is_disposable,
    running_in_ci,
    skip_reason,
)


class TestDatabaseName:
    """표기 방식이 달라도 같은 이름이 나와야 한다 — 판정이 표기에 흔들리면 가드가 아니다."""

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("postgresql://cii:cii@localhost:5432/cii", "cii"),
            ("postgresql+asyncpg://cii:cii@localhost:5432/cii_test", "cii_test"),
            ("postgresql+psycopg://u:p@db:5432/cii_test?sslmode=require", "cii_test"),
            ("postgresql://u:p@host/only_db", "only_db"),
        ],
    )
    def test_extracts_name(self, url: str, expected: str):
        assert database_name(url) == expected

    def test_missing_name_is_empty(self):
        assert database_name("postgresql://u:p@host:5432") == ""


class TestIsDisposable:
    """모르면 허용하지 않는다."""

    def test_test_suffix_is_allowed(self):
        assert is_disposable("postgresql://u:p@h:5432/cii_test")
        assert is_disposable("postgresql+asyncpg://u:p@h:5432/anything_test")

    def test_dev_database_is_not_allowed(self):
        # 이 이름이 실제로 데이터를 잃은 대상이다.
        assert not is_disposable("postgresql://cii:cii@localhost:5432/cii")

    def test_name_that_merely_contains_test_is_not_allowed(self):
        # `testing`·`cii_test_backup`처럼 끝나지 않는 이름은 허용하지 않는다.
        assert not is_disposable("postgresql://u:p@h:5432/testing")
        assert not is_disposable("postgresql://u:p@h:5432/cii_test_backup")

    def test_bare_suffix_is_not_allowed(self):
        # `_test`라는 이름만으로는 의도를 알 수 없다.
        assert not is_disposable("postgresql://u:p@h:5432/_test")

    def test_missing_name_is_not_allowed(self):
        assert not is_disposable("postgresql://u:p@h:5432")


class TestSkipReason:
    """건너뛸 때 왜인지·어떻게 하면 되는지 함께 말한다."""

    def test_names_the_target_and_the_way_out(self):
        reason = skip_reason("postgresql://cii:cii@localhost:5432/cii")
        assert "cii" in reason
        assert "#507" in reason
        assert TEST_DB_SUFFIX in reason
        # 해결 방법을 적지 않으면 사용자는 검사를 잃은 채로 지나간다.
        assert "DATABASE_URL=" in reason

    def test_missing_name_still_readable(self):
        assert "(이름 없음)" in skip_reason("postgresql://u:p@h:5432")


class TestRunningInCi:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
    def test_truthy(self, value: str):
        assert running_in_ci({"CI": value})

    @pytest.mark.parametrize("value", ["", "false", "0", "no"])
    def test_falsy(self, value: str):
        assert not running_in_ci({"CI": value})

    def test_absent_is_false(self):
        assert not running_in_ci({})


def test_ci_runs_against_a_disposable_database():
    """**CI에서 롤백 테스트가 조용히 skip되면 안 된다.**

    가드는 안전을 얻는 대신 검사를 잃을 위험을 만든다. CI의 postgres 서비스가
    `POSTGRES_DB: cii_test`를 쓰는 한 성립하고(`.github/workflows/ci.yml`), 그 이름이
    바뀌면 **여기서 실패한다** — 롤백 회귀 검사가 사라진 사실이 조용히 지나가지 않는다.

    로컬에서는 아무것도 요구하지 않는다. 개발 DB를 가리키는 것이 정상이다.
    """
    if not running_in_ci():
        pytest.skip("로컬 실행 — CI 전용 단언이다")
    assert is_disposable(TEST_DATABASE_URL), (
        f"CI가 파괴적 테스트를 돌릴 수 없는 DB를 가리키고 있다: "
        f"{database_name(TEST_DATABASE_URL)!r}. "
        "test_zz_roundtrip.py가 전부 skip되어 롤백 회귀 검사가 사라진다. "
        ".github/workflows/ci.yml의 POSTGRES_DB를 확인하라 (#507)."
    )
