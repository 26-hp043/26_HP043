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

import inspect

import pytest
from conftest import TEST_DATABASE_URL
from db_target import (
    TEST_DB_SUFFIX,
    database_name,
    is_disposable,
    refusal_reason,
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


# --- 가드를 「거는 곳」 (#691) ---------------------------------------------------
#
# `#507`은 판정을 만들고 **한 파일에만** 걸었다. 나머지 12개 파일은 그대로 개발 DB에
# 붙어 계정을 지웠고, 2026-08-23에 실제로 가입 계정이 사라졌다.
#
# **판정이 옳은 것과 그 판정이 실제로 걸려 있는 것은 다른 문제다.** 위 클래스들이
# 앞을 보고, 아래가 뒤를 본다.


class TestRefusalReason:
    """막을 때 **대상·이유·해결**을 함께 말한다. 하나라도 빠지면 사람은 우회를 찾는다."""

    def test_names_the_target_and_the_way_out(self):
        reason = refusal_reason("postgresql+asyncpg://cii:cii@localhost:5432/cii")

        assert "'cii'" in reason, "어느 DB가 막혔는지 말해야 한다"
        assert "#691" in reason
        assert "app_user" in reason, "무엇을 잃는지 말해야 한다"
        assert "createdb -U cii cii_test" in reason, "해결 명령이 있어야 한다"
        assert "DATABASE_URL=" in reason

    def test_says_ci_is_unaffected(self):
        """**CI가 막힌 줄 알고 되돌리는 것**을 막는다 — CI는 이미 cii_test를 쓴다."""
        assert "cii_test" in refusal_reason("postgresql://u:p@h:5432/cii")
        assert "ci.yml" in refusal_reason("postgresql://u:p@h:5432/cii")

    def test_is_not_the_skip_reason(self):
        """skip과 refusal은 읽는 사람이 할 일이 다르다 — 문장을 돌려 쓰지 않는다."""
        url = "postgresql://u:p@h:5432/cii"
        assert refusal_reason(url) != skip_reason(url)


class TestGuardVerdict:
    """``conftest.require_disposable_target``이 실제로 막고 실제로 통과시킨다."""

    def test_refuses_the_development_database(self, monkeypatch: pytest.MonkeyPatch):
        import conftest

        monkeypatch.setattr(
            conftest, "TEST_DATABASE_URL", "postgresql+asyncpg://cii:cii@localhost:5432/cii"
        )
        with pytest.raises(pytest.fail.Exception) as caught:
            conftest.require_disposable_target()

        # **skip이 아니라 fail이다.** skip은 조용해서 「돌았다고 착각」할 여지를 남긴다.
        assert "#691" in str(caught.value)

    def test_allows_a_test_database(self, monkeypatch: pytest.MonkeyPatch):
        import conftest

        monkeypatch.setattr(
            conftest, "TEST_DATABASE_URL", "postgresql+asyncpg://cii:cii@localhost:5432/cii_test"
        )
        conftest.require_disposable_target()  # 예외가 없어야 한다


class TestGuardIsActuallyWired:
    """**`#507`이 놓친 것이 여기다** — 판정 함수는 있었고 부르는 곳이 없었다.

    ``require_disposable_target``이 정의만 되고 fixture에서 빠지면 이 파일의 다른
    테스트는 전부 통과한다. 그 상태가 정확히 2026-08-23 이전이었다.

    그래서 **호출이 걸려 있는지**를 소스로 확인한다. `tests/test_demo_up_script.py`가
    셸 스크립트를 같은 방식으로 검사한다.
    """

    #: DB를 여는 자리. 하나라도 빠지면 그 경로로 개발 DB에 붙을 수 있다.
    ENTRY_POINTS = ("run_alembic", "migrated_db", "app_fresh_engine")

    @pytest.mark.parametrize("name", ENTRY_POINTS)
    def test_entry_point_calls_the_guard(self, name: str):
        import conftest

        target = getattr(conftest, name)
        # fixture는 데코레이터에 싸여 있다 — 원본 함수를 본다.
        source = inspect.getsource(getattr(target, "__wrapped__", target))

        assert "require_disposable_target()" in source, (
            f"conftest.{name}이 대상 DB 판정을 부르지 않는다. "
            "이 경로로 개발 DB에 붙을 수 있다 (#691)."
        )

    def test_the_offending_files_all_go_through_a_guarded_fixture(self):
        """`#691`이 지목한 12개 파일이 **가드가 걸린 fixture**를 통과한다.

        파일마다 가드를 붙이지 않는 대신, 그 파일들이 실제로 이 경로를 지나는지를
        확인한다. 어느 하나가 fixture 없이 DB를 열기 시작하면 여기서 드러난다.
        """
        from pathlib import Path

        offenders = [
            "test_account_self_service_db.py",
            "test_app_user_migration.py",
            "test_audit_actions_db.py",
            "test_audit_events_db.py",
            "test_auth_api.py",
            "test_auth_failure_paths.py",
            "test_auth_tokens.py",
            "test_auth_wiring.py",
            "test_calculations_query_db.py",
            "test_cii_history.py",
            "test_dev_auth.py",
            "test_scenario_compare_db.py",
        ]
        tests_dir = Path(__file__).resolve().parent

        unguarded = []
        for name in offenders:
            path = tests_dir / name
            assert path.exists(), f"{name}이 없다 — 목록이 낡았는지 확인할 것"
            text = path.read_text(encoding="utf-8")
            if not any(f in text for f in ("migrated_db", "app_fresh_engine", "conn")):
                unguarded.append(name)

        assert not unguarded, (
            f"가드가 걸린 fixture를 쓰지 않는 파일이 있다: {unguarded}. "
            "이 파일들은 개발 DB에 직접 붙을 수 있다 (#691)."
        )
