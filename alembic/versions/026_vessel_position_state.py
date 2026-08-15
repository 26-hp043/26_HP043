"""vessel 현재 위치·운항 상태 컬럼

Revision ID: 026
Revises: 025
Create Date: 2026-08-15

이슈 #346 · UIFLOW v2.0 §2-4(``detail_status`` 7값): 대시보드·선박 상세 화면이
표시할 선박의 **현재 위치와 운항 상태**를 ``vessel``에 추가한다. 종전
``DB_SCHEMA §2.1``은 13컬럼이며 위치·상태 컬럼이 없었다.

**상태 2축 분리 (#346 설계 결정)**

- ``underway_state`` 2값 — **계산 축**. CII 집계 로직은 「항해 중이냐」 이진 판단만
  필요하다. 계산 코드가 7값을 전부 알면 하위 호환 없이 값이 늘 때마다 깨진다.
- ``detail_status`` 7값 — **화면 축**. 「묵박 중」·「운하 통과 중」을 구분해 보여준다.
  SAILING을 제외한 6값은 ``not_underway_period.period_type``(025)의 값과 1:1로
  대응한다.

**정합 규칙 (CHECK)**

1. ``underway_state``·``detail_status``는 **둘 다 NULL 또는 둘 다 설정** — 반쪽 상태를
   허용하지 않는다.
2. ``detail_status = 'SAILING'`` ↔ ``underway_state = 'UNDER_WAY'`` (UIFLOW §2-4
   표에서 under way인 값은 이것뿐).
3. 나머지 6값 ↔ ``underway_state = 'NOT_UNDER_WAY'``.
4. 위치 페어링 — ``current_lat``·``current_lon``은 둘 다 NULL 또는 둘 다 설정.
   위치가 있으면 ``position_updated_at``도 필수다 — 화면이 「위치 갱신 시각」을
   표시하므로(UIFLOW §2-8) 시각 없는 위치는 표시 계약을 깨뜨린다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "026"
down_revision: str | Sequence[str] | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vessel", sa.Column("underway_state", sa.String(length=20), nullable=True))
    op.add_column("vessel", sa.Column("detail_status", sa.String(length=20), nullable=True))
    op.add_column(
        "vessel", sa.Column("current_lat", sa.Numeric(precision=9, scale=6), nullable=True)
    )
    op.add_column(
        "vessel", sa.Column("current_lon", sa.Numeric(precision=9, scale=6), nullable=True)
    )
    op.add_column(
        "vessel",
        sa.Column("position_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "chk_underway_state_allowed",
        "vessel",
        "underway_state IS NULL OR underway_state IN ('UNDER_WAY','NOT_UNDER_WAY')",
    )
    op.create_check_constraint(
        "chk_detail_status_allowed",
        "vessel",
        "detail_status IS NULL OR detail_status IN "
        "('SAILING','IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK')",
    )
    op.create_check_constraint(
        "chk_vessel_state_pair",
        "vessel",
        "(underway_state IS NULL AND detail_status IS NULL) "
        "OR (underway_state = 'UNDER_WAY' AND detail_status = 'SAILING') "
        "OR (underway_state = 'NOT_UNDER_WAY' AND detail_status IN "
        "('IN_PORT','AT_ANCHOR','DRIFTING','STS','CANAL_TRANSIT','DRYDOCK'))",
    )
    op.create_check_constraint(
        "chk_vessel_lat_range",
        "vessel",
        "current_lat IS NULL OR current_lat BETWEEN -90 AND 90",
    )
    op.create_check_constraint(
        "chk_vessel_lon_range",
        "vessel",
        "current_lon IS NULL OR current_lon BETWEEN -180 AND 180",
    )
    op.create_check_constraint(
        "chk_vessel_position_pair",
        "vessel",
        "(current_lat IS NULL AND current_lon IS NULL) "
        "OR (current_lat IS NOT NULL AND current_lon IS NOT NULL "
        "AND position_updated_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("chk_vessel_position_pair", "vessel", type_="check")
    op.drop_constraint("chk_vessel_lon_range", "vessel", type_="check")
    op.drop_constraint("chk_vessel_lat_range", "vessel", type_="check")
    op.drop_constraint("chk_vessel_state_pair", "vessel", type_="check")
    op.drop_constraint("chk_detail_status_allowed", "vessel", type_="check")
    op.drop_constraint("chk_underway_state_allowed", "vessel", type_="check")
    op.drop_column("vessel", "position_updated_at")
    op.drop_column("vessel", "current_lon")
    op.drop_column("vessel", "current_lat")
    op.drop_column("vessel", "detail_status")
    op.drop_column("vessel", "underway_state")
