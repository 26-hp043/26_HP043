"""not_underway_fuel_use ORM 모델.

DB_SCHEMA.md §2.18 (not_underway_fuel_use) 참조. 컬럼·제약·인덱스 정의는 마이그레이션
025와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

이슈 #345: not under way 구간의 소비자별 연료 기록. ``consumer_type`` 4값은
MEPC.385(81)이 MARPOL Annex VI Appendix IX에 추가한 DCS 보고 항목 그대로다
(적용 시작 데이터연도 2026 — 본 프로젝트 기준연도와 일치).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class NotUnderwayFuelUse(Base):
    """not under way 구간 연료 사용량."""

    __tablename__ = "not_underway_fuel_use"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    period_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    consumer_type = sa.Column(sa.String(length=20), nullable=False)
    fuel_type = sa.Column(sa.String(length=30), nullable=False)
    fuel_ton = sa.Column(sa.Numeric(precision=12, scale=2), nullable=False)
    # 030 (#378) — 계산 시점 CF snapshot. voyage_fuel_use.cf_used와 같은 역할이며
    # PRD §8.4 「CF 변경 시 과거 계산은 snapshot 보존」이 두 연료 갈래 모두에
    # 적용되게 한다. NULL을 허용하면 집계마다 snapshot 유무 분기가 생기고,
    # 그 분기가 곧 이 이슈가 없앤 이중 경로다.
    cf_used = sa.Column(sa.Numeric(precision=10, scale=6), nullable=False)

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_not_underway_fuel_use"),
        # 부모-자식: 구간 삭제 시 연료 기록도 함께 삭제(voyage_fuel_use 패턴).
        sa.ForeignKeyConstraint(
            ["period_id"],
            ["not_underway_period.id"],
            name="fk_not_underway_fuel_use_period",
            ondelete="CASCADE",
        ),
        # [S-1] / §7.1: fuel_type → fuel_type(code), ON UPDATE CASCADE, ON DELETE NO ACTION.
        sa.ForeignKeyConstraint(
            ["fuel_type"],
            ["fuel_type.code"],
            name="fk_not_underway_fuel_use_fuel_type",
            onupdate="CASCADE",
            ondelete="NO ACTION",
        ),
        # MEPC.385(81) Appendix IX DCS 보고 항목 4값 (데이터연도 2026~).
        sa.CheckConstraint(
            "consumer_type IN ('MAIN_ENGINE','AUX_ENGINE','OIL_FIRED_BOILER','OTHER')",
            name="chk_not_underway_consumer_type",
        ),
        sa.CheckConstraint("fuel_ton > 0", name="chk_not_underway_fuel_positive"),
        # 030 (#378) — CF는 물리적으로 항상 양수다(#96 chk_cf_positive 선례).
        sa.CheckConstraint("cf_used > 0", name="chk_nufu_cf_used_positive"),
        # 029 (#376) — 구간+소비원+연료 중복 방지. 중복 시 #353 YTD 집계가 CO₂를
        # 이중 산정해 등급이 실제보다 나쁘게 나온다(§2.3 [S-2]와 같은 사안).
        # 선행열이 period_id라 FK 자식 조회(CASCADE·조인) 경로도 이 인덱스가 처리한다
        # — 025의 단일열 idx_not_underway_fuel_use_period는 그래서 제거했다.
        sa.Index(
            "idx_not_underway_fuel_use_unique",
            "period_id",
            "consumer_type",
            "fuel_type",
            unique=True,
        ),
    )
