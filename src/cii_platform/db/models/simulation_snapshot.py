"""simulation_snapshot ORM 모델 (immutable).

DB_SCHEMA.md §2.7 (simulation_snapshot), TECH_SPEC §11 (스냅샷 격리) 참조.
컬럼·제약 정의는 마이그레이션 009와 1:1로 일치해야 한다 (zero drift —
tests/test_orm_schema_sync.py에서 검증).

**읽기 전용(immutable)**: 이 테이블은 생성 후 UPDATE/DELETE가 금지된다. 실제 차단은
DB 트리거 trg_snapshot_immutable(prevent_mutation(), DB_SCHEMA §7.3 [X-2])가 수행하며,
ORM으로 UPDATE/DELETE를 시도하면 DB 예외로 트랜잭션이 롤백된다. 서비스 코드는 이
테이블에 INSERT/SELECT만 수행해야 한다.

- annual_simulation_run(§2.6)과의 관계는 annual_simulation_run.snapshot_id →
  simulation_snapshot(id) 방향(1:1)이다. 이 테이블에는 simulation_run_id를 두지
  않는다(순환 의존 방지, 009 주석 참조). annual_simulation_run 테이블은 아직
  마이그레이션이 없어 이번 범위 밖.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class SimulationSnapshot(Base):
    """시뮬레이션 스냅샷 (immutable — INSERT/SELECT 전용)."""

    __tablename__ = "simulation_snapshot"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    vessel_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    regulation_year = sa.Column(sa.Integer(), nullable=False)
    voyages_json = sa.Column(postgresql.JSONB(), nullable=False)
    input_hash = sa.Column(sa.String(length=71), nullable=False)
    parameter_hash = sa.Column(sa.String(length=71), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
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
