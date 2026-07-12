"""calculation_run 테이블 (immutable)

Revision ID: 008
Revises: 007
Create Date: 2026-07-12

DB_SCHEMA.md §2.5 (calculation_run: 컬럼/인덱스/검증 제약 [S-7]), §7.1 (FK 정책),
§7.3 [X-2] (immutable 트리거) 참조.
vessel_id → vessel(003), voyage_id → voyage(005)를 참조한다.

immutable 테이블: §7.3 prevent_mutation() 트리거로 UPDATE/DELETE를 차단한다.
공유 함수 prevent_mutation()은 이 마이그레이션에서 최초 정의한다.

주의 (정본 대비 의도적 설계 결정):
- voyage_id FK는 정본 §2.5/§7.1의 ON DELETE SET NULL 대신 **ON DELETE RESTRICT**로
  구현한다. SET NULL은 내부적으로 자식(calculation_run) UPDATE로 실행되는데, immutable
  트리거(BEFORE UPDATE)가 이를 막아 트랜잭션이 롤백된다. 즉 SET NULL은 원리적으로 달성
  불가능하며 실효 동작이 RESTRICT다. 실효 동작에 문서를 맞추고(DB_SCHEMA.md 동시 정정),
  §7.1의 "immutable 테이블 참조는 RESTRICT" 관례와 대칭을 회복한다. (이슈 #28 검토 결정)
- 공유 함수 prevent_mutation()은 008.upgrade에서 생성하고 008.downgrade에서 드롭한다.
  009.downgrade에서 드롭하지 않는 이유: 함수는 이 테이블의 trg_calcrun_immutable 트리거가
  의존하므로, `alembic downgrade 008`(009만 한 단계 롤백)로 함수를 먼저 드롭하면 008의
  트리거가 깨져 calculation_run이 조용히 mutable해진다. 함수는 마지막 사용처(008)와 함께
  생성·소멸시켜야 부분 다운그레이드에서도 안전하다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # §7.3 [X-2]: immutable 보호 함수. 이 마이그레이션에서 최초 정의(009와 공유).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'immutable table: % cannot be modified after creation', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.create_table(
        "calculation_run",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("calculation_type", sa.String(length=30), nullable=False),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voyage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_hash", sa.String(length=71), nullable=False),
        sa.Column("parameter_hash", sa.String(length=71), nullable=False),
        sa.Column("model_version", postgresql.JSONB(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=False),
        sa.Column("parameters_used", postgresql.JSONB(), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calculation_run"),
        # §7.1 [C-3]: 계산 이력 보존 → 선박 물리 삭제 시 RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_calculation_run_vessel",
            ondelete="RESTRICT",
        ),
        # 정본은 SET NULL이나 immutable 트리거와 모순되어 RESTRICT로 구현(파일 상단 주의 참조).
        sa.ForeignKeyConstraint(
            ["voyage_id"],
            ["voyage.id"],
            name="fk_calculation_run_voyage",
            ondelete="RESTRICT",
        ),
        # §2.5 검증 제약 [S-7] (원문 그대로): sha256: + 64 hex.
        sa.CheckConstraint(
            "input_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="chk_input_hash_format",
        ),
        sa.CheckConstraint(
            "parameter_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="chk_param_hash_format",
        ),
    )

    # §2.5 인덱스 (원문 그대로).
    op.execute("CREATE INDEX idx_calc_vessel ON calculation_run (vessel_id, created_at DESC);")
    op.execute("CREATE INDEX idx_calc_input_hash ON calculation_run (input_hash, parameter_hash);")
    op.execute("CREATE INDEX idx_calc_type ON calculation_run (calculation_type, created_at DESC);")

    # §7.3 [X-2]: immutable 트리거. UPDATE/DELETE 차단.
    op.execute(
        """
        CREATE TRIGGER trg_calcrun_immutable
        BEFORE UPDATE OR DELETE ON calculation_run
        FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_calcrun_immutable ON calculation_run;")
    op.drop_table("calculation_run")
    # 공유 함수는 마지막 사용처(008)와 함께 드롭(파일 상단 주의 참조).
    # 이 시점(008.downgrade)에는 009가 이미 다운그레이드되어 의존 트리거가 없다.
    op.execute("DROP FUNCTION IF EXISTS prevent_mutation();")
