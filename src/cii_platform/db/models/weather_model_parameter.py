"""weather_model_parameter ORM 모델.

DB_SCHEMA.md §2.12 (weather_model_parameter) 참조. 컬럼·인덱스 정의는
마이그레이션 012와 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid

from datetime import datetime, timezone

import sqlalchemy as sa

from cii_platform.db.models.base import Base


class WeatherModelParameter(Base):
    """기상 모델 파라미터: Townsin-Kwon 저항 계산용 계수."""

    __tablename__ = "weather_model_parameter"

    id = sa.Column(
        sa.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    # NONE, SIMPLE_RULE, TOWNSIN_KWON_ALPHA (§2.12 설명 — CHECK는 정본에 없음).
    model_version = sa.Column(sa.String(length=50), nullable=False)
    key = sa.Column(sa.String(length=100), nullable=False)
    value = sa.Column(sa.String(length=200), nullable=False)
    unit = sa.Column(sa.String(length=30), nullable=True)
    source_ref = sa.Column(sa.String(length=200), nullable=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_weather_model_parameter"),
        # §2.12 [S-5] (원문 그대로): (model_version, key) 조합의 유일성 보장.
        sa.Index(
            "idx_weather_param_unique",
            "model_version",
            "key",
            unique=True,
        ),
    )
