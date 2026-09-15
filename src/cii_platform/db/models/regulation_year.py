"""regulation_year ORM 모델.

DB_SCHEMA.md §2.8 (regulation_year — 규정 연도 Z-factor) 참조. 컬럼·제약 정의는
마이그레이션 004와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서
검증). FK가 없는 독립 테이블이며, updated_at 컬럼이 없다.
"""

import uuid

from datetime import datetime, timezone

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class RegulationYear(Base):
    """규정 연도 Z-factor."""

    __tablename__ = "regulation_year"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    year = sa.Column(sa.Integer(), nullable=False)
    z_factor_percent = sa.Column(sa.Numeric(precision=8, scale=4), nullable=False)
    effective_from = sa.Column(sa.Date(), nullable=False)
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    version = sa.Column(sa.String(length=50), nullable=False)
    is_active = sa.Column(sa.Boolean(), default=True, server_default=sa.text("1"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_regulation_year"),
        sa.UniqueConstraint("year", name="uq_regulation_year_year"),
        # #96 (Oracle F5): Z-factor reduction은 음수일 수 없다 (MEPC.400(83) 0%~).
        sa.CheckConstraint("z_factor_percent >= 0", name="chk_z_factor_nonneg"),
    )
