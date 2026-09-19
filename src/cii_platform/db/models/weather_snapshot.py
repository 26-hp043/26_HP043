"""weather_snapshot ORM 모델.

DB_SCHEMA.md §2.13 (weather_snapshot) 참조. 컬럼·인덱스 정의는
마이그레이션 013과 1:1로 일치해야 한다 (zero drift — tests/test_orm_schema_sync.py에서 검증).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import UuidText


class WeatherSnapshot(Base):
    """기상 스냅샷: Open-Meteo API 응답 캐시."""

    __tablename__ = "weather_snapshot"

    id = sa.Column(
        UuidText,
        primary_key=True,
        default=uuid.uuid4,
    )
    lat = sa.Column(sa.Numeric(precision=9, scale=6), nullable=False)
    lon = sa.Column(sa.Numeric(precision=9, scale=6), nullable=False)
    # 캐시 key용 반올림 좌표 (§2.13).
    lat_rounded = sa.Column(sa.Numeric(precision=4, scale=1), nullable=False)
    lon_rounded = sa.Column(sa.Numeric(precision=5, scale=1), nullable=False)
    fetched_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    wave_height_m = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    wave_direction_deg = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    wave_period_s = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    wind_speed_ms = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    wind_direction_deg = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    # open_meteo_marine+forecast(기본) · open_meteo_marine · open_meteo_forecast · sample
    # (§2.13 값 목록 · 정본은 TECH_SPEC §7.1 — 집행 CHECK·트리거는 없다, #968).
    source = sa.Column(sa.String(length=50), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_weather_snapshot"),
        # §2.13 캐시 인덱스 (원문 그대로 — DESC는 컬럼 객체 .desc()로 표현).
        sa.Index("idx_weather_cache", lat_rounded, lon_rounded, fetched_at.desc()),
    )
