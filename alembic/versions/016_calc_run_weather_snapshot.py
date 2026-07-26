"""calculation_run.weather_snapshot_id 컬럼 + FK + 자식 인덱스

Revision ID: 016
Revises: 015
Create Date: 2026-07-26

DB_SCHEMA.md §2.5 [#102] (weather_snapshot_id 컬럼 스펙), §7.1 (FK 정책, 833행),
§2.13 [#102] (TTL과 보존의 구분) 참조. 이슈 #115.

#102(PR #109)가 스펙만 확정하고 "016+ 후속 마이그레이션"으로 미뤄둔 실물 컬럼을
상환한다. 당시 미룬 이유는 참조 대상인 weather_snapshot 테이블(013)이 없었기
때문이며, 013이 머지되어 이제 추가할 수 있다.

주의:
- FK는 §7.1 정본대로 ON DELETE RESTRICT다. calculation_run은 immutable(§7.3,
  BEFORE UPDATE OR DELETE 트리거)이라 SET NULL(자식 UPDATE)이 트리거에 차단되어
  원리적으로 달성 불가능하다. 실효 동작이 RESTRICT이며 voyage_id(#28)와 대칭이다.
- NULL을 허용한다. weather_model = NONE·캐시 만료 fallback(TECH_SPEC §7.3)은
  스냅샷 없이 계산하는 정상 경로이고, immutable 트리거 때문에 기존 행 backfill도
  불가능하다(§2.5 [#102] NULL 허용 근거).
- 자식 인덱스 idx_calc_weather_snapshot을 함께 만든다(이슈 체크리스트 외 항목).
  PostgreSQL은 FK 자식 컬럼에 인덱스를 자동 생성하지 않으므로, RESTRICT 검사가
  weather_snapshot DELETE마다 calculation_run을 full scan한다. §2.13 [#102]이
  eviction을 "참조되지 않는 행만 삭제"로 규정하여 이 경로가 상시 동작하고,
  calculation_run은 계산 실행마다 누적되어 가장 크게 자란다. #97은 007·009만
  대상으로 하여 이 인덱스를 담당하는 이슈가 없다. 경위는 #115 코멘트 참조.
- ALTER TABLE ADD/DROP COLUMN은 DDL이므로 FOR EACH ROW 트리거(trg_calcrun_immutable)에
  걸리지 않는다. 행 단위 UPDATE/DELETE만 차단된다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str | Sequence[str] | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # §2.5 [#102]: 계산에 사용한 기상 스냅샷. NONE 모델·fallback 계산은 NULL.
    op.add_column(
        "calculation_run",
        sa.Column("weather_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # §7.1 (833행): immutable 테이블 참조 → RESTRICT. 참조된 스냅샷은 TTL과 무관하게
    # 보존되어야 재현성 계약(TECH_SPEC §5.4)의 추적성이 성립한다(§2.13 [#102]).
    op.create_foreign_key(
        "fk_calculation_run_weather_snapshot",
        "calculation_run",
        "weather_snapshot",
        ["weather_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # FK 자식 인덱스: RESTRICT 검사가 full scan이 되지 않도록 한다(파일 상단 주의 참조).
    op.execute("CREATE INDEX idx_calc_weather_snapshot ON calculation_run (weather_snapshot_id);")


def downgrade() -> None:
    """Downgrade schema."""
    # 컬럼을 드롭하면 딸린 인덱스·FK도 함께 사라지지만, 생성의 역순으로 명시한다.
    op.execute("DROP INDEX idx_calc_weather_snapshot;")
    op.drop_constraint("fk_calculation_run_weather_snapshot", "calculation_run", type_="foreignkey")
    op.drop_column("calculation_run", "weather_snapshot_id")
