"""데모용 샘플 선박 3척 seed

Revision ID: 018
Revises: 017
Create Date: 2026-08-07

이슈 #34. 프론트엔드가 참조하는 데모 선박을 DB에 넣는다. 테이블·트리거는 003이 만들고
여기서는 행만 넣는다 — DB_SCHEMA.md §8.1 "스키마 변경과 seed 데이터 분리" 원칙.

**017(fuel_type CF seed)이 세운 data migration 패턴을 그대로 따른다.** 017 docstring이
자신을 "후속 seed 이슈(#127 · #34)의 선례"로 명시했다.

왜 지금 필요한가
----------------

프론트엔드 demo provider가 쓰는 ``vessel_id``가 **고정표(referenceTable.ts)에만 있고
DB에는 없었다.** 실 API(#55 · #51)로 전환하는 순간 첫 요청이 "그런 선박 없음"으로
떨어진다. 이 마이그레이션이 그 간극을 메운다.

주의
----

- **UUID를 명시적으로 박는다.** ``vessel.id``의 server_default는 ``gen_random_uuid()``라
  그대로 두면 환경마다 값이 달라진다. #132 계약이 1번 선박에
  ``00000000-0000-4000-8000-000000000001``을 지정했고 프론트엔드 고정표(#134)와
  입력 폼(#135)이 그 값을 참조하므로, **DB가 같은 UUID를 가져야 계약이 성립한다.**
  세 값 모두 UUID v4 형식을 만족한다(version nibble ``4``, variant nibble ``8``).

- **1번 선박의 IMO 번호는 합성값이다.** 50,000 DWT 벌크선은 실존 선박이 아니라
  ``PRD §13.1`` Fixture 1이 정의한 검산용 제원이다. IMO가 실제로 발급하지 않는 대역
  (0으로 시작)을 써서 ``chk_imo_format``(7자리 숫자)은 만족하되 **실선과 충돌할 수
  없게** 한다. **``#525``가 이 값을 ``0000012``로 바꿨다** — 대역은 유지하며 IMO
  체크섬도 만족하는 값이다. 이 리비전은 ``#451``로 무동작이 됐으므로 여기 적힌 값은
  기록일 뿐이고, 실제 적재는 ``db/demo_seed.py``가 한다.
  2·3번은 제원 조사로 받은 **실제 IMO 번호**다(공개 데이터).

- **``default_fuel_type``을 NULL로 둔다.** 연료 종류는 화면에서 사용자가 고르는 것으로
  확정됐다(2026-08-07 결정). 부수 효과로 **017의 downgrade가 막히지 않는다** —
  값을 넣으면 ``fk_vessel_default_fuel_type``이 걸려 CF 8행을 지울 수 없게 된다
  (PR #147 검증 3a).

- **``gross_tonnage``가 없는 두 척은 ``is_cii_applicable_hint``를 false로 둔다.**
  이 컬럼은 ``GT >= 5000`` 기준으로 산정하는데(PRD §7 · DB_SCHEMA §2.1) GT를 모르면
  판정할 수 없다. **"적용 대상이 아닐 수 있음"이 보수적인 방향**이므로 false다.
  GT 회신이 오면 별도 마이그레이션에서 갱신한다.

- **upsert를 쓰지 않는다.** Alembic은 각 마이그레이션을 한 번만 실행하는 모델이고,
  upsert는 덮어쓴 원래 값을 모르므로 downgrade를 정의할 수 없다(017과 같은 이유).

- **downgrade는 아래 3개 id만 지운다.** 전체 DELETE는 사용자가 등록한 선박까지
  지워버린다. 계산 이력(``calculation_run.vessel_id``)이 걸려 있으면 실패할 수 있으나
  그 컬럼에는 FK가 없어(003) 실제로는 막히지 않는다 — **고아 이력이 남을 수 있음을
  감수하는 것이 아니라, 데모 데이터를 지우는 상황 자체가 개발 중 롤백에 한정된다.**

- **GT 축 선박이 빠져 있다.** #34 본문은 3번 선박을 ``CRUISE_PASSENGER``(GT 축)로
  지정했으나 제원을 확보하지 못했다. GT 축은 후속 이슈에서 넣는다. 이 마이그레이션의
  3척은 **전부 DWT 축**이다.

2026-08-17 — 이 마이그레이션은 **더 이상 데이터를 넣지 않는다** (#451)
-------------------------------------------------------------------

데모 데이터는 ``cii_platform.db.demo_seed``로 옮겼다. 실행은
``python -m cii_platform.db.demo_seed``다.

**왜 옮겼는가.** 데모 선박으로 계산을 한 번 돌리면 ``calculation_run``이 그 선박을
참조하고, ``fk_calculation_run_vessel``(023 신설, ``RESTRICT``)이 아래 downgrade의
DELETE를 막았다. 이 파일은 원래 *"그 컬럼에는 FK가 없어(003) 실제로는 막히지 않는다"* 고
적어 두었는데, **그 전제가 023에서 깨졌다.**

세 안 중 「seed에서 분리」를 골랐다 — 마이그레이션이 사용자 계산 이력을 지우는 선례를
만들지 않고, 롤백이 절반만 되는 상태도 만들지 않는다. `DB_SCHEMA §8.1`의 「스키마 변경과
seed 데이터 분리」 원칙 그대로다.

**리비전은 그대로 둔다.** 이미 적용된 환경의 체인을 바꾸면 안 되고, 그 환경에 들어가 있는
행은 그대로 유효하다. 새 환경은 위 명령으로 넣는다.
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str | Sequence[str] | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 프론트엔드가 참조하는 고정 UUID (#132 계약 · #134 referenceTable.ts · #135 입력 폼).
# 값을 바꾸면 프론트엔드 고정표를 함께 고쳐야 한다.
VESSEL_ID_BULK = "00000000-0000-4000-8000-000000000001"
VESSEL_ID_CONTAINER = "00000000-0000-4000-8000-000000000002"
VESSEL_ID_GENERAL_CARGO = "00000000-0000-4000-8000-000000000003"

#: 1번 선박의 합성 IMO 번호. 모듈 docstring 「IMO 번호는 합성값이다」 참조.
SYNTHETIC_IMO_BULK = "0000001"

# 3척. 값의 출처를 행마다 주석으로 남긴다.
#
# op.bulk_insert()는 executemany라 모든 dict의 키 집합이 완전히 동일해야 한다.
# 아래 리터럴은 NULL인 컬럼도 키를 채워 그것을 보장한다.
#
# INSERT 대상에서 뺀 컬럼과 위임 대상(003의 server_default):
#   is_deleted → false · created_at → now() · updated_at → now()
SEED_VESSELS: list[dict[str, object]] = [
    {
        # PRD §13.1 Fixture 1 — Bulk carrier 50,000 DWT. 실존 선박이 아니다.
        # name에 제원을 함께 적는 이유: 이 배는 실선명이 없고 "무엇을 위한 배인가"가
        # 곧 이름이다. 프론트엔드 고정표가 쓰던 표시 문자열과 같아 전환 시 화면이
        # 바뀌지 않는다. 2·3번은 실선이라 실제 선박명만 넣는다.
        "id": VESSEL_ID_BULK,
        "imo_number": SYNTHETIC_IMO_BULK,
        "name": "샘플 벌크선 (50,000 DWT)",
        "ship_type": "BULK_CARRIER",
        # tests/fixtures/cii/bulk_50000_hfo_2026.json 의 input.gross_tonnage 와 같다.
        # 정본 픽스처가 이 배의 제원을 이미 정의하고 있으므로 새로 만들지 않는다.
        "gross_tonnage": Decimal("30000.00"),
        "deadweight": Decimal("50000.00"),
        "default_fuel_type": None,
        "reference_speed_kn": None,
        "reference_daily_foc_ton": None,
        # GT 30,000 >= 5,000 → 공식 CII 적용 대상.
        "is_cii_applicable_hint": True,
    },
    {
        # 제원 조사 회신 2026-08-07. 출처 namsung.co.kr (남성해운).
        "id": VESSEL_ID_CONTAINER,
        "imo_number": "9448839",
        "name": "STAR SKIPPER",
        "ship_type": "CONTAINER_SHIP",
        # GT 미회신. 모듈 docstring 「is_cii_applicable_hint」 항 참조.
        "gross_tonnage": None,
        "deadweight": Decimal("9520.00"),
        "default_fuel_type": None,
        "reference_speed_kn": Decimal("16.50"),
        "reference_daily_foc_ton": None,
        "is_cii_applicable_hint": False,
    },
    {
        # 제원 조사 회신 2026-08-07. 출처 djship.co.kr (동진상선).
        "id": VESSEL_ID_GENERAL_CARGO,
        "imo_number": "9633862",
        "name": "DONGJIN ENDURANCE",
        "ship_type": "GENERAL_CARGO_SHIP",
        "gross_tonnage": None,
        "deadweight": Decimal("6405.77"),
        "default_fuel_type": None,
        # 회신 원문은 "12,8 KNOT"이며 소수점 구분자가 쉼표로 적힌 것이다.
        "reference_speed_kn": Decimal("12.80"),
        "reference_daily_foc_ton": None,
        "is_cii_applicable_hint": False,
    },
]

# bulk_insert/delete용 경량 테이블 선언. 실제 컬럼 정의는 003이 소유한다.
#
# ⚠️ ``id``의 타입을 ``String``으로 두면 안 된다. 실제 컬럼은 ``uuid``이고
# asyncpg는 서버 타입과 파라미터 타입이 다르면 캐스팅하지 않고 거부한다 —
# ``DatatypeMismatchError: column "id" is of type uuid but expression is of type
# character varying``. 문자열로 값을 적더라도 **선언은 실제 타입을 따라야** 한다.
_vessel = sa.table(
    "vessel",
    sa.column("id", postgresql.UUID(as_uuid=False)),
    sa.column("imo_number", sa.String),
    sa.column("name", sa.String),
    sa.column("ship_type", sa.String),
    sa.column("gross_tonnage", sa.Numeric),
    sa.column("deadweight", sa.Numeric),
    sa.column("default_fuel_type", sa.String),
    sa.column("reference_speed_kn", sa.Numeric),
    sa.column("reference_daily_foc_ton", sa.Numeric),
    sa.column("is_cii_applicable_hint", sa.Boolean),
)


def upgrade() -> None:
    """무동작 — 데모 데이터는 ``cii_platform.db.demo_seed``가 넣는다 (#451).

    아래 상수는 **이 리비전이 그날 넣었던 값의 기록**으로 남긴다. 지우면 과거 환경에
    무엇이 들어갔는지 알 수 없게 된다.
    """


def downgrade() -> None:
    """무동작 — 이 리비전이 넣은 것이 없으므로 지울 것도 없다 (#451).

    종전에는 여기서 데모 선박을 DELETE했고, 그 선박을 참조하는 계산 이력이 있으면
    **``fk_calculation_run_vessel``에 막혀 롤백 전체가 실패**했다.
    """
