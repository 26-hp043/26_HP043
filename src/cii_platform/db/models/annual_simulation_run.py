"""annual_simulation_run ORM 모델.

DB_SCHEMA.md §2.6 (annual_simulation_run) 참조. 컬럼·제약·인덱스 정의는
마이그레이션 014와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import FK_ON_UPDATE, Base
from cii_platform.db.types import UuidText


class AnnualSimulationRun(Base):
    """연간 CII 시뮬레이션 실행 기록."""

    __tablename__ = "annual_simulation_run"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    calculation_run_id = sa.Column(UuidText, nullable=False)
    vessel_id = sa.Column(UuidText, nullable=False)
    regulation_year = sa.Column(sa.Integer(), nullable=False)
    target_rating = sa.Column(sa.String(length=1), nullable=False)
    simulation_runs = sa.Column(sa.Integer(), nullable=False)
    snapshot_id = sa.Column(UuidText, nullable=False)
    #: 실적 보정계수를 켜고 돌렸는가 (``PRD §12.2.1`` · `#363` · 마이그레이션 ``042``).
    #: **계수 값은 저장하지 않는다** — 같은 실행의 스냅샷에서 다시 계산하면 같은 값이다.
    apply_feedback_factor = sa.Column(
        sa.Boolean(), default=False, server_default=sa.text("0"), nullable=False
    )
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_annual_simulation_run"),
        # §7.1 [DB-C-3]: immutable 테이블(calculation_run) 참조 → RESTRICT.
        sa.ForeignKeyConstraint(
            ["calculation_run_id"],
            ["calculation_run.id"],
            name="fk_annual_simulation_run_calculation_run",
            ondelete="RESTRICT",
            onupdate=FK_ON_UPDATE,
        ),
        # §7.1 [DB-C-3]: 시뮬레이션 이력 보존 → 선박 물리 삭제 시 RESTRICT.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_annual_simulation_run_vessel",
            ondelete="RESTRICT",
            onupdate=FK_ON_UPDATE,
        ),
        # 🔴 `fk_annual_simulation_run_snapshot`은 **없다** (`#1058` · `050`).
        #
        # CUBRID는 FK가 만든 인덱스가 있는 열에 인덱스를 또 두는 것을 거부하므로
        # (`Index "fk_…" already defined for class` · 실측), 이 FK가 있으면 아래
        # `idx_sim_snapshot_unique`(= `§2.6 [S-6]`의 1스냅샷 = 1시뮬레이션)를 세울 수
        # 없다. 사용자가 「FK를 빼고 UNIQUE + 트리거」를 골랐다(결정요청 §0-3⑵).
        #
        # 빠진 것을 무엇이 대신하는가 —
        #   · 부모 쪽(`ON DELETE RESTRICT`) → `trg_snapshot_no_delete`가 이미 전면 차단.
        #     참조가 없어도 못 지우므로 **FK보다 강하다**.
        #   · 자식 쪽(없는 스냅샷 참조 금지) → `trg_annual_sim_snapshot_ref_ins/upd`.
        # §2.6 [M-4] (원문 그대로): E 불가.
        sa.CheckConstraint(
            "target_rating IN ('A','B','C','D')",
            name="chk_target_rating",
        ),
        # §2.6 [M-5] (원문 그대로).
        sa.CheckConstraint("simulation_runs > 0", name="chk_sim_runs_positive"),
        # §2.6 [S-6] (원문 그대로): 1스냅샷 = 1시뮬레이션 (1:1 관계 보장).
        sa.Index(
            "idx_sim_snapshot_unique",
            "snapshot_id",
            unique=True,
        ),
    )
