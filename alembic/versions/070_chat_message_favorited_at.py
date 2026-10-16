"""챗봇 답 즐겨찾기 — ``chat_message.favorited_at`` (#2405)

Revision ID: 070
Revises: 069
Create Date: 2026-10-16

왜 필요한가
-----------
사용자가 다시 보고 싶은 답에 별을 달고, 패널 안 목록에서 그 대화를 열람 전용으로 다시
연다(#2405 결정). 별은 **답 한 건**에 단다.

왜 별도 표가 아닌가
-------------------
별은 대화와 함께 90일 뒤 지워져야 한다(결정). 메시지 행의 열로 두면 세션이 지워질 때
``fk_chat_message_session``의 ``ON DELETE CASCADE``로 **함께** 사라진다 — 만료 청소
(``scripts/purge_expired.py``)와 삭제 요청 경로를 고치지 않아도 별만 남는 고아가 생기지
않는다. ``NULL``이면 별이 없다.

downgrade
---------
열을 지운다. 그 사이 단 별이 사라지지만 대화 본문은 한 행도 지워지지 않고, 그 결과는
070 이전과 같은 「별 없음」이다(``migration_guard`` ``REGENERABLE``) — 다시 달면 된다.
"""

import sqlalchemy as sa

from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message", sa.Column("favorited_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_message", "favorited_at")
