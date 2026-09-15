"""fuel_type ORM 모델.

DB_SCHEMA.md §2.9 (fuel_type) 참조. 컬럼·제약 정의는 마이그레이션 002와 1:1로
일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid

from datetime import datetime, timezone

import sqlalchemy as sa

from cii_platform.db.models.base import Base


class FuelType(Base):
    """연료 종류 및 CF(CO₂ 환산계수) 마스터."""

    __tablename__ = "fuel_type"

    id = sa.Column(
        sa.Uuid,
        primary_key=True,
        default=uuid.uuid4,
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
    is_active = sa.Column(sa.Boolean(), default=True, server_default=sa.text("1"), nullable=False)
    effective_from = sa.Column(sa.Date(), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )
    # updated_at 자동 갱신은 DB 트리거(trg_fuel_type_updated, §7.2)가 담당한다.
    updated_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_fuel_type"),
        sa.UniqueConstraint("code", name="uq_fuel_type_code"),
        # #96 (Oracle F5): cf는 물리적으로 항상 양수 — 음수면 배출량이 음수가 된다.
        sa.CheckConstraint("cf > 0", name="chk_cf_positive"),
    )
