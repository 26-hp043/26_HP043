"""파라미터 CHECK 제약·FK 자식 인덱스 검증 (#96 · #97, 마이그레이션 023).

- #96 (Oracle F5): ``fuel_type.cf > 0``, ``regulation_year.z_factor_percent >= 0``.
  Z-factor의 ``0``은 2023년 실측값이므로 유효 — ``> 0``이 아니라 ``>= 0``이다.
- #97 (Oracle F3+F4): ``voyage_scenario``·``simulation_snapshot``의 FK 자식 인덱스
  존재 — ORM zero drift(test_orm_schema_sync)와 별개로 DB 카탈로그로 직접 확인한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def test_fuel_type_negative_cf_rejected(conn):
    """cf <= 0 INSERT는 제약 위반 (#96)."""
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO fuel_type (code, display_name, cf, source_ref, version) "
                "VALUES ('BAD', 'Bad Fuel', -1.0, 'TEST', '1.0')"
            )
        )
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO fuel_type (code, display_name, cf, source_ref, version) "
                "VALUES ('ZERO', 'Zero Fuel', 0, 'TEST', '1.0')"
            )
        )


async def test_fuel_type_positive_cf_passes(conn):
    await conn.execute(
        text(
            "INSERT INTO fuel_type (code, display_name, cf, source_ref, version) "
            "VALUES ('TESTOK', 'Test Fuel', 3.114, 'TEST', '1.0')"
        )
    )
    row = await conn.execute(text("SELECT cf FROM fuel_type WHERE code = 'TESTOK'"))
    assert float(row.scalar_one()) == 3.114


async def test_regulation_year_negative_z_factor_rejected(conn):
    """z_factor_percent < 0 INSERT는 제약 위반 (#96)."""
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "INSERT INTO regulation_year "
                "(year, z_factor_percent, effective_from, source_ref, version) "
                "VALUES (1999, -2.0, '1999-01-01', 'TEST', '1.0')"
            )
        )


async def test_regulation_year_zero_z_factor_passes(conn):
    """z_factor_percent = 0은 유효 — 2023년 실측값 (MEPC.400(83))."""
    await conn.execute(
        text(
            "INSERT INTO regulation_year "
            "(year, z_factor_percent, effective_from, source_ref, version) "
            "VALUES (2023, 0, '2023-01-01', 'TEST', '1.0')"
        )
    )
    row = await conn.execute(text("SELECT z_factor_percent FROM regulation_year WHERE year = 2023"))
    assert float(row.scalar_one()) == 0.0


async def test_fk_child_indexes_exist(conn):
    """#97 인덱스 3종이 실제 DB에 존재한다."""
    expected = {
        ("voyage_scenario", "idx_scenario_vessel"),
        ("voyage_scenario", "idx_scenario_voyage"),
        ("simulation_snapshot", "idx_snapshot_vessel"),
    }
    rows = await conn.execute(
        text(
            "SELECT tablename, indexname FROM pg_indexes "
            "WHERE indexname IN ('idx_scenario_vessel', 'idx_scenario_voyage', "
            "'idx_snapshot_vessel')"
        )
    )
    found = {(r[0], r[1]) for r in rows}
    assert expected <= found, f"누락: {expected - found}"
