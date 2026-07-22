"""voyage_scenario ORM 모델.

DB_SCHEMA.md §2.4 (voyage_scenario) 참조. 컬럼·제약 정의는 마이그레이션 007과 1:1로
일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

- voyage_id는 ON DELETE SET NULL이며 NULL 허용(독립 시나리오 가능).
- weather_snapshot_id는 §2.4 정본대로 컬럼만 존재. weather_snapshot 테이블(§2.13)이
  아직 없어 FK 제약은 후속 이슈의 별도 마이그레이션에서 추가한다 (007 주석 참조).
  모델에도 FK를 정의하지 않는다 (정의 시 DB와 drift 발생).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class VoyageScenario(Base):
    """운항 시나리오."""

    __tablename__ = "voyage_scenario"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    # [S-8] vessel_id는 NOT NULL (독립 시나리오도 선박 단위 조회·권한 검사 필요).
    vessel_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    voyage_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=True)
    scenario_type = sa.Column(sa.String(length=20), nullable=False)
    scenario_name = sa.Column(sa.String(length=100), nullable=False)
    distance_nm = sa.Column(sa.Numeric(precision=12, scale=2), nullable=False)
    speed_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=False)
    duration_hours = sa.Column(sa.Numeric(precision=10, scale=2), nullable=False)
    fuel_ton = sa.Column(sa.Numeric(precision=12, scale=4), nullable=False)
    weather_factor = sa.Column(sa.Numeric(precision=8, scale=4), nullable=True)
    # [M-8] 목록 조회·정렬용 denormalized numeric cache. canonical 값은 calculation_run 사용.
    cii_value = sa.Column(sa.Numeric(precision=15, scale=8), nullable=False)
    estimated_rating = sa.Column(sa.String(length=1), nullable=False)
    risk_level = sa.Column(sa.String(length=10), nullable=False)
    is_adopted = sa.Column(sa.Boolean(), server_default=sa.text("false"), nullable=False)
    # [M-1] 다른 비즈니스 테이블과 삭제 정책 통일.
    is_deleted = sa.Column(sa.Boolean(), server_default=sa.text("false"), nullable=False)
    # weather_snapshot(§2.13) 미구현 → 컬럼만 존재, FK는 후속 마이그레이션에서 추가.
    weather_snapshot_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    # updated_at 자동 갱신은 DB 트리거(trg_voyage_scenario_updated, §7.2)가 담당한다.
    updated_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_voyage_scenario"),
        # §7.1 [S-8]: 시나리오는 선박 종속 데이터 → 선박 삭제 시 CASCADE.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_voyage_scenario_vessel",
            ondelete="CASCADE",
        ),
        # §7.1 [C-3]: 항차 삭제 시 시나리오는 보존하되 연결만 해제 → SET NULL.
        sa.ForeignKeyConstraint(
            ["voyage_id"],
            ["voyage.id"],
            name="fk_voyage_scenario_voyage",
            ondelete="SET NULL",
        ),
        # §2.4 검증 제약 [S-4] (원문 그대로).
        sa.CheckConstraint(
            "scenario_type IN ('DIRECT','DETOUR','SLOW_STEAMING')",
            name="chk_scenario_type",
        ),
        sa.CheckConstraint(
            "estimated_rating IN ('A','B','C','D','E')",
            name="chk_scenario_rating",
        ),
        sa.CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="chk_scenario_risk",
        ),
        # §2.4 물리량 양수 검증 (#84). speed_kn은 voyage(§2.2) chk_speed_positive와
        # 통일해 >= 1.0.
        sa.CheckConstraint("distance_nm > 0", name="chk_scenario_distance_positive"),
        sa.CheckConstraint("speed_kn >= 1.0", name="chk_scenario_speed_positive"),
        sa.CheckConstraint("duration_hours > 0", name="chk_scenario_duration_positive"),
        sa.CheckConstraint("fuel_ton > 0", name="chk_scenario_fuel_positive"),
    )
