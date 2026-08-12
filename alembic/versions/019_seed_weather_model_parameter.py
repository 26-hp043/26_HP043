"""Townsin-Kwon 기상 모델 파라미터 seed (#35)

Revision ID: 019
Revises: 018
Create Date: 2026-08-12

이슈 #35. ``weather_model_parameter`` 테이블(012 생성)에 ``TOWNSIN_KWON_ALPHA``
모델의 선종별 CU 계수를 넣는다. **017(fuel_type)·018(demo vessel)이 세운 data
migration 패턴을 그대로 따른다** — DB_SCHEMA.md §8.1 "스키마 변경과 seed 데이터 분리".

왜 지금 필요한가
----------------

TECH_SPEC §3.5 ``calculate_weather_factor``가 선종별 CU 계수를 DB에서 읽어야 하는데,
012 마이그레이션은 테이블만 만들고 행은 안 넣었다(012 docstring "Townsin-Kwon
파라미터 seed 값은 #35가 넣는다"). 이 마이그레이션이 그 값을 채운다.

주의
----

- **값은 TECH_SPEC §3.3 표에서 직접 복사했다** (AGENTS §2.1 정본 대조). ``CU = a×BN + b``
  선형 형태로 일반화해 ``cu_a.<ship_type>``·``cu_b.<ship_type>`` 키에 담는다.
  §3.3이 "Kwon (2008)을 참고한 **자체 단순화 계수 (실험 모델)**"이라고 명시하므로
  ``source_ref``는 TECH_SPEC §3.3 자체를 가리킨다.

- **upsert를 쓰지 않는다** (017·018과 같은 이유). Alembic은 각 마이그레이션을 한 번만
  실행하므로 원래 값을 알 필요가 없고, 덮어쓰면 downgrade를 정의할 수 없다.

- **downgrade는 10개 (model_version, key) 조합만 지운다.** 전체 ``DELETE``는 후속
  이슈에서 추가될 수 있는 다른 ``TOWNSIN_KWON_ALPHA`` 파라미터(예: BN-Hs 변환 계수)까지
  지워버린다. UNIQUE (model_version, key) 인덱스(DB_SCHEMA §2.12 [S-5])가 삭제 대상
  식별에 쓰인다.

- **5개 선종만 담는다.** TECH_SPEC §3.3이 명시하는 5종(Bulk·Tanker·Container·General
  cargo·LNG)이다. Gas carrier·Refrigerated cargo 등 다른 선종에 대한 CU 계수는
  원문(§3.3)에 없으므로 임의로 만들지 않는다 (AGENTS §2.1).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str | Sequence[str] | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: TECH_SPEC §3.3 — Kwon (2008) 단순화 기반 선종별 CU 계수.
#:
#: ``CU = a × BN + b`` 선형 형태. ``a``가 기울기, ``b``가 절편. §3.3 표 원문:
#:
#: - Bulk carrier:     ``CU = 0.5 × BN + 0.5`` → a=0.5, b=0.5
#: - Tanker:           ``CU = 0.7 × BN``       → a=0.7, b=0
#: - Container ship:   ``CU = 0.6 × BN + 0.2`` → a=0.6, b=0.2
#: - General cargo:    ``CU = 0.5 × BN + 0.5`` → a=0.5, b=0.5
#: - LNG carrier:      ``CU = 0.7 × BN``       → a=0.7, b=0
#:
#: §3.3 주석이 "실험 모델"이라고 명시하므로, ``source_ref``는 규제 문서가 아니라
#: 값을 인쇄하고 있는 TECH_SPEC §3.3 자체다 (DB_SCHEMA §2.12 source_ref 정의).
_TOWNSIN_KWON_ALPHA = "TOWNSIN_KWON_ALPHA"
_TECH_SPEC_REF = "TECH_SPEC §3.3 (Kwon 2008 단순화)"
_UNIT_DIMENSIONLESS = "dimensionless"

#: ``op.bulk_insert``는 executemany라 모든 dict의 키 집합이 같아야 한다.
SEED_WEATHER_PARAMS: list[dict[str, object]] = [
    # Bulk carrier — TECH_SPEC §3.3: CU = 0.5 × BN + 0.5
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_a.BULK_CARRIER",
        "value": "0.5",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_b.BULK_CARRIER",
        "value": "0.5",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    # Tanker — TECH_SPEC §3.3: CU = 0.7 × BN
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_a.TANKER",
        "value": "0.7",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_b.TANKER",
        "value": "0",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    # Container ship — TECH_SPEC §3.3: CU = 0.6 × BN + 0.2
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_a.CONTAINER_SHIP",
        "value": "0.6",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_b.CONTAINER_SHIP",
        "value": "0.2",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    # General cargo — TECH_SPEC §3.3: CU = 0.5 × BN + 0.5
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_a.GENERAL_CARGO_SHIP",
        "value": "0.5",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_b.GENERAL_CARGO_SHIP",
        "value": "0.5",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    # LNG carrier — TECH_SPEC §3.3: CU = 0.7 × BN
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_a.LNG_CARRIER",
        "value": "0.7",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
    {
        "model_version": _TOWNSIN_KWON_ALPHA,
        "key": "cu_b.LNG_CARRIER",
        "value": "0",
        "unit": _UNIT_DIMENSIONLESS,
        "source_ref": _TECH_SPEC_REF,
    },
]

# bulk_insert/delete용 경량 테이블 선언. 실제 컬럼 정의는 012가 소유한다.
# ``id``·``created_at``은 012의 server_default(gen_random_uuid()·now())에 위임한다.
_weather_model_parameter = sa.table(
    "weather_model_parameter",
    sa.column("model_version", sa.String),
    sa.column("key", sa.String),
    sa.column("value", sa.String),
    sa.column("unit", sa.String),
    sa.column("source_ref", sa.String),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(_weather_model_parameter, SEED_WEATHER_PARAMS)


def downgrade() -> None:
    """Downgrade schema."""
    # 10개 (model_version, key) 조합만 지운다(모듈 docstring 참조).
    keys = [row["key"] for row in SEED_WEATHER_PARAMS]
    op.execute(
        _weather_model_parameter.delete().where(
            _weather_model_parameter.c.model_version == _TOWNSIN_KWON_ALPHA,
            _weather_model_parameter.c.key.in_(keys),
        )
    )
