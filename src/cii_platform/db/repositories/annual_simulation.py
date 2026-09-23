"""annual_simulation_run 조회 (DB_SCHEMA §2.6).

이 표를 다루는 자리는 종전에 ``services/annual_simulation.py``의 raw SQL뿐이었다.
내보내기(`API_SPEC §8.1` · `#59`)가 **선박 단위 목록**을 필요로 하면서 조회가 하나
더 생겼고, 그것을 서비스에 또 raw SQL로 적으면 같은 조인이 두 곳에 남는다
(`TECH_SPEC §16` — 질의는 저장소가 갖는다).
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy import select, tuple_

from cii_platform.db.models.annual_simulation_run import AnnualSimulationRun
from cii_platform.db.models.calculation_run import CalculationRun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: `/calculations`(`db/repositories/calculation_run.py`)와 같은 페이지 규약이다 (`#1805`).
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

_CURSOR_SEP = "\x00"


class AnnualRunCursor(NamedTuple):
    """keyset 커서 — ``(created_at, id)``의 마지막 값 (`#1805`).

    값은 **네이티브 타입**으로 가진다 — 문자열을 바인딩하면 시각 비교가 실패한다
    (``CalcRunCursor``와 같은 이유).
    """

    created_at: datetime
    simulation_id: UUID


def encode_cursor(cursor: AnnualRunCursor) -> str:
    """불투명한 URL-safe base64 문자열로 만든다 (`§1.9`와 같은 정책)."""
    raw = f"{cursor.created_at.isoformat()}{_CURSOR_SEP}{cursor.simulation_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> AnnualRunCursor | None:
    """커서를 되돌린다. 형식이 깨졌으면 ``None`` — 예외를 던지지 않는다(서비스가 422로 옮긴다)."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    created_at_raw, sep, run_id_raw = raw.partition(_CURSOR_SEP)
    if not sep or not run_id_raw:
        return None
    try:
        return AnnualRunCursor(
            created_at=datetime.fromisoformat(created_at_raw), simulation_id=UUID(run_id_raw)
        )
    except ValueError:
        return None


async def list_for_vessel(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    limit: int,
    cursor: AnnualRunCursor | None = None,
) -> list[tuple[AnnualSimulationRun, CalculationRun]]:
    """선박의 연간 시뮬레이션 실행을 **최신순**으로 (`#1805`).

    연간 등급 관리가 들어올 때 「이 배의 지난번 결과」를 다시 열려고 쓴다(`#1707` ·
    `#1701`). ``limit + 1``건을 가져온다 — 호출부가 ``has_more``를 판단한다.

    :func:`list_for_export`와 순서가 **반대**다. 내보내기는 파일의 행 순서가 실행 순서여야
    하고, 이 목록은 가장 최근 실행을 첫 행에 둬야 한다.

    ``calculation_run``을 INNER JOIN한다 — ``needs_recalc``가 거기 있다.
    """
    stmt = (
        select(AnnualSimulationRun, CalculationRun)
        .join(CalculationRun, CalculationRun.id == AnnualSimulationRun.calculation_run_id)
        .where(AnnualSimulationRun.vessel_id == vessel_id)
    )
    if cursor is not None:
        stmt = stmt.where(
            tuple_(AnnualSimulationRun.created_at, AnnualSimulationRun.id)
            < (cursor.created_at, cursor.simulation_id)
        )
    stmt = stmt.order_by(
        AnnualSimulationRun.created_at.desc(), AnnualSimulationRun.id.desc()
    ).limit(limit + 1)
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def list_for_export(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    regulation_year: int | None = None,
) -> list[tuple[AnnualSimulationRun, CalculationRun]]:
    """선박의 연간 시뮬레이션 실행을 결과 본문과 함께 조회한다 (`§8.1`, #59).

    ``calculation_run``을 **INNER JOIN**한다 — ``calculation_run_id``가 NOT NULL이라
    (`DB_SCHEMA §2.6`) 짝이 없는 행은 존재할 수 없고, OUTER로 두면 있을 수 없는
    경우를 처리하는 분기가 호출부에 생긴다.

    정렬은 ``(created_at, id)`` 오름차순 — **내보낸 파일의 행 순서가 실행 순서**다.
    최신순으로 두면 스프레드시트에서 시간이 거꾸로 흐른다.
    """
    stmt = (
        select(AnnualSimulationRun, CalculationRun)
        .join(CalculationRun, CalculationRun.id == AnnualSimulationRun.calculation_run_id)
        .where(AnnualSimulationRun.vessel_id == vessel_id)
    )
    if regulation_year is not None:
        stmt = stmt.where(AnnualSimulationRun.regulation_year == regulation_year)

    stmt = stmt.order_by(AnnualSimulationRun.created_at, AnnualSimulationRun.id)
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]
