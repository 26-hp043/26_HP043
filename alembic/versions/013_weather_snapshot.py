"""weather_snapshot 테이블 + voyage_scenario FK 상환

Revision ID: 013
Revises: 012
Create Date: 2026-07-18

DB_SCHEMA.md §2.13 (weather_snapshot: 컬럼/캐시 인덱스), §7.1 (FK 정책) 참조.
이슈 #103 체크리스트 013.

주의:
- 007이 미뤄둔 FK를 여기서 상환한다: 007은 weather_snapshot 테이블 부재로
  voyage_scenario.weather_snapshot_id를 컬럼만 생성했다(007 docstring 예고).
  참조 대상이 생기는 이 리비전에서 fk_voyage_scenario_weather(ON DELETE SET NULL,
  §7.1)를 함께 추가해 원자성을 보장한다. downgrade는 FK를 먼저 드롭해야
  테이블 드롭이 가능하다.
- 자식 인덱스(voyage_scenario.weather_snapshot_id)는 #97 스코프(FK 자식 인덱스
  일원화 — #97 코멘트 참조)라 여기서 만들지 않는다.
- TTL 24시간은 코드에서 구현한다(§2.13 — DB는 데이터 저장만). TTL은 재사용 판단
  창이지 삭제 스케줄이 아니다(§2.13 [#102], PR #109).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | Sequence[str] | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "weather_snapshot",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=False),
        # 캐시 key용 반올림 좌표 (§2.13).
        sa.Column("lat_rounded", sa.Numeric(precision=4, scale=1), nullable=False),
        sa.Column("lon_rounded", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wave_height_m", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("wave_direction_deg", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("wave_period_s", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("wind_speed_ms", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("wind_direction_deg", sa.Numeric(precision=6, scale=2), nullable=True),
        # open_meteo_marine, open_meteo_forecast, sample (§2.13 설명 — CHECK는 정본에 없음).
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weather_snapshot"),
    )

    # §2.13 캐시 인덱스 (원문 그대로).
    op.execute(
        "CREATE INDEX idx_weather_cache "
        "ON weather_snapshot (lat_rounded, lon_rounded, fetched_at DESC);"
    )

    # §7.1: 007이 미뤄둔 FK 상환. 기상 스냅샷 만료(행 삭제) 시 시나리오 보존 → SET NULL.
    op.create_foreign_key(
        "fk_voyage_scenario_weather",
        "voyage_scenario",
        "weather_snapshot",
        ["weather_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 참조하는 FK를 먼저 드롭해야 피참조 테이블을 드롭할 수 있다.
    op.drop_constraint("fk_voyage_scenario_weather", "voyage_scenario", type_="foreignkey")
    op.drop_table("weather_snapshot")
