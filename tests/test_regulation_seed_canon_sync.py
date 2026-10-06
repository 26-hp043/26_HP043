"""규제값 시드 ↔ 정본 표 (`PRD §3.4.1`·`§3.4.3`·`§3.4.4` · `DB_SCHEMA §3.1`·`§3.3`·`§3.4` · #2144).

## 왜 필요한가

규제값은 세 곳에 적혀 있다 — 정본 표, ``db/seed.py`` 상수, 마이그레이션 032.
``tests/test_seed_migration.py``는 **뒤의 둘**을 맞추고, ``tests/test_seed_data.py``는
감축률 8개 중 3개와 LNG 두 값만 값으로 단언한다. 그래서 시드와 마이그레이션을 **같이**
고치면(값을 「정정」하는 PR이 정확히 그렇게 한다) 기준선 20행·등급 경계 14행·감축률 5행은
어느 검사에도 걸리지 않았다.

연료 CF는 이미 ``test_fuel_type_seed.py``·``test_fuel_table_sync_db.py``가 정본 표를 읽어
대조하므로 여기서 다루지 않는다.

## 무엇을 단언하는가

정본 표를 **기계로 읽어** 시드 상수와 행 단위로 맞춘다. 값을 여기 다시 적지 않는다 —
적으면 네 번째 사본이 생긴다.

## 이 검사가 말하지 않는 것

**어느 쪽이 옳은지는 말하지 않는다.** 표와 시드가 갈렸을 때 고칠 쪽은 IMO 원문
(``AGENTS §2.2``)을 사람이 대조해 정한다 — 한쪽을 다른 쪽에 맞춰 이 검사를 통과시키지
않는다. ``14479E10``과 ``14779E10``이 바로 그렇게 「정정」됐다가 되돌려진 값이다
(``AGENTS §2.3``).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cii_platform.db.seed import (
    SEED_RATING_BOUNDARIES,
    SEED_REFERENCE_LINES,
    SEED_Z_FACTORS,
    SOURCE_Z_FACTOR,
)

_ROOT = Path(__file__).resolve().parents[1]
PRD = _ROOT / "PRD.md"
DB_SCHEMA = _ROOT / "DB_SCHEMA.md"


def _section(path: Path, heading: str) -> str:
    """``heading`` 줄부터 다음 제목 줄 앞까지."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(heading)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("#"))
    return "\n".join(lines[start:end])


def _table_rows(section: str) -> list[list[str]]:
    """절 안의 **첫 표**의 데이터 행 — 머리글과 구분선은 뺀다. 강조(`**`)는 벗긴다."""
    rows: list[list[str]] = []
    in_table = False
    for line in section.splitlines():
        if line.startswith("|"):
            in_table = True
            rows.append([cell.strip().replace("**", "") for cell in line.strip("|").split("|")])
        elif in_table:
            break
    return rows[2:]


def _condition(text: str) -> str:
    """`PRD`의 표기(`DWT ≥ 279,000`)를 조건식(`DWT >= 279000`)으로 — 값은 건드리지 않는다."""
    return text.replace("≥", ">=").replace("≤", "<=").replace(",", "")


# ─── 시드 쪽 ─────────────────────────────────────────────────────────────────

SEED_Z = {row.year: row.z_factor_percent for row in SEED_Z_FACTORS}
SEED_REFERENCE = {
    (row.ship_type, row.condition_expr): (row.capacity_rule, row.a_raw, row.c)
    for row in SEED_REFERENCE_LINES
}
SEED_BOUNDARY = {
    (row.ship_type, row.condition_expr): (row.d1, row.d2, row.d3, row.d4)
    for row in SEED_RATING_BOUNDARIES
}


# ─── 감축률 Z ────────────────────────────────────────────────────────────────


def test_z_factors_match_prd():
    """`PRD §3.4.1` 8행 — 종전에는 2026·2027·2030 셋만 값으로 단언했다."""
    rows = _table_rows(_section(PRD, "#### 3.4.1 CII reduction factor, Z%"))
    documented = {}
    for year, percent in rows:
        assert percent.endswith("%"), percent
        documented[int(year)] = Decimal(percent.removesuffix("%"))

    assert len(documented) == len(rows) >= 8
    assert documented == SEED_Z


def test_z_factors_match_db_schema():
    """`DB_SCHEMA §3.1` — 값과 출처 결의안."""
    rows = _table_rows(_section(DB_SCHEMA, "### 3.1 규정 연도 Z-factor"))

    assert {int(year): Decimal(percent) for year, percent, _ in rows} == SEED_Z
    assert {source for _, _, source in rows} == {SOURCE_Z_FACTOR}


# ─── 기준선 a · c ────────────────────────────────────────────────────────────


def test_reference_lines_match_prd():
    """`PRD §3.4.3` 20행 — 선종 · 조건 · capacity rule · `a` 원문 표기 · `c`.

    `a`는 **원문 표기 문자열**(`a_raw`)로 맞춘다. 계산이 쓰는 `a_decimal`이 그 표기를 편
    값과 같은지는 `test_seed_data.py::test_reference_line_a_raw_matches_a_decimal`이 본다.
    """
    rows = _table_rows(_section(PRD, "#### 3.4.3 Ship type reference line 파라미터"))
    documented = {
        (ship_type, _condition(condition)): (capacity_rule, a_raw, Decimal(c))
        for ship_type, condition, capacity_rule, a_raw, c, _priority in rows
    }

    assert len(documented) == len(rows) >= 20  # 키가 겹쳐 행이 사라지지 않았다
    assert documented == SEED_REFERENCE


def test_reference_lines_match_db_schema():
    """`DB_SCHEMA §3.3` 20행."""
    rows = _table_rows(_section(DB_SCHEMA, "### 3.3 선종별 Reference Line"))
    documented = {
        (ship_type, condition): (capacity_rule, a_raw, Decimal(c))
        for ship_type, condition, capacity_rule, a_raw, c in rows
    }

    assert len(documented) == len(rows) >= 20
    assert documented == SEED_REFERENCE


# ─── 등급 경계 d1~d4 ─────────────────────────────────────────────────────────


def test_rating_boundaries_match_prd():
    """`PRD §3.4.4` 14행 — 선종 · 조건 · capacity basis · d1~d4."""
    rows = _table_rows(_section(PRD, "#### 3.4.4 d-vector rating boundary 파라미터"))
    documented = {
        (ship_type, _condition(condition)): tuple(Decimal(d) for d in ds)
        for ship_type, condition, _basis, *ds in rows
    }
    documented_basis = {
        (ship_type, _condition(condition)): basis for ship_type, condition, basis, *_ in rows
    }

    assert len(documented) == len(rows) >= 14
    assert documented == SEED_BOUNDARY
    assert documented_basis == {
        (row.ship_type, row.condition_expr): row.capacity_basis for row in SEED_RATING_BOUNDARIES
    }


def test_rating_boundaries_match_db_schema_excerpt():
    """`DB_SCHEMA §3.4` — 표가 **앞 6행만 싣고 `...`으로 줄인다**(전체는 `PRD §3.4.4`).

    실린 행은 시드와 같아야 한다. 줄임 행은 건너뛴다.
    """
    rows = _table_rows(_section(DB_SCHEMA, "### 3.4 등급 경계 d-vector"))
    documented = {
        (ship_type, condition): tuple(Decimal(d) for d in ds)
        for ship_type, condition, *ds in rows
        if ship_type != "..."
    }

    assert len(documented) >= 6
    assert documented == {key: SEED_BOUNDARY.get(key) for key in documented}
