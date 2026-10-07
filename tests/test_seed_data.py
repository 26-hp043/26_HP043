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
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from cii_platform.calc.hash import compute_parameter_hash
from cii_platform.calc.imo_parser import parse_imo_scientific
from cii_platform.db.models import CiiReferenceLine, RegulationYear
from cii_platform.db.seed import (
    _CF_ROWS,
    SEED_RATING_BOUNDARIES,
    SEED_REFERENCE_LINES,
    SEED_Z_FACTORS,
    seed_all,
    validate_reference_lines,
)
from cii_platform.services.parameter_import import partition_problem

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
                # `year`는 CUBRID 예약어라 인용해야 한다 (#1058).
                "SELECT z_factor_percent, effective_from, source_ref, version, is_active "
                'FROM regulation_year WHERE "year" = 2026'
            )
        )
    ).one()
    assert row.z_factor_percent == Decimal("11.0000")
    assert row.effective_from.isoformat() == "2026-01-01"
    assert row.source_ref == "MEPC.400(83)"
    assert row.version == "1.0"
    # CUBRID는 BOOLEAN을 SMALLINT로 저장한다 (#1058) — PostgreSQL의 `True`가 `1`로 온다.
    assert row.is_active in (True, 1), row.is_active


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


async def test_seed_restores_fuel_type_source_ref(seeded):
    """재적재가 CF 출처를 MEPC.364(79)로 복구한다 (#1240).

    부트스트랩 마이그레이션 검사가 아니라 규제 개정 재적재 경로를 직접 검증한다.
    G1에는 CF 표가 없으므로 값이 인쇄된 현행 EEDI 지침을 출처로 유지해야 한다
    (DB_SCHEMA §3.2 각주 [#87 정정]).
    """
    await seeded.execute(text("UPDATE fuel_type SET source_ref = 'IMO 2018 Guidelines'"))

    await seed_all(seeded)

    refs = (await seeded.execute(text("SELECT DISTINCT source_ref FROM fuel_type"))).scalars().all()
    assert refs == ["MEPC.364(79)"]


# --- 2-b. 시드는 시드 판본 행만 갱신한다 (#2086) ---------------------------------
#
# 배포마다 시드가 돈다(deploy.yml). 화면의 개정 적재(`import.<UTC>` 판본)가 그 한 번에
# 시드 값으로 되돌아가거나, 경계값 개정 뒤 옛 밴드 행이 다시 들어오면 안 된다.

_REVISION = "import.20261007T000000Z"


async def _revise_reference_lines(conn, ship_type: str, rows: list[tuple[str, str, str]]):
    """적재(`_apply_versioned`)와 같은 순서 — 그 선종의 활성 행을 전부 끄고 새 행을 넣는다."""
    await conn.execute(
        text("UPDATE cii_reference_line SET is_active = 0 WHERE ship_type = :st AND is_active = 1"),
        {"st": ship_type},
    )
    for condition_expr, capacity_rule, a_raw in rows:
        await conn.execute(
            sa.insert(CiiReferenceLine.__table__).values(
                ship_type=ship_type,
                condition_expr=condition_expr,
                capacity_rule=capacity_rule,
                a_raw=a_raw,
                a_decimal=parse_imo_scientific(a_raw),
                c=Decimal("0.622000"),
                source_ref="TEST revision",
                version=_REVISION,
                is_active=True,
            )
        )


async def _active_reference_lines(conn, ship_type: str):
    return (
        await conn.execute(
            text(
                "SELECT condition_expr, a_raw, version FROM cii_reference_line "
                "WHERE ship_type = :st AND is_active = 1 ORDER BY condition_expr"
            ),
            {"st": ship_type},
        )
    ).all()


async def test_seed_keeps_a_revised_value_and_its_version(seeded):
    """개정 적재 → 시드 → 값·판본 유지. 시드 판본 이행 행도 다시 켜지지 않는다."""
    await _revise_reference_lines(
        seeded,
        "BULK_CARRIER",
        [("DWT >= 279000", "fixed 279000", "4800"), ("DWT < 279000", "DWT", "4800")],
    )

    await seed_all(seeded)

    active = await _active_reference_lines(seeded, "BULK_CARRIER")
    assert [(row.condition_expr, row.a_raw, row.version) for row in active] == [
        ("DWT < 279000", "4800", _REVISION),
        ("DWT >= 279000", "4800", _REVISION),
    ]
    # 다른 선종은 종전대로 시드가 덮는다 — 범위를 좁혔을 뿐 시드 정정 경로는 남는다.
    assert {row.version for row in await _active_reference_lines(seeded, "GAS_CARRIER")} == {"1.0"}


async def test_seed_does_not_reinsert_old_bands_after_a_boundary_revision(seeded):
    """경계값 개정(옛 키 비활성) → 시드 → 옛 밴드 행이 다시 들어가지 않는다.

    종전 시드는 옛 키의 활성 행을 못 찾아 INSERT했고, 새 밴드와 겹쳐 계산이 409가 됐다.
    """
    await _revise_reference_lines(
        seeded,
        "BULK_CARRIER",
        [("DWT >= 300000", "fixed 300000", "4745"), ("DWT < 300000", "DWT", "4745")],
    )

    await seed_all(seeded)

    active = await _active_reference_lines(seeded, "BULK_CARRIER")
    assert [row.condition_expr for row in active] == ["DWT < 300000", "DWT >= 300000"]
    assert partition_problem([row.condition_expr for row in active]) is None


async def test_seed_keeps_a_revised_regulation_year(seeded):
    """규정연도는 연도가 개정 단위다 — 개정 판본 활성 행이 있는 연도는 건너뛴다."""
    await seeded.execute(
        text('UPDATE regulation_year SET is_active = 0 WHERE "year" = 2027 AND is_active = 1')
    )
    await seeded.execute(
        sa.insert(RegulationYear.__table__).values(
            year=2027,
            z_factor_percent=Decimal("13.7000"),
            effective_from=date(2027, 1, 1),
            source_ref="TEST revision",
            version=_REVISION,
            is_active=True,
        )
    )

    await seed_all(seeded)

    rows = (
        await seeded.execute(
            text(
                "SELECT z_factor_percent, version FROM regulation_year "
                'WHERE "year" = 2027 AND is_active = 1'
            )
        )
    ).all()
    assert [(row.z_factor_percent, row.version) for row in rows] == [
        (Decimal("13.7000"), _REVISION)
    ]


async def test_seed_fills_fuel_type_content_hash(seeded):
    """시드 실행 → ``fuel_type.content_hash`` 8행 NULL 없음.

    종전 시드는 ``REPLACE``(삭제 후 삽입)라 ``045``가 채운 해시를 실행마다 NULL로 돌렸다.
    """
    rows = (await seeded.execute(text("SELECT code, cf, content_hash FROM fuel_type"))).all()
    by_code = {row.code: row for row in rows}
    for code, _, cf in _CF_ROWS:
        expected = compute_parameter_hash({"code": code, "cf": Decimal(cf)})
        assert by_code[code].content_hash == expected, code


async def test_seed_keeps_a_revised_fuel_cf(seeded):
    """연료 개정 적재(제자리 갱신 · ``import.`` 판본) → 시드 → CF·판본 유지."""
    revised_hash = compute_parameter_hash({"code": "HFO", "cf": Decimal("3.120000")})
    await seeded.execute(
        text("UPDATE fuel_type SET cf = 3.12, version = :v, content_hash = :h WHERE code = 'HFO'"),
        {"v": _REVISION, "h": revised_hash},
    )

    await seed_all(seeded)

    row = (
        await seeded.execute(
            text("SELECT cf, version, content_hash FROM fuel_type WHERE code = 'HFO'")
        )
    ).one()
    assert (row.cf, row.version, row.content_hash) == (Decimal("3.120000"), _REVISION, revised_hash)


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
        # 이미 aiopycubrid — 그대로 둔다.
        (
            "cubrid+aiopycubrid://dba:@localhost:33000/cii",
            "cubrid+aiopycubrid://dba:@localhost:33000/cii",
        ),
        # 드라이버 생략(CI가 주입하는 형식) — aiopycubrid를 붙인다.
        (
            "cubrid://dba:@localhost:33000/cii_test",
            "cubrid+aiopycubrid://dba:@localhost:33000/cii_test",
        ),
        # 다른 cubrid 드라이버 — aiopycubrid로 바꾼다(async 방언이 그것뿐).
        ("cubrid+pycubrid://dba@db/cii", "cubrid+aiopycubrid://dba@db/cii"),
        # cubrid가 아니면 손대지 않는다.
        ("sqlite+aiosqlite:///./x.db", "sqlite+aiosqlite:///./x.db"),
    ],
)
def test_seed_script_normalizes_database_url(given, expected):
    """프로덕션 seed 진입점의 URL 정규화 분기를 고정한다.

    이 스크립트는 **규제 개정 시 재적재** 경로다(`DB_SCHEMA §8.1.1`). 신규 환경
    부트스트랩은 `alembic upgrade head`가 맡는다 — 종전에 이 docstring이 「유일한
    경로」라고 적은 것은 `#1058` 도중 부트스트랩 마이그레이션이 사라져 있던 동안의
    서술이고, `6c7496c4d122`가 그 경로를 되살렸다.
    정규화가 조용히 틀리면 첫 실행에서야 드러나므로 여기서 잠근다.
    구현은 ``db.url.normalize_to_async``(#1058) — alembic · conftest · 앱 세션과
    같은 함수를 공유한다.
    """
    from cii_platform.db.url import normalize_to_async

    assert normalize_to_async(given) == expected
