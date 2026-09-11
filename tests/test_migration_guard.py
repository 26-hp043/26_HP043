"""되돌릴 수 없는 downgrade의 프로덕션 차단 (``DB_SCHEMA §8.1.2``, #819).

세 가지를 본다.

1. **가드 자체** — 프로덕션에서만 막고, 리비전을 명시하고 **24시간 안의 백업 기록**이
   있어야만 풀린다(#827)
2. **배선** — 목록에 올린 리비전의 ``downgrade()``가 **무엇이든 지우기 전에** 가드에서
   끊기는가. 소스를 읽지 않고 **실제로 호출**한다: ``op``를 건드리는 순간 실패하는 대역을
   끼워 두면, 가드가 빠졌거나 뒤로 밀린 것이 그대로 드러난다
3. **분류의 완전성** — 파괴적 연산을 가진 모든 ``downgrade()``가 세 목록 중 하나에
   들어 있는가. 새 마이그레이션이 분류를 빠뜨리면 여기서 걸린다(`#775` 다중 회사처럼 큰
   마이그레이션이 예정돼 있다)

DB가 필요 없다 — ``downgrade()``는 가드에서 끊기거나 대역에서 끊긴다.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cii_platform.db import migration_guard
from cii_platform.db.migration_guard import (
    ALLOW_ENV,
    BACKUP_MAX_AGE,
    EPHEMERAL,
    IRREVERSIBLE,
    REGENERABLE,
    guard_irreversible_downgrade,
)

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _files() -> dict[str, Path]:
    """리비전 → 파일. 파일명 앞 세 자리가 리비전이다(`DB_SCHEMA §8.1` 명명 규칙)."""
    return {p.name[:3]: p for p in sorted(_VERSIONS.glob("[0-9][0-9][0-9]_*.py"))}


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migration_guard, "is_production", lambda: True)
    monkeypatch.delenv(ALLOW_ENV, raising=False)


def _backup_age(monkeypatch: pytest.MonkeyPatch, age: timedelta | None) -> None:
    """마지막 ``DB_BACKUP`` 기록을 ``age`` 전으로 둔다(``None``이면 기록 없음).

    가드는 마이그레이션의 연결로 감사 로그를 읽는다. 여기서는 연결 없이 그 시각만 바꾼다 —
    실제 조회는 ``tests/test_migration_guard_backup_db.py``가 DB로 확인한다.
    """
    at = None if age is None else datetime.now(UTC) - age
    monkeypatch.setattr(migration_guard, "_migration_bind", lambda: object())
    monkeypatch.setattr(migration_guard, "last_backup_at", lambda bind: at)


@pytest.fixture
def fresh_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    _backup_age(monkeypatch, timedelta(hours=1))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 가드
# ─────────────────────────────────────────────────────────────────────────────


def test_blocks_in_production(production):
    with pytest.raises(RuntimeError, match="037"):
        guard_irreversible_downgrade("037")


def test_message_says_what_is_lost_and_how_to_unlock(production):
    """막기만 하고 이유를 말하지 않으면 운영자는 가드를 지우는 쪽으로 간다."""
    with pytest.raises(RuntimeError) as exc:
        guard_irreversible_downgrade("037")
    assert IRREVERSIBLE["037"] in str(exc.value)
    assert f"{ALLOW_ENV}=037" in str(exc.value)


def test_does_not_block_outside_production(monkeypatch: pytest.MonkeyPatch):
    """개발·테스트는 막지 않는다 — `test_zz_roundtrip.py`의 downgrade 검증이 여기에 기댄다."""
    monkeypatch.setattr(migration_guard, "is_production", lambda: False)
    monkeypatch.delenv(ALLOW_ENV, raising=False)
    guard_irreversible_downgrade("037")


def test_named_revision_unlocks_and_leaves_a_warning(production, fresh_backup, monkeypatch, caplog):
    monkeypatch.setenv(ALLOW_ENV, "016, 037")
    caplog.set_level("WARNING", logger=migration_guard.__name__)

    guard_irreversible_downgrade("037")

    assert any("037" in r.getMessage() for r in caplog.records)


def test_unlocking_one_revision_does_not_unlock_another(production, monkeypatch):
    """「전부 허용」이 없다 — 켜진 채 남은 스위치가 다음 롤백에서 같은 손실을 낸다."""
    monkeypatch.setenv(ALLOW_ENV, "037")
    with pytest.raises(RuntimeError, match="016"):
        guard_irreversible_downgrade("016")


@pytest.mark.parametrize("value", ["*", "all", "true", "1"])
def test_there_is_no_wildcard(production, monkeypatch, value):
    monkeypatch.setenv(ALLOW_ENV, value)
    with pytest.raises(RuntimeError):
        guard_irreversible_downgrade("037")


# ── 백업 연계 (#827 · 2026-09-11 결정 2-⑤) ────────────────────────────────────


def test_naming_the_revision_is_not_enough_without_a_backup(production, monkeypatch):
    """종전(#819)에는 명시 한 번으로 백업 없이 지울 수 있었다.

    「백업을 뜬 뒤」가 오류 문구에만 있었다.
    """
    monkeypatch.setenv(ALLOW_ENV, "037")
    _backup_age(monkeypatch, None)

    with pytest.raises(RuntimeError) as exc:
        guard_irreversible_downgrade("037")

    assert "백업 기록이 없습니다" in str(exc.value)
    assert "scripts/db_backup.py backup" in str(exc.value), "무엇을 하면 풀리는지 말한다"


def test_a_backup_older_than_the_window_does_not_count(production, monkeypatch):
    monkeypatch.setenv(ALLOW_ENV, "037")
    _backup_age(monkeypatch, BACKUP_MAX_AGE + timedelta(minutes=1))

    with pytest.raises(RuntimeError, match="마지막 백업이"):
        guard_irreversible_downgrade("037")


def test_a_backup_inside_the_window_counts(production, monkeypatch):
    monkeypatch.setenv(ALLOW_ENV, "037")
    _backup_age(monkeypatch, BACKUP_MAX_AGE - timedelta(minutes=1))

    guard_irreversible_downgrade("037")


def test_the_backup_is_not_consulted_before_the_revision_is_named(production, monkeypatch):
    """명시되지 않은 리비전은 백업이 있어도 막힌다 — 백업은 해제 조건의 **추가**다."""
    _backup_age(monkeypatch, timedelta(minutes=5))

    with pytest.raises(RuntimeError, match=f"{ALLOW_ENV}=037"):
        guard_irreversible_downgrade("037")


def test_the_backup_is_not_consulted_outside_production(monkeypatch: pytest.MonkeyPatch):
    """개발·테스트에는 백업이 없다 — 연결을 찾기만 해도 roundtrip 검증이 깨진다."""
    monkeypatch.setattr(migration_guard, "is_production", lambda: False)

    def _no_bind():
        raise AssertionError("프로덕션이 아니면 백업을 찾지 않는다")

    monkeypatch.setattr(migration_guard, "_migration_bind", _no_bind)
    guard_irreversible_downgrade("037")


# ─────────────────────────────────────────────────────────────────────────────
# 2. 배선 — 실제로 downgrade()를 부른다
# ─────────────────────────────────────────────────────────────────────────────


class _OpTouched(Exception):
    """가드를 지나 ``op``에 닿았다 — 지우는 연산이 실행되기 직전이다."""


class _TrapOp:
    def __getattr__(self, name: str):
        raise _OpTouched(name)


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("revision", sorted(IRREVERSIBLE))
def test_downgrade_stops_before_touching_anything(production, revision):
    module = _load(_files()[revision])
    module.op = _TrapOp()

    # `_OpTouched`가 나면 가드가 없거나 연산 뒤에 있는 것이다.
    with pytest.raises(RuntimeError, match=revision):
        module.downgrade()


@pytest.mark.parametrize("revision", sorted(IRREVERSIBLE))
def test_downgrade_guards_its_own_revision(production, monkeypatch, revision):
    """자기 리비전으로 해제하면 가드를 지나 ``op``에 닿는다.

    다른 리비전 번호를 복사해 붙이면(037 파일이 "016"을 부르면) 위 검사는 통과하지만
    해제가 엉뚱한 번호에 걸린다. 자기 번호로만 풀리는지를 여기서 본다.
    """
    monkeypatch.setenv(ALLOW_ENV, revision)
    _backup_age(monkeypatch, timedelta(hours=1))
    module = _load(_files()[revision])
    module.op = _TrapOp()

    with pytest.raises(_OpTouched):
        module.downgrade()


@pytest.mark.parametrize("revision", sorted(IRREVERSIBLE))
def test_named_but_unbacked_downgrade_stops_before_touching_anything(
    production, monkeypatch, revision
):
    """명시했어도 백업이 없으면 **무엇이든 지우기 전에** 끊긴다 (#827)."""
    monkeypatch.setenv(ALLOW_ENV, revision)
    _backup_age(monkeypatch, None)
    module = _load(_files()[revision])
    module.op = _TrapOp()

    with pytest.raises(RuntimeError, match="백업"):
        module.downgrade()


# ─────────────────────────────────────────────────────────────────────────────
# 3. 분류의 완전성
# ─────────────────────────────────────────────────────────────────────────────

#: 데이터를 지울 수 있는 ``op`` 호출.
_DESTRUCTIVE_OPS = {"drop_table", "drop_column"}
#: ``op.execute`` 문자열 안의 파괴적 SQL.
_DESTRUCTIVE_SQL = re.compile(r"\b(DELETE|TRUNCATE|DROP\s+TABLE|DROP\s+COLUMN)\b", re.I)


def _is_destructive(path: Path) -> bool:
    """``downgrade()``가 행·열·테이블을 지우는가 — 주석·docstring은 보지 않는다(AST)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    down = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "downgrade")
    for node in ast.walk(down):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == "op":
            if attr in _DESTRUCTIVE_OPS:
                return True
            if attr == "execute" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _DESTRUCTIVE_SQL.search(arg.value):
                        return True
                # SQLAlchemy Core 문(`table.delete()` · `table.update()`)을 넘기는 경우
                elif isinstance(arg, ast.Call):
                    return True
    return False


def test_every_destructive_downgrade_is_classified():
    """분류를 빠뜨린 리비전이 없다.

    어느 목록에도 없으면 「지워도 되는지」를 아무도 판단하지 않은 것이다. 세 목록 중
    하나에 **이유와 함께** 넣어야 한다 — `IRREVERSIBLE`(막는다) · `EPHEMERAL`(일시
    데이터) · `REGENERABLE`(다시 upgrade하면 돌아온다).
    """
    classified = IRREVERSIBLE.keys() | EPHEMERAL.keys() | REGENERABLE.keys()
    missing = sorted(
        rev for rev, path in _files().items() if _is_destructive(path) and rev not in classified
    )
    assert not missing, f"분류되지 않은 파괴적 downgrade: {missing}"


def test_classes_do_not_overlap():
    pairs = [
        ("IRREVERSIBLE", IRREVERSIBLE, "EPHEMERAL", EPHEMERAL),
        ("IRREVERSIBLE", IRREVERSIBLE, "REGENERABLE", REGENERABLE),
        ("EPHEMERAL", EPHEMERAL, "REGENERABLE", REGENERABLE),
    ]
    for a_name, a, b_name, b in pairs:
        assert not (a.keys() & b.keys()), f"{a_name} ∩ {b_name}: {sorted(a.keys() & b.keys())}"


def test_every_listed_revision_exists():
    """목록이 없는 리비전을 가리키지 않는다 — 번호를 잘못 적으면 가드가 엉뚱한 곳에 선다."""
    files = _files()
    listed = IRREVERSIBLE.keys() | EPHEMERAL.keys() | REGENERABLE.keys()
    assert not sorted(listed - files.keys())


def test_the_classifier_sees_the_known_cases():
    """판별기 자신을 먼저 잠근다 — 틀리면 위 완전성 검사가 조용히 통과한다.

    `037`(열 드롭) · `033`(DELETE 문자열) · `017`(Core `delete()`)은 파괴적이고,
    `036`(무동작)은 아니다.
    """
    files = _files()
    assert _is_destructive(files["037"])
    assert _is_destructive(files["033"])
    assert _is_destructive(files["017"])
    assert not _is_destructive(files["036"])
