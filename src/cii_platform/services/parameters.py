"""규제 파라미터 조회 서비스 (API_SPEC §7.1~§7.4, #444).

## 왜 읽기만 하는가

이 값들은 **계산의 근거**다. 같은 항차를 다시 계산했을 때 값이 달라지면 안 되는
이유가 여기 있고(``TECH_SPEC §5.4`` 재현성 계약), 그래서 ``parameter_hash``가 이
테이블들의 내용을 덮는다. 임의 수정 경로를 열면 **과거 계산 이력의 근거가 사라진다** —
개정 적재(``§7.5`` import)는 이력 보존·``is_active`` 전환 규칙(``DB_SCHEMA §3``)과 함께
설계해야 하는 별개의 일이다.

## 수치를 문자열로 내보낸다

``API_SPEC §1.7``이 파라미터 값도 Layer 1과 같이 문자열로 규정한다. JSON float
파싱에서 정밀도가 깎이면 클라이언트가 계산한 값이 서버와 미세하게 갈리는데, 그 차이는
등급 경계 근처에서만 드러나 발견이 늦다.

**자릿수를 다시 만들지 않는다.** 저장된 그대로 문자열로 옮긴다 — 줄이면 그 값이
원문인지 반올림인지 알 수 없게 되고, ``Decimal.normalize()``는 ``279000``을
``2.79E+5``로 바꿔 놓는다. 그래서 ``API_SPEC §7`` 예시(``"11.0"``)와 자릿수가 다를 수
있다(``"11.0000"``). **값은 같다.**
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.calc.capacity import DWT_BASED_SHIP_TYPES, GT_BASED_SHIP_TYPES
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.errors import ValidationError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: ``PRD §3.4.3``의 13종. ``services.vessel``과 같은 집합을 본다.
VALID_SHIP_TYPES: frozenset[str] = DWT_BASED_SHIP_TYPES | GT_BASED_SHIP_TYPES


def _num(value) -> str | None:
    """수치를 문자열로. 저장된 자릿수를 그대로 둔다 (모듈 docstring 참조)."""
    return None if value is None else str(value)


def _date(value) -> str | None:
    return None if value is None else value.isoformat()


def _validate_ship_type(ship_type: str | None) -> None:
    """모르는 선종은 **빈 배열이 아니라 오류**로 돌려준다 (#237과 같은 판단).

    검증하지 않으면 오타(``BULK_CARIER``)와 「그 선종의 파라미터가 아직 없다」가 둘 다
    빈 배열이 되어, 호출자가 원인을 알 수 없다.
    """
    if ship_type is None:
        return
    if ship_type not in VALID_SHIP_TYPES:
        raise ValidationError(
            f"알 수 없는 선종입니다: {ship_type}",
            field="ship_type",
            field_label="선종",
        )


async def list_regulation_years(session: AsyncSession) -> list[dict[str, object]]:
    """규정 연도(Z계수) 목록 (``API_SPEC §7.1``).

    **활성 행만 돌려준다.** 개정으로 대체된 행까지 섞으면 같은 연도가 두 번 나오고,
    호출자는 어느 것이 현행인지 알 수 없다 — 계산이 쓰는 것도 활성 행이다.
    """
    rows = await param_repo.list_regulation_years(session)
    return [
        {
            "year": row.year,
            "z_factor_percent": _num(row.z_factor_percent),
            "effective_from": _date(row.effective_from),
            "source_ref": row.source_ref,
            "version": row.version,
        }
        for row in rows
    ]


async def list_fuel_types(
    session: AsyncSession, *, active: bool | None = True
) -> list[dict[str, object]]:
    """연료 종류·CF 목록 (``API_SPEC §7.2``).

    ``is_active``를 응답에 실어 둔다 — ``active=false``로 조회한 호출자가 각 행의
    상태를 다시 묻지 않아도 되게.
    """
    rows = await param_repo.list_fuel_types(session, active=active)
    return [
        {
            "code": row.code,
            "display_name": row.display_name,
            "cf": _num(row.cf),
            "unit": row.unit,
            "source_ref": row.source_ref,
            "is_active": row.is_active,
        }
        for row in rows
    ]


async def list_reference_lines(
    session: AsyncSession, *, ship_type: str | None = None
) -> list[dict[str, object]]:
    """선종별 기준선 (``API_SPEC §7.3``).

    ``a_raw``와 ``a_decimal``을 **둘 다** 내보낸다. ``14405E7``은 IMO 표의 원문 표기이고
    ``a_decimal``은 그것을 푼 값이다(``PRD §3.4.3``) — 원문을 빼면 호출자가 우리 변환을
    검증할 수 없다.
    """
    _validate_ship_type(ship_type)
    rows = await param_repo.list_reference_lines(session, ship_type)
    return [
        {
            "ship_type": row.ship_type,
            "condition_expr": row.condition_expr,
            "capacity_rule": row.capacity_rule,
            "a_raw": row.a_raw,
            "a_decimal": _num(row.a_decimal),
            "c": _num(row.c),
            "source_ref": row.source_ref,
        }
        for row in rows
    ]


async def list_rating_boundaries(
    session: AsyncSession, *, ship_type: str | None = None
) -> list[dict[str, object]]:
    """선종별 등급 경계 d-vector (``API_SPEC §7.4``)."""
    _validate_ship_type(ship_type)
    rows = await param_repo.list_rating_boundaries(session, ship_type)
    return [
        {
            "ship_type": row.ship_type,
            "condition_expr": row.condition_expr,
            "capacity_basis": row.capacity_basis,
            "d1": _num(row.d1),
            "d2": _num(row.d2),
            "d3": _num(row.d3),
            "d4": _num(row.d4),
            "source_ref": row.source_ref,
        }
        for row in rows
    ]
