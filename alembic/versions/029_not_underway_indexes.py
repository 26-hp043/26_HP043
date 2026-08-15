"""not under way 테이블 인덱스 3종 보강

Revision ID: 029
Revises: 028
Create Date: 2026-08-15

이슈 #376 · 025가 만든 인덱스는 2종이며 #345 체크리스트의 범위는 충족한다. 다만
이후 확정된 후행 이슈의 조회 경로와 기존 테이블의 정합성 관례를 대조하면 3종이 더
필요하다. **이 중 (1)은 성능이 아니라 데이터 정합성 사안이다.**

(1) 중복 삽입 시 CO₂ 이중 산정 — 정합성
---------------------------------------
``idx_not_underway_fuel_use_period``는 UNIQUE가 아니라 같은 구간·소비원·연료 행이
두 번 들어갈 수 있다. ``#353``이 머지한 집계
(``repositories/not_underway.py::sum_fuel_by_type``)는 ``Σ(fuel_ton)``을 유종별로
합산하므로 중복분이 그대로 분자 ``M``에 더해지고, **등급이 실제보다 나쁘게** 나온다.

같은 문제를 ``voyage_fuel_use``에서 이미 겪고 UNIQUE로 막아 두었다 —
``DB_SCHEMA.md`` §2.3 **[S-2]**: *"중복 시 CII 계산에서 CO₂ 배출량이 이중 산정되는
치명적 버그가 발생한다."* (마이그레이션 006 ``idx_fuel_use_unique``)

``not_underway_fuel_use``는 ``consumer_type`` 축이 하나 더 있으므로 키가 3열이다.
MEPC.385(81) DCS 보고 단위가 「구간 × 소비원 × 연료」이므로 이 조합이 곧 사실상의
자연키다.

⚠️ 기존 UNIQUE가 아닌 ``idx_not_underway_fuel_use_period``는 **제거한다.** 새
UNIQUE 인덱스의 선행열이 ``period_id``로 같아 prefix 조회를 그대로 처리하므로
완전히 중복이며, 선례인 ``voyage_fuel_use``도 UNIQUE 인덱스 하나만 둔다. 남겨 두면
INSERT·DELETE마다 인덱스를 두 번 갱신한다.

(2) 구간 겹침 조회 경로 — 성능
------------------------------
``#368`` 시뮬레이션 시계는 ``(vessel_id, [t0, as_of])``로 겹치는 구간을 찾는다.
쓸 수 있는 인덱스가 ``(vessel_id, regulation_year)``뿐인데 ``regulation_year``가
선행열이 아니라 ``started_at`` 범위 조건이 인덱스로 내려가지 않는다 — 한 선박의
해당 연도 전 구간을 읽은 뒤 필터링하게 된다.

``is_deleted = false`` partial로 두는 것은 025의 ``vessel_year`` 인덱스 및
``idx_vessel_imo``와 같은 soft delete 관례다.

(3) voyage 삭제 시 SET NULL 확인 — 성능
---------------------------------------
``fk_not_underway_period_voyage``는 ``ON DELETE SET NULL``이다. PostgreSQL은 참조
자식 행을 찾아야 하는데 ``voyage_id`` 인덱스가 없으면 ``not_underway_period``
전체를 훑는다. 같은 이유로 ``voyage_scenario``에는 마이그레이션 023(``#97``)이
``idx_scenario_voyage``를 만들어 두었다.

여기에는 partial 조건을 걸지 않는다 — FK 확인은 ``is_deleted`` 여부와 무관하게
**모든** 자식 행을 봐야 하므로, 활성 행만 인덱싱하면 삭제된 행에서 다시 full scan이
난다.

기존 데이터 안전성
------------------
UNIQUE 인덱스는 기존 행에 중복이 있으면 생성에 실패한다. 027(``#347``) 시드가 넣는
6행의 ``(period_id, consumer_type, fuel_type)`` 조합을 전수 확인했고 중복은 0건이다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "029"
down_revision: str | Sequence[str] | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # (1) 정합성 — 같은 구간+소비원+연료 중복 방지. 중복 시 CO₂ 이중 산정(§2.3 [S-2]).
    op.create_index(
        "idx_not_underway_fuel_use_unique",
        "not_underway_fuel_use",
        ["period_id", "consumer_type", "fuel_type"],
        unique=True,
    )
    # 위 UNIQUE의 선행열이 period_id라 025의 단일열 인덱스는 완전히 중복된다.
    # voyage_fuel_use도 UNIQUE 하나만 둔다(006).
    op.drop_index("idx_not_underway_fuel_use_period", table_name="not_underway_fuel_use")

    # (2) #368 구간 겹침 조회 — started_at 범위 조건이 인덱스로 내려가게 한다.
    op.create_index(
        "idx_not_underway_period_vessel_started",
        "not_underway_period",
        ["vessel_id", "started_at"],
        postgresql_where=sa.text("is_deleted = false"),
    )

    # (3) voyage 삭제 시 SET NULL 확인이 full scan 하지 않도록(023 idx_scenario_voyage 패턴).
    # FK 확인은 삭제된 행도 봐야 하므로 partial로 두지 않는다.
    op.create_index(
        "idx_not_underway_period_voyage",
        "not_underway_period",
        ["voyage_id"],
    )


def downgrade() -> None:
    """Downgrade schema — 025가 만든 인덱스 구성으로 되돌린다."""
    op.drop_index("idx_not_underway_period_voyage", table_name="not_underway_period")
    op.drop_index("idx_not_underway_period_vessel_started", table_name="not_underway_period")
    # 025 상태 복원 — UNIQUE를 지우기 전에 단일열 인덱스를 되살린다.
    op.create_index(
        "idx_not_underway_fuel_use_period",
        "not_underway_fuel_use",
        ["period_id"],
    )
    op.drop_index("idx_not_underway_fuel_use_unique", table_name="not_underway_fuel_use")
