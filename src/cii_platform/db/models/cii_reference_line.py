"""cii_reference_line ORM 모델.

DB_SCHEMA.md §2.10 (cii_reference_line) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 010과 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid

from datetime import datetime, timezone

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class CiiReferenceLine(Base):
    """CII reference line (G2): 선종별 조건에 따른 기준선."""

    __tablename__ = "cii_reference_line"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    ship_type = sa.Column(sa.String(length=50), nullable=False)
    condition_expr = sa.Column(sa.String(length=200), nullable=False)
    capacity_rule = sa.Column(sa.String(length=50), nullable=False)
    # TECH_SPEC §9: a_raw(IMO 원문 표기) + a_decimal(변환값) 이중 저장.
    a_raw = sa.Column(sa.String(length=50), nullable=False)
    a_decimal = sa.Column(sa.Numeric(precision=30, scale=6), nullable=False)
    c = sa.Column(sa.Numeric(precision=10, scale=6), nullable=False)
    source_ref = sa.Column(sa.String(length=200), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_cii_reference_line"),
        # capacity_rule 형식 검증은 앱 레벨에서 수행 — CUBRID는 regex CHECK 미지원 (#1058).
        sa.CheckConstraint(
            "capacity_rule IN ('DWT','GT') OR capacity_rule LIKE 'fixed %'",
            name="chk_capacity_rule",
        ),
        sa.CheckConstraint("a_decimal > 0", name="chk_a_decimal_positive"),
        # c >= 0: LNG_CARRIER DWT >= 100000은 c = 0.000000이 정상([Oracle 관찰]).
        sa.CheckConstraint("c >= 0", name="chk_c_positive"),
        # §2.10 인덱스 (원문 그대로).
        sa.Index(
            "idx_refline_unique",
            "ship_type",
            "condition_expr",
            unique=True,
        ),
        sa.Index("idx_refline_ship_type", "ship_type"),
    )
