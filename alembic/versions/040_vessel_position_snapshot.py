"""선박 위치 스냅샷 테이블 신설

Revision ID: 040
Revises: 039
Create Date: 2026-09-12

이슈 #764 · **위치에 이력이 없었다.**

무엇을 만드나
--------------
``vessel_position_snapshot`` — 선박의 위치를 **관측 시각과 함께 한 행씩** 쌓는다.

종전에는 ``vessel.current_lat/lon``(026) 하나뿐이라 새 값이 들어오면 **직전 값이
사라졌다.** 「지금 어디인가」는 알 수 있어도 「어디를 지나왔는가」는 남지 않는다.
자동 수집(AIS)은 값을 **자주** 밀어 넣으므로, 덮어쓰기만 있는 구조 위에 올리면
수집할수록 잃는 것이 늘어난다.

출처를 행에 적는다
------------------
``source``가 ``MANUAL``(사람이 입력) · ``AIS``(자동 수집) · ``SIMULATED``
(시뮬레이션 시계 · ``TECH_SPEC §5.4.1``) 셋을 가른다. ``PRD R-5``의 「시뮬레이션
데이터」 배지가 이 구분에 기댄다 — **한 항차 안에서 실측과 시계가 섞이므로**
선박 단위 플래그 하나로는 말할 수 없다.

관측 시각과 수신 시각을 나눈다
------------------------------
``observed_at``은 **배가 그 자리에 있던 시각**이고 ``received_at``은 **우리가 받은
시각**이다. AIS는 지연·재전송이 있어 둘이 벌어지며, 신선도를 ``received_at``으로
재면 「30분 전 위치를 방금 받았다」가 최신으로 읽힌다.

왜 지금 만드나 — 붙일 AIS가 아직 없는데
---------------------------------------
데모 선박 5척의 IMO는 **합성값**이라(``036``) 어떤 AIS 출처도 이 배들을 주지
않는다. 그래서 이 마이그레이션이 여는 것은 **수집 경로의 자리**이고, 지금 당장
채우는 것은 **사람이 넣는 위치**(``MANUAL``)다. 표가 비어 있는 채로 기다리지
않는다 — 그래야 AIS가 붙는 날 이 경로가 이미 검증돼 있다.

되돌리기
--------
``downgrade``는 표를 지운다. **수집한 위치 이력은 다시 만들 수 없다** — 지나간
시각의 좌표를 되살릴 방법이 없다. ``IRREVERSIBLE``로 분류한다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vessel_position_snapshot",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=False),
        # 대지속력·대지침로. AIS가 주는 값이고 사람이 넣을 때는 비어 있다.
        sa.Column("sog_kn", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("cog_deg", sa.Numeric(precision=6, scale=2), nullable=True),
        # ITU-R M.1371 항행 상태 코드(0~15). 운항 상태 파생의 근거이며, **파생 결과가
        # 아니라 원본**을 적는다 — 매핑 규칙이 바뀌어도 과거 행을 다시 읽을 수 있다.
        sa.Column("nav_status", sa.SmallInteger(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vessel_position_snapshot"),
        # 선박을 물리 삭제하려 해도 위치 이력이 있으면 막는다 — `not_underway_period`와
        # 같은 규약이다(`DB_SCHEMA §7.1`).
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
        # 026의 vessel 위경도와 같은 범위. 값이 들어오는 문이 늘었으므로 문마다 건다.
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
    )
    # 조회는 늘 「이 배의 최신 한 건」 또는 「이 배의 구간」이다.
    op.create_index(
        "idx_vessel_position_snapshot_vessel_observed",
        "vessel_position_snapshot",
        ["vessel_id", sa.text("observed_at DESC")],
    )
    # 같은 출처가 같은 관측 시각을 두 번 밀어 넣어도 한 행이다 — AIS는 재전송이
    # 정상이고, 중복을 받으면 항적이 같은 점에서 여러 번 꺾인 것처럼 보인다.
    op.create_index(
        "uq_vessel_position_snapshot_observation",
        "vessel_position_snapshot",
        ["vessel_id", "source", "observed_at"],
        unique=True,
    )


def downgrade() -> None:
    """표를 지운다 — **지나간 시각의 좌표는 되살릴 방법이 없다.**

    AIS는 재조회로 과거를 주지 않고(aisstream.io는 끊긴 구간 복구가 없다), 사람이
    넣은 위치는 애초에 재현 불가다. 그래서 프로덕션에서는 막는다
    (``DB_SCHEMA §8.1.2`` · #819).
    """
    guard_irreversible_downgrade("040")
    op.drop_index("uq_vessel_position_snapshot_observation", table_name="vessel_position_snapshot")
    op.drop_index(
        "idx_vessel_position_snapshot_vessel_observed", table_name="vessel_position_snapshot"
    )
    op.drop_table("vessel_position_snapshot")
