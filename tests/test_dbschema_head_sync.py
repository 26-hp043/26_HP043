"""`DB_SCHEMA.md` ↔ alembic head · ORM 동기화 (#1342).

문서 헤더는 v1.33까지 올라가 있었는데 절 일곱이 `051` 이전에 멈춰 있었다 — §2.6에
`052`·`053` 컬럼이 없었고, §8.1.0 그래프는 `051`에서 끝났으며, §7.4 트리거 합계 148은
`051` 시점 값이었다. 헤더 판본으로는 그 낡음을 볼 수 없다(`AGENTS §4.3` — 숫자만 올리면
하지 않은 확인을 했다고 적는 것이 된다).

여기서 잠그는 것은 **마이그레이션·ORM에서 기계적으로 셀 수 있는 셋**이다.

1. §8.1.0 리비전 그래프의 끝이 `alembic/versions`의 head와 같다
2. §7.4 「지금 DB에 있는 트리거」 head 열의 합계가 `upgrade()`가 내는 `CREATE TRIGGER`
   누적에서 `DROP TRIGGER`를 뺀 수와 같다 — `op`를 스텁해 DB 없이 센다
3. §2.6 `annual_simulation_run` 표의 열 집합이 ORM 모델의 열 집합과 같다

세 가지 다 DB를 띄우지 않는다. FK 총람(§7.1)·`updated_at` 서술(§7.2)처럼 문장으로
적힌 것은 여기서 보지 않는다 — 그쪽은 `test_constraint_triggers_db.py`가 실 DB로 본다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DOC = _ROOT / "DB_SCHEMA.md"
_VERSIONS = _ROOT / "alembic" / "versions"

#: §8.1.0 — ``base → 1c444a5c4819 → … → 059``. 마지막 토큰이 head다.
_GRAPH = re.compile(r"^base → 1c444a5c4819 → .* → (?P<head>\w+)$", re.MULTILINE)
#: §7.4 트리거 표 합계 행 — ``| **합계** | **148** | **160** | …``. 둘째 수가 head 열이다.
_TRIGGER_TOTAL = re.compile(r"^\| \*\*합계\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \|", re.MULTILINE)
_CREATE = re.compile(r"CREATE\s+TRIGGER\s+(\w+)", re.IGNORECASE)
_DROP = re.compile(r"DROP\s+TRIGGER\s+(\w+)", re.IGNORECASE)


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """``### 2.6 `` 헤딩부터 다음 같은 단계 헤딩 전까지."""
    start = text.index(heading)
    nxt = re.compile(r"^#{1,3} ", re.MULTILINE).search(text, start + len(heading))
    return text[start : nxt.start() if nxt else len(text)]


def _load_migrations() -> list[types.ModuleType]:
    """리비전 사슬 순서대로. 이름을 따로 붙여 `test_migration_guard`의 적재와 겹치지 않게 한다."""
    modules: list[types.ModuleType] = []
    for path in sorted(_VERSIONS.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"_dbschema_head_sync_{path.stem}", path)
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


class _CountingOp:
    """``op.execute``의 SQL에서 트리거 생성·삭제만 집계하고 나머지 연산은 삼킨다."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.dropped: list[str] = []

    def execute(self, sql, *args, **kwargs) -> None:
        text = str(sql)
        self.created.extend(_CREATE.findall(text))
        self.dropped.extend(_DROP.findall(text))

    def get_bind(self):
        return _NullBind()

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


class _NullResult:
    def scalar(self):
        return 0

    scalar_one = scalar

    def fetchall(self):
        return []

    all = fetchall

    def first(self):
        return None


class _NullBind:
    dialect = types.SimpleNamespace(name="cubrid")

    def execute(self, *args, **kwargs):
        return _NullResult()


@pytest.fixture
def stub_alembic(monkeypatch):
    op = _CountingOp()
    fake = types.ModuleType("alembic")
    fake.op = op  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "alembic", fake)
    monkeypatch.setitem(sys.modules, "alembic.op", op)
    return op


def test_revision_graph_ends_at_alembic_head(stub_alembic):
    """§8.1.0 그래프의 끝 = `alembic/versions`의 head. `051`에서 멈춰 있었다."""
    chain = _load_migrations()
    match = _GRAPH.search(_doc())
    assert match, "§8.1.0 리비전 그래프(`base → 1c444a5c4819 → …`)를 찾지 못했다"
    assert match.group("head") == chain[-1].revision, (
        f"§8.1.0 그래프는 {match.group('head')}에서 끝나는데 head는 {chain[-1].revision}이다"
    )


def test_trigger_total_matches_migrations(stub_alembic):
    """§7.4 트리거 표 head 열 합계 = CREATE TRIGGER 누적 − DROP TRIGGER. 148은 `051` 시점이었다."""
    live: set[str] = set()
    for module in _load_migrations():
        stub_alembic.created.clear()
        stub_alembic.dropped.clear()
        module.upgrade()
        live -= set(stub_alembic.dropped)
        live |= set(stub_alembic.created)
    match = _TRIGGER_TOTAL.search(_doc())
    assert match, "§7.4 「지금 DB에 있는 트리거」 합계 행(`| **합계** | **N** | **N** |`)이 없다"
    assert int(match.group(2)) == len(live), (
        f"§7.4 head 열 합계 {match.group(2)} ≠ 마이그레이션 실측 {len(live)}"
    )


def test_annual_simulation_run_columns_match_orm():
    """§2.6 표의 열 = ORM `AnnualSimulationRun`의 열.

    `052` `as_of`·`053` `alternative_fuel`이 빠져 있었다.
    """
    from cii_platform.db.models.annual_simulation_run import AnnualSimulationRun

    section = _section(_doc(), "### 2.6 `annual_simulation_run`")
    documented = set(re.findall(r"^\| `(\w+)` \|", section, re.MULTILINE))
    orm = {column.name for column in AnnualSimulationRun.__table__.columns}
    assert documented == orm, (
        f"§2.6 표에만: {sorted(documented - orm)} · ORM에만: {sorted(orm - documented)}"
    )
