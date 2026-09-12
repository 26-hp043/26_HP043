"""항만명 → 좌표 조회 결과 캐시 (``DB_SCHEMA §2.20`` · `#768`).

**캐시는 선택이 아니라 의무다.** Nominatim 사용 정책이 *"Results must be cached on your
side"*로 요구하고, 같은 질의를 반복하면 차단 대상이 된다.

`services/sample_ports.py`의 43곳(코드 상수)과 **다른 것**이다 — 그쪽은 원본(NGA WPI)을
옮겨 둔 고정 목록이고, 이 표는 **사용자가 물어서 생긴 결과**다. 출처가 다르므로 섞지
않는다: 어느 좌표가 어디서 왔는지 말할 수 없게 된다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from cii_platform.db.models.base import Base


class PortGeocode(Base):
    """조회한 항만명 한 건. 질의 문자열이 키다."""

    __tablename__ = "port_geocode"

    id = sa.Column(
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )
    #: 정규화한 질의(공백 정리 + 대문자). 같은 이름을 두 번 묻지 않게 하는 키다.
    query = sa.Column(sa.String(length=200), nullable=False)
    #: 사용자가 넣은 원문. 화면에 되돌려 보일 때 쓴다.
    raw_query = sa.Column(sa.String(length=200), nullable=False)
    #: 제공자가 준 표시명. 「무엇으로 찾았는지」를 사람이 확인하는 근거다.
    display_name = sa.Column(sa.String(length=500), nullable=False)
    lat = sa.Column(sa.Numeric(precision=9, scale=6), nullable=False)
    lon = sa.Column(sa.Numeric(precision=9, scale=6), nullable=False)
    #: 항만 판정에 쓴 분류(harbour · port · ferry_terminal · anchorage).
    kind = sa.Column(sa.String(length=50), nullable=False)
    #: 어디서 왔는가. 지금은 nominatim 하나지만, 제공자를 바꾸면 값이 는다.
    source = sa.Column(sa.String(length=50), nullable=False)
    fetched_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_port_geocode"),
        # 같은 이름을 두 번 묻지 않는다 — 정책이 요구하는 캐시의 실체다.
        sa.UniqueConstraint("query", name="uq_port_geocode_query"),
    )
