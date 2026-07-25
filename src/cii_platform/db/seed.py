"""IMO 규제 파라미터 seed 데이터 및 적재 로직 (#33).

대상 3종 — 모두 정본 문서에서 그대로 복사한 값이며 임의로 재작성하지 않는다
(AGENTS.md §3):

- ``regulation_year`` Z-factor (G3) — PRD §3.4.1 = DB_SCHEMA §3.1, 8행
- ``cii_reference_line`` (G2) — PRD §3.4.3 = DB_SCHEMA §3.3, 20행
- ``cii_rating_boundary`` d-vector (G4) — PRD §3.4.4, 14행

``fuel_type`` CF seed(§3.2)는 이 모듈 범위 밖이다 — 별도 이슈 #83이 마이그레이션으로
처리한다.

**a_decimal은 a_raw로부터 계산하지 않는다.** ``a_raw``(IMO 원문 표기)와
``a_decimal``(Decimal 변환값)을 각각 독립적으로 전사해 두고, :func:`validate_reference_lines`
가 ``parse_imo_scientific(a_raw) == a_decimal``로 대조한다. ``a_decimal``을
``parse_imo_scientific(a_raw)``로 생성하면 이 대조가 항상 참이 되어 검증이 무의미해지고,
전사 오류(AGENTS.md §2.3의 ``14479E10``/``14779E10`` 사례)를 잡을 수 없다.

**실행 방식은 DB_SCHEMA §8.1·§8.3과 편차가 있다.** §8.1은 seed를 ``seed/`` 디렉토리 +
Alembic data migration으로 규정하나, 이슈 #33의 완료 기준이 ``python scripts/seed.py``이고
재실행 idempotent(upsert)를 요구하므로 스크립트 방식으로 둔다. 데이터·로직을 패키지
안에 두어 DB 없이도 값 검증 테스트가 가능하며, #83의 data migration이 동일 상수를
재사용할 수 있다. 편차 경위는 이슈 #33 코멘트에 기록했다.
"""

import dataclasses
from datetime import date
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from cii_platform.calc.imo_parser import parse_imo_scientific
from cii_platform.db.models import CiiRatingBoundary, CiiReferenceLine, RegulationYear

# 출처(source_ref). 권위 소스는 AGENTS.md §2.2 표를 따른다.
SOURCE_Z_FACTOR = "MEPC.400(83)"
SOURCE_REFERENCE_LINE = "MEPC.353(78)"
SOURCE_RATING_BOUNDARY = "MEPC.354(78)"

# 파라미터 세트 버전 (DB_SCHEMA §8.3). fuel_type.version의 server_default '1.0'과 정렬한다.
PARAMETER_SET_VERSION = "1.0"


@dataclasses.dataclass(frozen=True)
class ZFactorRow:
    """``regulation_year`` 한 행 (PRD §3.4.1 = DB_SCHEMA §3.1)."""

    year: int
    z_factor_percent: Decimal

    @property
    def effective_from(self) -> date:
        """적용 시작일. Z%는 연 단위로 적용되므로 해당 연도 1월 1일이다."""
        return date(self.year, 1, 1)


@dataclasses.dataclass(frozen=True)
class ReferenceLineRow:
    """``cii_reference_line`` 한 행 (PRD §3.4.3 = DB_SCHEMA §3.3).

    ``a_raw``와 ``a_decimal``은 서로 독립적으로 전사한다 (모듈 docstring 참조).
    ``c``는 양수로 저장하고 계산 시 ``Capacity^(-c)``를 적용한다 (DB_SCHEMA §2.10).
    """

    ship_type: str
    condition_expr: str
    capacity_rule: str
    a_raw: str
    a_decimal: Decimal
    c: Decimal


@dataclasses.dataclass(frozen=True)
class RatingBoundaryRow:
    """``cii_rating_boundary`` 한 행 (PRD §3.4.4)."""

    ship_type: str
    condition_expr: str
    capacity_basis: str
    d1: Decimal
    d2: Decimal
    d3: Decimal
    d4: Decimal


# --- Z-factor (G3) — PRD §3.4.1 = DB_SCHEMA §3.1 --------------------------------
# required_CII = CII_ref × (1 - z_factor_percent / 100). 퍼센트 값 그대로 저장한다.
SEED_Z_FACTORS: tuple[ZFactorRow, ...] = (
    ZFactorRow(2023, Decimal("5.0000")),
    ZFactorRow(2024, Decimal("7.0000")),
    ZFactorRow(2025, Decimal("9.0000")),
    ZFactorRow(2026, Decimal("11.0000")),
    ZFactorRow(2027, Decimal("13.6250")),
    ZFactorRow(2028, Decimal("16.2500")),
    ZFactorRow(2029, Decimal("18.8750")),
    ZFactorRow(2030, Decimal("21.5000")),
)

# --- Reference Line (G2) — PRD §3.4.3 = DB_SCHEMA §3.3 --------------------------
# ⚠️ AGENTS.md §2.3: LNG_CARRIER의 14479E10(65000 ≤ DWT < 100000)과
#    14779E10(DWT < 65000)은 서로 다른 구간의 서로 다른 값이다. 오타가 아니다.
SEED_REFERENCE_LINES: tuple[ReferenceLineRow, ...] = (
    ReferenceLineRow(
        "BULK_CARRIER",
        "DWT >= 279000",
        "fixed 279000",
        "4745",
        Decimal("4745"),
        Decimal("0.622000"),
    ),
    ReferenceLineRow(
        "BULK_CARRIER", "DWT < 279000", "DWT", "4745", Decimal("4745"), Decimal("0.622000")
    ),
    ReferenceLineRow(
        "GAS_CARRIER",
        "DWT >= 65000",
        "DWT",
        "14405E7",
        Decimal("144050000000"),
        Decimal("2.071000"),
    ),
    ReferenceLineRow(
        "GAS_CARRIER", "DWT < 65000", "DWT", "8104", Decimal("8104"), Decimal("0.639000")
    ),
    ReferenceLineRow("TANKER", "all", "DWT", "5247", Decimal("5247"), Decimal("0.610000")),
    ReferenceLineRow("CONTAINER_SHIP", "all", "DWT", "1984", Decimal("1984"), Decimal("0.489000")),
    ReferenceLineRow(
        "GENERAL_CARGO_SHIP", "DWT >= 20000", "DWT", "31948", Decimal("31948"), Decimal("0.792000")
    ),
    ReferenceLineRow(
        "GENERAL_CARGO_SHIP", "DWT < 20000", "DWT", "588", Decimal("588"), Decimal("0.388500")
    ),
    ReferenceLineRow(
        "REFRIGERATED_CARGO_CARRIER", "all", "DWT", "4600", Decimal("4600"), Decimal("0.557000")
    ),
    ReferenceLineRow(
        "COMBINATION_CARRIER", "all", "DWT", "5119", Decimal("5119"), Decimal("0.622000")
    ),
    # c = 0.000000은 정상이다 — 대형 LNG 캐리어는 고정 CII_ref를 쓴다
    # (DB_SCHEMA §2.10 [Oracle 관찰]).
    ReferenceLineRow(
        "LNG_CARRIER", "DWT >= 100000", "DWT", "9.827", Decimal("9.827"), Decimal("0.000000")
    ),
    ReferenceLineRow(
        "LNG_CARRIER",
        "65000 <= DWT < 100000",
        "DWT",
        "14479E10",
        Decimal("144790000000000"),
        Decimal("2.673000"),
    ),
    ReferenceLineRow(
        "LNG_CARRIER",
        "DWT < 65000",
        "fixed 65000",
        "14779E10",
        Decimal("147790000000000"),
        Decimal("2.673000"),
    ),
    ReferenceLineRow(
        "RO_RO_CARGO_VEHICLE",
        "GT >= 57700",
        "fixed 57700",
        "3627",
        Decimal("3627"),
        Decimal("0.590000"),
    ),
    ReferenceLineRow(
        "RO_RO_CARGO_VEHICLE",
        "30000 <= GT < 57700",
        "GT",
        "3627",
        Decimal("3627"),
        Decimal("0.590000"),
    ),
    ReferenceLineRow(
        "RO_RO_CARGO_VEHICLE", "GT < 30000", "GT", "330", Decimal("330"), Decimal("0.329000")
    ),
    ReferenceLineRow("RO_RO_CARGO", "all", "GT", "1967", Decimal("1967"), Decimal("0.485000")),
    ReferenceLineRow("RO_RO_PASSENGER", "all", "GT", "2023", Decimal("2023"), Decimal("0.460000")),
    ReferenceLineRow(
        "RO_RO_PASSENGER_HSC", "all", "GT", "4196", Decimal("4196"), Decimal("0.460000")
    ),
    ReferenceLineRow("CRUISE_PASSENGER", "all", "GT", "930", Decimal("930"), Decimal("0.383000")),
)

# --- d-vector (G4) — PRD §3.4.4 -------------------------------------------------
# ⚠️ reference line에는 있는 RO_RO_PASSENGER_HSC가 이 표에는 없다. G2(MEPC.353(78))와
#    G4(MEPC.354(78))는 별개 결의안이라 원문상 의도된 부재일 수 있으므로, 정본에 없는
#    행을 임의로 만들지 않는다 (AGENTS.md §2.1·§3). 후속 이슈에서 원문 확인 대상.
SEED_RATING_BOUNDARIES: tuple[RatingBoundaryRow, ...] = (
    RatingBoundaryRow(
        "BULK_CARRIER",
        "all",
        "DWT",
        Decimal("0.8600"),
        Decimal("0.9400"),
        Decimal("1.0600"),
        Decimal("1.1800"),
    ),
    RatingBoundaryRow(
        "GAS_CARRIER",
        "DWT >= 65000",
        "DWT",
        Decimal("0.8100"),
        Decimal("0.9100"),
        Decimal("1.1200"),
        Decimal("1.4400"),
    ),
    RatingBoundaryRow(
        "GAS_CARRIER",
        "DWT < 65000",
        "DWT",
        Decimal("0.8500"),
        Decimal("0.9500"),
        Decimal("1.0600"),
        Decimal("1.2500"),
    ),
    RatingBoundaryRow(
        "TANKER",
        "all",
        "DWT",
        Decimal("0.8200"),
        Decimal("0.9300"),
        Decimal("1.0800"),
        Decimal("1.2800"),
    ),
    RatingBoundaryRow(
        "CONTAINER_SHIP",
        "all",
        "DWT",
        Decimal("0.8300"),
        Decimal("0.9400"),
        Decimal("1.0700"),
        Decimal("1.1900"),
    ),
    RatingBoundaryRow(
        "GENERAL_CARGO_SHIP",
        "all",
        "DWT",
        Decimal("0.8300"),
        Decimal("0.9400"),
        Decimal("1.0600"),
        Decimal("1.1900"),
    ),
    RatingBoundaryRow(
        "REFRIGERATED_CARGO_CARRIER",
        "all",
        "DWT",
        Decimal("0.7800"),
        Decimal("0.9100"),
        Decimal("1.0700"),
        Decimal("1.2000"),
    ),
    RatingBoundaryRow(
        "COMBINATION_CARRIER",
        "all",
        "DWT",
        Decimal("0.8700"),
        Decimal("0.9600"),
        Decimal("1.0600"),
        Decimal("1.1400"),
    ),
    RatingBoundaryRow(
        "LNG_CARRIER",
        "DWT >= 100000",
        "DWT",
        Decimal("0.8900"),
        Decimal("0.9800"),
        Decimal("1.0600"),
        Decimal("1.1300"),
    ),
    RatingBoundaryRow(
        "LNG_CARRIER",
        "DWT < 100000",
        "DWT",
        Decimal("0.7800"),
        Decimal("0.9200"),
        Decimal("1.1000"),
        Decimal("1.3700"),
    ),
    RatingBoundaryRow(
        "RO_RO_CARGO_VEHICLE",
        "all",
        "GT",
        Decimal("0.8600"),
        Decimal("0.9400"),
        Decimal("1.0600"),
        Decimal("1.1600"),
    ),
    RatingBoundaryRow(
        "RO_RO_CARGO",
        "all",
        "GT",
        Decimal("0.7600"),
        Decimal("0.8900"),
        Decimal("1.0800"),
        Decimal("1.2700"),
    ),
    RatingBoundaryRow(
        "RO_RO_PASSENGER",
        "all",
        "GT",
        Decimal("0.7600"),
        Decimal("0.9200"),
        Decimal("1.1400"),
        Decimal("1.3000"),
    ),
    RatingBoundaryRow(
        "CRUISE_PASSENGER",
        "all",
        "GT",
        Decimal("0.8700"),
        Decimal("0.9500"),
        Decimal("1.0600"),
        Decimal("1.1600"),
    ),
)


def validate_reference_lines() -> None:
    """모든 reference line 행에서 ``parse_imo_scientific(a_raw) == a_decimal``을 검증한다.

    TECH_SPEC §9.3 / TEST_PLAN UT-IMO-003. DB 접근 없이 상수만 검사하므로 seed 실행
    전에 호출해 잘못된 값이 DB에 들어가는 것을 막는다.
    """
    mismatches = []
    for row in SEED_REFERENCE_LINES:
        parsed = parse_imo_scientific(row.a_raw)
        if parsed != row.a_decimal:
            mismatches.append(
                f"{row.ship_type} ({row.condition_expr}): {row.a_raw} → {parsed} != {row.a_decimal}"
            )
    if mismatches:
        raise ValueError("a_raw/a_decimal mismatch:\n  " + "\n  ".join(mismatches))


async def _upsert_z_factors(conn: AsyncConnection) -> int:
    """``regulation_year``를 upsert한다. 충돌 키는 UNIQUE 제약 ``year``."""
    values = [
        {
            "year": row.year,
            "z_factor_percent": row.z_factor_percent,
            "effective_from": row.effective_from,
            "source_ref": SOURCE_Z_FACTOR,
            "version": PARAMETER_SET_VERSION,
            "is_active": True,
        }
        for row in SEED_Z_FACTORS
    ]
    stmt = pg_insert(RegulationYear.__table__).values(values)
    # created_at은 갱신하지 않는다 — 최초 적재 시점을 보존한다.
    stmt = stmt.on_conflict_do_update(
        index_elements=["year"],
        set_={
            "z_factor_percent": stmt.excluded.z_factor_percent,
            "effective_from": stmt.excluded.effective_from,
            "source_ref": stmt.excluded.source_ref,
            "version": stmt.excluded.version,
            "is_active": stmt.excluded.is_active,
        },
    )
    await conn.execute(stmt)
    return len(values)


async def _upsert_reference_lines(conn: AsyncConnection) -> int:
    """``cii_reference_line``을 upsert한다. 충돌 키는 ``idx_refline_unique``."""
    values = [
        {
            "ship_type": row.ship_type,
            "condition_expr": row.condition_expr,
            "capacity_rule": row.capacity_rule,
            "a_raw": row.a_raw,
            "a_decimal": row.a_decimal,
            "c": row.c,
            "source_ref": SOURCE_REFERENCE_LINE,
        }
        for row in SEED_REFERENCE_LINES
    ]
    stmt = pg_insert(CiiReferenceLine.__table__).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ship_type", "condition_expr"],
        set_={
            "capacity_rule": stmt.excluded.capacity_rule,
            "a_raw": stmt.excluded.a_raw,
            "a_decimal": stmt.excluded.a_decimal,
            "c": stmt.excluded.c,
            "source_ref": stmt.excluded.source_ref,
        },
    )
    await conn.execute(stmt)
    return len(values)


async def _upsert_rating_boundaries(conn: AsyncConnection) -> int:
    """``cii_rating_boundary``를 upsert한다. 충돌 키는 ``idx_boundary_unique``."""
    values = [
        {
            "ship_type": row.ship_type,
            "condition_expr": row.condition_expr,
            "capacity_basis": row.capacity_basis,
            "d1": row.d1,
            "d2": row.d2,
            "d3": row.d3,
            "d4": row.d4,
            "source_ref": SOURCE_RATING_BOUNDARY,
        }
        for row in SEED_RATING_BOUNDARIES
    ]
    stmt = pg_insert(CiiRatingBoundary.__table__).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ship_type", "condition_expr"],
        set_={
            "capacity_basis": stmt.excluded.capacity_basis,
            "d1": stmt.excluded.d1,
            "d2": stmt.excluded.d2,
            "d3": stmt.excluded.d3,
            "d4": stmt.excluded.d4,
            "source_ref": stmt.excluded.source_ref,
        },
    )
    await conn.execute(stmt)
    return len(values)


async def seed_all(conn: AsyncConnection) -> dict[str, int]:
    """규제 파라미터 3종을 upsert하고 테이블별 적재 행 수를 돌려준다.

    재실행해도 같은 결과가 되도록 모두 ``ON CONFLICT DO UPDATE``를 쓴다(이슈 #33).
    호출자가 트랜잭션을 관리한다 — 이 함수는 commit하지 않는다.
    """
    validate_reference_lines()
    return {
        "regulation_year": await _upsert_z_factors(conn),
        "cii_reference_line": await _upsert_reference_lines(conn),
        "cii_rating_boundary": await _upsert_rating_boundaries(conn),
    }
