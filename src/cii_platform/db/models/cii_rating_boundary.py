"""cii_rating_boundary ORM 모델.

DB_SCHEMA.md §2.11 (cii_rating_boundary) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 011과 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class CiiRatingBoundary(Base):
    """CII rating boundary (G4): 등급 경계선(d-vector)."""

    __tablename__ = "cii_rating_boundary"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    ship_type = sa.Column(sa.String(length=50), nullable=False)
    condition_expr = sa.Column(sa.String(length=200), nullable=False)
    capacity_basis = sa.Column(sa.String(length=10), nullable=False)
    d1 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    d2 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    d3 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    d4 = sa.Column(sa.Numeric(precision=6, scale=4), nullable=False)
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    # 개정 적재 경로(#673 · 054) — `cii_reference_line`과 같은 이유로 추가됐다.
    version = sa.Column(
        sa.String(length=50),
        server_default=sa.text("'1.0'"),
        nullable=False,
    )
    is_active = sa.Column(sa.Boolean(), default=True, server_default=sa.text("1"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_cii_rating_boundary"),
        # §2.11 [M-3] (원문 그대로): d-vector 순서 보장.
        sa.CheckConstraint(
            "d1 < d2 AND d2 < d3 AND d3 < d4",
            name="chk_d_order",
        ),
        # 🔴 `idx_boundary_unique`(전역 유니크)는 `054`가 뺐다 — 개정 이행 행이 같은
        # 키로 쌓여야 하므로(`DB_SCHEMA §7.2`). 유일성은 **활성 행끼리만**
        # `trg_cii_rating_boundary_active_unique_*`가 집행한다.
    )
