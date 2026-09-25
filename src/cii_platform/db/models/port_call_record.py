"""공적 재항 기록 원본 (``DB_SCHEMA §2.25`` · `#1197` B단계).

공공데이터(해양수산부 선박운항정보)에서 받은 **기항 한 번**이 한 행이다. 사용자가 넣은
항차·정박 구간과 **견주기만** 한다 — 이 표의 값이 항차·계산으로 흘러가는 경로는 없다
(``PRD §17.1`` 「덮어쓰지 않는다」 · 계산과 ``input_hash`` 불변).

``port_geocode``(`#768`)와 같은 성격이다 — 바깥에서 받아 둔 사본이지 사람이 만든 값이 아니다.
그래서 **다시 받으면 갱신한다**: 공적 기록 쪽이 신고를 ``최초`` → ``최종``으로 고치면 우리
사본도 따라가야 한다. 사용자가 넣은 값을 바꾸는 것이 아니다.

``arrival_at``·``departure_at``은 ``reports``에서 **규칙으로** 뽑은 값(결정 G-7 ①-2 ⓐ —
가장 이른 입항 · 가장 늦은 출항)을 조회용으로 함께 적어 둔 것이다. 원본은 ``raw``다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from cii_platform.db.models.base import Base
from cii_platform.db.types import JSONText, UuidText


class PortCallRecord(Base):
    """공적 기록의 기항 한 번. ``(source, 항만청, 입항연도, 입항차수)``가 키다."""

    __tablename__ = "port_call_record"

    id = sa.Column(UuidText, primary_key=True, default=uuid.uuid4)
    #: 제공자 — 지금은 ``MOF_VESSEL_OPS`` 하나. 제공자를 더하면 값이 는다.
    source = sa.Column(sa.String(length=50), nullable=False)
    #: 항만청코드(``prtAgCd`` · 부산 ``020``).
    port_authority_code = sa.Column(sa.String(length=10), nullable=False)
    port_authority_name = sa.Column(sa.String(length=100), nullable=True)
    #: 원문 ``etryptYear``·``etryptCo`` — 항만청 안의 연도별 입항 차수.
    call_year = sa.Column(sa.Integer, nullable=False)
    call_seq = sa.Column(sa.String(length=20), nullable=False)
    #: 호출부호 — ``vessel.call_sign``과 같은 칸 폭(``§2.1``). 선박과 잇는 유일한 열쇠다.
    call_sign = sa.Column(sa.String(length=7), nullable=False)
    vessel_name = sa.Column(sa.String(length=200), nullable=True)
    #: 전출항지 · 차항지 (UN/LOCODE).
    previous_port = sa.Column(sa.String(length=10), nullable=True)
    next_port = sa.Column(sa.String(length=10), nullable=True)
    #: 규칙으로 뽑은 두 시각(위 docstring). 신고가 없으면 NULL.
    arrival_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    departure_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    #: 입항·출항 신고 목록(파싱한 것) — ``[{kind, request, at, facility_name, …}]``.
    reports = sa.Column(JSONText(), nullable=False)
    #: 제공자가 준 원문 그대로.
    raw = sa.Column(sa.Text(), nullable=True)
    #: 마지막으로 받은 시각 — 「언제 기준의 공적 기록인가」.
    fetched_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pk_port_call_record"),
        sa.UniqueConstraint(
            "source",
            "port_authority_code",
            "call_year",
            "call_seq",
            name="uq_port_call_record_call",
        ),
        sa.Index("idx_port_call_record_sign", "call_sign", "port_authority_code"),
    )
