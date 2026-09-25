"""공적 재항 기록 원본 표 신설 (#1197 B단계)

Revision ID: 063
Revises: 062
Create Date: 2026-09-26

무엇을 저장하나
----------------
``port_call_record`` — 해양수산부 선박운항정보 오픈API(``port_calls/mof_vessel_ops.py``)에서
받은 **기항 한 번**. 사용자가 넣은 항차 실제 시각·정박 구간과 견주는 데만 쓴다 — 항차·계산으로
흘러가는 경로는 없다(``PRD §17.1`` · 계산과 ``input_hash`` 불변).

``raw``에 제공자 원문(XML ``<item>``)을 그대로 둔다(``PRD §15.1`` ``[#1197]`` 「원본 그대로
보관」). 파싱 규칙을 고쳐도 원문에서 다시 읽는다.

값 제약을 트리거로 걸지 않는다 — 사람이 넣는 표가 아니라 수집기(``port_calls/collect.py``)만
쓰고, 수집기는 제공자가 파싱한 값을 그대로 옮긴다.

되돌리기
--------
``downgrade``는 표를 지운다. 사라지는 것은 **바깥에서 받아 둔 사본**뿐이라 수집기를 다시
돌리면 같은 기록이 돌아온다(공적 기록이 그 사이 정정됐다면 정정본이). ``REGENERABLE``로
분류한다.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from cii_platform.db.types import JSONText, UuidText

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "port_call_record",
        # CUBRID에는 `id` 기본값을 둘 수단이 없다(`#1058`) — 넣는 쪽이 만든다.
        sa.Column("id", UuidText(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("port_authority_code", sa.String(length=10), nullable=False),
        sa.Column("port_authority_name", sa.String(length=100), nullable=True),
        sa.Column("call_year", sa.Integer(), nullable=False),
        sa.Column("call_seq", sa.String(length=20), nullable=False),
        sa.Column("call_sign", sa.String(length=7), nullable=False),
        sa.Column("vessel_name", sa.String(length=200), nullable=True),
        sa.Column("previous_port", sa.String(length=10), nullable=True),
        sa.Column("next_port", sa.String(length=10), nullable=True),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reports", JSONText(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_port_call_record"),
        # 같은 기항을 두 번 넣지 않는다 — 수집기는 이 키로 갱신한다(ON DUPLICATE KEY UPDATE).
        sa.UniqueConstraint(
            "source",
            "port_authority_code",
            "call_year",
            "call_seq",
            name="uq_port_call_record_call",
        ),
    )
    # 대조는 「이 호출부호의 이 항만청 기록」을 읽는다.
    op.create_index(
        "idx_port_call_record_sign",
        "port_call_record",
        ["call_sign", "port_authority_code"],
    )


def downgrade() -> None:
    # 인덱스는 테이블과 함께 사라진다 — CUBRID는 alembic의 `DROP INDEX <이름>`을 받지 않는다
    # (`043` downgrade와 같은 판단).
    op.drop_table("port_call_record")
