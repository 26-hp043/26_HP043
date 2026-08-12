"""선박 조회·등록 서비스 (#51, #50).

``api/routes``와 ``db/repositories`` 사이에서 **표현 규칙과 페이지네이션 판단**을 맡는다
(TECH_SPEC §16).

ORM 객체를 라우트로 그대로 올리지 않는다 — 그러면 API 응답 형태가 DB 스키마에
묶여, 컬럼을 추가하는 순간 응답이 조용히 바뀐다. 여기서 API_SPEC §2.1 형태의 dict로
옮긴다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from cii_platform.calc.capacity import DWT_BASED_SHIP_TYPES, GT_BASED_SHIP_TYPES
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.db.repositories import vessel as vessel_repo
from cii_platform.db.repositories.vessel import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Cursor,
    decode_cursor,
    encode_cursor,
)
from cii_platform.errors import NotFoundError, ParameterError, ValidationError

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: API_SPEC §2.3 — ``is_cii_applicable_hint`` 자동 산정 기준 (DB_SCHEMA §2.1).
#: ``gross_tonnage >= 5,000``이면 공식 CII 적용 대상 힌트를 true로 둔다.
CII_APPLICABLE_GT_THRESHOLD = Decimal("5000")

#: 검색어 최대 길이. ``Vessel.name``이 ``String(100)``이라 그보다 긴 검색어는 의미가
#: 없다 (#237). 초과 시 422가 아니라 절단 — ``normalize_limit``과 같은 정책.
SEARCH_MAX_LENGTH = 100

#: 유효한 선종 집합 (PRD §3.4.3 13종). ``ship_type`` 쿼리 파라미터 검증에 쓴다 (#237).
VALID_SHIP_TYPES: frozenset[str] = DWT_BASED_SHIP_TYPES | GT_BASED_SHIP_TYPES


def _number(value: Decimal | None) -> float | None:
    """선박 제원을 JSON number로 만든다.

    **Layer 1 값이 아니다.** ``gross_tonnage``·``deadweight``는 계산 입력이지 결정론
    산출값이 아니며, API_SPEC §2.1 예시가 ``25000.0``처럼 숫자로 적고 있다.
    Layer 1 문자열 직렬화(§1.7)는 계산 **결과**에만 적용된다.
    """
    return None if value is None else float(value)


def _iso(value) -> str | None:
    """``created_at``·``updated_at``을 ISO8601 문자열로 만든다."""
    return None if value is None else value.isoformat()


def to_dict(vessel) -> dict[str, object]:
    """ORM 객체를 API_SPEC §2.1 선박 객체로 옮긴다.

    키 순서를 §2.1 예시와 같게 둔다 — 계약 예시와 실제 응답을 눈으로 대조할 때
    순서가 다르면 대조가 느려진다.
    """
    return {
        "id": str(vessel.id),
        "imo_number": vessel.imo_number,
        "name": vessel.name,
        "ship_type": vessel.ship_type,
        "gross_tonnage": _number(vessel.gross_tonnage),
        "deadweight": _number(vessel.deadweight),
        "default_fuel_type": vessel.default_fuel_type,
        "reference_speed_kn": _number(vessel.reference_speed_kn),
        "reference_daily_foc_ton": _number(vessel.reference_daily_foc_ton),
        "is_cii_applicable_hint": vessel.is_cii_applicable_hint,
        "created_at": _iso(vessel.created_at),
        "updated_at": _iso(vessel.updated_at),
    }


def normalize_limit(limit: int | None) -> int:
    """``limit`` 쿼리 파라미터를 정규화한다 (API_SPEC §2.1 「기본 20, 최대 100」).

    **초과값을 오류로 만들지 않고 잘라 낸다.** 목록 조회에서 큰 ``limit``은 공격이
    아니라 오해인 경우가 대부분이고, 422를 내면 클라이언트가 재시도 로직을 따로
    만들어야 한다. 상한을 넘겨도 상한만큼은 정상 응답한다.
    """
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        raise ValidationError(
            "limit은 1 이상이어야 합니다.", field="limit", field_label="페이지 크기"
        )
    return min(limit, MAX_LIMIT)


def _parse_cursor(cursor: str | None) -> Cursor | None:
    """커서를 해석한다. 깨진 커서는 **422**로 돌려준다.

    첫 페이지로 조용히 폴백하면 클라이언트가 무한 루프에 빠질 수 있다 — 같은 커서로
    계속 요청하면서 매번 첫 페이지를 받게 된다.
    """
    if cursor is None:
        return None
    parsed = decode_cursor(cursor)
    if parsed is None:
        raise ValidationError(
            "cursor 형식이 올바르지 않습니다.", field="cursor", field_label="커서"
        )
    return parsed


def _normalize_search(search: str | None) -> str | None:
    """``search`` 쿼리 파라미터를 정규화한다 (#237).

    빈 문자열은 ``None``으로 — 빈 검색 = 필터 없음과 같다. 길이 상한
    (:data:`SEARCH_MAX_LENGTH`) 초과는 절단한다 — ``normalize_limit``과 같은 정책,
    초과값을 422로 만들면 클라이언트가 재시도 로직을 따로 만들어야 한다.
    """
    if search is None or search == "":
        return None
    return search[:SEARCH_MAX_LENGTH]


def _validate_ship_type(ship_type: str | None) -> None:
    """``ship_type`` 쿼리 파라미터가 13종 안에 없으면 ``ValidationError`` (#237).

    오타(``BULK_CARIER``)와 "해당 선박 없음"을 응답에서 구분한다 — 미검증 시 둘 다
    빈 배열로 돌아와 사용자가 원인을 알 수 없다.
    """
    if ship_type is None:
        return
    if ship_type not in VALID_SHIP_TYPES:
        raise ValidationError(
            f"알 수 없는 선종입니다: {ship_type}",
            field="ship_type",
            field_label="선종",
        )


async def get_vessel(session: AsyncSession, vessel_id: UUID) -> dict[str, object]:
    """선박 상세 (API_SPEC §2.2). 없으면 404."""
    vessel = await vessel_repo.get_by_id(session, vessel_id)
    if vessel is None:
        raise NotFoundError(f"선박을 찾을 수 없습니다: {vessel_id}")
    return to_dict(vessel)


async def create_vessel(
    session: AsyncSession,
    *,
    imo_number: str,
    name: str,
    ship_type: str,
    gross_tonnage: Decimal | None = None,
    deadweight: Decimal | None = None,
    default_fuel_type: str | None = None,
    reference_speed_kn: Decimal | None = None,
    reference_daily_foc_ton: Decimal | None = None,
) -> dict[str, object]:
    """선박을 등록한다 (API_SPEC §2.3, #50). 성공 시 201.

    서비스가 담당하는 3가지 (형식·범위는 Pydantic이 잡음):

    - **VAL-004 (``ship_type`` 존재)**: ``cii_reference_line`` 테이블에 해당 선종의
      행이 있어야 한다. 없으면 ``ValidationError``(422).
    - **중복 IMO**: 활성 선박(soft delete 제외) 중 같은 IMO가 있으면
      ``ParameterError``(409). **409 → PARAMETER_ERROR 매핑이 API_SPEC §1.4에서
      유일한 409 코드**라 이를 재사용한다. 전용 CONFLICT 코드 신설은 별도 정본
      변경 이슈로 둔다.
    - **``is_cii_applicable_hint`` 자동 산정**: ``gross_tonnage >= 5,000``(§2.3).

    ``commit``을 여기서 한다 — 단일 리소스 생성이 트랜잭션 경계다.
    """
    ref_lines = await param_repo.list_reference_lines(session, ship_type)
    if not ref_lines:
        raise ValidationError(
            f"알 수 없는 선종입니다: {ship_type}",
            field="ship_type",
            field_label="선종",
        )

    existing = await vessel_repo.find_active_by_imo(session, imo_number)
    if existing is not None:
        raise ParameterError(f"이미 등록된 IMO 번호입니다: {imo_number}")

    is_cii_applicable_hint = bool(
        gross_tonnage is not None and gross_tonnage >= CII_APPLICABLE_GT_THRESHOLD
    )

    vessel = await vessel_repo.insert(
        session,
        imo_number=imo_number,
        name=name,
        ship_type=ship_type,
        gross_tonnage=gross_tonnage,
        deadweight=deadweight,
        default_fuel_type=default_fuel_type,
        reference_speed_kn=reference_speed_kn,
        reference_daily_foc_ton=reference_daily_foc_ton,
        is_cii_applicable_hint=is_cii_applicable_hint,
    )
    await session.commit()
    return to_dict(vessel)


async def list_vessels(
    session: AsyncSession,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    ship_type: str | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """선박 목록과 페이지네이션 메타를 반환한다 (API_SPEC §2.1).

    저장소가 ``limit + 1``건을 주므로 **초과분의 존재 여부가 곧 ``has_more``**다.
    별도 COUNT 쿼리를 돌리지 않는다 — 그 값은 응답에 쓰이지도 않는다(§2.1 meta에
    ``total``이 없다).
    """
    # ship_type을 먼저 검증한다 — repo가 쿼리를 날리기 전에 422로 끊는다 (#237).
    _validate_ship_type(ship_type)
    page_size = normalize_limit(limit)
    rows = await vessel_repo.list_active(
        session,
        limit=page_size,
        cursor=_parse_cursor(cursor),
        ship_type=ship_type,
        search=_normalize_search(search),
    )

    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = (
        encode_cursor(Cursor(name=page[-1].name, vessel_id=str(page[-1].id)))
        if has_more and page
        else None
    )

    return [to_dict(row) for row in page], {
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
