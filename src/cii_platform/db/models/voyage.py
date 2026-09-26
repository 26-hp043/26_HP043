"""voyage ORM 모델.

DB_SCHEMA.md §2.2 (voyage) 참조. 컬럼·제약·인덱스 정의는 마이그레이션 005와 1:1로
일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

- status는 CANCELLED 포함 7개 값.
- annual_inclusion_policy는 EXCLUDE / INCLUDE_AS_PLAN / INCLUDE_AS_ACTUAL.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import FK_ON_UPDATE, Base
from cii_platform.db.types import UuidText


class Voyage(Base):
    """항차."""

    __tablename__ = "voyage"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    vessel_id = sa.Column(UuidText, nullable=False)
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
    # 계획 거리의 출처 (#1256 · 059). `USER_INPUT`(직접 입력 · CSV) 또는
    # `COORDINATE_ESTIMATE`(두 좌표의 대권거리 · `PRD §15.2`). **NULL은 「모른다」** —
    # 059 이전 행과, 출처 없이 거리를 넣은 API 요청이 여기 든다. 거리가 바뀌면 옛 출처는
    # 새 값에 붙지 않는다(`services/voyage.py` `update_voyage`). 값 집행은 059의 트리거.
    planned_distance_source = sa.Column(sa.String(length=30), nullable=True)
    actual_distance_nm = sa.Column(sa.Numeric(precision=12, scale=2), nullable=True)
    planned_speed_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=False)
    actual_avg_speed_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    planned_departure_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    planned_arrival_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    actual_departure_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    actual_arrival_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    # 실제 출항·도착 시각의 출처 (#1923 · 064). `USER_INPUT`(사람이 넣음) 또는
    # `PUBLIC_RECORD`(공적 재항 기록에서 「이 값으로 채우기」 · `PRD §17.4.4`).
    # **NULL은 「모른다」** — 064 이전 행과 출처 없이 시각을 넣은 요청이 여기 든다. 시각이
    # 바뀌면 옛 출처는 새 값에 붙지 않는다(`services/voyage.py` `set_actuals`). 값 집행은 064의
    # 트리거.
    actual_departure_source = sa.Column(sa.String(length=30), nullable=True)
    actual_arrival_source = sa.Column(sa.String(length=30), nullable=True)
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
    is_deleted = sa.Column(sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    # updated_at 자동 갱신은 열 속성 ON UPDATE CURRENT_DATETIME(마이그레이션 049 · DB_SCHEMA §7.2)이
    # 담당한다 — CUBRID에는 갱신 트리거가 없다(재귀에 걸린다).
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_voyage"),
        # §7.1 [C-3]: vessel은 soft-delete만 허용하므로 물리 삭제 시 항차 orphan 방지 → RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_voyage_vessel",
            ondelete="RESTRICT",
            onupdate=FK_ON_UPDATE,
        ),
        # §2.2 검증 제약 (원문 그대로). status는 CANCELLED 포함 7개 값.
        sa.CheckConstraint(
            "\"status\" IN ('DRAFT','PLANNED','IN_PROGRESS','COMPLETED','CONFIRMED',"
            "'CANCELLED','ARCHIVED')",
            name="chk_voyage_status",
        ),
        sa.CheckConstraint(
            "annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN','INCLUDE_AS_ACTUAL')",
            name="chk_voyage_policy",
        ),
        # status × annual_inclusion_policy 제약 (PRD §8.1.2 ORACLE-R1).
        sa.CheckConstraint(
            "(\"status\" = 'DRAFT' AND annual_inclusion_policy = 'EXCLUDE')"
            " OR (\"status\" IN ('PLANNED','IN_PROGRESS')"
            " AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_PLAN'))"
            " OR (\"status\" IN ('COMPLETED','CONFIRMED')"
            " AND annual_inclusion_policy IN ('EXCLUDE','INCLUDE_AS_ACTUAL'))"
            " OR (\"status\" IN ('CANCELLED','ARCHIVED') AND annual_inclusion_policy = 'EXCLUDE')",
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
        # #1256 — 선언은 `chk_fuel_source`와 같은 형태이고, 집행은 059의 트리거
        # `trg_chk_planned_distance_source_ins/upd`가 한다(CUBRID는 CHECK를 보관하지 않는다 · §7.4).
        sa.CheckConstraint(
            "planned_distance_source IS NULL OR planned_distance_source IN "
            "('USER_INPUT','COORDINATE_ESTIMATE')",
            name="chk_distance_source",
        ),
        # #1923 — 선언은 `chk_distance_source`와 같은 형태이고, 집행은 064의 트리거
        # `trg_chk_actual_departure_source_ins/upd`·`trg_chk_actual_arrival_source_ins/upd`가 한다.
        sa.CheckConstraint(
            "actual_departure_source IS NULL OR actual_departure_source IN "
            "('USER_INPUT','PUBLIC_RECORD')",
            name="chk_actual_departure_source",
        ),
        sa.CheckConstraint(
            "actual_arrival_source IS NULL OR actual_arrival_source IN "
            "('USER_INPUT','PUBLIC_RECORD')",
            name="chk_actual_arrival_source",
        ),
        sa.CheckConstraint("planned_speed_kn >= 1.0", name="chk_speed_positive"),
        # #1269 — 속력의 물리 상한(VAL-009). 집행은 062 트리거다(CUBRID는 CHECK를 검사하지 않는다).
        sa.CheckConstraint("planned_speed_kn <= 60", name="chk_speed_max_voyage"),
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
            "actual_avg_speed_kn IS NULL OR actual_avg_speed_kn <= 60",
            name="chk_actual_speed_max",
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
        ),
        sa.Index(
            "idx_voyage_status",
            "vessel_id",
            "status",
        ),
        sa.Index(
            "idx_voyage_year",
            "vessel_id",
            "regulation_year",
        ),
    )
