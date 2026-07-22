"""cii_rating_boundary ORM 모델.

DB_SCHEMA.md §2.11 (cii_rating_boundary) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 011과 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class CiiRatingBoundary(Base):
    """CII rating boundary (G4): 등급 경계선(d-vector)."""

    __tablename__ = "cii_rating_boundary"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    ship_type = sa.Column(sa.String(length=50), nullable=False)
    condition_expr = sa.Column(sa.String(length=200), nullable=False)
    capacity_basis = sa.Column(sa.String(length=10), nullable=False)
    d1 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    d2 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    d3 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    d4 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_cii_rating_boundary"),
        # §2.11 [M-3] (원문 그대로): d-vector 순서 보장.
        sa.CheckConstraint(
            "d1 < d2 AND d2 < d3 AND d3 < d4",
            name="chk_d_order",
        ),
        # §2.11 인덱스 (원문 그대로).
        sa.Index(
            "idx_boundary_unique",
            "ship_type",
            "condition_expr",
            unique=True,
        ),
    )
