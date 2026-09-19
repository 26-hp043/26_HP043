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

**이 모듈이 담는 것은 「지금 옳다고 보는 값」이다** (DB_SCHEMA §8.1.1 · #127).

신규 환경 부트스트랩은 이 모듈이 하지 않는다 — data migration 032가 42행을 넣으며
``alembic upgrade head`` 하나로 적재가 끝난다. :func:`seed_all`의 upsert는 **규제
개정 시 재적재** 경로다.

===========================  ===================================================
주체                          담는 것
===========================  ===================================================
data migration (017 · 032)   그날 넣은 값 · **불변** · 신규 환경 부트스트랩
``seed_all()`` (upsert)      지금 옳다고 보는 값 · **가변** · 규제 개정 시 재적재
===========================  ===================================================

**마이그레이션은 이 모듈의 상수를 import하지 않는다.** 마이그레이션은 과거 시점
스냅샷이라 가변 상수를 참조하면 과거 동작이 소급 변경된다(017이 세우고 031·032가
따른 원칙 · §8.1.1 🔒). 규제 개정으로 둘이 갈라지는 것은 정상이며, 그 순간을 모르고
지나가지 않도록 ``tests/test_seed_migration.py``가 양쪽을 매 실행 대조한다.

값·로직이 ``seed/`` 디렉토리가 아니라 패키지 안에 있는 이유는 **DB 없이 값 검증
테스트가 가능해야** 하기 때문이다 — 5개 테스트 파일이 이 상수를 import해 ``PRD``
§3.4와 대조한다. §8.1은 원래 ``seed/`` 디렉토리를 규정했으나 #127에서 실제 구조로
고쳤다.
"""

import dataclasses
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy_cubrid.dml import replace as cubrid_replace

from cii_platform.calc.imo_parser import parse_imo_scientific
from cii_platform.db.models import CiiRatingBoundary, CiiReferenceLine, RegulationYear
from cii_platform.db.models.fuel_type import FuelType

# 출처(source_ref). 권위 소스는 AGENTS.md §2.2 표를 따른다.
SOURCE_Z_FACTOR = "MEPC.400(83)"
SOURCE_REFERENCE_LINE = "MEPC.353(78)"
SOURCE_RATING_BOUNDARY = "MEPC.354(78)"
SOURCE_FUEL_TYPE = "MEPC.364(79)"

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
#
# [#149] 원문 전수 대조 절차 (2026-07-30 · 20행 · 불일치 0건)
#   원문: MEPC.353(78) Table 1 — MEPC 78/17/Add.1 Annex 15, 인쇄면 4쪽
#   1. 원문 PDF에서 Table 1 페이지 텍스트를 추출한다.
#   2. 추출 텍스트에서 20행을 (선종, 조건, Capacity 칸, a, c)로 전사한다.
#   3. 전사 가드 — 전사한 40개 a·c 토큰이 추출 텍스트에 실재하는지 먼저 검사한다.
#      (이 단계를 건너뛰면 전사 실수가 대조 결과에 그대로 섞인다. 누락 0건 확인)
#   4. 이 상수를 import해 행 단위로 diff 한다.
#
#   재현 명령 — 위 PDF를 /tmp/mepc353.pdf로 받은 뒤 실행한다. 로컬에 PDF 도구를
#   설치하지 않아도 된다. Table 1은 Annex 15 인쇄면 4쪽이며 PDF에서는 5번째
#   페이지(0-index 4)다. 표지·결의문이 앞에 붙어 인쇄 번호와 인덱스가 어긋난다.
#
#     docker run --rm -v /tmp:/w python:3.12-slim sh -c \
#       "pip install -q pypdf && python -c \"
#     import pypdf; print(pypdf.PdfReader('/w/mepc353.pdf').pages[4].extract_text())\""
#
#   대조 결과 요약과 특기 사항은 DB_SCHEMA §3.3 각주에 있다.
#   ⚠️ 이 대조는 개발이 수행했다. AGENTS §2.1이 요구하는 팀원 원문 확인은 아직 없다.
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
#    G4(MEPC.354(78))는 별개 결의안이라 **원문상 의도된 부재**다 (#126 원문 대조로 확인).
#    정본에 없는 행을 임의로 만들지 않는다 (AGENTS.md §2.1·§3). 등급 경계가 필요하면
#    rating_engine.RATING_BOUNDARY_FALLBACK이 RO_RO_PASSENGER로 폴백한다.
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


async def _upsert_active(
    conn: AsyncConnection,
    table: sa.Table,
    key_columns: tuple[str, ...],
    row: dict[str, object],
) -> None:
    """활성 행을 갱신하고, 없으면 삽입한다 — 전역 유니크가 없어진 키의 upsert.

    🔴 종전 충돌 판정은 전역 유니크 인덱스(``uq_regulation_year_year``·
    ``idx_refline_unique``·``idx_boundary_unique``)가 했는데 ``054``(#673)가 셋 다
    뺐다 — 개정 이행 행이 같은 키로 쌓여야 하므로. ``REPLACE``는 유니크 인덱스로
    충돌을 찾으므로 인덱스가 없으면 **항상 INSERT**가 되어 활성-유니크 트리거에
    걸린다. 대상을 **활성 행**으로 못 박아 같은 의미(README의 「upsert라 값을
    덮어쓴다」)를 유지한다 — 개정 이행 행은 건드리지 않는다(``DB_SCHEMA §7.2``).
    """
    conditions = [table.c.is_active == 1] + [
        table.c[column] == row[column] for column in key_columns
    ]
    result = await conn.execute(sa.update(table).where(*conditions).values(**row))
    if result.rowcount == 0:
        await conn.execute(sa.insert(table).values(row))


async def _upsert_z_factors(conn: AsyncConnection) -> int:
    """``regulation_year``를 upsert한다 — 활성 행 갱신 · 없으면 삽입 (054 이후)."""
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
    for row in values:
        await _upsert_active(conn, RegulationYear.__table__, ("year",), row)
    return len(values)


async def _upsert_reference_lines(conn: AsyncConnection) -> int:
    """``cii_reference_line``을 upsert한다 — 활성 행 갱신 · 없으면 삽입 (054 이후)."""
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
    for row in values:
        await _upsert_active(conn, CiiReferenceLine.__table__, ("ship_type", "condition_expr"), row)
    return len(values)


async def _upsert_rating_boundaries(conn: AsyncConnection) -> int:
    """``cii_rating_boundary``을 upsert한다 — 활성 행 갱신 · 없으면 삽입 (054 이후)."""
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
    for row in values:
        await _upsert_active(
            conn, CiiRatingBoundary.__table__, ("ship_type", "condition_expr"), row
        )
    return len(values)


# MEPC.364(79) §2.2.1 — PRD §3.4 연료 종류별 CO₂ 배출 계수 (tCO₂/tFuel).
_CF_ROWS = (
    ("DIESEL_GAS_OIL", "Diesel/Gas Oil", "3.206000"),
    ("LFO", "Light Fuel Oil", "3.151000"),
    ("HFO", "Heavy Fuel Oil", "3.114000"),
    ("LPG_PROPANE", "LPG Propane", "3.000000"),
    ("LPG_BUTANE", "LPG Butane", "3.030000"),
    ("LNG", "Liquefied Natural Gas", "2.750000"),
    ("METHANOL", "Methanol", "1.375000"),
    ("ETHANOL", "Ethanol", "1.913000"),
)


async def _upsert_fuel_types(conn: AsyncConnection) -> int:
    """fuel_type 8행을 upsert한다."""
    import uuid as _uuid

    count = 0
    for code, display_name, cf in _CF_ROWS:
        row = {
            "id": _uuid.uuid4(),
            "code": code,
            "display_name": display_name,
            "cf": Decimal(cf),
            "source_ref": SOURCE_FUEL_TYPE,
            "version": PARAMETER_SET_VERSION,
        }
        await conn.execute(cubrid_replace(FuelType.__table__).values(row))
        count += 1
    return count


# 시뮬레이션 파라미터 (035_simulation_parameter.py에서 이전)
_SIM_PARAM_ROWS = (
    # (variable, bound_type, min, mode, max, floor)
    ("DISTANCE", "FACTOR", "0.9700", "1.0000", "1.0500", None),
    ("FUEL", "FACTOR", "0.9000", "1.0000", "1.1500", None),
    ("SPEED", "DELTA", "-1.0000", "0.0000", "1.0000", "1.0000"),
)
_SIM_PARAM_PROFILE = "DEFAULT"


async def _upsert_simulation_parameters(conn: AsyncConnection) -> int:
    """simulation_parameter 3행을 upsert한다."""
    import uuid as _uuid

    from cii_platform.db.models.simulation_parameter import SimulationParameter

    count = 0
    for variable, bound_type, min_v, mode_v, max_v, floor_v in _SIM_PARAM_ROWS:
        row = {
            "id": _uuid.uuid4(),
            "profile": _SIM_PARAM_PROFILE,
            "variable": variable,
            "distribution": "TRIANGULAR",
            "bound_type": bound_type,
            "min_value": Decimal(min_v),
            "mode_value": Decimal(mode_v),
            "max_value": Decimal(max_v),
            "floor_value": Decimal(floor_v) if floor_v else None,
            "source_ref": "PRD §12.4.1",
            "version": PARAMETER_SET_VERSION,
        }
        await conn.execute(cubrid_replace(SimulationParameter.__table__).values(row))
        count += 1
    return count


# 기상 모델 파라미터 (019_seed_weather_model_parameter.py에서 이전)
_WEATHER_PARAMS = [
    ("TOWNSIN_KWON_ALPHA", "cu_a.BULK_CARRIER", "0.5", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_b.BULK_CARRIER", "0.5", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_a.TANKER", "0.7", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_b.TANKER", "0", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_a.CONTAINER_SHIP", "0.6", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_b.CONTAINER_SHIP", "0.2", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_a.GENERAL_CARGO_SHIP", "0.5", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_b.GENERAL_CARGO_SHIP", "0.5", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_a.LNG_CARRIER", "0.7", "dimensionless"),
    ("TOWNSIN_KWON_ALPHA", "cu_b.LNG_CARRIER", "0", "dimensionless"),
]


async def _upsert_weather_params(conn: AsyncConnection) -> int:
    """weather_model_parameter 10행을 upsert한다."""
    import uuid as _uuid

    from cii_platform.db.models.weather_model_parameter import WeatherModelParameter

    count = 0
    for model_ver, key, value, unit in _WEATHER_PARAMS:
        row = {
            "id": _uuid.uuid4(),
            "model_version": model_ver,
            "key": key,
            "value": value,
            "unit": unit,
            "source_ref": "TECH_SPEC §3.3 (Kwon 2008 단순화)",
        }
        await conn.execute(cubrid_replace(WeatherModelParameter.__table__).values(row))
        count += 1
    return count


async def seed_all(conn: AsyncConnection) -> dict[str, int]:
    """규제 파라미터 + 연료 종류 + 시뮬레이션 파라미터를 upsert한다.

    재실행해도 같은 결과가 되도록 모두 upsert를 쓴다.
    호출자가 트랜잭션을 관리한다 — 이 함수는 commit하지 않는다.
    """
    validate_reference_lines()
    return {
        "fuel_type": await _upsert_fuel_types(conn),
        "regulation_year": await _upsert_z_factors(conn),
        "cii_reference_line": await _upsert_reference_lines(conn),
        "cii_rating_boundary": await _upsert_rating_boundaries(conn),
        "simulation_parameter": await _upsert_simulation_parameters(conn),
        "weather_model_parameter": await _upsert_weather_params(conn),
    }


async def main() -> None:  # pragma: no cover - 프로세스 진입점
    """엔진을 열고 단일 트랜잭션으로 seed를 적재한다.

    ``python -m cii_platform.db.seed``로 실행한다 (#240). 진입점을 패키지 안에 둔 이유는
    **프로덕션 이미지가 wheel만 설치**하기 때문이다 — ``scripts/``는 이미지에 없으므로
    ``scripts/seed.py``를 배포 절차의 명령으로 쓸 수 없다. ``scripts/seed.py``는 이
    함수에 위임하는 개발용 래퍼로 남는다(로직 사본을 두지 않는다 — #234).
    """
    # 지연 import — 이 모듈은 DB 없이 값 검증 테스트에 쓰이므로(모듈 docstring),
    # 진입점에서만 필요한 엔진 계열을 상단 import로 올리지 않는다.
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import create_async_engine

    from cii_platform.config import DATABASE_URL
    from cii_platform.db.url import normalize_to_async

    # URL 정규화는 alembic/env.py·tests/conftest.py·db/session.py와 같은 함수를
    # 공유한다 (#234). 사본을 두면 앱만 분기가 빠지는 일이 다시 생긴다.
    engine = create_async_engine(normalize_to_async(DATABASE_URL), poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            counts = await seed_all(conn)
    finally:
        # 성공·실패와 무관하게 커넥션을 반납한다.
        await engine.dispose()

    for table, count in counts.items():
        print(f"{table}: {count}행 적재(upsert)")


if __name__ == "__main__":  # pragma: no cover - 프로세스 진입점
    import asyncio

    asyncio.run(main())
