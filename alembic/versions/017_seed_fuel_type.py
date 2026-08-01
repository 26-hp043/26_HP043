"""fuel_type CF 기본값 8행 seed

Revision ID: 017
Revises: 016
Create Date: 2026-07-29

DB_SCHEMA.md §3.2 (연료 CF 기본값)의 8행을 적재한다. 테이블·트리거는 002가 만들고
여기서는 행만 넣는다 — §8.1 "스키마 변경과 seed 데이터 분리" 원칙. 이슈 #83.

seed가 없으면 vessel.default_fuel_type · voyage_fuel_use.fuel_type이 참조할 대상이
없어 프로덕션에서 연료 기록을 한 건도 INSERT할 수 없다(FK 위반).

**이 저장소 최초의 data migration이다.** 001~016은 전부 스키마 전용이므로 아래 패턴이
후속 seed 이슈(#127 · #34)의 선례가 된다.

주의:

- **8행 값은 이 파일에 인라인으로 고정한다. src/ 상수를 import하지 않는다.**
  마이그레이션은 과거 한 시점의 스냅샷이다. ``cii_platform.db.seed``의 상수를
  import하면 규제 개정으로 그 상수가 바뀔 때 017의 동작이 소급 변경되어, 새 환경의
  ``upgrade head``가 "017 당시의 8행"이 아니라 "오늘의 8행"을 넣게 되고 017 이후
  마이그레이션의 전제가 무너진다. seed.py 상수(지금 옳다고 보는 값 · 가변)와 017의
  8행(그날 넣은 값 · 불변)은 규제 개정 시 갈라지는 것이 정상이다.
- **upsert(ON CONFLICT DO UPDATE)를 쓰지 않는다.** Alembic은 각 마이그레이션을 한 번만
  실행하는 모델이고, upsert는 덮어쓴 원래 값을 모르므로 downgrade를 정의할 수 없다.
  §8.1의 "모든 마이그레이션에 downgrade() 구현 필수"를 위반하게 된다.
- **downgrade는 아래 8개 code만 지운다.** 전체 DELETE는 런타임에 생성되는 OTHER 연료
  행(§2.9 effective_from 설명)까지 지워버린다.
- 참조 중인 행이 있으면 downgrade의 DELETE가 실패한다. vessel.default_fuel_type
  (fk_vessel_default_fuel_type, 003) 또는 voyage_fuel_use.fuel_type
  (fk_voyage_fuel_use_fuel_type, 006) 중 하나라도 걸리면 막힌다. 둘 다 §7.1 정본대로
  ON DELETE NO ACTION이며(#80), DEFERRABLE 선언이 없어 DELETE 문 시점에 즉시 검사된다.
  **이는 데이터 보호가 정상 작동한 것이다** — 트랜잭션이 통째로 롤백되어 리비전은
  017에 머무르고 8행도 온전히 남는다.
- OTHER 연료(PRD §3.4.2)는 seed하지 않는다. CF가 "사용자 입력"인데 fuel_type.cf는
  NOT NULL이고, §2.9가 effective_from을 "(OTHER 연료용)"으로 정의하여 정본도 OTHER를
  런타임 생성 행으로 전제한다. code에 CHECK·enum이 없어 OTHER 기능 자체는 막히지 않는다.
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: str | Sequence[str] | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# source_ref에는 **값이 인쇄된 문서**를 적는다 (DB_SCHEMA §3.2 각주 · AGENTS.md §2.2).
# CF 값표는 EEDI 산정 지침 MEPC.364(79) §2.2.1(Annex 9)에 인쇄되어 있다. CII G1
# (MEPC.352(78)) §4.1은 CF를 이 계열에 참조 지정할 뿐 표 자체가 없다.
# 종전 표기 MEPC.352(78)은 PR #140(#87)에서 정정됐고 팀원 원문 대조로 확인됐다(PR #145).
# 이슈 #83 본문의 "MEPC.352(78) G1 기준"은 그 정정 이전 표기다.
SOURCE_REF = "MEPC.364(79)"

# 파라미터 세트 버전 (DB_SCHEMA §8.3). 002의 server_default '1.0'과 같은 값을 명시 삽입한다.
# seed.py의 PARAMETER_SET_VERSION을 import하지 않는 이유는 모듈 docstring 참조.
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
#
# - content_hash: NULL로 둔다. "무엇을 해싱하는가"(행 단위 vs 8행 집합, canonical JSON
#   규칙)가 정본에 없고 그 규칙을 정하는 것은 #42다. 규칙을 임의 선점하면 AGENTS.md §3
#   위반이므로, #42 확정 후 별도 마이그레이션에서 채운다. 누락이 아니다.
# - effective_from: NULL로 둔다. 8종 CF는 연도 스코프가 없는 상시 적용값이다
#   (연도 스코프를 갖는 regulation_year와 다르다). §2.9는 이 컬럼을 OTHER 연료용으로 정의한다.
# - unit · is_active · id · created_at · updated_at은 INSERT 대상에서 빼고 002의
#   server_default('tCO₂/tFuel' · true · gen_random_uuid() · now())에 위임한다.
#   §3.2 표에 unit 열 자체가 없다.
SEED_FUEL_TYPES: list[dict[str, object]] = [
    {
        "code": code,
        "display_name": display_name,
        "cf": Decimal(cf),
        "source_ref": SOURCE_REF,
        "version": PARAMETER_SET_VERSION,
        "content_hash": None,
        "effective_from": None,
    }
    for code, display_name, cf in _CF_ROWS
]

# bulk_insert/delete용 경량 테이블 선언. 실제 컬럼 정의는 002가 소유한다.
_fuel_type = sa.table(
    "fuel_type",
    sa.column("code", sa.String),
    sa.column("display_name", sa.String),
    sa.column("cf", sa.Numeric),
    sa.column("source_ref", sa.String),
    sa.column("version", sa.String),
    sa.column("content_hash", sa.String),
    sa.column("effective_from", sa.Date),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(_fuel_type, SEED_FUEL_TYPES)


def downgrade() -> None:
    """Downgrade schema."""
    # 8개 code만 지운다(위 docstring 참조). 참조 중인 행이 있으면 NO ACTION FK가
    # 즉시 거부하며, 이는 정상 동작이다.
    codes = [row["code"] for row in SEED_FUEL_TYPES]
    op.execute(_fuel_type.delete().where(_fuel_type.c.code.in_(codes)))
