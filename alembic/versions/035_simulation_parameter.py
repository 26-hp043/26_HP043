"""simulation_parameter 테이블 + 기본 프로파일 seed

Revision ID: 035
Revises: 034
Create Date: 2026-08-17

이슈 #434 · ``PRD §12.4.1``이 *"분포 기본값은 ``simulation_parameter``로 관리하며
코드 하드코딩하지 않는다"* 를 요구하는데 **그 테이블이 존재하지 않았다** — PRD가
이름만 부르고 ``DB_SCHEMA``에 정의조차 없었다. ``#63``이 상수로 임시 처리한 것을
정본대로 되돌린다.

왜 파라미터를 테이블로 빼는가
------------------------------
삼각분포의 min/mode/max는 규제값이 아니라 **모델 가정**이다. 운항 데이터가 쌓이면
조정될 값이고, 그때 코드를 고쳐 배포하는 대신 행을 바꿀 수 있어야 한다 —
``regulation_year``·``cii_reference_line``을 코드 밖에 둔 것과 같은 이유다.

``bound_type``이 있는 이유
--------------------------
``PRD §12.4.1`` 표에서 거리·연료는 계획값의 **배수**(``0.97×plan``)지만 속도는
**덧셈**(``plan − 1kn``)이다. 한 컬럼 집합으로 둘을 담으려면 해석 방식을 행이 스스로
말해야 한다. 배수만 지원하면 속도를 표현할 수 없고, 속도용 테이블을 따로 만들면 같은
개념이 두 곳에 생긴다.

seed를 이 마이그레이션에 넣는다
-------------------------------
``032``(#127)가 세운 원칙 그대로다 — ``alembic upgrade head`` 하나로 화면이 뜨는
상태를 유지한다. 별도 seed 단계를 만들면 배포 절차가 다시 갈라진다.

**``src/`` 상수를 import하지 않는다.** 마이그레이션은 과거 한 시점의 스냅샷이고,
상수를 참조하면 값이 바뀔 때 이 마이그레이션의 동작이 **소급 변경**된다(032 주석 참조).
값을 여기에 그대로 적는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "035"
down_revision: str | Sequence[str] | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``PRD §12.4.1`` 표를 그대로 옮긴다. **수치를 임의로 재작성하지 않는다**
#: (AGENTS §3 — 수치·공식은 상위 문서에서 복사).
#:
#: (variable, bound_type, min, mode, max, floor)
_DEFAULT_ROWS = (
    # 거리 — 우회·대기 가능성. min=0.97×plan, mode=plan, max=1.05×plan
    ("DISTANCE", "FACTOR", "0.9700", "1.0000", "1.0500", None),
    # 연료 사용량 — 기상·운항 변동. min=0.90×plan, mode=plan, max=1.15×plan
    ("FUEL", "FACTOR", "0.9000", "1.0000", "1.1500", None),
    # 속도 — 감속·증속 변동. min=plan-1kn, mode=plan, max=plan+1kn
    # floor 1.0kn: [ORACLE 삼각분포 가드] 계획 1.5kn이면 min이 0.5kn이 되므로.
    ("SPEED", "DELTA", "-1.0000", "0.0000", "1.0000", "1.0000"),
)

_SOURCE_REF = "PRD §12.4.1"
_VERSION = "2026.08"
_DEFAULT_PROFILE = "DEFAULT"


def upgrade() -> None:
    op.create_table(
        "simulation_parameter",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("profile", sa.String(length=30), nullable=False),
        sa.Column("variable", sa.String(length=20), nullable=False),
        sa.Column("distribution", sa.String(length=20), nullable=False),
        sa.Column("bound_type", sa.String(length=10), nullable=False),
        sa.Column("min_value", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("mode_value", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("max_value", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("floor_value", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_parameter"),
        sa.CheckConstraint(
            "variable IN ('DISTANCE','FUEL','SPEED')", name="chk_sim_param_variable"
        ),
        sa.CheckConstraint("distribution IN ('TRIANGULAR')", name="chk_sim_param_distribution"),
        sa.CheckConstraint("bound_type IN ('FACTOR','DELTA')", name="chk_sim_param_bound_type"),
        # [ORACLE 삼각분포 가드] — 애플리케이션도 재조정하지만(계산이 파라미터 오타로
        # 죽지 않게), 애초에 위반한 행이 들어오지 않는 편이 낫다.
        sa.CheckConstraint(
            "min_value <= mode_value AND mode_value <= max_value",
            name="chk_sim_param_bounds_ordered",
        ),
        sa.CheckConstraint(
            "floor_value IS NULL OR floor_value > 0", name="chk_sim_param_floor_positive"
        ),
    )
    # 조회는 언제나 (프로파일, 변수) 단위다. 같은 조합이 둘이면 어느 쪽을 쓸지 알 수 없다.
    op.create_index(
        "idx_sim_param_unique",
        "simulation_parameter",
        ["profile", "variable"],
        unique=True,
    )

    rows = [
        {
            "profile": _DEFAULT_PROFILE,
            "variable": variable,
            "distribution": "TRIANGULAR",
            "bound_type": bound_type,
            "min_value": min_value,
            "mode_value": mode_value,
            "max_value": max_value,
            "floor_value": floor_value,
            "source_ref": _SOURCE_REF,
            "version": _VERSION,
        }
        for variable, bound_type, min_value, mode_value, max_value, floor_value in _DEFAULT_ROWS
    ]
    op.bulk_insert(
        sa.table(
            "simulation_parameter",
            sa.column("profile", sa.String),
            sa.column("variable", sa.String),
            sa.column("distribution", sa.String),
            sa.column("bound_type", sa.String),
            sa.column("min_value", sa.Numeric),
            sa.column("mode_value", sa.Numeric),
            sa.column("max_value", sa.Numeric),
            sa.column("floor_value", sa.Numeric),
            sa.column("source_ref", sa.String),
            sa.column("version", sa.String),
        ),
        rows,
    )


def downgrade() -> None:
    # 테이블째 지우므로 seed 행도 함께 사라진다 — 별도 DELETE가 필요 없다.
    op.drop_index("idx_sim_param_unique", table_name="simulation_parameter")
    op.drop_table("simulation_parameter")
