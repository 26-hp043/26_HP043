"""이슈 #127 · 마이그레이션 032가 넣은 규제 파라미터 42행 검증.

**이 파일이 잡는 것은 두 값이 갈라지는 순간이다.**

032는 ``src/`` 상수를 import하지 않는다 — 마이그레이션은 과거 한 시점의 스냅샷이라,
가변 상수를 참조하면 규제 개정 시 과거 동작이 소급 변경된다(017이 세우고 031이 따른
원칙). 그래서 042행이 두 곳에 존재한다.

===========================  ===================================================
주체                          담는 것
===========================  ===================================================
마이그레이션 032               그날 넣은 값 · 불변
``seed.py`` 상수               지금 옳다고 보는 값 · 가변
===========================  ===================================================

**둘이 갈라지는 것 자체는 정상이다** — 규제가 개정되면 상수만 바뀐다. 다만 그 순간을
**모르고 지나가면 안 된다.** 이 파일은 갈라짐을 드러내는 알림이며, 값 자체가 정본과
맞는지는 tests/test_seed_data.py가 ``PRD`` §3.4와 대조해 검증한다.

DB 적재 결과 검증은 아래 ``test_migration_loaded_*`` 3건이 담당한다. downgrade로
42행이 지워지는지는 전역 스키마를 변형하므로 test_zz_roundtrip.py가 검증한다
(#82의 격리 정책).
"""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from cii_platform.db.seed import (
    SEED_RATING_BOUNDARIES,
    SEED_REFERENCE_LINES,
    SEED_Z_FACTORS,
)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "032_seed_regulation_parameters.py"
)


def _load_migration():
    """032를 모듈로 읽는다.

    ``alembic/versions``는 패키지가 아니라 일반 import가 안 된다. 파일 경로로 직접
    적재한다 — 032가 ``src/``를 import하지 않는 것과 이 테스트가 032를 읽는 것은
    방향이 반대라 원칙에 어긋나지 않는다.
    """
    spec = importlib.util.spec_from_file_location("migration_032", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_zfactors_match_constants():
    """032의 Z-factor 8행이 ``seed.py`` 상수와 일치한다 (PRD §3.4.1)."""
    m = _load_migration()
    assert len(m.SEED_Z_FACTORS) == len(SEED_Z_FACTORS) == 8

    actual = {(r["year"], r["z_factor_percent"], r["effective_from"]) for r in m.SEED_Z_FACTORS}
    expected = {(r.year, r.z_factor_percent, r.effective_from) for r in SEED_Z_FACTORS}
    assert actual == expected


def test_migration_reference_lines_match_constants():
    """032의 reference line 20행이 ``seed.py`` 상수와 일치한다 (PRD §3.4.3).

    ``a_raw``와 ``a_decimal``을 **둘 다** 대조한다. ``seed.py`` 모듈 docstring이
    밝힌 대로 둘은 독립 전사본이며, 한쪽만 보면 ``AGENTS`` §2.3의 전사 오류
    (``14479E10``/``14779E10``)를 놓친다.
    """
    m = _load_migration()
    assert len(m.SEED_REFERENCE_LINES) == len(SEED_REFERENCE_LINES) == 20

    actual = {
        (
            r["ship_type"],
            r["condition_expr"],
            r["capacity_rule"],
            r["a_raw"],
            r["a_decimal"],
            r["c"],
        )
        for r in m.SEED_REFERENCE_LINES
    }
    expected = {
        (r.ship_type, r.condition_expr, r.capacity_rule, r.a_raw, r.a_decimal, r.c)
        for r in SEED_REFERENCE_LINES
    }
    assert actual == expected


def test_migration_rating_boundaries_match_constants():
    """032의 d-vector 14행이 ``seed.py`` 상수와 일치한다 (PRD §3.4.4)."""
    m = _load_migration()
    assert len(m.SEED_RATING_BOUNDARIES) == len(SEED_RATING_BOUNDARIES) == 14

    actual = {
        (
            r["ship_type"],
            r["condition_expr"],
            r["capacity_basis"],
            r["d1"],
            r["d2"],
            r["d3"],
            r["d4"],
        )
        for r in m.SEED_RATING_BOUNDARIES
    }
    expected = {
        (r.ship_type, r.condition_expr, r.capacity_basis, r.d1, r.d2, r.d3, r.d4)
        for r in SEED_RATING_BOUNDARIES
    }
    assert actual == expected


def test_migration_does_not_import_src():
    """032가 ``cii_platform``을 import하지 않는다 — 017이 세운 원칙을 코드로 고정한다.

    import하면 규제 개정으로 상수가 바뀔 때 032의 동작이 **소급 변경**되어, 새 환경의
    ``upgrade head``가 "032 당시의 42행"이 아니라 "오늘의 42행"을 넣는다.
    """
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    code_lines = [
        line
        for line in source.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    assert not any("cii_platform" in line for line in code_lines), (
        f"032가 src/를 import한다: {[ln for ln in code_lines if 'cii_platform' in ln]}"
    )


async def test_migration_loaded_regulation_year(conn):
    """``alembic upgrade head`` 만으로 Z-factor 8행이 DB에 있다 (#127 완료 기준)."""
    rows = (
        await conn.execute(
            text(
                "SELECT year, z_factor_percent, source_ref, version, is_active FROM regulation_year"
            )
        )
    ).all()
    assert len(rows) == 8
    by_year = {r.year: r for r in rows}
    for expected in SEED_Z_FACTORS:
        row = by_year[expected.year]
        assert row.z_factor_percent == expected.z_factor_percent
        assert row.source_ref == "MEPC.400(83)"
        assert row.version == "1.0"
        assert row.is_active is True


async def test_migration_loaded_reference_lines(conn):
    """reference line 20행이 DB에 있다 (#127 완료 기준)."""
    rows = (
        await conn.execute(
            text(
                "SELECT ship_type, condition_expr, a_raw, a_decimal, c, source_ref"
                " FROM cii_reference_line"
            )
        )
    ).all()
    assert len(rows) == 20
    by_key = {(r.ship_type, r.condition_expr): r for r in rows}
    for expected in SEED_REFERENCE_LINES:
        row = by_key[(expected.ship_type, expected.condition_expr)]
        assert row.a_raw == expected.a_raw
        assert row.a_decimal == expected.a_decimal
        assert row.c == expected.c
        assert row.source_ref == "MEPC.353(78)"


async def test_migration_loaded_rating_boundaries(conn):
    """d-vector 14행이 DB에 있다 (#127 완료 기준)."""
    rows = (
        await conn.execute(
            text(
                "SELECT ship_type, condition_expr, d1, d2, d3, d4, source_ref"
                " FROM cii_rating_boundary"
            )
        )
    ).all()
    assert len(rows) == 14
    by_key = {(r.ship_type, r.condition_expr): r for r in rows}
    for expected in SEED_RATING_BOUNDARIES:
        row = by_key[(expected.ship_type, expected.condition_expr)]
        assert (row.d1, row.d2, row.d3, row.d4) == (
            expected.d1,
            expected.d2,
            expected.d3,
            expected.d4,
        )
        assert row.source_ref == "MEPC.354(78)"


async def test_seed_all_is_idempotent_over_migration(conn):
    """032 적재 위에 ``seed_all()``을 돌려도 행이 늘지 않는다.

    둘의 역할 분담(032=불변 스냅샷 · ``seed_all``=가변 재적재)이 성립하려면,
    이미 적재된 DB에 재적재를 돌렸을 때 **중복이 아니라 갱신**이 되어야 한다.
    upsert의 충돌 키가 032의 UNIQUE 키와 같아야 성립한다.
    """
    from cii_platform.db.seed import seed_all

    await seed_all(conn)

    for table, expected_count in (
        ("regulation_year", 8),
        ("cii_reference_line", 20),
        ("cii_rating_boundary", 14),
    ):
        count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        assert count == expected_count, f"{table}: seed_all 후 {count}행 (기대 {expected_count})"
