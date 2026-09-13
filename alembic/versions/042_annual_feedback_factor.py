"""연간 시뮬레이션에 「실적 보정계수 적용」 여부를 저장한다

Revision ID: 042
Revises: 041
Create Date: 2026-09-13

이슈 #363 · ``PRD §12.2.1``.

무엇을 저장하나
----------------
``annual_simulation_run.apply_feedback_factor`` — 사용자가 **보정계수를 켜고 돌렸는지**
하나다. **계수 값은 저장하지 않는다.** 계수는 같은 실행의 ``simulation_snapshot``에 든
확정 항차의 계획·실적에서 **다시 계산해도 같은 값**이 나오므로, 따로 적으면 두 곳에
같은 사실이 생겨 갈릴 수 있다.

왜 켜짐 여부는 저장해야 하나
----------------------------
``reproduce``(``API_SPEC §6.4``)가 원본을 **같은 조건으로** 다시 계산해야 한다. 켜짐
여부는 스냅샷 어디에도 없는 **사용자 선택**이라, 저장하지 않으면 재현이 원본 설정을
알 수 없다.

기존 행
-------
``server_default false``로 채운다. **기존 실행은 전부 보정 없이 계산됐으므로 사실과
같다.** ``input_hash``도 바뀌지 않는다 — 켜진 실행만 해시 재료에 그 키를 넣는다
(``services/annual_simulation._input_hash``).

되돌리기
--------
``downgrade``는 열을 지운다. **어느 실행이 보정계수를 켜고 돌았는지가 사라지고, 그
실행들은 재현이 불가능해진다** — ``annual_simulation_run``은 보존 대상이라 다시
upgrade해도 채울 근거가 없다. ``IRREVERSIBLE``로 분류한다(``037``과 같은 이유).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "annual_simulation_run",
        sa.Column(
            "apply_feedback_factor",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """열을 지운다 — **보정계수를 켜고 돈 실행들이 재현 불가가 된다.**

    보존 대상 테이블이라 다시 upgrade해도 채울 근거가 없다. 프로덕션에서는 막는다
    (``DB_SCHEMA §8.1.2`` · #819).
    """
    guard_irreversible_downgrade("042")
    op.drop_column("annual_simulation_run", "apply_feedback_factor")
