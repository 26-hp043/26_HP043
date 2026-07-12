"""simulation_snapshot 테이블 (immutable)

Revision ID: 009
Revises: 008
Create Date: 2026-07-12

DB_SCHEMA.md §2.7 (simulation_snapshot: 컬럼/검증 제약 [S-7]), §7.1 (FK 정책),
§7.3 [X-2] (immutable 트리거), TECH_SPEC.md §11 (스냅샷 격리) 참조.
vessel_id → vessel(003)을 참조한다.

immutable 테이블: §7.3 prevent_mutation() 트리거(008에서 정의)로 UPDATE/DELETE를 차단한다.

주의 (이슈 본문 대비 정본 우선, AGENTS §3):
- 이슈 본문의 `simulation_run_id (FK → annual_simulation_run)` 컬럼은 정본에 없다. 관계는
  반대로 annual_simulation_run.snapshot_id → simulation_snapshot(id) (1:1, §2.6)이다.
  따라서 이 테이블에는 simulation_run_id를 두지 않는다(순환 의존 방지). [C-1]
- 이슈 본문의 snapshot_data(TEXT)는 정본 §2.7의 voyages_json(JSONB)이다. regulation_year,
  input_hash, parameter_hash(+형식 CHECK)도 정본에 있으나 이슈 본문에 누락되어 있었다. [C-4]
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | Sequence[str] | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "simulation_snapshot",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("regulation_year", sa.Integer(), nullable=False),
        sa.Column("voyages_json", postgresql.JSONB(), nullable=False),
        sa.Column("input_hash", sa.String(length=71), nullable=False),
        sa.Column("parameter_hash", sa.String(length=71), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_snapshot"),
        # §7.1 [C-3]: 스냅샷 보존 → 선박 물리 삭제 시 RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_simulation_snapshot_vessel",
            ondelete="RESTRICT",
        ),
        # §2.7 검증 제약 [S-7] (원문 그대로): sha256: + 64 hex.
        sa.CheckConstraint(
            "input_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="chk_snap_input_hash_format",
        ),
        sa.CheckConstraint(
            "parameter_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="chk_snap_param_hash_format",
        ),
    )

    # §7.3 [X-2]: immutable 트리거. 함수 prevent_mutation()은 008에서 정의됨.
    op.execute(
        """
        CREATE TRIGGER trg_snapshot_immutable
        BEFORE UPDATE OR DELETE ON simulation_snapshot
        FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_snapshot_immutable ON simulation_snapshot;")
    op.drop_table("simulation_snapshot")
    # 공유 함수 prevent_mutation()은 여기서 드롭하지 않는다. 008의 트리거가 아직 의존하므로
    # 함수 드롭은 008.downgrade가 담당한다(부분 다운그레이드 안전성).
