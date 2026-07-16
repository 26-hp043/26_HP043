"""voyage_fuel_use 테이블

Revision ID: 006
Revises: 005
Create Date: 2026-07-09

DB_SCHEMA.md §2.3 (voyage_fuel_use: 컬럼/인덱스/검증 제약), §7.1 (FK 정책),
§7.2 [M-2] (updated_at 트리거) 참조.
voyage_id → voyage(005), fuel_type → fuel_type(002)를 참조한다.

주의: chk_actual_fuel_positive는 `actual_fuel_ton IS NULL OR actual_fuel_ton > 0`이다
(이슈 본문의 `>= 0`이 아님 — DB_SCHEMA §2.3 정본 기준, AGENTS §3).

[ORACLE-C4] voyage.status = COMPLETED 전환 시 최소 1개 actual_fuel_ton > 0 필요 제약은
DB가 아닌 애플리케이션 서비스 계층에서 검증한다(§2.3). 이 마이그레이션 범위 밖.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | Sequence[str] | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "voyage_fuel_use",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("voyage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fuel_type", sa.String(length=30), nullable=False),
        sa.Column("planned_fuel_ton", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("actual_fuel_ton", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("cf_used", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_voyage_fuel_use"),
        # §7.1 [C-3]: 연료 기록은 항차 종속 → 항차 삭제 시 CASCADE.
        sa.ForeignKeyConstraint(
            ["voyage_id"],
            ["voyage.id"],
            name="fk_voyage_fuel_use_voyage",
            ondelete="CASCADE",
        ),
        # [S-1]: 연료 코드 변경 시 자동 전파 (ON UPDATE CASCADE).
        sa.ForeignKeyConstraint(
            ["fuel_type"],
            ["fuel_type.code"],
            name="fk_voyage_fuel_use_fuel_type",
            onupdate="CASCADE",
        ),
        # §2.3 검증 제약 (원문 그대로).
        sa.CheckConstraint(
            "source IN ('USER_INPUT','MODEL_ESTIMATE','IMPORT','SAMPLE')",
            name="chk_fuel_source",
        ),
        sa.CheckConstraint(
            "planned_fuel_ton IS NULL OR planned_fuel_ton > 0",
            name="chk_fuel_positive",
        ),
        sa.CheckConstraint(
            "actual_fuel_ton IS NULL OR actual_fuel_ton > 0",
            name="chk_actual_fuel_positive",
        ),
    )

    # [S-2] 동일 항차+연료 타입 중복 방지 (중복 시 CO₂ 이중 산정 버그 방어).
    op.execute("CREATE UNIQUE INDEX idx_fuel_use_unique ON voyage_fuel_use (voyage_id, fuel_type);")

    # §7.2: updated_at 자동 갱신 트리거.
    op.execute(
        """
        CREATE TRIGGER trg_voyage_fuel_use_updated
        BEFORE UPDATE ON voyage_fuel_use
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_voyage_fuel_use_updated ON voyage_fuel_use;")
    op.drop_table("voyage_fuel_use")
