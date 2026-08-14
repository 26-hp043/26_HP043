"""calculation_run needs_recalc 컬럼 + 조건부 immutable 가드

Revision ID: 024
Revises: 023
Create Date: 2026-08-14

PRD §8.4 · API_SPEC §2.4 (#283): 선박 DWT/GT 변경 시 해당 선박의 **미확정 계산
결과**에 재계산 필요 표시를 남긴다.

**트리거 교체 이유** — 008의 ``trg_calcrun_immutable``은 UPDATE를 전면 차단한다.
needs_recalc 플립도 UPDATE라서 그대로는 표시를 남길 수 없다. 단 **immutable 정책
자체는 유지**해야 한다(§7.3 [X-2] — result_json 변조 차단이 목적). 따라서:

- ``calc_run_guard()`` 전용 함수로 바꾼다 — **나머지 컬럼 전부가 불변이고
  needs_recalc만 false→true로 넘어가는 UPDATE**만 통과시킨다.
- 비교는 ``(to_jsonb(NEW) - 'needs_recalc') IS NOT DISTINCT FROM (to_jsonb(OLD) -
  'needs_recalc')`` — 컬럼을 열거하지 않으므로 이후 컬럼 추가도 자동으로 보호된다.
- true→false 롤백도 거부한다(표시는 누적 전용).
- DELETE는 종전과 같이 전면 차단 — 계산 이력 보존(§7.1 RESTRICT와 같은 목적).

공유 함수 ``prevent_mutation()``은 simulation_snapshot(009)이 계속 쓰므로 건드리지
않는다. 008의 downgrade가 ``DROP FUNCTION prevent_mutation``을 하는 것도 그대로
유효하다(009가 먼저 내려가는 순서 불변).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "024"
down_revision: str | Sequence[str] | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "calculation_run",
        sa.Column(
            "needs_recalc",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.execute("DROP TRIGGER IF EXISTS trg_calcrun_immutable ON calculation_run;")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION calc_run_guard()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'immutable table: calculation_run cannot be modified after creation';
            END IF;
            IF NEW.needs_recalc = TRUE AND OLD.needs_recalc = FALSE
               AND (to_jsonb(NEW) - 'needs_recalc')
                   IS NOT DISTINCT FROM (to_jsonb(OLD) - 'needs_recalc')
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION
                'immutable table: calculation_run cannot be modified after creation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_calcrun_immutable
        BEFORE UPDATE OR DELETE ON calculation_run
        FOR EACH ROW EXECUTE FUNCTION calc_run_guard();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_calcrun_immutable ON calculation_run;")
    op.execute(
        """
        CREATE TRIGGER trg_calcrun_immutable
        BEFORE UPDATE OR DELETE ON calculation_run
        FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
        """
    )
    op.execute("DROP FUNCTION IF EXISTS calc_run_guard();")
    op.drop_column("calculation_run", "needs_recalc")
