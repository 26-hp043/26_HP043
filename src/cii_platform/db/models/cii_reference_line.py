"""cii_reference_line ORM 모델.

DB_SCHEMA.md §2.10 (cii_reference_line) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 010과 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class CiiReferenceLine(Base):
    """CII reference line (G2): 선종별 조건에 따른 기준선."""

    __tablename__ = "cii_reference_line"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
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
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_cii_reference_line"),
        # §2.10 [M-7] (원문 그대로): 'fixed' 뒤에 숫자만 허용.
        sa.CheckConstraint(
            r"capacity_rule IN ('DWT','GT') OR capacity_rule ~ '^fixed \d+$'",
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
