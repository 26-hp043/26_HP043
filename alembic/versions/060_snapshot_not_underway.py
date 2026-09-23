"""simulation_snapshot.not_underway_json — 연말 예상에 넣은 정박·묘박 몫 사본 (#1803)

Revision ID: 060
Revises: 059
Create Date: 2026-09-23

왜 필요한가
-----------
연말 예상이 올해 **이미 쓴** 정박·묘박 연료를 확정분에 넣게 됐다(``PRD §12.3`` · #1803).
그 값은 계산 입력이므로 스냅샷에 남아야 재현이 스냅샷만으로 같은 결과를 낸다
(``TECH_SPEC §11.4`` 2항). ``voyages_json`` 배열에 행으로 섞지 않는 이유 — 그 배열은
**항차**의 사본이고, 항차 수(``voyage_count``)·스냅샷 항차 조회(``§6.x`` snapshot-voyages)가
배열 길이와 행을 그대로 항차로 읽는다.

**``NULL``은 「정박 몫을 넣지 않은 실행」이다.** 정박 기록이 없던 실행과 이 마이그레이션
이전 실행이 여기에 든다. 둘 다 원본이 정박을 넣지 않고 계산했고 ``input_hash`` 재료에도
키가 없으므로, 재현은 NULL 그대로 같은 입력을 만든다. backfill하지 않는다 — 이 테이블은
immutable이다(``trg_snapshot_immutable``).

downgrade
---------
열을 지우면 그 사이 저장된 실행의 정박 몫이 사라지고, 다시 upgrade해도 **채울 방법이
없다**(immutable). 그 실행들은 해시 재료를 잃어 재현이 깨진다 — ``037``(``vessel_json``)과
같은 성질이라 ``migration_guard``의 ``IRREVERSIBLE``로 분류한다.
"""

import sqlalchemy as sa

from alembic import op
from cii_platform.db.migration_guard import guard_irreversible_downgrade
from cii_platform.db.types import JSONText

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("simulation_snapshot", sa.Column("not_underway_json", JSONText(), nullable=True))


def downgrade() -> None:
    guard_irreversible_downgrade("060")
    op.drop_column("simulation_snapshot", "not_underway_json")
