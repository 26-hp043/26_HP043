"""voyage_fuel_use ORM 모델.

DB_SCHEMA.md §2.3 (voyage_fuel_use) 참조. 컬럼·제약·인덱스 정의는 마이그레이션 006과
1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

[ORACLE-C4] voyage.status = COMPLETED 전환 시 최소 1개 actual_fuel_ton > 0 필요 제약은
DB가 아닌 애플리케이션 서비스 계층에서 검증한다(§2.3). 이 모델 범위 밖.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class VoyageFuelUse(Base):
    """항차 연료 사용량."""

    __tablename__ = "voyage_fuel_use"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    voyage_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    fuel_type = sa.Column(sa.String(length=30), nullable=False)
    planned_fuel_ton = sa.Column(sa.Numeric(precision=12, scale=4), nullable=True)
    actual_fuel_ton = sa.Column(sa.Numeric(precision=12, scale=4), nullable=True)
    cf_used = sa.Column(sa.Numeric(precision=10, scale=6), nullable=False)
    source = sa.Column(sa.String(length=30), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    # updated_at 자동 갱신은 DB 트리거(trg_voyage_fuel_use_updated, §7.2)가 담당한다.
    updated_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_voyage_fuel_use"),
        # §7.1 [C-3]: 연료 기록은 항차 종속 → 항차 삭제 시 CASCADE.
        sa.ForeignKeyConstraint(
            ["voyage_id"],
            ["voyage.id"],
            name="fk_voyage_fuel_use_voyage",
            ondelete="CASCADE",
        ),
        # [S-1] / §7.1: fuel_type → fuel_type(code), ON UPDATE CASCADE, ON DELETE NO ACTION.
        sa.ForeignKeyConstraint(
            ["fuel_type"],
            ["fuel_type.code"],
            name="fk_voyage_fuel_use_fuel_type",
            onupdate="CASCADE",
            ondelete="NO ACTION",
        ),
        # §2.3 검증 제약 (원문 그대로).
        sa.CheckConstraint(
            "source IN ('USER_INPUT','MODEL_ESTIMATE','IMPORT','SAMPLE')",
            name="chk_fuel_source",
        ),
        sa.CheckConstraint(
            "planned_fuel_ton IS NULL OR planned_fuel_ton > 0",
            name="chk_fuel_positive",
        ),
        sa.CheckConstraint(
            "actual_fuel_ton IS NULL OR actual_fuel_ton > 0",
            name="chk_actual_fuel_positive",
        ),
        # [S-2] 동일 항차+연료 타입 중복 방지 (중복 시 CO₂ 이중 산정 버그 방어).
        sa.Index("idx_fuel_use_unique", "voyage_id", "fuel_type", unique=True),
    )
