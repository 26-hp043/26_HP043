"""cii_reference_line 테이블

Revision ID: 010
Revises: 009
Create Date: 2026-07-18

DB_SCHEMA.md §2.10 (cii_reference_line: 컬럼/인덱스/검증 제약, [EXT-P0-1], [M-7]) 참조.
이슈 #103 체크리스트 010.

주의 (AGENTS §3, ROADMAP 가드레일):
- 이 마이그레이션은 스키마만 생성한다. seed 값(§3.3)은 넣지 않는다 — a_decimal 손입력
  금지, 값 주입은 #33 seed가 파서 #36(parse_imo_scientific)으로 수행한다.
- capacity_rule은 reference CII 공식에만 적용된다([EXT-P0-1] — attained CII의
  transport work에는 실제 DWT/GT 사용). 컬럼이 이 테이블에 속하는 근거.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | Sequence[str] | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "cii_reference_line",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("ship_type", sa.String(length=50), nullable=False),
        sa.Column("condition_expr", sa.String(length=200), nullable=False),
        sa.Column("capacity_rule", sa.String(length=50), nullable=False),
        # TECH_SPEC §9: a_raw(IMO 원문 표기) + a_decimal(변환값) 이중 저장.
        sa.Column("a_raw", sa.String(length=50), nullable=False),
        sa.Column("a_decimal", sa.Numeric(precision=30, scale=6), nullable=False),
        sa.Column("c", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cii_reference_line"),
        # §2.10 [M-7] (원문 그대로): 'fixed' 뒤에 숫자만 허용.
        sa.CheckConstraint(
            r"capacity_rule IN ('DWT','GT') OR capacity_rule ~ '^fixed \d+$'",
            name="chk_capacity_rule",
        ),
        sa.CheckConstraint("a_decimal > 0", name="chk_a_decimal_positive"),
        # c >= 0: LNG_CARRIER DWT >= 100000은 c = 0.000000이 정상([Oracle 관찰]).
        sa.CheckConstraint("c >= 0", name="chk_c_positive"),
    )

    # §2.10 인덱스 (원문 그대로).
    op.execute(
        "CREATE UNIQUE INDEX idx_refline_unique ON cii_reference_line (ship_type, condition_expr);"
    )
    op.execute("CREATE INDEX idx_refline_ship_type ON cii_reference_line (ship_type);")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("cii_reference_line")
