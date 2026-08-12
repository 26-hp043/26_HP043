"""이슈 #33 규제 파라미터 seed 검증.

두 층으로 나눈다:

1. **값 검증 (DB 불필요)** — ``cii_platform.db.seed``의 상수만 검사한다. 핵심은
   ``parse_imo_scientific(a_raw) == a_decimal`` 전수 대조(TEST_PLAN UT-IMO-003)이며,
   ``a_decimal``이 ``a_raw``에서 계산된 값이 아니라 독립 전사이므로 실제로 오전사를 잡는다.
2. **적재 검증 (DB 필요)** — ``seed_all``을 실행해 이슈 #33 완료 기준(값 조회, 재실행
   idempotency)을 확인한다.
3. **CLI 진입점 (DB 불필요)** — ``scripts/seed.py``의 URL 정규화를 검증한다.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from cii_platform.calc.imo_parser import parse_imo_scientific
from cii_platform.db.seed import (
    SEED_RATING_BOUNDARIES,
    SEED_REFERENCE_LINES,
    SEED_Z_FACTORS,
    seed_all,
    validate_reference_lines,
)

# --- 1. 값 검증 (DB 불필요) -----------------------------------------------------


def test_reference_line_a_raw_matches_a_decimal():
    """UT-IMO-003: 모든 행에서 parse(a_raw) == a_decimal (TECH_SPEC §9.3)."""
    for row in SEED_REFERENCE_LINES:
        assert parse_imo_scientific(row.a_raw) == row.a_decimal, (
            f"{row.ship_type} ({row.condition_expr}): {row.a_raw}"
        )


def test_validate_reference_lines_passes():
    """seed 실행 전 가드가 통과한다 (예외를 던지지 않는다)."""
    validate_reference_lines()


def test_seed_row_counts():
    """정본 문서의 행 수와 일치한다 — 행 누락·중복 전사 방지."""
    assert len(SEED_Z_FACTORS) == 8  # PRD §3.4.1 = DB_SCHEMA §3.1
    assert len(SEED_REFERENCE_LINES) == 20  # PRD §3.4.3 = DB_SCHEMA §3.3
    assert len(SEED_RATING_BOUNDARIES) == 14  # PRD §3.4.4


def test_seed_keys_are_unique():
    """UNIQUE 제약(year / ship_type+condition_expr)을 상수 단계에서 미리 확인한다."""
    years = [row.year for row in SEED_Z_FACTORS]
    assert len(set(years)) == len(years)

    refline_keys = [(row.ship_type, row.condition_expr) for row in SEED_REFERENCE_LINES]
    assert len(set(refline_keys)) == len(refline_keys)

    boundary_keys = [(row.ship_type, row.condition_expr) for row in SEED_RATING_BOUNDARIES]
    assert len(set(boundary_keys)) == len(boundary_keys)


def test_lng_carrier_a_values_are_distinct():
    """AGENTS.md §2.3: 14479E10과 14779E10은 서로 다른 구간의 서로 다른 값이다."""
    lng = {
        row.condition_expr: row for row in SEED_REFERENCE_LINES if row.ship_type == "LNG_CARRIER"
    }
    assert lng["65000 <= DWT < 100000"].a_raw == "14479E10"
    assert lng["65000 <= DWT < 100000"].a_decimal == Decimal("144790000000000")
    assert lng["DWT < 65000"].a_raw == "14779E10"
    assert lng["DWT < 65000"].a_decimal == Decimal("147790000000000")
    assert lng["DWT < 65000"].capacity_rule == "fixed 65000"


def test_reference_line_satisfies_db_constraints():
    """010의 CHECK 제약(capacity_rule 패턴, a_decimal > 0, c >= 0)을 상수가 만족한다."""
    for row in SEED_REFERENCE_LINES:
        assert row.capacity_rule in ("DWT", "GT") or row.capacity_rule.startswith("fixed ")
        if row.capacity_rule.startswith("fixed "):
            assert row.capacity_rule.removeprefix("fixed ").isdigit()
        assert row.a_decimal > 0
        assert row.c >= 0


def test_rating_boundary_d_vector_is_ordered():
    """011의 CHECK 제약 d1 < d2 < d3 < d4 (DB_SCHEMA §2.11 [M-3])."""
    for row in SEED_RATING_BOUNDARIES:
        assert row.d1 < row.d2 < row.d3 < row.d4, row.ship_type
        assert row.capacity_basis in ("DWT", "GT")


def test_z_factor_values_and_effective_from():
    """PRD §3.4.1 값과, 적용 시작일이 해당 연도 1월 1일인지 확인한다."""
    by_year = {row.year: row for row in SEED_Z_FACTORS}
    assert sorted(by_year) == list(range(2023, 2031))
    assert by_year[2026].z_factor_percent == Decimal("11.0000")
    assert by_year[2027].z_factor_percent == Decimal("13.6250")
    assert by_year[2030].z_factor_percent == Decimal("21.5000")
    for year, row in by_year.items():
        assert row.effective_from.year == year
        assert (row.effective_from.month, row.effective_from.day) == (1, 1)


def test_ro_ro_passenger_hsc_boundary_is_absent():
    """PRD §3.4.4에 없는 RO_RO_PASSENGER_HSC 행을 임의로 만들지 않았음을 고정한다.

    reference line에는 있으나 d-vector에는 없다. #126에서 MEPC.354(78) 원문을 대조해
    확인한 결과 **의도된 부재**이며, 이 상태가 원문대로다. 따라서 행을 추가하지 않고
    이 테스트를 유지한다.

    HSC의 등급 경계는 RO_RO_PASSENGER 행을 적용한다(근거는 PRD §3.4.4 각주 참조).
    선종 매핑은 등급 판정(#39)에서 처리하며, 규제값 표에 원문에 없는 행을 넣지 않는다.
    """
    assert any(row.ship_type == "RO_RO_PASSENGER_HSC" for row in SEED_REFERENCE_LINES)
    assert not any(row.ship_type == "RO_RO_PASSENGER_HSC" for row in SEED_RATING_BOUNDARIES)


# --- 2. 적재 검증 (DB 필요) -----------------------------------------------------


@pytest.fixture
async def seeded(conn):
    """seed를 1회 적재한 커넥션. conn fixture가 테스트 종료 시 롤백한다."""
    await seed_all(conn)
    return conn


async def test_seed_all_loads_expected_row_counts(seeded):
    """완료 기준: 모든 규제값이 적재된다."""
    for table, expected in (
        ("regulation_year", 8),
        ("cii_reference_line", 20),
        ("cii_rating_boundary", 14),
    ):
        count = await seeded.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        assert count == expected, table


async def test_regulation_year_2026(seeded):
    """완료 기준: year = 2026 → z_factor_percent = 11.000."""
    row = (
        await seeded.execute(
            text(
                "SELECT z_factor_percent, effective_from, source_ref, version, is_active "
                "FROM regulation_year WHERE year = 2026"
            )
        )
    ).one()
    assert row.z_factor_percent == Decimal("11.0000")
    assert row.effective_from.isoformat() == "2026-01-01"
    assert row.source_ref == "MEPC.400(83)"
    assert row.version == "1.0"
    assert row.is_active is True


async def test_bulk_carrier_c_is_positive(seeded):
    """완료 기준: BULK_CARRIER의 c = 0.622 (양수로 저장, 계산 시 ^(-c) 적용)."""
    rows = (
        await seeded.execute(
            text(
                "SELECT condition_expr, capacity_rule, c, source_ref FROM cii_reference_line "
                "WHERE ship_type = 'BULK_CARRIER' ORDER BY condition_expr"
            )
        )
    ).all()
    assert len(rows) == 2
    for row in rows:
        assert row.c == Decimal("0.622000")
        assert row.source_ref == "MEPC.353(78)"
    assert {r.capacity_rule for r in rows} == {"DWT", "fixed 279000"}


async def test_stored_a_raw_matches_stored_a_decimal(seeded):
    """완료 기준: DB에 적재된 모든 행에서 parse_imo_scientific(a_raw) == a_decimal."""
    rows = (
        await seeded.execute(
            text("SELECT ship_type, condition_expr, a_raw, a_decimal FROM cii_reference_line")
        )
    ).all()
    assert len(rows) == 20
    for row in rows:
        assert parse_imo_scientific(row.a_raw) == row.a_decimal, (
            f"{row.ship_type} ({row.condition_expr})"
        )


async def test_lng_a_values_persisted_distinctly(seeded):
    """AGENTS.md §2.3 사례가 DB에도 서로 다른 값으로 남는지 확인한다."""
    rows = dict(
        (
            await seeded.execute(
                text(
                    "SELECT condition_expr, a_decimal FROM cii_reference_line "
                    "WHERE ship_type = 'LNG_CARRIER'"
                )
            )
        ).all()
    )
    assert rows["65000 <= DWT < 100000"] == Decimal("144790000000000")
    assert rows["DWT < 65000"] == Decimal("147790000000000")


async def test_seed_is_idempotent(seeded):
    """완료 기준: 재실행해도 동일한 데이터 (upsert)."""
    before = (
        await seeded.execute(
            text(
                "SELECT ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c "
                "FROM cii_reference_line ORDER BY ship_type, condition_expr"
            )
        )
    ).all()

    await seed_all(seeded)

    after = (
        await seeded.execute(
            text(
                "SELECT ship_type, condition_expr, capacity_rule, a_raw, a_decimal, c "
                "FROM cii_reference_line ORDER BY ship_type, condition_expr"
            )
        )
    ).all()
    assert before == after

    for table, expected in (
        ("regulation_year", 8),
        ("cii_reference_line", 20),
        ("cii_rating_boundary", 14),
    ):
        count = await seeded.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        assert count == expected, table


async def test_seed_updates_changed_values(seeded):
    """upsert가 INSERT만이 아니라 UPDATE로도 동작하는지 확인한다.

    값을 일부러 훼손한 뒤 재적재하면 정본 값으로 복구되어야 한다. 이게 없으면
    "재실행해도 동일"이 단순히 중복 INSERT 회피만 의미하게 된다.
    """
    await seeded.execute(
        text(
            "UPDATE cii_reference_line SET a_decimal = 1, c = 9.999999 "
            "WHERE ship_type = 'LNG_CARRIER' AND condition_expr = 'DWT < 65000'"
        )
    )

    await seed_all(seeded)

    row = (
        await seeded.execute(
            text(
                "SELECT a_decimal, c FROM cii_reference_line "
                "WHERE ship_type = 'LNG_CARRIER' AND condition_expr = 'DWT < 65000'"
            )
        )
    ).one()
    assert row.a_decimal == Decimal("147790000000000")
    assert row.c == Decimal("2.673000")


# --- 3. CLI 진입점 (DB 불필요) --------------------------------------------------


def _load_seed_script():
    """``scripts/seed.py``를 모듈로 로드한다.

    ``scripts/``는 Python 패키지가 아니라 일반 import가 불가능하므로 파일 경로로
    직접 로드한다. 스크립트는 ``if __name__ == "__main__"`` 가드 뒤에서만 실행되므로
    import 시 DB에 접속하지 않는다.
    """
    path = Path(__file__).resolve().parent.parent / "scripts" / "seed.py"
    spec = importlib.util.spec_from_file_location("seed_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # 이미 asyncpg — 그대로 둔다.
        (
            "postgresql+asyncpg://cii:cii@localhost:5432/cii",
            "postgresql+asyncpg://cii:cii@localhost:5432/cii",
        ),
        # 드라이버 생략(CI가 주입하는 형식) — asyncpg를 붙인다.
        (
            "postgresql://cii:cii@localhost:5432/cii_test",
            "postgresql+asyncpg://cii:cii@localhost:5432/cii_test",
        ),
        # 다른 postgresql 드라이버 — asyncpg로 바꾼다(설치된 드라이버가 asyncpg뿐).
        ("postgresql+psycopg://cii@db/cii", "postgresql+asyncpg://cii@db/cii"),
        # postgresql이 아니면 손대지 않는다.
        ("sqlite+aiosqlite:///./x.db", "sqlite+aiosqlite:///./x.db"),
    ],
)
def test_seed_script_normalizes_database_url(given, expected):
    """프로덕션 seed 진입점의 URL 정규화 분기를 고정한다.

    이 스크립트는 배포 시 ``alembic upgrade head`` 이후 규제 파라미터를 넣는 유일한
    경로다. 정규화가 조용히 틀리면 첫 배포 실행에서야 드러나므로 여기서 잠근다.
    구현은 ``db.url.normalize_to_asyncpg``(#234) — alembic · conftest · 앱 세션과
    같은 함수를 공유한다.
    """
    from cii_platform.db.url import normalize_to_asyncpg

    assert normalize_to_asyncpg(given) == expected
