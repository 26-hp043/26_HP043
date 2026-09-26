"""공적 기록으로 채우기 — 「공적 기록과 다름」의 「이 값으로 채우기」 (`#1923` · ``API_SPEC §3.12``).

데이터 점검(``UIFLOW 2-11``)이 띄운 어긋난 칸 **하나**를 공적 재항 기록(``port_call_record``)의
시각으로 바꾼다. 사용자가 누르기 전에는 아무것도 바뀌지 않는다(``PRD §15.1`` ``[#1197]``) —
이 함수는 그 「누름」의 서버 쪽이다.

## 무엇을 지키나

1. **누른 칸만 바뀐다.** 출항이 어긋났다고 도착까지 바꾸지 않는다(`#1923` 완료 기준).
2. **확정 항차는 되돌리기 전환을 거친다.** `CONFIRMED`의 실적은 조용히 갈아 끼우지 않는다
   (``API_SPEC §3.6`` · ``PRD §8.1.1``). 화면이 재확인 다이얼로그를 통과했다는 표시
   (``revert_confirmed``)가 있어야 ``CONFIRMED → COMPLETED`` 전환(:func:`transition_voyage`)을
   태우고 그 다음에 채운다. 항차는 ``COMPLETED``로 남고 **재확정은 사용자가 `2-8`에서** 누른다 —
   여기서 다시 확정해 주면 ``PRD §8.1.1``의 재확인 요구가 빈말이 된다.
3. **되돌리기·채우기·감사가 한 트랜잭션이다.** 화면이 전환과 실적 입력을 차례로 보내면 첫
   요청이 성공하고 둘째가 실패할 때 되돌려진 채 옛값이 남는다. 그래서 이 함수는 **커밋하지
   않고 flush만** 하며, 라우트가 감사 기록을 넣은 뒤 한 번 커밋한다(`#1625` 패턴 ·
   ``TECH_SPEC §13.1``).
4. **사용자가 확인한 값이 들어간다.** 요청의 ``recorded_at``(화면이 보인 공적 기록 시각)과
   지금 기록의 시각이 다르면 거절한다(409) — 화면을 연 뒤 수집기가 기록을 갱신했을 수 있다.
5. **출처가 남는다.** 바꾼 칸의 출처 열에 ``PUBLIC_RECORD``를 적는다(``DB_SCHEMA §2.2``·``§2.17``).
   사람이 그 시각을 다시 고치면 ``NULL``로 돌아간다(``services/voyage.py`` · ``not_underway.py``).

반환 dict의 ``_audit``은 라우트가 ``VOYAGE_ACTUALS_FILL``의 ``details_json``으로 옮기는 재료다
(칸 · 이전 값 · 새 값 · 공적 기록 키 · 되돌린 상태). 주체(user)·IP는 HTTP 개념이라 서비스가
기록하지 않는다(``TECH_SPEC §16.1``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.db.repositories import not_underway as nu_repo
from cii_platform.db.repositories import port_call as port_call_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import (
    ConflictError,
    NotFoundError,
    StateTransitionError,
    ValidationError,
)
from cii_platform.port_calls.reconcile import (
    FIELD_ARRIVAL,
    FIELD_BERTH_END,
    FIELD_BERTH_START,
    FIELD_DEPARTURE,
)
from cii_platform.services import not_underway as nu_svc
from cii_platform.services import voyage as voyage_svc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: 출처 열에 적는 값 — ``ACTUAL_TIME_SOURCES``의 둘째 (`api/schemas/voyage.py`).
SOURCE_PUBLIC_RECORD = "PUBLIC_RECORD"

#: 항차 칸 → (시각 열, 출처 열, 기록에서 읽는 쪽). ``PRD §17.4.4`` 표 그대로 — 출항은 기항의
#: 가장 늦은 출항(``departure_at``), 도착은 가장 이른 입항(``arrival_at``).
_VOYAGE_FIELDS: dict[str, tuple[str, str, str]] = {
    FIELD_DEPARTURE: ("actual_departure_at", "actual_departure_source", "departure_at"),
    FIELD_ARRIVAL: ("actual_arrival_at", "actual_arrival_source", "arrival_at"),
}
#: 정박 구간 칸 → 같은 셋. 시작은 입항, 끝은 출항과 짝이다.
_PERIOD_FIELDS: dict[str, tuple[str, str, str]] = {
    FIELD_BERTH_START: ("started_at", "started_at_source", "arrival_at"),
    FIELD_BERTH_END: ("ended_at", "ended_at_source", "departure_at"),
}

_STATUS_CONFIRMED = "CONFIRMED"
_STATUS_COMPLETED = "COMPLETED"


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


async def _require_record(
    session: AsyncSession, *, key: dict[str, object], call_sign: str | None, side: str
) -> tuple[object, datetime]:
    """요청이 가리킨 기항을 다시 읽고 **이 선박의 기록인지**·**그 쪽 시각이 있는지** 본다."""
    record = await port_call_repo.get_by_call_key(
        session,
        source=str(key["source"]),
        port_authority_code=str(key["port_authority_code"]),
        call_year=int(key["call_year"]),  # type: ignore[call-overload]
        call_seq=str(key["call_seq"]),
    )
    if record is None:
        raise NotFoundError("공적 기록을 찾을 수 없습니다. 데이터 점검을 다시 불러와 주세요.")
    # 다른 배의 기항을 이 항차에 옮기는 길을 막는다 — 선박과 기록을 잇는 열쇠는 호출부호 하나다
    # (`DB_SCHEMA §2.25`). 호출부호가 없는 배는 대조 대상이 아니었으므로 채울 것도 없다.
    if not call_sign or record.call_sign != call_sign:
        raise ValidationError(
            "이 선박의 공적 기록이 아닙니다.", field="record", field_label="공적 기록"
        )
    recorded_at = getattr(record, side)
    if recorded_at is None:
        raise ValidationError(
            "공적 기록에 그 시각의 신고가 없습니다.", field="record", field_label="공적 기록"
        )
    return record, recorded_at


async def fill_from_public_record(
    session: AsyncSession,
    voyage_id: UUID,
    *,
    field: str,
    record_key: dict[str, object],
    recorded_at: datetime,
    period_id: UUID | None = None,
    revert_confirmed: bool = False,
) -> dict[str, object]:
    """어긋난 칸 하나를 공적 기록의 시각으로 채운다 (``API_SPEC §3.12``). **커밋하지 않는다.**

    라우트가 반환값의 ``_audit``으로 감사 기록을 넣고 한 번 커밋한다. 응답에는 ``_audit``을
    빼고 보낸다(``_from_status``와 같은 규약).
    """
    if field in _VOYAGE_FIELDS:
        value_key, source_key, side = _VOYAGE_FIELDS[field]
        if period_id is not None:
            raise ValidationError(
                "항차 칸에는 정박 구간을 보내지 않습니다.",
                field="period_id",
                field_label="정박·묘박 구간",
            )
    elif field in _PERIOD_FIELDS:
        value_key, source_key, side = _PERIOD_FIELDS[field]
        if period_id is None:
            raise ValidationError(
                "정박 시각을 채우려면 어느 구간인지 필요합니다.",
                field="period_id",
                field_label="정박·묘박 구간",
            )
    else:
        raise ValidationError(f"채울 수 없는 칸입니다: {field}", field="field", field_label="채울 칸")

    # 항차 행을 먼저 잠그고 읽는다 (`#1626` · `TECH_SPEC §16.3`) — 아래 상태 판정이 옛 상태 위에서
    # 통과하지 않게. 잠금은 라우트의 커밋·롤백에서 풀린다.
    voyage = await voyage_repo.get_by_id(session, voyage_id, for_update=True)
    if voyage is None:
        raise NotFoundError(f"항차를 찾을 수 없습니다: {voyage_id}")
    vessel = await vessel_repo.get_by_id(session, voyage.vessel_id)
    call_sign = None if vessel is None else vessel.call_sign

    record, current_recorded_at = await _require_record(
        session, key=record_key, call_sign=call_sign, side=side
    )
    if current_recorded_at != recorded_at:
        # 화면이 보인 값과 지금 기록이 다르다 — 수집기가 그 사이 정정본을 받았다. 사용자가 확인한
        # 값이 아닌 것을 넣지 않는다.
        raise ConflictError(
            "공적 기록이 그 사이 갱신됐습니다. 데이터 점검을 다시 불러와 확인해 주세요."
        )

    # ── 확정 항차는 되돌리기 전환을 먼저 (`PRD §8.1.1` · `API_SPEC §3.6`).
    reverted_from: str | None = None
    if voyage.status == _STATUS_CONFIRMED:
        if not revert_confirmed:
            raise StateTransitionError(
                "실적이 확정된 항차입니다. 확정을 되돌리는 것을 확인해야 채울 수 있습니다."
            )
        # 항차 칸이든 정박 칸이든 같다 — 확정 실적의 근거가 되는 시각을 바꾸는 일이다.
        await voyage_svc.transition_voyage(
            session, voyage_id, to_status=_STATUS_COMPLETED, commit=False
        )
        reverted_from = _STATUS_CONFIRMED
    elif field in _VOYAGE_FIELDS and voyage.status not in voyage_svc.ACTUALS_ALLOWED_STATUSES:
        # 실적 입력(`§3.6`)과 같은 상태 규칙 — 뜨지 않은 항차·종결된 기록에는 실적을 넣지 않는다.
        raise StateTransitionError(
            f"{voyage.status} 상태의 항차에는 실적을 입력할 수 없습니다. "
            f"허용: {', '.join(sorted(voyage_svc.ACTUALS_ALLOWED_STATUSES))}."
        )

    # ── 그 칸 하나만 채운다.
    period_dict: dict[str, object] | None = None
    if field in _VOYAGE_FIELDS:
        before = getattr(voyage, value_key)
        setattr(voyage, value_key, current_recorded_at)
        setattr(voyage, source_key, SOURCE_PUBLIC_RECORD)
        await session.flush()
    else:
        period = await nu_repo.get_period(session, period_id)  # type: ignore[arg-type]
        if period is None or period.is_deleted or period.voyage_id != voyage.id:
            # 다른 항차의 구간을 이 항차 요청으로 고치는 길을 막는다.
            raise NotFoundError(f"이 항차에 매인 구간을 찾을 수 없습니다: {period_id}")
        before = getattr(period, value_key)
        # 순서·겹침·귀속 연도 검사는 구간 수정(`§2.11`)과 같은 함수가 한다.
        period_dict = await nu_svc.update_period(
            session,
            period.id,
            commit=False,
            **{value_key: current_recorded_at, source_key: SOURCE_PUBLIC_RECORD},
        )

    fuel_uses = await voyage_repo.list_fuel_uses(session, voyage.id)
    return {
        "field": field,
        "before": _iso(before),
        "after": _iso(current_recorded_at),
        "source": SOURCE_PUBLIC_RECORD,
        "reverted_from_status": reverted_from,
        "voyage": voyage_svc.to_dict(voyage, fuel_uses),
        "period": period_dict,
        # 감사 재료 — 라우트가 `VOYAGE_ACTUALS_FILL`의 `details_json`으로 옮기고 응답에서 뺀다.
        "_audit": {
            "field": field,
            "target": "voyage" if field in _VOYAGE_FIELDS else "not_underway_period",
            "period_id": None if period_id is None else str(period_id),
            "before": _iso(before),
            "after": _iso(current_recorded_at),
            "source": SOURCE_PUBLIC_RECORD,
            "public_record": {
                "source": record.source,
                "port_authority_code": record.port_authority_code,
                "call_year": record.call_year,
                "call_seq": record.call_seq,
                "fetched_at": _iso(record.fetched_at),
            },
            "reverted_from_status": reverted_from,
        },
    }
