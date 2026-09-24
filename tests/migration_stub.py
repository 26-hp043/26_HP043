"""DB 없이 마이그레이션 ``upgrade()``를 돌려 트리거 집합을 세는 스텁 (#1373 · #1342 · #1861).

``tests/test_dbschema_head_sync.py``(§7.4 합계 대조)와 ``tests/test_zz_roundtrip.py``(head DB의
트리거 이름 대조)가 함께 쓴다. ``tests/``는 패키지가 아니지만 pytest가 ``rootdir``의
``tests/``를 ``sys.path``에 넣으므로 ``from conftest import …``·``from db_target import …``와
같은 방식으로 ``from migration_stub import …``가 로컬·CI 양쪽에서 된다 — 막히는 것은
``from tests.X import``(패키지 경로) 쪽이다.

## 카탈로그를 스텁이 답한다

``db/trigger_ddl.py``는 만들기·지우기 전에 ``db_trigger``를 묻는다. 그 조회가 늘 빈 결과를
받으면 **지우는 쪽이 전부 건너뛰어** ``050``·``051``·``057``의 지우고-다시-만들기가 실제와
다르게 집계된다(중복이 있어도 집합이라 티가 안 날 뿐이다). 그래서 ``execute``가 지금까지
만든−지운 이름을 ``live``로 들고, ``db_trigger`` 조회에는 그 집합으로 답한다 — 헬퍼가 실제
DB에서 하는 그대로 지우고 만든다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

CREATE_TRIGGER = re.compile(r"CREATE\s+TRIGGER\s+(\w+)", re.IGNORECASE)
#: 이름 뒤의 본문 전부 — ``BEFORE INSERT ON vessel IF NOT (…) EXECUTE REJECT``.
CREATE_TRIGGER_BODY = re.compile(r"CREATE\s+TRIGGER\s+(\w+)\s+(.*)$", re.IGNORECASE | re.DOTALL)


def normalized_body(body: str) -> str:
    """본문 비교용 — 공백만 한 칸으로. 뜻이 같은데 줄바꿈만 다른 것을 「다르다」로 읽지 않는다."""
    return " ".join(body.split())


DROP_TRIGGER = re.compile(r"DROP\s+TRIGGER\s+(\w+)", re.IGNORECASE)


class CountingOp:
    """``op.execute``의 SQL에서 트리거 생성·삭제만 집계하고 나머지 연산은 삼킨다."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.dropped: list[str] = []
        #: 지금까지의 사슬이 남긴 트리거 — ``db_trigger`` 조회에 이것으로 답한다.
        self.live: set[str] = set()
        #: 살아 있는 트리거의 본문(정규화) — ``create_trigger`` 건너뜀을 판정한다 (#1861).
        self.bodies: dict[str, str] = {}
        #: 「이미 있는 이름에 다른 본문으로 ``create_trigger``」 — (이름, 있던 본문, 부른 본문).
        #: 헬퍼는 그 호출을 **조용히 건너뛰어** 운영 DB에는 옛 정의가, 새 DB에는 새 정의가
        #: 남는다. 본문을 바꾸려면 ``replace_trigger``를 쓴다.
        self.skipped_changes: list[tuple[str, str, str]] = []

    def execute(self, sql, *args, **kwargs) -> None:
        text = str(sql)
        created = CREATE_TRIGGER.findall(text)
        dropped = DROP_TRIGGER.findall(text)
        self.created.extend(created)
        self.dropped.extend(dropped)
        self.live.difference_update(dropped)
        self.live.update(created)
        for name in dropped:
            self.bodies.pop(name, None)
        match = CREATE_TRIGGER_BODY.match(text.strip())
        if match:
            self.bodies[match.group(1)] = normalized_body(match.group(2))

    def get_bind(self):
        return NullBind(self)

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


class NullResult:
    def __init__(self, rows: list[tuple[str]] | None = None) -> None:
        self._rows = rows or []

    def scalar(self):
        return 0

    scalar_one = scalar

    def fetchall(self):
        return list(self._rows)

    all = fetchall

    def first(self):
        return self._rows[0] if self._rows else None


class NullBind:
    dialect = types.SimpleNamespace(name="cubrid")

    def __init__(self, op: CountingOp) -> None:
        self._op = op

    def execute(self, sql, *args, **kwargs):
        if "db_trigger" in str(sql):
            return NullResult([(name,) for name in sorted(self._op.live)])
        return NullResult()


def install(monkeypatch: pytest.MonkeyPatch) -> CountingOp:
    """``alembic``을 세는 스텁으로 갈아 끼운다 — 마이그레이션의 ``op``가 이것이 된다.

    ``db/trigger_ddl.create_trigger``도 감싼다 — 이름이 이미 있는데 **본문이 다르면**
    ``skipped_changes``에 적는다(#1861). 마이그레이션은 모듈을 적재할 때 그 이름을
    가져가므로(``from … import create_trigger``) 이 함수가 :func:`load_chain` **전에**
    불려야 감싼 것이 들어간다.
    """
    from cii_platform.db import trigger_ddl

    op = CountingOp()
    fake = types.ModuleType("alembic")
    fake.op = op  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "alembic", fake)
    monkeypatch.setitem(sys.modules, "alembic.op", op)

    original = trigger_ddl.create_trigger

    def checking_create_trigger(op_, name, body, *, existing=None):
        before = op.bodies.get(name)
        if before is not None and before != normalized_body(body):
            op.skipped_changes.append((name, before, normalized_body(body)))
        return original(op_, name, body, existing=existing)

    monkeypatch.setattr(trigger_ddl, "create_trigger", checking_create_trigger)
    return op


def load_chain(prefix: str) -> list[types.ModuleType]:
    """리비전 사슬 순서대로. ``prefix``를 달리해 다른 검사 파일의 적재와 겹치지 않게 한다."""
    modules: list[types.ModuleType] = []
    for path in sorted(VERSIONS.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"{prefix}_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    by_down = {m.down_revision: m for m in modules}
    chain: list[types.ModuleType] = []
    rev = None
    while rev in by_down:
        chain.append(by_down[rev])
        rev = by_down[rev].revision
    assert len(chain) == len(modules), "리비전 사슬이 한 줄이 아니다 — 분기가 생겼다"
    return chain


def run_chain(monkeypatch: pytest.MonkeyPatch, prefix: str) -> CountingOp:
    """base부터 head까지 ``upgrade()``를 차례로 부르고 스텁을 돌려준다."""
    op = install(monkeypatch)
    for module in load_chain(prefix):
        module.upgrade()
    return op


def head_triggers(monkeypatch: pytest.MonkeyPatch, prefix: str) -> set[str]:
    """base부터 head까지 ``upgrade()``를 차례로 불러 남는 트리거 이름 집합."""
    return set(run_chain(monkeypatch, prefix).live)
