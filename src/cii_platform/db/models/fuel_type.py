"""fuel_type ORM 모델.

DB_SCHEMA.md §2.9 (fuel_type) 참조. 컬럼·제약 정의는 마이그레이션 002와 1:1로
일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class FuelType(Base):
    """연료 종류 및 CF(CO₂ 환산계수) 마스터."""

    __tablename__ = "fuel_type"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    code = sa.Column(sa.String(length=30), nullable=False)
    display_name = sa.Column(sa.String(length=100), nullable=False)
    cf = sa.Column(sa.Numeric(precision=10, scale=6), nullable=False)
    unit = sa.Column(
        sa.String(length=30),
        server_default=sa.text("'tCO₂/tFuel'"),
        nullable=False,
    )
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    # [X-3] version / content_hash: 파라미터 세트 변경 추적용.
    version = sa.Column(
        sa.String(length=50),
        server_default=sa.text("'1.0'"),
        nullable=False,
    )
    content_hash = sa.Column(sa.String(length=71), nullable=True)
    is_active = sa.Column(sa.Boolean(), server_default=sa.text("true"), nullable=False)
    effective_from = sa.Column(sa.Date(), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    # updated_at 자동 갱신은 DB 트리거(trg_fuel_type_updated, §7.2)가 담당한다.
    updated_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_fuel_type"),
        sa.UniqueConstraint("code", name="uq_fuel_type_code"),
    )
