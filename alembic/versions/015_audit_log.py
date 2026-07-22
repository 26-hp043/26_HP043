"""audit_log 테이블

Revision ID: 015
Revises: 014
Create Date: 2026-07-18

DB_SCHEMA.md §2.14 (audit_log: 컬럼/인덱스, [Oracle 관찰 #4]) 참조.
이슈 #103 체크리스트 015. TECH_SPEC §13.1 요구사항.

주의 (이슈 본문 대비 정본 우선, AGENTS §3):
- #103이 흡수한 구 이슈 #32 본문의 diff_json(TEXT)·created_at은 정본 §2.14의
  details_json(JSONB)·timestamp가 정본이다. action 값도 §2.14의 6종
  (PARAMETER_CHANGE 등)이며 #32의 CREATE/UPDATE/DELETE가 아니다. 단 action에
  CHECK 제약은 정본에 정의되어 있지 않으므로 추가하지 않는다.
- entity_type은 [Oracle 관찰 #4]에 따라 'parameter' 대신 구체 테이블명을 사용한다.
- audit_log는 §7.3 immutable 지정 대상이 아니다(트리거 없음). 감사 로그 기록
  기능은 #65(Layer 8)에서 구현하며, 그 전에는 이 테이블을 읽어 표시하지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str | Sequence[str] | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # §2.14: 이벤트 시각. created_at을 겸한다(정본에 별도 created_at 없음).
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        # PARAMETER_CHANGE, VOYAGE_CONFIRM, CALCULATION_RUN, VOYAGE_TRANSITION,
        # IMPORT, EXPORT (§2.14 설명 — CHECK는 정본에 없음).
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
        # IPv6 최대 45자 (§2.14).
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )

    # §2.14 인덱스 (원문 그대로). timestamp는 예약어와 겹쳐 인용 부호로 감싼다.
    op.execute('CREATE INDEX idx_audit_timestamp ON audit_log ("timestamp" DESC);')
    op.execute("CREATE INDEX idx_audit_entity ON audit_log (entity_type, entity_id);")
    op.execute('CREATE INDEX idx_audit_action ON audit_log (action, "timestamp" DESC);')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("audit_log")
