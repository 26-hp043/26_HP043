"""not under way 구간 CRUD 서비스 (API_SPEC §2.9~§2.13, #370).

``#345``가 테이블을 만들고 ``#347``이 시드를 넣고 ``#353``이 그걸 읽어 계산한다.
**쓰는 쪽이 없었다** — 이 모듈이 그 입구다.

## 왜 입구가 없으면 기능이 성립하지 않는가

not under way 연료는 CII 분자 ``M``에 그대로 들어간다(``#353``). 기록이 없으면
``M``이 늘지 않아 **정박해도 등급이 떨어지지 않고**, 대시보드의 위험 선박 판정이
실제보다 낙관적으로 나온다. CSV 가져오기(``#60``)는 항차만 다루므로 이 경로를
대신하지 못한다.

## 이 모듈이 지키는 세 가지

1. **CF는 서버가 뜬다.** ``not_underway_fuel_use.cf_used``는 NOT NULL이고(마이그레이션
   030 · ``#378``) 계산 시점 snapshot이다. 화면이 CF를 보내면 사용자가 배출계수를
   정하는 셈이 되고, ``PRD §8.4``의 「CF 개정 시 과거 계산 보존」이 무너진다.
   ``create_voyage``가 항차 연료에 하는 것과 같은 처리다.
2. **구간은 겹치지 않는다.** 같은 정박이 두 번 들어가면 ``M``이 두 배가 된다 —
   등급이 실제보다 나쁘게 나오고, 사용자는 그 이유를 화면에서 알 수 없다.
3. **삭제는 소프트다.** 지운 구간이 과거 계산에서 사라지면 같은 연도를 다시 계산할
   때 값이 조용히 달라진다. ``is_deleted``로 가리고 행은 남긴다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.db.repositories import not_underway as nu_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.errors import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: ``chk_not_underway_period_type`` (마이그레이션 025)와 같은 6값.
#: MEPC.401(83) EOSP→FAOP 구간의 실체다. **DB 제약과 이 목록은 함께 바뀌어야 한다** —
#: 여기만 늘리면 INSERT가 IntegrityError로 500이 되고, DB만 늘리면 입력이 막힌다.
PERIOD_TYPES: tuple[str, ...] = (
    "IN_PORT",
    "AT_ANCHOR",
    "DRIFTING",
    "STS",
    "CANAL_TRANSIT",
    "DRYDOCK",
)

#: ``chk_not_underway_consumer_type``와 같은 4값. MEPC.385(81)이 MARPOL Annex VI
#: Appendix IX에 추가한 DCS 보고 항목 그대로다(데이터연도 2026~).
CONSUMER_TYPES: tuple[str, ...] = (
    "MAIN_ENGINE",
    "AUX_ENGINE",
    "OIL_FIRED_BOILER",
    "OTHER",
)


#: 오류 메시지의 한국어 항목명. ``api.field_labels``를 쓰지 않는 이유는 ``services``가
#: ``api``를 import 할 수 없기 때문이다(TECH_SPEC §16 계층 방향, ``errors`` 주석 참조).
_FIELD_LABELS = {
    "period_type": "구간 유형",
    "started_at": "시작 시각",
    "distance_nm": "이동 거리",
}


def _number(value: Decimal | None) -> float | None:
    """Layer 1 계산 결과가 아니므로 JSON number다 (``API_SPEC §1.7`` · voyage와 동일)."""
    return None if value is None else float(value)


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


def _fuel_use_to_dict(fuel_use) -> dict[str, object]:
    """``NotUnderwayFuelUse`` ORM → API_SPEC §2.9 연료 객체."""
    return {
        "id": str(fuel_use.id),
        "period_id": str(fuel_use.period_id),
        "consumer_type": fuel_use.consumer_type,
        "fuel_type": fuel_use.fuel_type,
        "fuel_ton": _number(fuel_use.fuel_ton),
        # 화면은 이 값을 편집하지 않지만 보여 준다 — 어떤 CF로 계산됐는지 확인할
        # 경로가 없으면 과거 계산과 지금 값이 다를 때 원인을 찾을 수 없다.
        "cf_used": _number(fuel_use.cf_used),
    }


def to_dict(period, fuel_uses: list) -> dict[str, object]:
    """``NotUnderwayPeriod`` ORM → API_SPEC §2.9 구간 객체."""
    return {
        "id": str(period.id),
        "vessel_id": str(period.vessel_id),
        "regulation_year": period.regulation_year,
        "period_type": period.period_type,
        "started_at": _iso(period.started_at),
        # null은 「진행 중」이다. 「모름」이 아니다 — 화면이 이 둘을 같게 그리면
        # 사용자가 끝난 구간의 종료 시각을 잊었다고 오해한다.
        "ended_at": _iso(period.ended_at),
        "port_name": period.port_name,
        "lat": _number(period.lat),
        "lon": _number(period.lon),
        "distance_nm": _number(period.distance_nm),
        "voyage_id": None if period.voyage_id is None else str(period.voyage_id),
        "fuel_uses": [_fuel_use_to_dict(fu) for fu in fuel_uses],
        "created_at": _iso(period.created_at),
    }


async def _require_vessel(session: AsyncSession, vessel_id: UUID) -> None:
    """선박이 없으면 404. 구간은 선박에 귀속되므로 부모부터 확인한다."""
    if await vessel_repo.get_by_id(session, vessel_id) is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")


async def _require_period(session: AsyncSession, period_id: UUID):
    """살아 있는 구간을 가져온다. 없거나 삭제됐으면 404.

    삭제된 구간을 「이미 삭제됨」으로 따로 알리지 않는다 — 소프트 삭제는 내부
    사정이고, 사용자에게는 없는 것과 같다.
    """
    period = await nu_repo.get_period(session, period_id)
    if period is None or period.is_deleted:
        raise NotFoundError(f"구간을 찾을 수 없습니다: {period_id}")
    return period


def _resolve_regulation_year(
    started_at: datetime, ended_at: datetime | None, requested: int | None
) -> int:
    """구간의 귀속 연도를 정한다.

    **생략하면 ``started_at``의 UTC 연도**다. 대부분의 구간이 한 해 안에서 끝나므로
    이 기본값이 맞고, 사용자에게 매번 연도를 묻는 것은 실수를 만드는 질문이다.

    명시했다면 ``started_at`` 또는 ``ended_at``의 연도 중 하나여야 한다. 연말을
    걸치는 구간(12/30~1/2)은 **어느 해에 넣을지가 실제로 판단 사항**이라 사용자의
    선택을 받되, 무관한 연도(2020년 구간을 2026년으로)는 오타로 보고 막는다.
    """
    start_year = started_at.year
    allowed = {start_year}
    if ended_at is not None:
        allowed.add(ended_at.year)

    if requested is None:
        return start_year
    if requested not in allowed:
        raise ValidationError(
            f"규제연도는 구간이 걸친 연도({' 또는 '.join(str(y) for y in sorted(allowed))})"
            "여야 합니다.",
            field="regulation_year",
            field_label="규제연도",
        )
    return requested


async def _assert_no_overlap(
    session: AsyncSession,
    *,
    vessel_id: UUID,
    started_at: datetime,
    ended_at: datetime | None,
    exclude_id: UUID | None = None,
) -> None:
    """겹치는 구간이 있으면 409. 어느 구간과 겹치는지 시각까지 알린다.

    「겹칩니다」만으로는 사용자가 기존 기록을 찾아 고칠 수 없다. 상대 구간의 시각을
    실어 어디를 봐야 하는지 알려 준다.
    """
    clash = await nu_repo.find_overlapping(
        session,
        vessel_id=vessel_id,
        started_at=started_at,
        ended_at=ended_at,
        exclude_id=exclude_id,
    )
    if clash is None:
        return

    tail = "진행 중" if clash.ended_at is None else clash.ended_at.isoformat()
    raise ConflictError(
        "같은 선박에 이미 겹치는 구간이 있습니다 "
        f"({clash.started_at.isoformat()} ~ {tail}). "
        "기존 구간의 종료 시각을 먼저 확정해 주세요."
    )


async def _snapshot_cf(session: AsyncSession, fuel_type: str) -> Decimal:
    """유종의 **현재 CF**를 떠 온다. 없거나 비활성이면 422.

    ``create_voyage``와 같은 처리다 — 이 값이 행에 박히고, 이후 CF가 개정돼도 과거
    계산은 이 snapshot으로 재현된다(``PRD §8.4``).
    """
    rows = await param_repo.get_fuel_types_by_codes(session, [fuel_type])
    if fuel_type not in rows:
        raise ValidationError(
            f"알 수 없는 연료 종류입니다: {fuel_type}",
            field="fuel_type",
            field_label="연료 종류",
        )
    return Decimal(str(rows[fuel_type].cf))


def _validate_enum(value: str, allowed: tuple[str, ...], *, field: str, label: str) -> None:
    """DB CHECK 제약을 **먼저** 확인한다.

    제약에 맡기면 IntegrityError가 올라와 500이 되고, 사용자는 「서버 오류」를 본다.
    실제로는 고칠 수 있는 입력이므로 422여야 한다.
    """
    if value not in allowed:
        # 조사를 붙이지 않는다 — 「유형은」/「소비원은」처럼 받침에 따라 갈리고,
        # 한국어 조사 판정을 오류 메시지 하나 때문에 들여올 이유가 없다.
        raise ValidationError(
            f"{label} 값이 올바르지 않습니다. 다음 중 하나여야 합니다: {', '.join(allowed)}",
            field=field,
            field_label=label,
        )


async def list_periods(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    regulation_year: int | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
) -> list[dict[str, object]]:
    """선박의 구간 목록 (API_SPEC §2.9).

    기록이 없으면 **빈 목록**이다 — 정박 기록이 없는 선박은 정상 상태이며 오류가
    아니다(저장소 ``sum_fuel_by_type``과 같은 판단).
    """
    await _require_vessel(session, vessel_id)

    periods = await nu_repo.list_periods(
        session,
        vessel_id=vessel_id,
        regulation_year=regulation_year,
        started_from=started_from,
        started_to=started_to,
    )
    # 구간마다 연료를 조회하면 N+1이다 — 한 번에 읽어 묶는다.
    fuel_map = await nu_repo.list_fuel_uses_for_periods(session, [p.id for p in periods])
    return [to_dict(p, fuel_map.get(p.id, [])) for p in periods]


async def create_period(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    period_type: str,
    started_at: datetime,
    ended_at: datetime | None,
    port_name: str | None,
    lat: Decimal | None,
    lon: Decimal | None,
    distance_nm: Decimal,
    regulation_year: int | None,
    voyage_id: UUID | None,
    fuel_uses: list[dict],
) -> dict[str, object]:
    """구간을 생성한다 (API_SPEC §2.10). 성공 시 201.

    **연료를 함께 받는다.** 구간만 먼저 만들고 연료를 뒤에 붙이게 하면, 중간에
    실패한 사용자가 연료 없는 구간을 남긴다 — 그 구간은 ``M``에 아무것도 더하지
    않으므로 **넣었는데 등급이 안 변하는** 상태가 된다. 한 번에 받아 한 트랜잭션에
    넣는다. 연료를 나중에 추가하는 경로(§2.13)는 따로 있다.
    """
    await _require_vessel(session, vessel_id)
    _validate_enum(period_type, PERIOD_TYPES, field="period_type", label="구간 유형")
    for fu in fuel_uses:
        _validate_enum(fu["consumer_type"], CONSUMER_TYPES, field="consumer_type", label="소비원")

    year = _resolve_regulation_year(started_at, ended_at, regulation_year)
    await _assert_no_overlap(session, vessel_id=vessel_id, started_at=started_at, ended_at=ended_at)

    # 알 수 있는 오류는 쓰기 전에 전부 확인한다 — 구간을 INSERT 한 뒤 연료에서
    # 실패하면 롤백되지만, 그때까지의 쿼리가 낭비다.
    _assert_no_duplicate_fuel(fuel_uses)
    cf_by_fuel = {fu["fuel_type"]: await _snapshot_cf(session, fu["fuel_type"]) for fu in fuel_uses}

    period = await nu_repo.insert_period(
        session,
        vessel_id=vessel_id,
        regulation_year=year,
        period_type=period_type,
        started_at=started_at,
        ended_at=ended_at,
        port_name=port_name,
        lat=lat,
        lon=lon,
        distance_nm=distance_nm,
        voyage_id=voyage_id,
    )

    for fu in fuel_uses:
        await nu_repo.insert_fuel_use(
            session,
            period_id=period.id,
            consumer_type=fu["consumer_type"],
            fuel_type=fu["fuel_type"],
            fuel_ton=fu["fuel_ton"],
            cf_used=cf_by_fuel[fu["fuel_type"]],
        )

    await session.commit()
    return to_dict(period, await nu_repo.list_fuel_uses(session, period.id))


def _assert_no_duplicate_fuel(fuel_uses: list[dict]) -> None:
    """같은 요청 안의 ``(소비원, 유종)`` 중복을 막는다.

    DB의 ``idx_not_underway_fuel_use_unique``가 막아 주지만, 그건 IntegrityError로
    올라와 500이 된다. 요청 안에서 미리 보면 어느 줄이 문제인지 말할 수 있다.
    """
    seen: set[tuple[str, str]] = set()
    for fu in fuel_uses:
        key = (fu["consumer_type"], fu["fuel_type"])
        if key in seen:
            raise ValidationError(
                f"같은 소비원·유종이 두 번 있습니다: {key[0]} · {key[1]}. 한 줄로 합쳐 주세요.",
                field="fuel_uses",
                field_label="연료 기록",
            )
        seen.add(key)


async def update_period(
    session: AsyncSession, period_id: UUID, **fields: object
) -> dict[str, object]:
    """구간을 수정한다 (API_SPEC §2.11). 없으면 404.

    **진행 중 구간의 종료 시각 확정이 주된 용도**다. 정박이 시작될 때는 언제 끝날지
    모르므로 ``ended_at`` 없이 넣고, 출항할 때 이 경로로 닫는다.

    ``exclude_unset`` 규약은 항차 수정(``#312``)과 같다 — **생략 = 변경 없음,
    명시적 ``null`` = 클리어**. 다만 ``ended_at``의 ``null``은 클리어가 아니라
    「다시 진행 중으로 되돌림」을 뜻한다. 잘못 닫은 구간을 되돌릴 경로가 필요하다.
    """
    period = await _require_period(session, period_id)

    # NOT NULL 열에 명시적 null이 오면 IntegrityError로 500이 된다. 이 열들에서
    # null은 「클리어」가 아니라 그냥 잘못된 입력이므로 422로 돌려준다.
    for column in ("period_type", "started_at", "distance_nm"):
        if column in fields and fields[column] is None:
            raise ValidationError(
                "비울 수 없는 항목입니다.",
                field=column,
                field_label=_FIELD_LABELS[column],
            )

    if "period_type" in fields:
        _validate_enum(
            str(fields["period_type"]), PERIOD_TYPES, field="period_type", label="구간 유형"
        )

    # 시각이 하나라도 바뀌면 순서와 겹침을 **바뀐 뒤의 값으로** 다시 본다.
    # 바뀌는 쪽만 검사하면 「종료만 앞당겨 시작보다 이르게」가 통과한다.
    started_at = fields.get("started_at", period.started_at)
    ended_at = fields.get("ended_at", period.ended_at)

    if ended_at is not None and started_at is not None and ended_at <= started_at:
        raise ValidationError(
            "종료 시각은 시작 시각보다 뒤여야 합니다.",
            field="ended_at",
            field_label="종료 시각",
        )

    if "started_at" in fields or "ended_at" in fields:
        await _assert_no_overlap(
            session,
            vessel_id=period.vessel_id,
            started_at=started_at,
            ended_at=ended_at,
            exclude_id=period.id,
        )

    # 시각이 바뀌면 귀속 연도가 더 이상 맞지 않을 수 있다.
    #
    # **기존 연도를 그대로 들고 검증하면 안 된다** — 2026년 구간을 2027년으로 옮기면
    # 저장된 2026이 새 범위에 없어 항상 거부된다. 사용자는 연도를 건드리지도 않았다.
    #
    # 그렇다고 무조건 다시 계산하면, 연말을 걸친 구간에서 사용자가 **일부러 고른**
    # 연도가 조용히 뒤집힌다. 그래서 세 갈래다.
    #   ⑴ 명시했으면 그 값을 검증한다.
    #   ⑵ 명시하지 않았고 기존 연도가 새 범위에 여전히 유효하면 그대로 둔다.
    #   ⑶ 유효하지 않으면 새 시작 연도로 옮긴다 — 아니면 집계에서 사라진다.
    if "regulation_year" in fields:
        fields["regulation_year"] = _resolve_regulation_year(
            started_at, ended_at, fields["regulation_year"]
        )
    elif "started_at" in fields or "ended_at" in fields:
        valid_years = {started_at.year} | ({ended_at.year} if ended_at else set())
        if period.regulation_year not in valid_years:
            fields["regulation_year"] = started_at.year

    for key, value in fields.items():
        setattr(period, key, value)

    await session.commit()
    await session.refresh(period)
    return to_dict(period, await nu_repo.list_fuel_uses(session, period.id))


async def delete_period(session: AsyncSession, period_id: UUID) -> dict[str, object]:
    """구간을 **소프트 삭제**한다 (API_SPEC §2.12). 없으면 404.

    자식 연료 행은 남는다 — 저장소 조회가 모두 부모의 ``is_deleted``로 판정하므로
    (``sum_fuel_by_type``) 집계에서는 즉시 빠진다. 자식까지 지우면 되살릴 수 없다.
    """
    period = await _require_period(session, period_id)
    period.is_deleted = True
    await session.commit()
    return {"id": str(period.id), "deleted": True}


async def add_fuel_use(
    session: AsyncSession,
    period_id: UUID,
    *,
    consumer_type: str,
    fuel_type: str,
    fuel_ton: Decimal,
) -> dict[str, object]:
    """구간에 연료 기록을 추가한다 (API_SPEC §2.13). 성공 시 201.

    구간을 만든 뒤 실적이 확인되는 경우를 위한 경로다 — 정박이 끝나야 총 소모량을
    알 수 있는 것이 보통이다.
    """
    period = await _require_period(session, period_id)
    _validate_enum(consumer_type, CONSUMER_TYPES, field="consumer_type", label="소비원")
    cf = await _snapshot_cf(session, fuel_type)

    # 중복은 DB unique 인덱스가 막지만 500이 된다. 먼저 확인해 409로 알린다 —
    # 「이미 있으니 수정하라」는 사용자가 할 수 있는 행동이다.
    for existing in await nu_repo.list_fuel_uses(session, period.id):
        if existing.consumer_type == consumer_type and existing.fuel_type == fuel_type:
            raise ConflictError(
                f"이 구간에 {consumer_type} · {fuel_type} 기록이 이미 있습니다. "
                "기존 기록을 지우고 다시 넣어 주세요."
            )

    fuel_use = await nu_repo.insert_fuel_use(
        session,
        period_id=period.id,
        consumer_type=consumer_type,
        fuel_type=fuel_type,
        fuel_ton=fuel_ton,
        cf_used=cf,
    )
    await session.commit()
    return _fuel_use_to_dict(fuel_use)


async def delete_fuel_use(
    session: AsyncSession, period_id: UUID, fuel_use_id: UUID
) -> dict[str, object]:
    """연료 기록을 삭제한다 (API_SPEC §2.13). 없으면 404.

    ``period_id``를 함께 받아 **다른 구간의 연료를 지우지 못하게** 한다. 자식 ID만
    받으면 URL을 바꿔 남의 구간을 건드릴 수 있고, 그 삭제는 CII 값을 조용히 바꾼다.
    """
    await _require_period(session, period_id)

    fuel_use = await nu_repo.get_fuel_use(session, fuel_use_id)
    if fuel_use is None or fuel_use.period_id != period_id:
        raise NotFoundError(f"연료 기록을 찾을 수 없습니다: {fuel_use_id}")

    await nu_repo.delete_fuel_use(session, fuel_use)
    await session.commit()
    return {"id": str(fuel_use_id), "deleted": True}
