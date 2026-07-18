"""ORM 모델 ↔ 실제 DB 스키마 동기화(zero drift) 검증 (#101).

Alembic autogenerate의 비교 엔진(compare_metadata)으로 두 방향을 검증한다:

1. zero drift — ``Base.metadata``(ORM 모델)와 마이그레이션이 만든 실제 DB가
   일치하여 diff가 비어 있어야 한다. 이후 누군가 모델만 고치고 마이그레이션을
   만들지 않으면(또는 그 반대) 이 테스트가 CI에서 실패한다.
2. 감지 능력 — 비교 엔진이 실제로 차이를 감지하는지 canary 테이블로 확인한다.
   (1번이 "diff 없음"만 보므로, 비교가 아예 동작하지 않아도 통과하는 위양성을
   차단한다. 이슈 #101 체크리스트의 "일부러 컬럼 추가 후 감지 확인"을 CI에서
   상시 실행 가능한 형태로 옮긴 것.)

읽기 전용 비교만 수행하며 DDL은 실행하지 않는다.
"""

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from cii_platform.db.models import Base


def _compare(sync_conn, metadata: sa.MetaData) -> list:
    """현재 DB와 metadata를 비교해 autogenerate diff 목록을 반환한다."""
    ctx = MigrationContext.configure(
        sync_conn,
        # 타입 변경도 감지한다. server_default는 텍스트 표기 차이(now() 등)로
        # 오탐이 잦아 비교에서 제외한다(기본값). — 2단계 결정 2-A.
        opts={"compare_type": True},
    )
    return compare_metadata(ctx, metadata)


async def test_orm_models_match_db_zero_drift(conn):
    """8개 테이블 ORM 모델이 마이그레이션 결과 DB와 정확히 일치한다."""
    diffs = await conn.run_sync(_compare, Base.metadata)
    assert diffs == [], f"ORM 모델과 DB 스키마가 불일치:\n{diffs}"


async def test_compare_engine_detects_drift(conn):
    """비교 엔진이 모델↔DB 차이를 실제로 감지한다 (canary 테이블)."""
    canary_metadata = sa.MetaData()
    sa.Table(
        "orm_drift_canary",
        canary_metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    diffs = await conn.run_sync(_compare, canary_metadata)
    # canary는 DB에 없으므로 add_table diff가 나와야 한다.
    added = [d for d in diffs if d[0] == "add_table" and d[1].name == "orm_drift_canary"]
    assert added, f"비교 엔진이 canary 테이블 추가를 감지하지 못함:\n{diffs}"
