"""calculation_run ORM 모델 (immutable).

DB_SCHEMA.md §2.5 (calculation_run) 참조. 컬럼·제약·인덱스 정의는 마이그레이션 008과
1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).

**읽기 전용(immutable)**: 이 테이블은 생성 후 UPDATE/DELETE가 금지된다. 실제 차단은
DB 트리거 trg_calcrun_immutable(prevent_mutation(), DB_SCHEMA §7.3 [X-2])가 수행하며,
ORM으로 UPDATE/DELETE를 시도하면 DB 예외로 트랜잭션이 롤백된다. 서비스 코드는 이
테이블에 INSERT/SELECT만 수행해야 한다.

- voyage_id FK는 정본 §2.5의 SET NULL 대신 RESTRICT (immutable 트리거와 모순 →
  실효 동작 기준, 이슈 #28 검토 결정. 008 파일 상단 주의 참조).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class CalculationRun(Base):
    """계산 실행 결과 (immutable — INSERT/SELECT 전용)."""

    __tablename__ = "calculation_run"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    calculation_type = sa.Column(sa.String(length=30), nullable=False)
    vessel_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    voyage_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=True)
    input_hash = sa.Column(sa.String(length=71), nullable=False)
    parameter_hash = sa.Column(sa.String(length=71), nullable=False)
    model_version = sa.Column(postgresql.JSONB(), nullable=False)
    result_json = sa.Column(postgresql.JSONB(), nullable=False)
    parameters_used = sa.Column(postgresql.JSONB(), nullable=False)
    warnings_json = sa.Column(postgresql.JSONB(), nullable=True)
    duration_ms = sa.Column(sa.Integer(), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_calculation_run"),
        # §7.1 [C-3]: 계산 이력 보존 → 선박 물리 삭제 시 RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_calculation_run_vessel",
            ondelete="RESTRICT",
        ),
        # 정본은 SET NULL이나 immutable 트리거와 모순되어 RESTRICT로 구현(008 주의 참조).
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
        # §2.5 calculation_type enum 검증 (#84). 4개 허용값 외 임의 문자열 차단.
        sa.CheckConstraint(
            "calculation_type IN "
            "('VOYAGE_ESTIMATE','SCENARIO','ANNUAL_DETERMINISTIC','ANNUAL_MONTE_CARLO')",
            name="chk_calculation_type",
        ),
        # §2.5 인덱스 (원문 그대로).
        sa.Index("idx_calc_vessel", vessel_id, created_at.desc()),
        sa.Index("idx_calc_input_hash", "input_hash", "parameter_hash"),
        sa.Index("idx_calc_type", calculation_type, created_at.desc()),
    )
