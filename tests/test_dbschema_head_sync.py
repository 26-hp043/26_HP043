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

import re
from pathlib import Path

import pytest
from migration_stub import head_triggers, install, load_chain, run_chain

_ROOT = Path(__file__).resolve().parents[1]
_DOC = _ROOT / "DB_SCHEMA.md"

#: §8.1.0 — ``base → 1c444a5c4819 → … → 059``. 마지막 토큰이 head다.
_GRAPH = re.compile(r"^base → 1c444a5c4819 → .* → (?P<head>\w+)$", re.MULTILINE)
#: §7.4 트리거 표 합계 행 — ``| **합계** | **148** | **160** | …``. 둘째 수가 head 열이다.
_TRIGGER_TOTAL = re.compile(r"^\| \*\*합계\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \|", re.MULTILINE)


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """``### 2.6 `` 헤딩부터 다음 같은 단계 헤딩 전까지."""
    start = text.index(heading)
    nxt = re.compile(r"^#{1,3} ", re.MULTILINE).search(text, start + len(heading))
    return text[start : nxt.start() if nxt else len(text)]


#: 스텁(`tests/migration_stub.py`)에 적재할 때 붙이는 이름 — `test_migration_guard`·
#: `test_zz_roundtrip`의 적재와 겹치지 않게 한다.
_PREFIX = "_dbschema_head_sync"


def test_revision_graph_ends_at_alembic_head(monkeypatch: pytest.MonkeyPatch):
    """§8.1.0 그래프의 끝 = `alembic/versions`의 head. `051`에서 멈춰 있었다."""
    install(monkeypatch)
    chain = load_chain(_PREFIX)
    match = _GRAPH.search(_doc())
    assert match, "§8.1.0 리비전 그래프(`base → 1c444a5c4819 → …`)를 찾지 못했다"
    assert match.group("head") == chain[-1].revision, (
        f"§8.1.0 그래프는 {match.group('head')}에서 끝나는데 head는 {chain[-1].revision}이다"
    )


def test_trigger_total_matches_migrations(monkeypatch: pytest.MonkeyPatch):
    """§7.4 트리거 표 head 열 합계 = CREATE TRIGGER 누적 − DROP TRIGGER. 148은 `051` 시점이었다.

    스텁의 `db_trigger`가 지금까지 만든−지운 집합으로 답하므로(`#1373`), `db/trigger_ddl.py`를
    지나는 DROP도 실제 DB에서처럼 집계된다 — 빈 카탈로그로 답하면 지우는 쪽이 전부 건너뛴다.
    """
    live = head_triggers(monkeypatch, _PREFIX)
    match = _TRIGGER_TOTAL.search(_doc())
    assert match, "§7.4 「지금 DB에 있는 트리거」 합계 행(`| **합계** | **N** | **N** |`)이 없다"
    assert int(match.group(2)) == len(live), (
        f"§7.4 head 열 합계 {match.group(2)} ≠ 마이그레이션 실측 {len(live)}"
    )


def test_no_migration_changes_a_trigger_body_through_create_trigger(
    monkeypatch: pytest.MonkeyPatch,
):
    """이미 있는 이름에 **다른 본문**으로 ``create_trigger``를 부르는 리비전이 없다 (#1861).

    헬퍼는 「있으면 만들지 않는다」라 그 호출을 **조용히 건너뛴다** — 운영 DB에는 옛 정의가
    남고 새 DB에는 새 정의가 들어가 둘이 갈린다. 이름·개수 대조로는 보이지 않는다(둘 다
    같은 이름 하나다). 본문을 바꾸는 리비전은 ``replace_trigger``를 써야 한다.
    """
    op = run_chain(monkeypatch, _PREFIX + "_bodies")
    assert op.bodies, "트리거 본문을 하나도 모으지 못했다 — 이 검사가 헛돌고 있다"
    assert op.skipped_changes == [], (
        "create_trigger가 다른 본문을 건너뛴다(본문을 바꾸려면 replace_trigger): "
        + "; ".join(name for name, _before, _after in op.skipped_changes)
    )


def test_a_body_change_slipped_into_the_chain_is_caught(monkeypatch: pytest.MonkeyPatch):
    """대조군 — 조건만 바꾼 가짜 리비전을 사슬 끝에 끼우면 위 검사가 잡는다 (#1861 완료 기준).

    같은 변경을 ``replace_trigger``로 하면 잡히지 않는다 — 지우고 만들므로 갈리지 않는다.
    """
    op = run_chain(monkeypatch, _PREFIX + "_control")
    from cii_platform.db import trigger_ddl

    name = "trg_chk_call_sign_ins"
    assert name in op.bodies, f"{name}이 head에 없다 — 대조군 대상을 바꿀 것"
    changed = "BEFORE INSERT ON vessel IF NOT (new.call_sign IS NULL) EXECUTE REJECT"

    trigger_ddl.create_trigger(op, name, changed)  # 가짜 리비전 — 헬퍼로 조건만 바꾼다
    assert [entry[0] for entry in op.skipped_changes] == [name]

    op.skipped_changes.clear()
    trigger_ddl.replace_trigger(op, name, changed)  # 올바른 방법
    assert op.skipped_changes == []
    assert op.bodies[name] == changed


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
