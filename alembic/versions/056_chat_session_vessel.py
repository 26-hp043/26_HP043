"""chat_session.vessel_id — 대화에 선박 귀속을 둔다 (#1242)

Revision ID: 056
Revises: 055
Create Date: 2026-09-19

왜 필요한가
-----------
``search_vessel`` 도구가 선박을 찾아도 그 결과가 어디에도 남지 않아, 화면이
``vessel_id``를 주지 않는 대화(대시보드 등)에서는 계산 도구가 매번 「어느 선박인지
먼저 정해야 합니다」로 떨어졌다. 도구 설명은 「찾은 선박을 서버가 알아서 쓴다」고
모델에게 말하고 있는데 서버는 그렇게 하지 않았다 — 검색→계산→검색 반복이 도구
예산(``MAX_TOOL_CALLS_PER_TURN``)을 소진시켰다.

우선순위는 **요청 ``vessel_id``(화면) > 세션 귀속(검색으로 정한 것)** — 화면이 넘긴
값이 항상 더 최신이므로 세션이 화면값을 덮어쓰지 않는다(``API_SPEC §15.1``).

``ON DELETE SET NULL``
----------------------
선박이 지워져도(SQL 삭제 — 운영은 soft delete지만 향후 대비) **대화는 남고 귀속만
푼다**. ``fleet_reduction_plan.created_by``와 같은 선례다. FK 참조 무결성의 자식
쪽(없는 선박을 가리키지 못함)은 DB가 강제한다.
"""

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

_TABLE = "chat_session"
_FK = "fk_chat_session_vessel"
_COLUMN = "vessel_id"


def upgrade() -> None:
    # UuidText의 저장 형식은 CHAR(32) hex다(db/types.py · #1058).
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} CHAR(32)")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_FK} FOREIGN KEY ({_COLUMN}) "
        "REFERENCES vessel(id) ON DELETE SET NULL ON UPDATE RESTRICT"
    )


def downgrade() -> None:
    """구조만 되돌린다 — 귀속을 잃어도 대화·메시지는 그대로다(데이터 무변)."""
    op.execute(f"ALTER TABLE {_TABLE} DROP FOREIGN KEY {_FK}")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {_COLUMN}")
