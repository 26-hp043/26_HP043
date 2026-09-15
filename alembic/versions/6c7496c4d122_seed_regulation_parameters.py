"""규제 파라미터·연료 CF 부트스트랩 — 종전 017 + 032 (#1058).

**CUBRID 전환(`9ddeb22`)에서 data migration 017·032가 통째로 사라졌다.** 스키마를
`1c444a5c4819` 하나로 합치면서 값을 넣던 리비전이 함께 지워졌고, 그 결과
`alembic upgrade head`만으로는 **규제 파라미터가 한 행도 들어오지 않는다.**
`DB_SCHEMA §8.1.1`이 「계산에 필요한 seed는 `alembic upgrade head` 경로에 들어 있다.
배포에 별도 스크립트 실행 단계가 없다」로 정한 계약이라 그대로 되살린다.

**`1c444a5c4819`를 고치지 않고 뒤에 새 리비전으로 붙인다.** 스키마와 data migration을
가르는 것이 017·032가 쓰던 구조이고, 그 파일은 지금 `#1142`가 만지고 있다.

`DB_SCHEMA §8.1.1`의 🔒 세 가지를 그대로 따른다.

* **`src/` 상수를 import하지 않는다** — 값은 아래에 인라인으로 고정한다. import하면
  규제 개정 때 과거 마이그레이션의 동작이 소급 변경되어, 새 환경이 「그날의 값」이
  아니라 「오늘의 값」을 받는다.
* **upsert를 쓰지 않는다** — 재적재는 `seed_all()`의 몫이다.
* **downgrade는 자기가 넣은 키만 지운다** — 전체 DELETE는 운영 중 추가된 행까지 지운다.

CUBRID에서 달라진 것 하나 — **`id`에 기본값이 없다.** PostgreSQL 시절에는
`gen_random_uuid()` server_default에 위임했는데(`017`·`032`의 주석), CUBRID 스키마의
`id`는 `CHAR` NOT NULL에 기본값이 없어 **넣는 쪽이 만들어야 한다.** 값은 환경마다
달라도 되는 대리키라 `uuid4().hex`로 만든다 — 종전 `gen_random_uuid()`와 같은 성격이다.

`content_hash`·`effective_from`을 NULL로 두는 이유는 017의 주석 그대로다
(`#42`가 해싱 규칙을 정한 뒤 별도 마이그레이션에서 채운다 · 8종 CF는 연도 스코프가 없다).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

revision: str = "6c7496c4d122"
down_revision: str | Sequence[str] | None = "1c444a5c4819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 출처(source_ref) — 권위 소스는 AGENTS.md §2.2 표를 따른다.
SOURCE_REF_FUEL = "MEPC.364(79)"
SOURCE_Z_FACTOR = "MEPC.400(83)"
SOURCE_REFERENCE_LINE = "MEPC.353(78)"
SOURCE_RATING_BOUNDARY = "MEPC.354(78)"

# 파라미터 세트 버전 (DB_SCHEMA §8.3).
PARAMETER_SET_VERSION = "1.0"


# DB_SCHEMA.md §3.2 표 그대로 — (code, display_name, cf). 행 순서도 정본 표와 같다.
_CF_ROWS: tuple[tuple[str, str, str], ...] = (
    ("DIESEL_GAS_OIL", "Diesel/Gas Oil", "3.206000"),
    ("LFO", "Light Fuel Oil", "3.151000"),
    ("HFO", "Heavy Fuel Oil", "3.114000"),
    ("LPG_PROPANE", "LPG Propane", "3.000000"),
    ("LPG_BUTANE", "LPG Butane", "3.030000"),
    ("LNG", "Liquefied Natural Gas", "2.750000"),
    ("METHANOL", "Methanol", "1.375000"),
    ("ETHANOL", "Ethanol", "1.913000"),
)

# op.bulk_insert()는 executemany라 모든 dict의 키 집합이 완전히 동일해야 한다.
# 아래 컴프리헨션이 그것을 구조적으로 보장한다(None인 컬럼도 키는 채운다).
SEED_FUEL_TYPES: list[dict[str, object]] = [
    {
        "code": code,
        "display_name": display_name,
        "cf": Decimal(cf),
        "source_ref": SOURCE_REF_FUEL,
        "version": PARAMETER_SET_VERSION,
        "content_hash": None,
        "effective_from": None,
    }
    for code, display_name, cf in _CF_ROWS
]


SEED_Z_FACTORS: tuple[dict[str, object], ...] = (
    {"year": 2023, "z_factor_percent": Decimal("5.0000"), "effective_from": date(2023, 1, 1)},
    {"year": 2024, "z_factor_percent": Decimal("7.0000"), "effective_from": date(2024, 1, 1)},
    {"year": 2025, "z_factor_percent": Decimal("9.0000"), "effective_from": date(2025, 1, 1)},
    {"year": 2026, "z_factor_percent": Decimal("11.0000"), "effective_from": date(2026, 1, 1)},
    {"year": 2027, "z_factor_percent": Decimal("13.6250"), "effective_from": date(2027, 1, 1)},
    {"year": 2028, "z_factor_percent": Decimal("16.2500"), "effective_from": date(2028, 1, 1)},
    {"year": 2029, "z_factor_percent": Decimal("18.8750"), "effective_from": date(2029, 1, 1)},
    {"year": 2030, "z_factor_percent": Decimal("21.5000"), "effective_from": date(2030, 1, 1)},
)


SEED_REFERENCE_LINES: tuple[dict[str, object], ...] = (
    {
        "ship_type": "BULK_CARRIER",
        "condition_expr": "DWT >= 279000",
        "capacity_rule": "fixed 279000",
        "a_raw": "4745",
        "a_decimal": Decimal("4745"),
        "c": Decimal("0.622000"),
    },
    {
        "ship_type": "BULK_CARRIER",
        "condition_expr": "DWT < 279000",
        "capacity_rule": "DWT",
        "a_raw": "4745",
        "a_decimal": Decimal("4745"),
        "c": Decimal("0.622000"),
    },
    {
        "ship_type": "GAS_CARRIER",
        "condition_expr": "DWT >= 65000",
        "capacity_rule": "DWT",
        "a_raw": "14405E7",
        "a_decimal": Decimal("144050000000"),
        "c": Decimal("2.071000"),
    },
    {
        "ship_type": "GAS_CARRIER",
        "condition_expr": "DWT < 65000",
        "capacity_rule": "DWT",
        "a_raw": "8104",
        "a_decimal": Decimal("8104"),
        "c": Decimal("0.639000"),
    },
    {
        "ship_type": "TANKER",
        "condition_expr": "all",
        "capacity_rule": "DWT",
        "a_raw": "5247",
        "a_decimal": Decimal("5247"),
        "c": Decimal("0.610000"),
    },
    {
        "ship_type": "CONTAINER_SHIP",
        "condition_expr": "all",
        "capacity_rule": "DWT",
        "a_raw": "1984",
        "a_decimal": Decimal("1984"),
        "c": Decimal("0.489000"),
    },
    {
        "ship_type": "GENERAL_CARGO_SHIP",
        "condition_expr": "DWT >= 20000",
        "capacity_rule": "DWT",
        "a_raw": "31948",
        "a_decimal": Decimal("31948"),
        "c": Decimal("0.792000"),
    },
    {
        "ship_type": "GENERAL_CARGO_SHIP",
        "condition_expr": "DWT < 20000",
        "capacity_rule": "DWT",
        "a_raw": "588",
        "a_decimal": Decimal("588"),
        "c": Decimal("0.388500"),
    },
    {
        "ship_type": "REFRIGERATED_CARGO_CARRIER",
        "condition_expr": "all",
        "capacity_rule": "DWT",
        "a_raw": "4600",
        "a_decimal": Decimal("4600"),
        "c": Decimal("0.557000"),
    },
    {
        "ship_type": "COMBINATION_CARRIER",
        "condition_expr": "all",
        "capacity_rule": "DWT",
        "a_raw": "5119",
        "a_decimal": Decimal("5119"),
        "c": Decimal("0.622000"),
    },
    {
        "ship_type": "LNG_CARRIER",
        "condition_expr": "DWT >= 100000",
        "capacity_rule": "DWT",
        "a_raw": "9.827",
        "a_decimal": Decimal("9.827"),
        "c": Decimal("0.000000"),
    },
    {
        "ship_type": "LNG_CARRIER",
        "condition_expr": "65000 <= DWT < 100000",
        "capacity_rule": "DWT",
        "a_raw": "14479E10",
        "a_decimal": Decimal("144790000000000"),
        "c": Decimal("2.673000"),
    },
    {
        "ship_type": "LNG_CARRIER",
        "condition_expr": "DWT < 65000",
        "capacity_rule": "fixed 65000",
        "a_raw": "14779E10",
        "a_decimal": Decimal("147790000000000"),
        "c": Decimal("2.673000"),
    },
    {
        "ship_type": "RO_RO_CARGO_VEHICLE",
        "condition_expr": "GT >= 57700",
        "capacity_rule": "fixed 57700",
        "a_raw": "3627",
        "a_decimal": Decimal("3627"),
        "c": Decimal("0.590000"),
    },
    {
        "ship_type": "RO_RO_CARGO_VEHICLE",
        "condition_expr": "30000 <= GT < 57700",
        "capacity_rule": "GT",
        "a_raw": "3627",
        "a_decimal": Decimal("3627"),
        "c": Decimal("0.590000"),
    },
    {
        "ship_type": "RO_RO_CARGO_VEHICLE",
        "condition_expr": "GT < 30000",
        "capacity_rule": "GT",
        "a_raw": "330",
        "a_decimal": Decimal("330"),
        "c": Decimal("0.329000"),
    },
    {
        "ship_type": "RO_RO_CARGO",
        "condition_expr": "all",
        "capacity_rule": "GT",
        "a_raw": "1967",
        "a_decimal": Decimal("1967"),
        "c": Decimal("0.485000"),
    },
    {
        "ship_type": "RO_RO_PASSENGER",
        "condition_expr": "all",
        "capacity_rule": "GT",
        "a_raw": "2023",
        "a_decimal": Decimal("2023"),
        "c": Decimal("0.460000"),
    },
    {
        "ship_type": "RO_RO_PASSENGER_HSC",
        "condition_expr": "all",
        "capacity_rule": "GT",
        "a_raw": "4196",
        "a_decimal": Decimal("4196"),
        "c": Decimal("0.460000"),
    },
    {
        "ship_type": "CRUISE_PASSENGER",
        "condition_expr": "all",
        "capacity_rule": "GT",
        "a_raw": "930",
        "a_decimal": Decimal("930"),
        "c": Decimal("0.383000"),
    },
)


SEED_RATING_BOUNDARIES: tuple[dict[str, object], ...] = (
    {
        "ship_type": "BULK_CARRIER",
        "condition_expr": "all",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8600"),
        "d2": Decimal("0.9400"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.1800"),
    },
    {
        "ship_type": "GAS_CARRIER",
        "condition_expr": "DWT >= 65000",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8100"),
        "d2": Decimal("0.9100"),
        "d3": Decimal("1.1200"),
        "d4": Decimal("1.4400"),
    },
    {
        "ship_type": "GAS_CARRIER",
        "condition_expr": "DWT < 65000",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8500"),
        "d2": Decimal("0.9500"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.2500"),
    },
    {
        "ship_type": "TANKER",
        "condition_expr": "all",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8200"),
        "d2": Decimal("0.9300"),
        "d3": Decimal("1.0800"),
        "d4": Decimal("1.2800"),
    },
    {
        "ship_type": "CONTAINER_SHIP",
        "condition_expr": "all",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8300"),
        "d2": Decimal("0.9400"),
        "d3": Decimal("1.0700"),
        "d4": Decimal("1.1900"),
    },
    {
        "ship_type": "GENERAL_CARGO_SHIP",
        "condition_expr": "all",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8300"),
        "d2": Decimal("0.9400"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.1900"),
    },
    {
        "ship_type": "REFRIGERATED_CARGO_CARRIER",
        "condition_expr": "all",
        "capacity_basis": "DWT",
        "d1": Decimal("0.7800"),
        "d2": Decimal("0.9100"),
        "d3": Decimal("1.0700"),
        "d4": Decimal("1.2000"),
    },
    {
        "ship_type": "COMBINATION_CARRIER",
        "condition_expr": "all",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8700"),
        "d2": Decimal("0.9600"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.1400"),
    },
    {
        "ship_type": "LNG_CARRIER",
        "condition_expr": "DWT >= 100000",
        "capacity_basis": "DWT",
        "d1": Decimal("0.8900"),
        "d2": Decimal("0.9800"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.1300"),
    },
    {
        "ship_type": "LNG_CARRIER",
        "condition_expr": "DWT < 100000",
        "capacity_basis": "DWT",
        "d1": Decimal("0.7800"),
        "d2": Decimal("0.9200"),
        "d3": Decimal("1.1000"),
        "d4": Decimal("1.3700"),
    },
    {
        "ship_type": "RO_RO_CARGO_VEHICLE",
        "condition_expr": "all",
        "capacity_basis": "GT",
        "d1": Decimal("0.8600"),
        "d2": Decimal("0.9400"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.1600"),
    },
    {
        "ship_type": "RO_RO_CARGO",
        "condition_expr": "all",
        "capacity_basis": "GT",
        "d1": Decimal("0.7600"),
        "d2": Decimal("0.8900"),
        "d3": Decimal("1.0800"),
        "d4": Decimal("1.2700"),
    },
    {
        "ship_type": "RO_RO_PASSENGER",
        "condition_expr": "all",
        "capacity_basis": "GT",
        "d1": Decimal("0.7600"),
        "d2": Decimal("0.9200"),
        "d3": Decimal("1.1400"),
        "d4": Decimal("1.3000"),
    },
    {
        "ship_type": "CRUISE_PASSENGER",
        "condition_expr": "all",
        "capacity_basis": "GT",
        "d1": Decimal("0.8700"),
        "d2": Decimal("0.9500"),
        "d3": Decimal("1.0600"),
        "d4": Decimal("1.1600"),
    },
)


# bulk_insert/delete용 경량 테이블 선언. 실제 컬럼 정의는 `1c444a5c4819`가 소유한다.
# `id`는 종전 017·032에 없던 열이다 — CUBRID에는 기본값이 없어 명시해야 한다.
_fuel_type = sa.table(
    "fuel_type",
    sa.column("id", sa.String),
    sa.column("code", sa.String),
    sa.column("display_name", sa.String),
    sa.column("cf", sa.Numeric),
    sa.column("source_ref", sa.String),
    sa.column("version", sa.String),
    sa.column("content_hash", sa.String),
    sa.column("effective_from", sa.Date),
)

_regulation_year = sa.table(
    "regulation_year",
    sa.column("id", sa.String),
    sa.column("year", sa.Integer),
    sa.column("z_factor_percent", sa.Numeric),
    sa.column("effective_from", sa.Date),
    sa.column("source_ref", sa.String),
    sa.column("version", sa.String),
    sa.column("is_active", sa.SmallInteger),
)

_cii_reference_line = sa.table(
    "cii_reference_line",
    sa.column("id", sa.String),
    sa.column("ship_type", sa.String),
    sa.column("condition_expr", sa.String),
    sa.column("capacity_rule", sa.String),
    sa.column("a_raw", sa.String),
    sa.column("a_decimal", sa.Numeric),
    sa.column("c", sa.Numeric),
    sa.column("source_ref", sa.String),
)

_cii_rating_boundary = sa.table(
    "cii_rating_boundary",
    sa.column("id", sa.String),
    sa.column("ship_type", sa.String),
    sa.column("condition_expr", sa.String),
    sa.column("capacity_basis", sa.String),
    sa.column("d1", sa.Numeric),
    sa.column("d2", sa.Numeric),
    sa.column("d3", sa.Numeric),
    sa.column("d4", sa.Numeric),
    sa.column("source_ref", sa.String),
)


def _with_id(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """각 행에 `id`를 채운다.

    종전에는 `gen_random_uuid()` server_default가 했다. CUBRID에는 그 기본값이 없어
    **넣지 않으면 NOT NULL 위반**이다. 대리키라 값 자체에 의미는 없다.
    """
    return [{"id": uuid.uuid4().hex, **row} for row in rows]


def upgrade() -> None:
    """연료 CF 8행 + 규제 파라미터 42행 = 50행을 넣는다.

    `ci.yml`의 「규제 파라미터 적재 확인 (50행)」이 세는 그 50행이다.
    """
    op.bulk_insert(_fuel_type, _with_id(SEED_FUEL_TYPES))
    op.bulk_insert(
        _regulation_year,
        _with_id(
            [
                {
                    **row,
                    "source_ref": SOURCE_Z_FACTOR,
                    "version": PARAMETER_SET_VERSION,
                    "is_active": 1,
                }
                for row in SEED_Z_FACTORS
            ]
        ),
    )
    op.bulk_insert(
        _cii_reference_line,
        _with_id([{**row, "source_ref": SOURCE_REFERENCE_LINE} for row in SEED_REFERENCE_LINES]),
    )
    op.bulk_insert(
        _cii_rating_boundary,
        _with_id([{**row, "source_ref": SOURCE_RATING_BOUNDARY} for row in SEED_RATING_BOUNDARIES]),
    )


def downgrade() -> None:
    """이 마이그레이션이 넣은 50행만 지운다 (`DB_SCHEMA §8.1.1` 🔒).

    `fuel_type`은 `code`가, `regulation_year`는 `year`가, 나머지 둘은
    `(ship_type, condition_expr)`이 UNIQUE 키다. 그 키로 한정한다.
    참조 중인 행이 있으면 FK가 즉시 거부하며, 이는 정상 동작이다.
    """
    op.execute(
        _fuel_type.delete().where(_fuel_type.c.code.in_([row["code"] for row in SEED_FUEL_TYPES]))
    )
    op.execute(
        _regulation_year.delete().where(
            _regulation_year.c.year.in_([row["year"] for row in SEED_Z_FACTORS])
        )
    )
    for table, rows in (
        (_cii_reference_line, SEED_REFERENCE_LINES),
        (_cii_rating_boundary, SEED_RATING_BOUNDARIES),
    ):
        for row in rows:
            op.execute(
                table.delete().where(
                    sa.and_(
                        table.c.ship_type == row["ship_type"],
                        table.c.condition_expr == row["condition_expr"],
                    )
                )
            )
