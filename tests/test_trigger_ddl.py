"""`db/trigger_ddl.py` — 트리거 DDL의 멱등 계약 (#1373 · D-20).

CUBRID는 같은 이름의 트리거를 두 번 만드는 것을 막지 않고, 중복이 생기면 이름으로는 어느
쪽도 지울 수 없다(-503). 그래서 트리거를 만들고 지우는 마이그레이션 전부가 이 모듈을
지난다. DB 없이 **가짜 ``op``**로 넷을 고정한다.

1. 있으면 만들지 않는다 · 없으면 만든다
2. 없으면 지우지 않는다 · 있으면 지운다
3. 카탈로그에 있는데 ``-503``이 오면 넘어간다(경고) — 다른 오류는 그대로 올린다
4. ``existing``을 주면 카탈로그를 다시 묻지 않고, 만든·지운 이름을 그 집합에 반영한다
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import exc as sa_exc

from cii_platform.db import trigger_ddl
from cii_platform.db.trigger_ddl import create_trigger, drop_trigger, existing_triggers


class _Result:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def fetchall(self):
        return [(name,) for name in self._names]


class _Bind:
    def __init__(self, op: _FakeOp) -> None:
        self._op = op

    def execute(self, *_args, **_kwargs):
        self._op.catalog_reads += 1
        return _Result(sorted(self._op.names))


class _FakeOp:
    """``db_trigger``를 흉내 낸다 — ``CREATE``는 이름을 더하고 ``DROP``은 뺀다."""

    def __init__(self, names: set[str] = frozenset(), *, drop_error: Exception | None = None):
        self.names = set(names)
        self.executed: list[str] = []
        self.catalog_reads = 0
        self._drop_error = drop_error

    def get_bind(self):
        return _Bind(self)

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        verb, _, rest = sql.partition(" TRIGGER ")
        name = rest.split(" ", 1)[0]
        if verb == "CREATE":
            self.names.add(name)
        elif verb == "DROP":
            if self._drop_error is not None:
                raise self._drop_error
            self.names.discard(name)


def _not_found() -> sa_exc.DatabaseError:
    return sa_exc.DatabaseError(
        "DROP TRIGGER trg_x",
        {},
        Exception('Trigger "dba.trg_x" was not found. (errno=-503)'),
    )


# ── 1. CREATE ────────────────────────────────────────────────────────────────


def test_create_skips_an_existing_name():
    op = _FakeOp({"trg_x"})
    assert create_trigger(op, "trg_x", "BEFORE INSERT ON t EXECUTE REJECT") is False
    assert op.executed == []


def test_create_makes_a_missing_one_with_the_body_after_the_name():
    op = _FakeOp()
    assert create_trigger(op, "trg_x", "BEFORE INSERT ON t EXECUTE REJECT") is True
    assert op.executed == ["CREATE TRIGGER trg_x BEFORE INSERT ON t EXECUTE REJECT"]


# ── 2. DROP ──────────────────────────────────────────────────────────────────


def test_drop_skips_a_missing_name():
    op = _FakeOp()
    assert drop_trigger(op, "trg_x") is False
    assert op.executed == []


def test_drop_removes_an_existing_one():
    op = _FakeOp({"trg_x"})
    assert drop_trigger(op, "trg_x") is True
    assert op.executed == ["DROP TRIGGER trg_x"]
    assert op.names == set()


# ── 3. 카탈로그에는 있는데 -503 ─────────────────────────────────────────────────


def test_drop_tolerates_not_found_when_the_catalog_still_lists_it(caplog):
    """같은 이름이 둘 이상인 상태 — 롤백을 그 자리에서 멈추지 않고 경고로 남긴다."""
    caplog.set_level(logging.WARNING, logger=trigger_ddl.__name__)
    op = _FakeOp({"trg_x"}, drop_error=_not_found())

    assert drop_trigger(op, "trg_x") is False

    assert any("trg_x" in r.getMessage() and "#1373" in r.getMessage() for r in caplog.records)


def test_drop_raises_any_other_error():
    other = sa_exc.DatabaseError("DROP TRIGGER trg_x", {}, Exception("permission denied"))
    op = _FakeOp({"trg_x"}, drop_error=other)
    with pytest.raises(sa_exc.DatabaseError, match="permission denied"):
        drop_trigger(op, "trg_x")


# ── 4. existing 집합 ──────────────────────────────────────────────────────────


def test_existing_set_is_reused_and_kept_in_sync():
    """수십 개를 만드는 마이그레이션이 카탈로그를 한 번만 묻고, 지운 뒤 만들기가 통한다."""
    op = _FakeOp({"trg_a"})
    have = existing_triggers(op)
    assert have == {"trg_a"} and op.catalog_reads == 1

    assert drop_trigger(op, "trg_a", existing=have) is True
    assert "trg_a" not in have
    # 지운 이름을 집합에서 뺐으므로 같은 이름을 곧바로 다시 만들 수 있다(050·051·057의 교체 패턴).
    assert create_trigger(op, "trg_a", "BEFORE UPDATE ON t EXECUTE REJECT", existing=have) is True
    assert "trg_a" in have
    assert create_trigger(op, "trg_a", "BEFORE UPDATE ON t EXECUTE REJECT", existing=have) is False
    assert op.catalog_reads == 1
