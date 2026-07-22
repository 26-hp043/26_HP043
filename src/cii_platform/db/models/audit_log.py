"""audit_log ORM 모델.

DB_SCHEMA.md §2.14 (audit_log) 참조. 컬럼·인덱스 정의는
마이그레이션 015와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class AuditLog(Base):
    """감사 로그: 시스템 이벤트 기록."""

    __tablename__ = "audit_log"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    # §2.14: 이벤트 시각. created_at을 겸한다(정본에 별도 created_at 없음).
    timestamp = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    user_id = sa.Column(sa.String(length=100), nullable=True)
    # PARAMETER_CHANGE, VOYAGE_CONFIRM, CALCULATION_RUN, VOYAGE_TRANSITION,
    # IMPORT, EXPORT (§2.14 설명 — CHECK는 정본에 없음).
    action = sa.Column(sa.String(length=50), nullable=False)
    entity_type = sa.Column(sa.String(length=30), nullable=True)
    entity_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=True)
    details_json = sa.Column(postgresql.JSONB(), nullable=True)
    # IPv6 최대 45자 (§2.14).
    ip_address = sa.Column(sa.String(length=45), nullable=True)

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        # §2.14 인덱스 (원문 그대로 — DESC는 컬럼 객체 .desc()로 표현).
        sa.Index("idx_audit_timestamp", timestamp.desc()),
        sa.Index("idx_audit_entity", entity_type, entity_id),
        sa.Index("idx_audit_action", action, timestamp.desc()),
    )
