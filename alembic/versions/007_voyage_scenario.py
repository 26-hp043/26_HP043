"""voyage_scenario 테이블

Revision ID: 007
Revises: 006
Create Date: 2026-07-09

DB_SCHEMA.md §2.4 (voyage_scenario: 컬럼/검증 제약 [S-4]), §7.1 (FK 정책),
§7.2 [M-2] (updated_at 트리거) 참조.
vessel_id → vessel(003), voyage_id → voyage(005)를 참조한다.

주의 (AGENTS §3, DB_SCHEMA 정본 기준):
- voyage_id는 ON DELETE SET NULL이며 NULL 허용(독립 시나리오 가능). 이슈 본문의 CASCADE 아님.
- weather_snapshot_id 컬럼은 §2.4 정본대로 생성하되, weather_snapshot 테이블(§2.13)이
  아직 없으므로 FK 제약은 이 마이그레이션에서 생략한다. weather_snapshot 테이블을 만드는
  후속 이슈에서 별도 마이그레이션으로 FK(fk_voyage_scenario_weather, ON DELETE SET NULL)를
  추가한다. 컬럼이 nullable이라 데이터 무결성 문제는 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | Sequence[str] | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "voyage_scenario",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # [S-8] vessel_id는 NOT NULL (독립 시나리오도 선박 단위 조회·권한 검사 필요).
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voyage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scenario_type", sa.String(length=20), nullable=False),
        sa.Column("scenario_name", sa.String(length=100), nullable=False),
        sa.Column("distance_nm", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("speed_kn", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("duration_hours", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("fuel_ton", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("weather_factor", sa.Numeric(precision=8, scale=4), nullable=True),
        # [M-8] 목록 조회·정렬용 denormalized numeric cache. canonical 값은 calculation_run 사용.
        sa.Column("cii_value", sa.Numeric(precision=15, scale=8), nullable=False),
        sa.Column("estimated_rating", sa.String(length=1), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column(
            "is_adopted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        # [M-1] 다른 비즈니스 테이블과 삭제 정책 통일.
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        # weather_snapshot(§2.13) 미구현 → 컬럼만 생성하고 FK는 후속 마이그레이션에서 추가.
        sa.Column("weather_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
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
    )

    # §7.2: updated_at 자동 갱신 트리거.
    op.execute(
        """
        CREATE TRIGGER trg_voyage_scenario_updated
        BEFORE UPDATE ON voyage_scenario
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_voyage_scenario_updated ON voyage_scenario;")
    op.drop_table("voyage_scenario")
