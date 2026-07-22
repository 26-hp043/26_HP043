"""vessel ORM 모델.

DB_SCHEMA.md §2.1 (vessel) 참조. 컬럼·제약·인덱스 정의는 마이그레이션 003과 1:1로
일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class Vessel(Base):
    """선박."""

    __tablename__ = "vessel"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    imo_number = sa.Column(sa.String(length=7), nullable=False)
    name = sa.Column(sa.String(length=100), nullable=False)
    ship_type = sa.Column(sa.String(length=50), nullable=False)
    gross_tonnage = sa.Column(sa.Numeric(precision=12, scale=2), nullable=True)
    deadweight = sa.Column(sa.Numeric(precision=12, scale=2), nullable=True)
    default_fuel_type = sa.Column(sa.String(length=30), nullable=True)
    reference_speed_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    reference_daily_foc_ton = sa.Column(sa.Numeric(precision=8, scale=2), nullable=True)
    is_cii_applicable_hint = sa.Column(
        sa.Boolean(), server_default=sa.text("false"), nullable=False
    )
    is_deleted = sa.Column(sa.Boolean(), server_default=sa.text("false"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    # updated_at 자동 갱신은 DB 트리거(trg_vessel_updated, §7.2)가 담당한다.
    updated_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_vessel"),
        # [S-1] / §7.1: default_fuel_type → fuel_type(code), ON UPDATE CASCADE, ON DELETE NO ACTION.
        sa.ForeignKeyConstraint(
            ["default_fuel_type"],
            ["fuel_type.code"],
            name="fk_vessel_default_fuel_type",
            onupdate="CASCADE",
            ondelete="NO ACTION",
        ),
        # §2.1 검증 제약 (원문 그대로).
        sa.CheckConstraint(r"imo_number ~ '^\d{7}$'", name="chk_imo_format"),
        sa.CheckConstraint("gross_tonnage IS NULL OR gross_tonnage > 0", name="chk_gt_positive"),
        sa.CheckConstraint("deadweight IS NULL OR deadweight > 0", name="chk_dwt_positive"),
        sa.CheckConstraint(
            "reference_speed_kn IS NULL OR reference_speed_kn > 0", name="chk_speed_positive"
        ),
        # §2.1 인덱스 (모두 partial: WHERE is_deleted = false). soft delete 호환.
        sa.Index(
            "idx_vessel_imo",
            "imo_number",
            unique=True,
            postgresql_where=sa.text("is_deleted = false"),
        ),
        sa.Index(
            "idx_vessel_ship_type",
            "ship_type",
            postgresql_where=sa.text("is_deleted = false"),
        ),
        # pg_trgm GIN 인덱스 (001에서 extension 생성됨).
        sa.Index(
            "idx_vessel_name",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_where=sa.text("is_deleted = false"),
        ),
    )
