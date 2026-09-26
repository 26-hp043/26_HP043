"""공적 재항 기록 저장소 (`#1197` · ``DB_SCHEMA §2.25``)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy_cubrid.dml import insert as cubrid_insert

from cii_platform.db.models.port_call_record import PortCallRecord

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.port_calls.provider import PortCall, PortCallReport


def _report_json(report: PortCallReport) -> dict[str, object]:
    """신고 한 줄을 JSON으로 — 시각은 시간대를 붙인 ISO, 톤수는 문자열(Decimal 그대로)."""
    return {
        "kind": report.kind,
        "request": report.request,
        "at": report.at.isoformat(),
        "facility_name": report.facility_name,
        "facility_code": report.facility_code,
        "gross_tonnage": None if report.gross_tonnage is None else str(report.gross_tonnage),
        "international_gross_tonnage": (
            None
            if report.international_gross_tonnage is None
            else str(report.international_gross_tonnage)
        ),
    }


async def upsert_port_call(session: AsyncSession, call: PortCall, *, fetched_at: datetime) -> bool:
    """기항 한 건을 넣거나, 이미 있으면 받은 값으로 갱신한다. 새로 넣었으면 ``True``.

    갱신하는 것은 **공적 기록의 사본**이다 — 공적 기록이 신고를 ``최초`` → ``최종``으로 고치면
    따라간다. 사용자가 넣은 항차·정박 구간은 이 함수가 읽지도 쓰지도 않는다(``PRD §17.1``).
    """
    values: dict[str, object] = {
        "port_authority_name": call.port_authority_name,
        "call_sign": call.call_sign,
        "vessel_name": call.vessel_name,
        "previous_port": call.previous_port,
        "next_port": call.next_port,
        "arrival_at": call.arrival_at,
        "departure_at": call.departure_at,
        "reports": [_report_json(report) for report in call.reports],
        "raw": call.raw,
        "fetched_at": fetched_at,
    }
    statement = (
        cubrid_insert(PortCallRecord)
        .values(
            id=uuid.uuid4(),
            source=call.source,
            port_authority_code=call.port_authority_code,
            call_year=call.call_year,
            call_seq=call.call_seq,
            **values,
        )
        .on_duplicate_key_update(**values)
    )
    result = await session.execute(statement)
    # 삽입이면 1, 갱신이면 2다(CUBRID · MySQL 규약 — `position_snapshot.insert_snapshot` 실측).
    return result.rowcount == 1


async def get_by_call_key(
    session: AsyncSession,
    *,
    source: str,
    port_authority_code: str,
    call_year: int,
    call_seq: str,
) -> PortCallRecord | None:
    """기항 한 건 — ``uq_port_call_record_call`` 키로 (`#1923` 「이 값으로 채우기」). 없으면 ``None``."""
    result = await session.execute(
        select(PortCallRecord).where(
            PortCallRecord.source == source,
            PortCallRecord.port_authority_code == port_authority_code,
            PortCallRecord.call_year == call_year,
            PortCallRecord.call_seq == call_seq,
        )
    )
    return result.scalars().first()


async def list_for_call_signs(
    session: AsyncSession, call_signs: Sequence[str]
) -> list[PortCallRecord]:
    """호출부호들의 기록 전부 — 입항 시각 순. 호출부호가 없으면 빈 목록."""
    if not call_signs:
        return []
    result = await session.execute(
        select(PortCallRecord)
        .where(PortCallRecord.call_sign.in_(sorted(set(call_signs))))
        .order_by(PortCallRecord.arrival_at, PortCallRecord.call_seq)
    )
    return list(result.scalars().all())
