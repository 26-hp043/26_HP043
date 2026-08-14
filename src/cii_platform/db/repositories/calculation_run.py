"""계산 이력 저장소 — 쓰기 + 조회 담당 (TECH_SPEC §16).

``calculation_run``은 **append-only**다. 같은 입력으로 다시 요청하면 새 행이 생긴다
(#55 「항상 새로 생성, 멱등성 없음」). ``input_hash``·``parameter_hash``는 중복 제거용이
아니라 **재현성 추적용**이다 — 같은 해시의 두 행이 다른 결과를 담고 있으면 그 사이에
코드나 파라미터가 바뀐 것이며, 그것을 찾아내는 것이 이 컬럼의 목적이다. 조회는
API_SPEC §1.9의 hash 기반 조회(#56)가 사용한다.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from sqlalchemy import select, tuple_

from cii_platform.db.models.calculation_run import CalculationRun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: DB_SCHEMA §2.5 ``chk_calculation_type``의 허용값 중 기능①에 해당하는 것.
#: 이 문자열이 틀리면 INSERT가 CHECK 제약에 걸린다.
CALCULATION_TYPE_VOYAGE = "VOYAGE_ESTIMATE"

#: API_SPEC §1.9 — 페이지 크기 기본 20, 최대 100 (vessel · voyage와 동일).
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: 커서 인코딩 구분자. ISO 8601 문자열과 UUID에 등장할 수 없는 제어문자를 쓴다.
_CURSOR_SEP = "\x00"


class CalcRunCursor(NamedTuple):
    """keyset 페이지네이션 커서 — 정렬 키 ``(created_at, id)``의 마지막 값.

    offset 대신 keyset을 쓰는 이유는 vessel · voyage와 같다(#51): 앞 페이지에서
    행이 빠지면 offset은 다음 페이지가 한 건을 건너뛴다. ``created_at``은 계산이
    동시에 끝나면 같을 수 있어 ``id``를 2차 키로 둔다.

    값은 **네이티브 타입**(``datetime``·``UUID``)으로 가진다 — 문자열을 그대로
    바인딩하면 PostgreSQL이 ``timestamptz < varchar`` 연산자를 못 찾아 쿼리가
    실패한다. 직렬화는 encode/decode에서만 일어난다.
    """

    created_at: datetime
    calculation_run_id: UUID


def encode_cursor(cursor: CalcRunCursor) -> str:
    """커서를 URL-safe base64 문자열로 만든다 (vessel §2.1과 같은 정책)."""
    raw = f"{cursor.created_at.isoformat()}{_CURSOR_SEP}{cursor.calculation_run_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> CalcRunCursor | None:
    """커서를 되돌린다. 형식이 깨졌으면 ``None`` (예외를 던지지 않는다).

    잘못된 커서는 사용자가 URL을 손댄 경우가 대부분이고, 그때 500이 나가면 안 된다.
    오류로 볼지 첫 페이지로 볼지는 서비스가 정한다.
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    created_at_raw, sep, run_id_raw = raw.partition(_CURSOR_SEP)
    if not sep or not run_id_raw:
        return None
    try:
        created_at = datetime.fromisoformat(created_at_raw)
        calculation_run_id = UUID(run_id_raw)
    except ValueError:
        return None
    return CalcRunCursor(created_at=created_at, calculation_run_id=calculation_run_id)


async def mark_needs_recalc(session: AsyncSession, vessel_id: UUID) -> int:
    """선박의 미확정 계산 결과에 재계산 필요 표시를 남긴다 (PRD §8.4, #283).

    ``needs_recalc = false``인 행만 갱신한다 — 이미 표시된 행은 누적 전용이고
    true→false 되돌림은 가드 트리거(024)가 거부한다. **UPDATE문은
    ``needs_recalc``만 세팅한다** — 그 외 컬럼은 immutable 가드가 지킨다.

    반환값은 표시된 행 수.
    """
    from sqlalchemy import update

    result = await session.execute(
        update(CalculationRun)
        .where(
            CalculationRun.vessel_id == vessel_id,
            CalculationRun.needs_recalc.is_(False),
        )
        .values(needs_recalc=True)
    )
    return result.rowcount or 0


async def insert_voyage_estimate(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    input_hash: str,
    parameter_hash: str,
    model_version: dict[str, object],
    result_json: dict[str, object],
    parameters_used: dict[str, object],
    warnings: list[str],
    duration_ms: int,
) -> CalculationRun:
    """기능① 계산 이력 1건을 저장하고 flush한다.

    **commit하지 않는다.** 트랜잭션 경계는 서비스 계층이 정한다(``db/session.py``의
    ``get_session`` docstring 참조).

    ``flush``는 하는 이유: 응답의 ``calculation_run_id``에 이 행의 PK가 필요한데,
    PK가 ``gen_random_uuid()`` server_default라 **DB에 문장을 보내기 전에는 값이 없다.**

    ``warnings``를 ``warnings_json``에 넣을 때 리스트를 그대로 쓴다 — 컬럼이 JSONB이고
    TECH_SPEC §12.2 4항이 「모든 오류를 warnings_json에 기록」으로 규정한다.
    """
    run = CalculationRun(
        calculation_type=CALCULATION_TYPE_VOYAGE,
        vessel_id=vessel_id,
        voyage_id=None,
        weather_snapshot_id=None,
        input_hash=input_hash,
        parameter_hash=parameter_hash,
        model_version=model_version,
        result_json=result_json,
        parameters_used=parameters_used,
        warnings_json=warnings,
        duration_ms=duration_ms,
    )
    session.add(run)
    await session.flush()
    return run


async def list_runs(
    session: AsyncSession,
    *,
    limit: int,
    cursor: CalcRunCursor | None = None,
    input_hash: str | None = None,
    parameter_hash: str | None = None,
    calculation_type: str | None = None,
    vessel_id: UUID | None = None,
) -> list[CalculationRun]:
    """계산 이력을 조회한다 (API_SPEC §1.9).

    ``limit + 1``건을 가져온다 — 호출부가 ``has_more``를 별도 COUNT 없이 판단한다.

    정렬은 ``(created_at desc, id desc)`` — 최신 계산이 먼저 나온다. ``created_at``
    은 ``now()`` server_default라 동시 커밋 시 같을 수 있어 ``id``를 2차 키로 둔다.

    필터는 모두 AND 결합이다. ``input_hash`` + ``parameter_hash``를 함께 주면 두
    값이 **정확히 일치하는** 결과만 반환한다 — 재현성 검증의 핵심 용법(§1.9).
    """
    stmt = select(CalculationRun)

    if input_hash is not None:
        stmt = stmt.where(CalculationRun.input_hash == input_hash)
    if parameter_hash is not None:
        stmt = stmt.where(CalculationRun.parameter_hash == parameter_hash)
    if calculation_type is not None:
        stmt = stmt.where(CalculationRun.calculation_type == calculation_type)
    if vessel_id is not None:
        stmt = stmt.where(CalculationRun.vessel_id == vessel_id)

    if cursor is not None:
        # 행 값 비교. (created_at, id) < (:created_at, :id) 를 한 번에 표현한다 —
        # OR 조건으로 풀어 쓰면 인덱스를 타지 못하는 형태가 되기 쉽다.
        stmt = stmt.where(
            tuple_(CalculationRun.created_at, CalculationRun.id)
            < (cursor.created_at, cursor.calculation_run_id)
        )

    stmt = stmt.order_by(CalculationRun.created_at.desc(), CalculationRun.id.desc()).limit(
        limit + 1
    )
    return list((await session.execute(stmt)).scalars().all())
