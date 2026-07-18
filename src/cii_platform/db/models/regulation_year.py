"""regulation_year ORM 모델.

DB_SCHEMA.md §2.8 (regulation_year — 규정 연도 Z-factor) 참조. 컬럼·제약 정의는
마이그레이션 004와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서
검증). FK가 없는 독립 테이블이며, updated_at 컬럼이 없다.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class RegulationYear(Base):
    """규정 연도 Z-factor."""

    __tablename__ = "regulation_year"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    year = sa.Column(sa.Integer(), nullable=False)
    z_factor_percent = sa.Column(sa.Numeric(precision=8, scale=4), nullable=False)
    effective_from = sa.Column(sa.Date(), nullable=False)
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    version = sa.Column(sa.String(length=50), nullable=False)
    is_active = sa.Column(sa.Boolean(), server_default=sa.text("true"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_regulation_year"),
        sa.UniqueConstraint("year", name="uq_regulation_year_year"),
    )
