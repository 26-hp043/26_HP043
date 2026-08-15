"""not_underway_period ORM 모델.

DB_SCHEMA.md §2.17 (not_underway_period) 참조. 컬럼·제약·인덱스 정의는 마이그레이션
025와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

이슈 #345: 항해하지 않는 구간(정박·묘박·표류·STS·운하 통과·드라이독)을 항차가 아닌
선박+규제연도에 귀속시킨다. 정박 구간은 연료(분자 ``M``)만 늘리고 거리(분모 ``W``)는
늘리지 않아 등급이 악화되는데, 이것이 규제 계산식의 원래 동작이다(새 계산식 아님).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class NotUnderwayPeriod(Base):
    """not under way 구간 — 정박·묘박·표류·STS·운하 통과·드라이독."""

    __tablename__ = "not_underway_period"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    vessel_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    regulation_year = sa.Column(sa.Integer(), nullable=False)
    period_type = sa.Column(sa.String(length=20), nullable=False)
    started_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    ended_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    port_name = sa.Column(sa.String(length=200), nullable=True)
    lat = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    lon = sa.Column(sa.Numeric(precision=9, scale=6), nullable=True)
    voyage_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=True)
    # 마이그레이션 028 (#353) — CII 분모 Dt는 not under way 이동 거리도 포함한다
    # (MEPC.412(84) §4.2 "both under way and not under way"). 접안·묘박은 0이 정상값이라
    # NULL을 허용하지 않는다 — 「모름」과 「0」이 섞이면 합계가 조용히 달라진다.
    distance_nm = sa.Column(
        sa.Numeric(precision=12, scale=2), server_default=sa.text("0"), nullable=False
    )
    is_deleted = sa.Column(sa.Boolean(), server_default=sa.text("false"), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    # updated_at 자동 갱신은 DB 트리거(trg_not_underway_period_updated, §7.2)가 담당한다.
    updated_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_not_underway_period"),
        # §7.1: 정박 기록이 있는 선박은 물리 삭제 거부.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_not_underway_period_vessel",
            ondelete="RESTRICT",
        ),
        # 맥락 참조 — 항차 삭제 시 링크만 끊는다(정박 기록 자체는 선박에 귀속).
        sa.ForeignKeyConstraint(
            ["voyage_id"],
            ["voyage.id"],
            name="fk_not_underway_period_voyage",
            ondelete="SET NULL",
        ),
        # MEPC.401(83) EOSP→FAOP 구간의 실체 6값.
        sa.CheckConstraint(
            "period_type IN ('IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')",
            name="chk_not_underway_period_type",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="chk_not_underway_period_time_order",
        ),
        # 028 — voyage.actual_distance_nm과 달리 0이 정상값이라 > 0 이 아니라 >= 0 이다.
        sa.CheckConstraint("distance_nm >= 0", name="chk_nup_distance_non_negative"),
        # 연도 조회 경로(선박×연도) + soft delete 호환 partial index.
        sa.Index(
            "idx_not_underway_period_vessel_year",
            "vessel_id",
            "regulation_year",
            postgresql_where=sa.text("is_deleted = false"),
        ),
        # 029 (#376) — #368 시뮬레이션 시계의 구간 겹침 조회 경로.
        # vessel_year 인덱스는 regulation_year가 선행열이 아니라 started_at 범위
        # 조건이 인덱스로 내려가지 않는다.
        sa.Index(
            "idx_not_underway_period_vessel_started",
            "vessel_id",
            "started_at",
            postgresql_where=sa.text("is_deleted = false"),
        ),
        # 029 (#376) — voyage 삭제 시 ON DELETE SET NULL 확인이 full scan 하지
        # 않도록(023 idx_scenario_voyage 패턴). FK 확인은 삭제된 행도 봐야 하므로
        # partial로 두지 않는다.
        sa.Index("idx_not_underway_period_voyage", "voyage_id"),
    )
