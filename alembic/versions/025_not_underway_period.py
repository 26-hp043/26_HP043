"""not under way 구간·연료 테이블 신설

Revision ID: 025
Revises: 024
Create Date: 2026-08-15

이슈 #345 · PRD v4.0 §3.3.2(``M`` 정의): 항해하지 않는 구간(정박·묘박·표류·STS·
운하 통과·드라이독)의 연료 소모를 기록한다. 현재 연료는 ``voyage_fuel_use``로
항차에만 매달려 있어 not under way 구간의 연료를 담을 곳이 없었다.

설계 결정 (#345):

- **새 테이블** — ``voyage``에 유형을 추가하면 거리 0 → 항차 CII에서 ``M/0`` 폭발,
  리포트에 정박 레코드가 섞인다.
- **귀속은 ``vessel_id`` + ``regulation_year``** — 정박은 항차 사이에 있어 특정
  항차에 속하지 않는다. ``voyage_id``는 nullable 맥락 참조(ON DELETE SET NULL).
- **부모-자식** — 기존 ``voyage ──< voyage_fuel_use`` 패턴과 동일.

``period_type`` 6값은 「not under way」의 실체(``MEPC.401(83)`` EOSP→다음 FAOP
구간 — 묘박·표류·STS·운하 통과 포함, 드라이독도 idle 배출 범위)를, ``consumer_type``
4값은 MARPOL Annex VI Appendix IX의 DCS 보고 항목(``MEPC.385(81)``, 적용 시작
데이터연도 2026 — 본 프로젝트 기준연도와 일치)을 따른다.

⚠️ ``M``이 not under way 연료를 포함한다는 최종 근거는 1차 규정 원문 대조 미완이다
(#358에서 처리). 결과가 달라져도 스키마가 아니라 집계 로직만 바뀐다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "025"
down_revision: str | Sequence[str] | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """not_underway_period + not_underway_fuel_use 신설 (DB_SCHEMA §2.17·§2.18)."""
    op.create_table(
        "not_underway_period",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("regulation_year", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("port_name", sa.String(length=200), nullable=True),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("voyage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_not_underway_period"),
        # §7.1: 정박 기록이 있는 선박은 물리 삭제 거부(감사·이력 보존).
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
        # MEPC.401(83) EOSP→FAPP 구간의 실체 6값.
        sa.CheckConstraint(
            "period_type IN ('IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')",
            name="chk_not_underway_period_type",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="chk_not_underway_period_time_order",
        ),
    )
    op.create_index(
        "idx_not_underway_period_vessel_year",
        "not_underway_period",
        ["vessel_id", "regulation_year"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_not_underway_period_updated
        BEFORE UPDATE ON not_underway_period
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """
    )

    op.create_table(
        "not_underway_fuel_use",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("period_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumer_type", sa.String(length=20), nullable=False),
        sa.Column("fuel_type", sa.String(length=30), nullable=False),
        sa.Column("fuel_ton", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_not_underway_fuel_use"),
        # 부모-자식: 구간 삭제 시 연료 기록도 함께 삭제(voyage_fuel_use 패턴).
        sa.ForeignKeyConstraint(
            ["period_id"],
            ["not_underway_period.id"],
            name="fk_not_underway_fuel_use_period",
            ondelete="CASCADE",
        ),
        # [S-1] / §7.1: fuel_type → fuel_type(code), ON UPDATE CASCADE, ON DELETE NO ACTION.
        sa.ForeignKeyConstraint(
            ["fuel_type"],
            ["fuel_type.code"],
            name="fk_not_underway_fuel_use_fuel_type",
            onupdate="CASCADE",
            ondelete="NO ACTION",
        ),
        # MEPC.385(81) Appendix IX DCS 보고 항목 4값 (데이터연도 2026~).
        sa.CheckConstraint(
            "consumer_type IN ('MAIN_ENGINE','AUX_ENGINE','OIL_FIRED_BOILER','OTHER')",
            name="chk_not_underway_consumer_type",
        ),
        sa.CheckConstraint("fuel_ton > 0", name="chk_not_underway_fuel_positive"),
    )
    # FK 자식 인덱스 — CASCADE/조인 경로 (§4 전략: 자식 쪽 조회·삭제 경로 보장).
    op.create_index(
        "idx_not_underway_fuel_use_period",
        "not_underway_fuel_use",
        ["period_id"],
    )


def downgrade() -> None:
    """테이블 제거 — 트리거는 DROP TABLE와 함께 사라진다."""
    op.drop_table("not_underway_fuel_use")
    op.drop_table("not_underway_period")
