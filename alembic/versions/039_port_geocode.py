"""항만명 → 좌표 조회 결과 캐시 테이블 신설

Revision ID: 039
Revises: 038
Create Date: 2026-09-12

이슈 #768 · **항만명을 좌표로 바꾸는 경로가 없었다.**

무엇을 만드나
--------------
``port_geocode`` — 사용자가 물어서 얻은 항만 좌표를 담는다. 질의 문자열(정규화)이
유일 키라 **같은 이름을 두 번 묻지 않는다.**

왜 캐시가 의무인가
------------------
공개 Nominatim 사용 정책이 *"Results must be cached on your side"*로 요구한다. 같은
질의를 반복하면 차단 대상이다(초당 1회 상한과 별개). 즉 이 표는 성능이 아니라
**정책 준수의 실체**다.

샘플 항만과 왜 섞지 않나
------------------------
``services/sample_ports.py``의 43곳은 **NGA World Port Index를 옮긴 고정 목록**이고
코드 상수다(`#760`이 「테이블로 두면 마이그레이션·시드·보존 분류가 따라오는데 얻는
것이 없다」고 판단했다). 이 표는 **출처가 다르다** — 사용자 질의로 생긴 외부 조회
결과다. 한 표에 담으면 어느 좌표가 어디서 왔는지 말할 수 없게 된다.

되돌리기
--------
``downgrade``는 표를 지운다. **캐시라 잃는 것이 없다** — 다시 물으면 다시 채워진다.
계산 이력이 이 표를 참조하지 않으므로(항차에는 좌표 값이 복사돼 들어간다) FK도 없다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "port_geocode",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("raw_query", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_port_geocode"),
        sa.UniqueConstraint("query", name="uq_port_geocode_query"),
    )


def downgrade() -> None:
    op.drop_table("port_geocode")
