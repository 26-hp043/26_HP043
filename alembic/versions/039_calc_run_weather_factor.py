"""calculation_run.weather_factor 컬럼

Revision ID: 039
Revises: 038
Create Date: 2026-09-12

DB_SCHEMA.md §2.5 · TECH_SPEC §5.4 4항 (#904). 이슈 #904 — C안(실물 컬럼).

``TECH_SPEC §5.4``가 ``weather_factor``를 재현성 계약의 대상으로 규정하는데, 그 값이
어디에도 기록되지 않았다 — ``result_json``·``parameters_used`` 어느 쪽에도 없다
(라이브 덤프 확인, #904). ``weather_model = NONE``만 쓰이는 동안에는 인자가 항상
1.0이라 증상이 없고, 기상 모델이 켜지는 순간 같은 입력으로 재현해도 그때의 인자를
알 수 없게 된다.

위치를 **실물 컬럼**(``weather_snapshot_id`` 옆)으로 정한 근거 (#904):

- **A안(result_json)** — ``result_json``은 ``API_SPEC §4.1`` ``data`` 블록과 같은
  dict를 그대로 쓴다. 넣으면 API 응답 계약이 함께 바뀐다.
- **B안(parameters_used)** — 「요청마다 달라지는 값을 넣지 않는다」는 그 쪽의
  명시적 규율과 충돌한다.
- **C안(컬럼)** — ``weather_snapshot_id``와 같은 층이다. 하나는 출처, 하나는 그
  출처에서 유도한 인자. 스냅샷 ID만으로는 어떤 인자가 나왔는지 재계산해야 알고,
  경험식이 바뀌면 그 재계산이 달라진다.

주의:
- NULL을 허용한다. 이 컬럼 이전의 행은 값이 없으며, immutable 트리거(024) 때문에
  backfill할 수 없다(#751 옛 형식 폴백 선례). **읽는 쪽은 NULL을 1.0으로 해석한다**
  — 이 컬럼이 생기기 전의 계산은 전부 ``weather_model = NONE``(인자 1.0) 시대다.
- ALTER TABLE ADD COLUMN은 DDL이라 trg_calcrun_immutable에 걸리지 않는다(016과 같은
  근거).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade

# revision identifiers, used by Alembic.
revision: str = "039"
down_revision: str | Sequence[str] | None = "038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # §2.5 [#904]: 계산에 사용한 기상 보정 계수. voyage_scenario과 같은 스케일.
    # 과거 행은 NULL — 읽는 쪽이 1.0으로 해석한다(파일 상단 주의).
    op.add_column(
        "calculation_run",
        sa.Column("weather_factor", sa.Numeric(precision=8, scale=4), nullable=True),
    )


def downgrade() -> None:
    """``weather_factor`` 열을 지운다. **기존 계산의 기상 인자는 복원되지 않는다.**

    되돌린 뒤 다시 ``upgrade``하면 열은 생기지만 기존 행은 영원히 NULL이다 —
    어느 계산이 어떤 기상 인자로 돌았는지가 사라진다(016과 같은 구조).

    그래서 프로덕션에서는 막는다(``DB_SCHEMA §8.1.2`` · #819).
    """
    # 운영 데이터를 복구 불가능하게 지운다 — 프로덕션에서는 막는다 (#819).
    guard_irreversible_downgrade("039")
    op.drop_column("calculation_run", "weather_factor")
