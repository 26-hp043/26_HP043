"""규제 파라미터 seed를 data migration으로 승격

Revision ID: 032
Revises: 031
Create Date: 2026-08-15

이슈 #127 · ``alembic upgrade head`` 하나로 규제 파라미터 3종(42행)이 적재되게 해
배포 경로를 일원화한다. 이 마이그레이션이 들어가면 배포 절차에서 별도 seed 단계가
사라진다 — ``#240``이 「``up`` 한 번으로」를 미충족으로 남긴 이유가 해소된다.

이슈 본문의 제안과 다른 방향을 택했다
--------------------------------------
``#127``은 "``src/`` 상수를 그대로 wrapping"하고 "상수 기반 upsert"를 제안했다.
**둘 다 채택하지 않았다.** ``#127``이 017보다 먼저 작성됐고(본문이 "리비전 번호는
#115(016) 이후로 잡는다"고 적는다), 017(#83 · PR #147)이 그 두 가지를 명시적으로
기각하며 원칙을 세웠기 때문이다. ``#154``의 031도 같은 원칙을 따랐다.

**⑴ ``src/`` 상수를 import하지 않는다.** 마이그레이션은 과거 한 시점의 스냅샷이다.
``cii_platform.db.seed``의 상수를 import하면 규제 개정으로 그 상수가 바뀔 때 이
마이그레이션의 동작이 **소급 변경**되어, 새 환경의 ``upgrade head``가 "032 당시의
42행"이 아니라 "오늘의 42행"을 넣는다. 그러면 032 이후 마이그레이션의 전제가
무너진다.

**⑵ upsert를 쓰지 않는다.** Alembic은 각 마이그레이션을 한 번만 실행하는 모델이고,
upsert는 덮어쓴 원래 값을 모르므로 ``downgrade``를 정의할 수 없다 — ``DB_SCHEMA``
§8.1의 "모든 마이그레이션에 ``downgrade()`` 구현 필수"를 위반한다.

seed.py와의 역할 분담
---------------------
둘은 중복이 아니라 **서로 다른 시점을 담는다**. 017 주석이 규정한 관계 그대로다.

===========================  ===================================================
주체                          담는 것
===========================  ===================================================
이 마이그레이션 (032)          그날 넣은 값 · **불변** · 신규 환경 부트스트랩
``seed_all()`` (upsert)      지금 옳다고 보는 값 · **가변** · 규제 개정 시 재적재
===========================  ===================================================

규제 개정 시 둘이 갈라지는 것이 정상이다. ``seed.py``를 패키지 안에 두는 이유는
DB 없이 값 검증 테스트가 가능해야 하기 때문이며(5개 테스트 파일이 상수를 import
한다), 그 사정을 ``DB_SCHEMA`` §8.1에 기록했다.

아래 42행은 어디서 왔는가
-------------------------
값의 정본은 ``PRD`` §3.4.1(Z-factor 8행) · §3.4.3(reference line 20행) ·
§3.4.4(d-vector 14행)이며, ``seed.py``가 그것을 전사해 두었고
``tests/test_seed_data.py``가 정본과 대조한다. 이 파일의 42행은 **수기 전사가 아니라
그 상수에서 기계적으로 생성**했다 — ``AGENTS`` §2.3이 경계한 전사 오류
(``14479E10``/``14779E10``)를 사람 손이 닿는 구간에서 없애기 위해서다.

생성 후에도 ``tests/test_seed_migration.py``가 이 파일의 42행과 ``seed.py`` 상수를
매 실행 대조한다. 두 값이 갈라지면(규제 개정으로 상수만 바뀌는 정상 상황 포함)
테스트가 그 사실을 드러낸다.

``a_raw``와 ``a_decimal``을 둘 다 담는다 — ``seed.py`` 모듈 docstring이 밝힌 대로
``a_decimal``을 ``a_raw``에서 계산하지 않고 각각 독립 전사해야 검증이 성립한다.

downgrade
---------
넣은 키만 지운다. 전체 DELETE는 운영 중 추가된 행까지 지운다 — downgrade는 자기가
한 일만 되돌려야 한다(017·031과 같은 방침).

⚠️ 참조 중인 행이 있으면 DELETE가 FK에 걸려 실패한다. ``calculation_run``이
``regulation_year``를 참조하므로, 계산 이력이 쌓인 DB에서는 downgrade 전에 그
이력을 먼저 정리해야 한다.
"""

from datetime import date
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

# 출처(source_ref) — 권위 소스는 AGENTS.md §2.2 표를 따른다.
SOURCE_Z_FACTOR = "MEPC.400(83)"
SOURCE_REFERENCE_LINE = "MEPC.353(78)"
SOURCE_RATING_BOUNDARY = "MEPC.354(78)"

# 파라미터 세트 버전 (DB_SCHEMA §8.3).
PARAMETER_SET_VERSION = "1.0"


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


# bulk_insert/delete용 경량 테이블 선언. 실제 컬럼 정의는 001·002가 소유한다(017과 같은 방식).
_regulation_year = sa.table(
    "regulation_year",
    sa.column("year", sa.Integer),
    sa.column("z_factor_percent", sa.Numeric),
    sa.column("effective_from", sa.Date),
    sa.column("source_ref", sa.String),
    sa.column("version", sa.String),
    sa.column("is_active", sa.Boolean),
)

_cii_reference_line = sa.table(
    "cii_reference_line",
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
    sa.column("ship_type", sa.String),
    sa.column("condition_expr", sa.String),
    sa.column("capacity_basis", sa.String),
    sa.column("d1", sa.Numeric),
    sa.column("d2", sa.Numeric),
    sa.column("d3", sa.Numeric),
    sa.column("d4", sa.Numeric),
    sa.column("source_ref", sa.String),
)


def upgrade() -> None:
    """규제 파라미터 42행을 넣는다.

    ``op.bulk_insert()``는 executemany라 모든 dict의 키 집합이 완전히 동일해야 한다 —
    아래 컴프리헨션이 그것을 구조적으로 보장한다(017과 같은 방식).

    ``id``·``created_at``·``updated_at``은 INSERT 대상에서 빼고 001·002의
    server_default(``gen_random_uuid()`` · ``now()``)에 위임한다.
    """
    op.bulk_insert(
        _regulation_year,
        [
            {
                **row,
                "source_ref": SOURCE_Z_FACTOR,
                "version": PARAMETER_SET_VERSION,
                "is_active": True,
            }
            for row in SEED_Z_FACTORS
        ],
    )
    op.bulk_insert(
        _cii_reference_line,
        [{**row, "source_ref": SOURCE_REFERENCE_LINE} for row in SEED_REFERENCE_LINES],
    )
    op.bulk_insert(
        _cii_rating_boundary,
        [{**row, "source_ref": SOURCE_RATING_BOUNDARY} for row in SEED_RATING_BOUNDARIES],
    )


def downgrade() -> None:
    """이 마이그레이션이 넣은 42행만 지운다.

    전체 DELETE를 쓰지 않는 이유는 운영 중 추가된 행까지 지우기 때문이다 —
    downgrade는 자기가 한 일만 되돌려야 한다(017·031과 같은 방침).

    ``regulation_year``는 ``year``가, 나머지 둘은 ``(ship_type, condition_expr)``이
    UNIQUE 키다(``idx_refline_unique`` · ``idx_boundary_unique``). 그 키로 한정한다.
    """
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
                        table.c.ship_type == op.inline_literal(row["ship_type"]),
                        table.c.condition_expr == op.inline_literal(row["condition_expr"]),
                    )
                )
            )
