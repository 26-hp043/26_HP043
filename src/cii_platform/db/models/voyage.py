"""voyage ORM 모델.

DB_SCHEMA.md §2.2 (voyage) 참조. 컬럼·제약·인덱스 정의는 마이그레이션 005와 1:1로
일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

- status는 CANCELLED 포함 7개 값.
- annual_inclusion_policy는 EXCLUDE / INCLUDE_AS_PLAN / INCLUDE_AS_ACTUAL.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class Voyage(Base):
    """항차."""

    __tablename__ = "voyage"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    vessel_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    voyage_no = sa.Column(sa.String(length=100), nullable=True)
    status = sa.Column(sa.String(length=20), nullable=False)
    # [C-1] annual_inclusion_policy ≠ EXCLUDE인 경우 NOT NULL 필수 (chk_year_policy).
    regulation_year = sa.Column(sa.Integer(), nullable=True)
    departure_port_name = sa.Column(sa.String(length=200), nullable=False)
    departure_lat = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    departure_lon = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    arrival_port_name = sa.Column(sa.String(length=200), nullable=False)
    arrival_lat = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    arrival_lon = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    planned_distance_nm = sa.Column(sa.Numeric(precision=12, scale=2), nullable=False)
    actual_distance_nm = sa.Column(sa.Numeric(precision=12, scale=2), nullable=True)
    planned_speed_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=False)
    actual_avg_speed_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    planned_departure_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    planned_arrival_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    actual_departure_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    actual_arrival_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    annual_inclusion_policy = sa.Column(
        sa.String(length=30),
        server_default=sa.text("'EXCLUDE'"),
        nullable=False,
    )
    created_from = sa.Column(
        sa.String(length=30),
        server_default=sa.text("'MANUAL'"),
        nullable=False,
    )
    notes = sa.Column(sa.Text(), nullable=True)
    is_deleted = sa.Column(sa.Boolean(), server_default=sa.text("false"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    # updated_at 자동 갱신은 DB 트리거(trg_voyage_updated, §7.2)가 담당한다.
    updated_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_voyage"),
        # §7.1 [C-3]: vessel은 soft-delete만 허용하므로 물리 삭제 시 항차 orphan 방지 → RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_voyage_vessel",
            ondelete="RESTRICT",
        ),
        # §2.2 검증 제약 (원문 그대로). status는 CANCELLED 포함 7개 값.
        sa.CheckConstraint(
            "status IN ('DRAFT','PLANNED','IN_PROGRESS','COMPLETED','CONFIRMED',"
            "'CANCELLED','ARCHIVED')",
            name="chk_voyage_status",
        ),
        sa.CheckConstraint(
            "annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN','INCLUDE_AS_ACTUAL')",
            name="chk_voyage_policy",
        ),
        # status × annual_inclusion_policy 제약 (PRD §8.1.2 ORACLE-R1).
        sa.CheckConstraint(
            "(status = 'DRAFT' AND annual_inclusion_policy = 'EXCLUDE')"
            " OR (status IN ('PLANNED','IN_PROGRESS')"
            " AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN'))"
            " OR (status IN ('COMPLETED','CONFIRMED')"
            " AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_ACTUAL'))"
            " OR (status IN ('CANCELLED','ARCHIVED') AND annual_inclusion_policy = 'EXCLUDE')",
            name="chk_status_policy",
        ),
        # regulation_year 범위 및 policy 연관 제약 [C-1].
        sa.CheckConstraint(
            "regulation_year IS NULL OR regulation_year BETWEEN 2019 AND 2050",
            name="chk_regulation_year_range",
        ),
        sa.CheckConstraint(
            "annual_inclusion_policy = 'EXCLUDE' OR regulation_year IS NOT NULL",
            name="chk_year_policy",
        ),
        sa.CheckConstraint("planned_distance_nm > 0", name="chk_distance_positive"),
        sa.CheckConstraint("planned_speed_kn >= 1.0", name="chk_speed_positive"),
        # [M-6] actual 값은 nullable.
        sa.CheckConstraint(
            "actual_distance_nm IS NULL OR actual_distance_nm > 0",
            name="chk_actual_dist_positive",
        ),
        sa.CheckConstraint(
            "actual_avg_speed_kn IS NULL OR actual_avg_speed_kn >= 1.0",
            name="chk_actual_speed_positive",
        ),
        sa.CheckConstraint(
            "departure_lat IS NULL OR departure_lat BETWEEN -90 AND 90",
            name="chk_dep_lat_range",
        ),
        sa.CheckConstraint(
            "departure_lon IS NULL OR departure_lon BETWEEN -180 AND 180",
            name="chk_dep_lon_range",
        ),
        # [S-3]
        sa.CheckConstraint(
            "arrival_lat IS NULL OR arrival_lat BETWEEN -90 AND 90",
            name="chk_arr_lat_range",
        ),
        sa.CheckConstraint(
            "arrival_lon IS NULL OR arrival_lon BETWEEN -180 AND 180",
            name="chk_arr_lon_range",
        ),
        # §2.2 인덱스 (모두 partial: WHERE is_deleted = false). soft delete 호환.
        sa.Index(
            "idx_voyage_vessel",
            vessel_id,
            created_at.desc(),
            postgresql_where=sa.text("is_deleted = false"),
        ),
        sa.Index(
            "idx_voyage_status",
            "vessel_id",
            "status",
            postgresql_where=sa.text("is_deleted = false"),
        ),
        sa.Index(
            "idx_voyage_year",
            "vessel_id",
            "regulation_year",
            postgresql_where=sa.text("is_deleted = false"),
        ),
    )
