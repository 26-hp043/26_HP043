"""만료 행 정리 스크립트 (`#827` ⑶ · IT-PURGE-001~007).

## 왜 검사가 필요한가

이 스크립트는 **지우는 것**이고, 지운 것은 되돌릴 수 없다. 그런데 프로덕션 호스트
cron에서 도는 물건이라 **아무도 보고 있지 않을 때** 실행된다.

가짜 실행기를 끼워 **실제로 어떤 SQL이 나가는지**를 본다 — DB를 붙이면 「지워졌다」는
확인할 수 있어도 「무엇을 지우려 했는지」는 못 본다.

## 특히 조심하는 두 가지

=====================================  =============================================
 `--dry-run`이 세는 조건이 실제 삭제 조건  다르면 **dry-run이 거짓말을 한다**
 살아 있는 세션을 건드리지 않는다          만료 조건 없는 `DELETE`는 전원 로그아웃이다
=====================================  =============================================
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "purge_expired.py"


def _load():
    spec = importlib.util.spec_from_file_location("purge_expired", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["purge_expired"] = module
    spec.loader.exec_module(module)
    return module


purge_expired = _load()


class _FakeDb:
    """나간 SQL을 모으고, 정해 둔 답을 돌려준다."""

    def __init__(self, answers: dict[str, str] | None = None, fail: set[str] | None = None):
        self.sql: list[str] = []
        self.plain: list[bool] = []
        self._answers = answers or {}
        self._fail = fail or set()

    def query(self, sql: str, *, plain: bool = True) -> str:
        self.sql.append(sql)
        self.plain.append(plain)
        for marker in self._fail:
            if marker in sql:
                raise purge_expired.QueryError(f'relation "{marker}" does not exist')
        for marker, answer in self._answers.items():
            if marker in sql:
                # `--dry-run`은 세는 문장이라 숫자만 오고, 실제 삭제는 csql의 장식
                # 출력이 온다. 답을 숫자로만 적어 두면 **DELETE 경로가 검사되지 않는다.**
                return answer if plain else f"{answer} rows affected. (0.001 sec)"
        return "0" if plain else "0 row affected. (0.001 sec)"


def test_every_statement_filters_by_expiry() -> None:
    """IT-PURGE-001 — ⚠️ **조건 없는 `DELETE`가 하나도 없다**.

    조건을 빠뜨린 `DELETE FROM user_session`은 **전원 로그아웃**이다. 코드 리뷰로
    놓치기 쉬운 한 줄이라 단언으로 고정한다.
    """
    for table in purge_expired._SQL:
        sql = purge_expired.delete_sql(table, 7)
        assert sql.startswith(f"DELETE FROM {table} WHERE "), sql
        # ⚠️ **열 이름이 아니라 「시각으로 자른다」는 성질**을 단언한다 (`#1347`).
        # 종전에는 `expires_at`을 글자 그대로 찾았는데, `weather_snapshot`은
        # 만료 열이 없어 `fetched_at`(그 기상이 언제 것인가)으로 자른다.
        condition = sql.partition(" WHERE ")[2]
        assert any(column in condition for column in ("expires_at", "fetched_at")), sql


def test_dry_run_counts_exactly_what_delete_would_remove() -> None:
    """IT-PURGE-002 — 세는 조건과 지우는 조건이 **글자 그대로 같다**.

    다르면 `--dry-run`이 거짓말을 한다 — 「3건입니다」를 보고 실행했더니 300건이
    지워지는 것이 이 검사가 막는 일이다.
    """
    for table in purge_expired._SQL:
        delete_condition = purge_expired.delete_sql(table, 7).partition(" WHERE ")[2]
        count_condition = purge_expired.count_sql(table, 7).partition(" WHERE ")[2]
        assert delete_condition == count_condition, table
        assert purge_expired.count_sql(table, 7).startswith("SELECT count(*)")


def test_grace_days_applies_to_sessions_and_tokens_only() -> None:
    """IT-PURGE-003 — 유예는 세션·토큰에만 붙고 **채팅에는 안 붙는다**.

    채팅의 `expires_at`은 이미 `PRD §16.3`의 90일이다. 거기에 유예를 더하면
    「90일 보존」이 사실과 달라진다 — 97일이 된다.
    """
    # `#1058` — CUBRID에 `make_interval`이 없어 `DATE_SUB(NOW(), INTERVAL n DAY)`로
    # 옮겼다. 검사가 보는 것은 **유예가 붙는 자리**이지 함수 이름이 아니다.
    assert "INTERVAL 7 DAY" in purge_expired.delete_sql("user_session", 7)
    assert "INTERVAL 7 DAY" in purge_expired.delete_sql("user_token", 7)
    assert "INTERVAL" not in purge_expired.delete_sql("chat_session", 7)
    # `weather_snapshot`도 유예를 받지 않는다 (`#1347`) — 30일은 `DB_SCHEMA §4.3`이
    # 정한 값이라 인자로 열면 정본과 다른 값으로 돌릴 수 있게 된다.
    weather = purge_expired.delete_sql("weather_snapshot", 7)
    assert "INTERVAL 7 DAY" not in weather
    assert f"INTERVAL {purge_expired.WEATHER_RETENTION_DAYS} DAY" in weather


def test_weather_snapshots_that_something_points_at_are_kept() -> None:
    """⚠️ **참조 검사가 두 표다** (`DB_SCHEMA §2.13` · `#1347`).

    `calculation_run`은 `ON DELETE RESTRICT`라 지우려 들면 DB가 막는다. 그런데
    `voyage_scenario`는 **`ON DELETE SET NULL`**이라 막지 않고 **조용히 링크만
    끊는다** — 「어느 기상으로 계산했나」가 사라진 것을 아무도 모른다. 그쪽이 더
    나쁘므로 두 표 모두에서 미참조인 행만 지운다.
    """
    sql = purge_expired.delete_sql("weather_snapshot", 7)

    for table in ("calculation_run", "voyage_scenario"):
        assert f"SELECT weather_snapshot_id FROM {table}" in sql, table
    # `NOT IN`에 NULL이 하나라도 섞이면 **전체가 거짓**이 되어 한 행도 지우지 못한다.
    assert sql.count("weather_snapshot_id IS NOT NULL") == 2, sql


def test_a_failing_table_does_not_stop_the_others() -> None:
    """IT-PURGE-004 — ⚠️ 한 표가 실패해도 **나머지는 돈다**.

    실제로 겪었다 — 마이그레이션이 덜 적용된 판에서 `chat_session`이 없어 앞의 두
    표까지 함께 멈췄다. 배포 순서상 **코드가 먼저 가고 마이그레이션이 뒤따르는**
    순간이 있으므로, 그 틈에서도 세션 정리는 돌아야 한다.
    """
    db = _FakeDb(answers={"user_session": "5", "user_token": "2"}, fail={"chat_session"})
    counts, failures = purge_expired.purge(db, grace_days=7, dry_run=True)

    # 표를 통째로 비교하지 않는다 (`#1347`) — 대상 표가 하나 늘 때마다 깨지는데,
    # 이 검사가 지키려는 것은 **실패한 표가 나머지를 세우지 않는다**이지
    # 「대상이 정확히 셋이다」가 아니다.
    assert counts["user_session"] == 5
    assert counts["user_token"] == 2
    assert "chat_session" not in counts
    assert set(failures) == {"chat_session"}


def test_failure_makes_the_exit_code_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    """IT-PURGE-005 — 실패가 있으면 **0을 내지 않는다**.

    cron이 성공으로 읽으면 아무도 모른다. 「돌긴 도는데 아무것도 안 지워지는」 상태가
    가장 오래 숨는다.
    """
    db = _FakeDb(fail={"chat_session"})
    monkeypatch.setattr(purge_expired, "Db", lambda *_a, **_k: db)
    assert purge_expired.main(["--dry-run"]) == 1


def test_success_records_an_audit_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """IT-PURGE-006 — 감사 로그에 남긴다. **지운 것이 없어도** 남긴다.

    「돌았는데 지울 것이 없었다」와 「안 돌았다」는 다르고, 그 차이가 이 작업이 살아
    있는지의 유일한 증거다(`#827` ⑵ 관측성). `db_backup.py`의 `DB_BACKUP`과 같은
    자리다.
    """
    db = _FakeDb()
    monkeypatch.setattr(purge_expired, "Db", lambda *_a, **_k: db)
    assert purge_expired.main([]) == 0

    inserts = [s for s in db.sql if s.startswith("INSERT INTO audit_log")]
    assert len(inserts) == 1

    # `#1058` — `action`은 **CUBRID 예약어**다. 인용을 빠뜨리면 구문 오류가 나고
    # 감사 기록만 조용히 사라진다. 실행해서 확인한 자리라 문자열로 잠근다.
    assert '"action"' in inserts[0], inserts[0]
    # `audit_log.id`는 기본값이 없다 — 빠지면 NOT NULL 위반이다.
    assert "(id, " in inserts[0], inserts[0]
    assert purge_expired.PURGE_ACTION in inserts[0]
    assert '"grace_days"' in inserts[0]


def test_dry_run_never_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    """IT-PURGE-007 — `--dry-run`은 `DELETE`도 감사 기록도 내지 않는다.

    **보려고 돌린 것이 지워 버리면** 다음부터 아무도 dry-run을 쓰지 않는다.
    """
    db = _FakeDb()
    monkeypatch.setattr(purge_expired, "Db", lambda *_a, **_k: db)
    assert purge_expired.main(["--dry-run"]) == 0

    assert not [s for s in db.sql if s.startswith("DELETE")]
    assert not [s for s in db.sql if s.startswith("INSERT")]
