"""not under way 구간 입력 서비스 (#370).

``#345``가 테이블을 만들고 ``#353``이 읽어 계산에 넣는다면, 여기가 **쓰는 경로**다.
시드 없이도 「8/10 14:00~8/12 09:00 묘박, 보일러 12t」를 넣을 수 있어야 명세 3-③
(정박 지속 시 등급 하락)가 실제로 성립한다.

이 서비스가 지키는 규칙:

- **구간 겹침 금지** — ``#368`` ``_overlap_hours``가 겹침을 두 번 뺀다는 문서화된
  전제를 강제한다. 겹치면 조용히 병합하지 않고 409로 돌려준다.
- **연도 정합** — ``regulation_year == started_at.year``. YTD 집계가
  ``(vessel_id, regulation_year)``로 묶고 ``started_at``으로 절단하므로, 시작 연도와
  귀속 연도가 어긋난 구간은 조회에서 사라지거나 두 번 잡힌다. 연도를 걸치는 구간은
  **시작 연도에 귀속**한다.
- **CF snapshot (030)** — 자식 연료의 ``cf_used``는 기록 시점의 현재 CF로 확정한다.
  CF가 개정돼도 과거 실적의 YTD가 변하지 않는다(``PRD §8.4``).
- **(consumer_type, fuel_type) 유일** — UNIQUE 인덱스(029)가 막기 전에 서비스가
  422로 돌려준다. DB 무결성 오류(500)는 사용자가 고칠 수 있는 입력 오류가 아니다.

PATCH 의미론은 ``#312``를 따른다 — 생략 = 변경 없음, 명시적 ``null`` = 클리어.
``ended_at``의 ``null``은 「진행 중으로 되돌린다」, ``fuel_uses`` 제공은 목록 전체
교체다.
"""

from __future__ import annotations

import base64
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from cii_platform.db.repositories import not_underway as not_underway_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories import voyage as voyage_repo
from cii_platform.errors import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

_CURSOR_SEP = "|"


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


def _uuid_str(value) -> str | None:
    """UUID 전용 — ``isoformat``이 없어 ``_iso``와 분리한다."""
    return None if value is None else str(value)


def _number(value: Decimal | None) -> float | None:
    """구간 부가 정보 — Layer 1 계산값이 아니므로 JSON number (voyage와 같은 규약)."""
    return None if value is None else float(value)


def _fuel_to_dict(row) -> dict[str, object]:
    return {
        "id": str(row.id),
        "consumer_type": row.consumer_type,
        "fuel_type": row.fuel_type,
        "fuel_ton": _number(row.fuel_ton),
        "cf_used": _number(row.cf_used),
    }


def to_dict(period, fuel_uses: list) -> dict[str, object]:
    """ORM 객체를 API_SPEC §3.8 구간 객체로 옮긴다."""
    return {
        "id": str(period.id),
        "vessel_id": str(period.vessel_id),
        "period_type": period.period_type,
        "started_at": _iso(period.started_at),
        "ended_at": _iso(period.ended_at),
        "regulation_year": period.regulation_year,
        "port_name": period.port_name,
        "lat": _number(period.lat),
        "lon": _number(period.lon),
        "voyage_id": _uuid_str(period.voyage_id),
        "distance_nm": _number(period.distance_nm),
        "fuel_uses": [_fuel_to_dict(fu) for fu in fuel_uses],
        "created_at": _iso(period.created_at),
        "updated_at": _iso(period.updated_at),
    }


# --- 검증 ------------------------------------------------------------------------


async def _load_vessel(session: AsyncSession, vessel_id: UUID):
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")
    return vessel


def _validate_time_order(started_at: datetime, ended_at: datetime | None) -> None:
    """``ended_at > started_at`` — DB CHECK(chk_not_underway_period_time_order)와 같은
    규칙을 422로 먼저 걸러준다."""
    if ended_at is not None and ended_at <= started_at:
        raise ValidationError(
            "종료 시각은 시작 시각보다 나중이어야 합니다.",
            field="ended_at",
            field_label="종료 시각",
        )


def _validate_year_consistency(started_at: datetime, regulation_year: int) -> None:
    if started_at.year != regulation_year:
        raise ValidationError(
            f"규제연도는 구간 시작 연도({started_at.year})와 같아야 합니다. "
            "연도를 걸치는 구간은 시작 연도에 귀속합니다.",
            field="regulation_year",
            field_label="규제연도",
        )


async def _validate_voyage_link(
    session: AsyncSession, vessel_id: UUID, voyage_id: UUID | None
) -> None:
    """맥락 항차 참조 — 같은 선박의 항차여야 한다."""
    if voyage_id is None:
        return
    voyage = await voyage_repo.get_by_id(session, voyage_id)
    if voyage is None or voyage.vessel_id != vessel_id:
        raise ValidationError(
            "맥락 항차는 같은 선박의 항차여야 합니다.",
            field="voyage_id",
            field_label="맥락 항차",
        )


def _validate_fuel_uniqueness(fuel_uses: list[dict]) -> None:
    """요청 안에서 (consumer_type, fuel_type) 중복 — 029 UNIQUE를 422로 선제 검증."""
    seen: set[tuple[str, str]] = set()
    for fu in fuel_uses:
        key = (fu["consumer_type"], fu["fuel_type"])
        if key in seen:
            raise ValidationError(
                f"같은 소비원·연료 조합이 중복되었습니다: {key[0]} × {key[1]}",
                field="fuel_uses",
                field_label="구간 연료",
            )
        seen.add(key)


async def _resolve_fuel_cf(session: AsyncSession, fuel_uses: list[dict]) -> dict[str, Decimal]:
    """연료 코드 → 현재 CF. 존재하지 않거나 비활성이면 422 (VAL-006)."""
    codes = [fu["fuel_type"] for fu in fuel_uses]
    rows = await param_repo.get_fuel_types_by_codes(session, codes)
    missing = sorted({code for code in codes if code not in rows})
    if missing:
        raise ValidationError(
            f"알 수 없거나 비활성 연료 종류입니다: {', '.join(missing)}",
            field="fuel_uses",
            field_label="연료 종류",
        )
    return {code: Decimal(rows[code].cf) for code in codes}


async def _ensure_no_overlap(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    started_at: datetime,
    ended_at: datetime | None,
    exclude_id: UUID | None = None,
) -> None:
    overlapping = await not_underway_repo.find_overlapping(
        session,
        vessel_id=vessel_id,
        started_at=started_at,
        ended_at=ended_at,
        exclude_id=exclude_id,
    )
    if overlapping is not None:
        raise ConflictError(
            "같은 선박의 구간과 시간이 겹칩니다. 기존 구간을 먼저 종료하거나 시간을 조정해 주세요."
        )


# --- 커서 (keyset — started_at desc, id desc) ---------------------------------------


def encode_cursor(started_at: str, period_id: str) -> str:
    raw = f"{started_at}{_CURSOR_SEP}{period_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> tuple[datetime, UUID] | None:
    """커서를 ``(started_at, id)``로 파싱한다 — 저장소 컬럼 타입과 맞춘 값으로.

    파싱 실패는 ``None`` — 호출부가 422로 바꾼다. ISO 파싱 실패·UUID 파싱 실패
    모두 여기에 포함된다(문자열을 그대로 바인딩하면 asyncpg이 실패한다).
    """
    import binascii
    from datetime import fromisoformat
    from uuid import UUID as _UUID

    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    started_at_str, sep, period_id_str = raw.partition(_CURSOR_SEP)
    if not sep or not period_id_str:
        return None
    try:
        return fromisoformat(started_at_str), _UUID(period_id_str)
    except ValueError:
        return None


# --- 서비스 진입점 ----------------------------------------------------------------


async def create_period(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    period_type: str,
    started_at: datetime,
    ended_at: datetime | None,
    regulation_year: int,
    port_name: str | None,
    lat: Decimal | None,
    lon: Decimal | None,
    voyage_id: UUID | None,
    distance_nm: Decimal,
    fuel_uses: list[dict],
) -> dict[str, object]:
    """구간을 생성한다 (API_SPEC §3.8). 성공 시 201.

    ``commit``을 여기서 한다 — 구간 + 자식 연료가 하나의 트랜잭션 경계다.
    """
    await _load_vessel(session, vessel_id)

    if started_at.tzinfo is None or (ended_at is not None and ended_at.tzinfo is None):
        raise ValidationError(
            "시각에 타임존을 포함해야 합니다 (ISO 8601).",
            field="started_at",
            field_label="시작 시각",
        )
    _validate_time_order(started_at, ended_at)
    _validate_year_consistency(started_at, regulation_year)
    await _validate_voyage_link(session, vessel_id, voyage_id)
    _validate_fuel_uniqueness(fuel_uses)
    cf_by_code = await _resolve_fuel_cf(session, fuel_uses)
    await _ensure_no_overlap(session, vessel_id=vessel_id, started_at=started_at, ended_at=ended_at)

    period = await not_underway_repo.insert_period(
        session,
        vessel_id=vessel_id,
        period_type=period_type,
        started_at=started_at,
        ended_at=ended_at,
        regulation_year=regulation_year,
        port_name=port_name,
        lat=lat,
        lon=lon,
        voyage_id=voyage_id,
        distance_nm=distance_nm,
    )
    for fu in fuel_uses:
        await not_underway_repo.insert_fuel_use(
            session,
            period_id=period.id,
            consumer_type=fu["consumer_type"],
            fuel_type=fu["fuel_type"],
            fuel_ton=fu["fuel_ton"],
            cf_used=cf_by_code[fu["fuel_type"]],
        )

    await session.commit()
    fuels = await not_underway_repo.list_fuel_uses_by_period_ids(session, [period.id])
    return to_dict(period, fuels.get(period.id, []))


async def list_periods(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    regulation_year: int | None = None,
    period_type: str | None = None,
    ongoing: bool | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """선박의 구간 목록 (API_SPEC §3.8.2). 최근 시작 순 + keyset 페이지네이션."""
    await _load_vessel(session, vessel_id)

    # API_SPEC §3.8.2 — 기본 20, 최대 100 (큰 limit은 자르지 않고 상한 적용).
    page_size = DEFAULT_LIMIT if limit is None else min(max(limit, 1), MAX_LIMIT)
    parsed = None
    if cursor is not None:
        parsed = decode_cursor(cursor)
        if parsed is None:
            raise ValidationError(
                "cursor 형식이 올바르지 않습니다.",
                field="cursor",
                field_label="커서",
            )

    rows = await not_underway_repo.list_active_periods(
        session,
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        period_type=period_type,
        ongoing=ongoing,
        limit=page_size,
        cursor=parsed,
    )
    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(last.started_at.isoformat(), str(last.id))

    fuels = await not_underway_repo.list_fuel_uses_by_period_ids(session, [p.id for p in page])
    data = [to_dict(p, fuels.get(p.id, [])) for p in page]
    return data, {"next_cursor": next_cursor, "has_more": has_more}


async def get_period(session: AsyncSession, period_id: UUID) -> dict[str, object]:
    """구간 상세 (API_SPEC §3.8.3). 없거나 soft delete면 404."""
    period = await not_underway_repo.get_period_by_id(session, period_id)
    if period is None or period.is_deleted:
        raise NotFoundError(f"구간을 찾을 수 없습니다: {period_id}")
    fuels = await not_underway_repo.list_fuel_uses_by_period_ids(session, [period.id])
    return to_dict(period, fuels.get(period.id, []))


async def update_period(
    session: AsyncSession,
    period_id: UUID,
    fields: dict,
) -> dict[str, object]:
    """구간을 수정한다 (API_SPEC §3.8.4). 진행 중 구간의 ``ended_at`` 확정 포함.

    ``fields``는 라우트가 ``exclude_unset``으로 걸러 준 것 — 키가 있으면(값이
    ``None``이어도) 변경 대상이다 (#312).
    """
    period = await not_underway_repo.get_period_by_id(session, period_id)
    if period is None or period.is_deleted:
        raise NotFoundError(f"구간을 찾을 수 없습니다: {period_id}")

    # 확정 후 값으로 검증한다 — started_at만 바뀌어도 순서·연도 정합은 합쳐서 본다.
    next_started = fields.get("started_at", period.started_at)
    next_ended = fields.get("ended_at", period.ended_at)
    next_year = fields.get("regulation_year", period.regulation_year)

    if ("started_at" in fields or "ended_at" in fields) and (
        next_started.tzinfo is None or (next_ended is not None and next_ended.tzinfo is None)
    ):
        raise ValidationError(
            "시각에 타임존을 포함해야 합니다 (ISO 8601).",
            field="started_at",
            field_label="시작 시각",
        )
    _validate_time_order(next_started, next_ended)
    _validate_year_consistency(next_started, next_year)
    if "voyage_id" in fields:
        await _validate_voyage_link(session, period.vessel_id, fields["voyage_id"])
    if "started_at" in fields or "ended_at" in fields:
        await _ensure_no_overlap(
            session,
            vessel_id=period.vessel_id,
            started_at=next_started,
            ended_at=next_ended,
            exclude_id=period.id,
        )

    new_fuels = fields.get("fuel_uses")
    cf_by_code: dict[str, Decimal] | None = None
    if new_fuels is not None:
        _validate_fuel_uniqueness(new_fuels)
        cf_by_code = await _resolve_fuel_cf(session, new_fuels)

    for key in (
        "period_type",
        "started_at",
        "ended_at",
        "regulation_year",
        "port_name",
        "lat",
        "lon",
        "voyage_id",
        "distance_nm",
    ):
        if key in fields:
            setattr(period, key, fields[key])

    if new_fuels is not None and cf_by_code is not None:
        await not_underway_repo.delete_fuel_uses(session, period.id)
        for fu in new_fuels:
            await not_underway_repo.insert_fuel_use(
                session,
                period_id=period.id,
                consumer_type=fu["consumer_type"],
                fuel_type=fu["fuel_type"],
                fuel_ton=fu["fuel_ton"],
                cf_used=cf_by_code[fu["fuel_type"]],
            )

    await session.commit()
    fuels = await not_underway_repo.list_fuel_uses_by_period_ids(session, [period.id])
    return to_dict(period, fuels.get(period.id, []))


async def delete_period(session: AsyncSession, period_id: UUID) -> dict[str, object]:
    """구간을 soft delete 한다 (API_SPEC §3.8.5). 자식 연료는 CASCADE 대상이 아니라
    부모 플래그로 집계에서 제외된다(#345 설계)."""
    period = await not_underway_repo.get_period_by_id(session, period_id)
    if period is None or period.is_deleted:
        raise NotFoundError(f"구간을 찾을 수 없습니다: {period_id}")

    period.is_deleted = True
    await session.commit()
    return {"id": str(period.id), "deleted": True}
