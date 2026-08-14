"""파라미터 CHECK 제약 + FK 자식 인덱스

Revision ID: 023
Revises: 022
Create Date: 2026-08-14

- #96 (Oracle 재리뷰 F5): ``fuel_type.cf``·``regulation_year.z_factor_percent`` 양수
  CHECK 제약. 음수 cf는 CO₂ 배출량이 음수가 되고, 음수 Z-factor는 required_CII가
  역산돼 계산이 무의미해진다. ``cii_reference_line``의 ``chk_a_decimal_positive``·
  ``chk_c_positive``와 같은 물리량 가드로 정합성을 맞춘다.
- #97 (Oracle 재리뷰 F3+F4): ``voyage_scenario``·``simulation_snapshot``의 FK 컬럼
  인덱스. vessel/voyage 삭제 시 RESTRICT·CASCADE·SET NULL 체크가 full table scan을
  하던 것을 막는다. 다른 자식 테이블(voyage·voyage_fuel_use·calculation_run)은
  인덱스를 보유하고 있어 불일치였다.

seed 호환성: 연료 CF(017)는 전부 양수, Z-factor(seed)는 0% 포함 전부 >= 0 —
기존 seed는 제약 추가 후에도 그대로 통과한다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "023"
down_revision: str | Sequence[str] | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- #96: 파라미터 물리량 CHECK 제약 (DB_SCHEMA §2.8·§2.9) ------------------
    op.execute("ALTER TABLE fuel_type ADD CONSTRAINT chk_cf_positive CHECK (cf > 0);")
    op.execute(
        "ALTER TABLE regulation_year ADD CONSTRAINT chk_z_factor_nonneg "
        "CHECK (z_factor_percent >= 0);"
    )

    # --- #97: FK 자식 인덱스 (DB_SCHEMA §2.4·§2.7) ------------------------------
    # FK 체크(vessel/voyage 삭제)와 목록 조회(WHERE vessel_id ORDER BY created_at)를
    # 함께 서비스한다 — idx_calc_vessel과 같은 복합 형태.
    op.execute("CREATE INDEX idx_scenario_vessel ON voyage_scenario (vessel_id, created_at DESC);")
    # voyage_id는 SET NULL 체크 전용 — 단일 컬럼으로 족하다 (NULL 허용 컬럼).
    op.execute("CREATE INDEX idx_scenario_voyage ON voyage_scenario (voyage_id);")
    op.execute(
        "CREATE INDEX idx_snapshot_vessel ON simulation_snapshot (vessel_id, created_at DESC);"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_snapshot_vessel;")
    op.execute("DROP INDEX IF EXISTS idx_scenario_voyage;")
    op.execute("DROP INDEX IF EXISTS idx_scenario_vessel;")
    op.execute("ALTER TABLE regulation_year DROP CONSTRAINT IF EXISTS chk_z_factor_nonneg;")
    op.execute("ALTER TABLE fuel_type DROP CONSTRAINT IF EXISTS chk_cf_positive;")
