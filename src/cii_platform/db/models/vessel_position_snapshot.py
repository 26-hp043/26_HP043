"""선박 위치 스냅샷 (``DB_SCHEMA §2.21`` · `#764`).

``vessel.current_lat/lon``(026)은 **덮어쓰는 한 칸**이라 「지금 어디인가」만 말한다.
이 표는 **관측 시각과 함께 한 행씩** 쌓아 「어디를 지나왔는가」를 남긴다.

``source``가 ``MANUAL``·``AIS``·``SIMULATED``를 가른다. ``PRD R-5``의 「시뮬레이션
데이터」 배지가 이 구분에 기대며, **한 항차 안에서 실측과 시계가 섞이므로** 선박
단위 플래그 하나로는 말할 수 없다.

``observed_at``(배가 그 자리에 있던 시각)과 ``received_at``(우리가 받은 시각)을
나눈 이유는 AIS에 지연·재전송이 있기 때문이다 — ``received_at``으로 신선도를 재면
「30분 전 위치를 방금 받았다」가 최신으로 읽힌다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class VesselPositionSnapshot(Base):
    """한 선박·한 시각의 위치 한 건."""

    __tablename__ = "vessel_position_snapshot"

    # id: UUID v4 PK (DB_SCHEMA §0.1). 서버측 gen_random_uuid()로 v4 생성 (PG13+ 내장).
    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    vessel_id = sa.Column(postgresql.UUID(as_uuid=True), nullable=False)
    source = sa.Column(sa.String(length=20), nullable=False)
    lat = sa.Column(sa.Numeric(precision=9, scale=6), nullable=False)
    lon = sa.Column(sa.Numeric(precision=9, scale=6), nullable=False)
    sog_kn = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    cog_deg = sa.Column(sa.Numeric(precision=6, scale=2), nullable=True)
    #: ITU-R M.1371 항행 상태 코드(0~15). **파생 결과가 아니라 원본**을 적는다 —
    #: 매핑 규칙이 바뀌어도 과거 행을 다시 읽을 수 있다.
    nav_status = sa.Column(sa.SmallInteger(), nullable=True)
    observed_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    received_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_vessel_position_snapshot"),
        # §7.1: 위치 이력이 있는 선박은 물리 삭제 거부.
        sa.ForeignKeyConstraint(
            ["vessel_id"],
            ["vessel.id"],
            name="fk_vessel_position_snapshot_vessel",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "source IN ('MANUAL','AIS','SIMULATED')",
            name="chk_vessel_position_snapshot_source",
        ),
        sa.CheckConstraint("lat BETWEEN -90 AND 90", name="chk_vessel_position_snapshot_lat"),
        sa.CheckConstraint("lon BETWEEN -180 AND 180", name="chk_vessel_position_snapshot_lon"),
        sa.CheckConstraint(
            "sog_kn IS NULL OR sog_kn >= 0", name="chk_vessel_position_snapshot_sog"
        ),
        sa.CheckConstraint(
            "cog_deg IS NULL OR (cog_deg >= 0 AND cog_deg < 360)",
            name="chk_vessel_position_snapshot_cog",
        ),
        sa.CheckConstraint(
            "nav_status IS NULL OR (nav_status >= 0 AND nav_status <= 15)",
            name="chk_vessel_position_snapshot_nav_status",
        ),
        sa.Index(
            "idx_vessel_position_snapshot_vessel_observed",
            "vessel_id",
            sa.text("observed_at DESC"),
        ),
        # 같은 출처가 같은 관측 시각을 두 번 밀어 넣어도 한 행이다 — AIS는 재전송이
        # 정상이고, 중복을 받으면 항적이 같은 점에서 여러 번 꺾인 것처럼 보인다.
        sa.Index(
            "uq_vessel_position_snapshot_observation",
            "vessel_id",
            "source",
            "observed_at",
            unique=True,
        ),
    )
