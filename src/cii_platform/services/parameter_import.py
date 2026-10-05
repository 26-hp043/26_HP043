"""규제 파라미터 CSV 적재 서비스 (API_SPEC §7.5, #673 · 결정요청 v9 회신 「가」).

## 사무직 전용

``#672``의 역할 2종으로 「누가 부를 수 있는가」가 정해졌다 — 라우트가
``require_office``를 걸고, 적재를 감사 로그(``PARAMETER_IMPORT``)에 남긴다.

## 전부 아니면 전무

항차·정박 CSV(``§8.2``)가 **부분 성공**인 것과 정반대 계약이다. 규정 파라미터는
일부만 들어가면 계산 근거가 반쪽이 되므로(``§8.2`` 각주 · ``TEST_PLAN``
``IT-IMPORT-005``), **한 행이라도 걸리면 아무것도 들어가지 않는다.** ``dry_run``과
``errors[]``의 모양만 ``§8.2`` 규약을 따른다(#1190 — 원본 행 번호·필드·사유,
``dry_run``은 실제 적재와 같은 판정).

## 개정은 새 행, 연료는 제자리

세 테이블(``regulation_year`` · ``cii_reference_line`` · ``cii_rating_boundary``)은
기존 활성 행을 끄고(``is_active = 0``) 새 행을 넣는다(``DB_SCHEMA §7.2`` · ``#98``).
``fuel_type``은 같은 절의 **명시적 예외** — CF를 제자리에서 고치고 ``content_hash``를
다시 계산한다(``TECH_SPEC §5.2`` ``parameter_hash`` 계약이 제자리 갱신 추적을 요구).
``OTHER`` 연료 생성(``PRD §3.4.2`` SHOULD)은 이 경로가 유일한 쓰기 경로다.

## 재현성

과거 계산은 각자 스냅숏을 가지므로 보존된다(``PRD §8.4``). 연간 시뮬레이션의
재현은 활성 CF를 다시 읽어 ``parameter_hash``가 갈리면 409로 끊는다(#816 ⑶) —
**개정이 드러나는 것이 계약대로다.**
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from cii_platform.calc.capacity import ConditionInterval, parse_condition
from cii_platform.calc.hash import compute_parameter_hash
from cii_platform.calc.imo_parser import parse_imo_scientific
from cii_platform.db.models.cii_rating_boundary import CiiRatingBoundary
from cii_platform.db.models.cii_reference_line import CiiReferenceLine
from cii_platform.db.models.fuel_type import FuelType
from cii_platform.db.models.regulation_year import RegulationYear
from cii_platform.db.repositories import audit_log as audit_repo
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.errors import ValidationError
from cii_platform.reports.csv_export import sanitize
from cii_platform.services.parameters import VALID_SHIP_TYPES
from cii_platform.services.voyage_import import (
    RowError,
    _check_limits,
    _decode,
    column_length,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

#: 지원하는 적재 종류 — 라우트의 ``type`` 폼 필드 값 그대로.
KINDS: tuple[str, ...] = (
    "regulation_years",
    "reference_lines",
    "rating_boundaries",
    "fuel_types",
)

#: 행 수 상한은 항차 CSV와 같은 값을 쓴다(``§8.2`` 보안 표). 시드 전체(연도 8 ·
#: 기준선 20 · 경계 14 · 연료 8)를 합쳐도 50행이다 — 규정 개정이 1,000행을 넘지 않는다.
MAX_ROWS = 1_000

#: 규정연도 범위 — 항차의 ``chk_regulation_year_range``(046)와 같은 값이다. 이 표에
#: 2019년 이전·2050년 이후의 규정연도는 없다.
_YEAR_MIN, _YEAR_MAX = 2019, 2050

#: 050 ⑶ — 정본 ``§2.10 [M-7]``: ``fixed`` 뒤에는 숫자만, 대소문자 구분.
_FIXED_RE = re.compile(r"^fixed [0-9]+$")

_SAVE_STAGE_MESSAGE = "저장 단계에서 거부됐습니다. 값을 확인해 주세요."

#: 조건식 문법 안내 — 예시는 엔진이 받는 세 형태 그대로다(``calc/capacity.py``).
_CONDITION_MESSAGE = (
    "조건식을 읽을 수 없습니다. 'all' · 'DWT >= 279000' · 'GT < 30000' · "
    "'65000 <= DWT < 100000' 형태여야 합니다."
)

#: 구간 판정을 하는 종류와 그 활성 행 조회 함수.
_PARTITIONED = {
    "reference_lines": param_repo.list_reference_lines,
    "rating_boundaries": param_repo.list_rating_boundaries,
}


#: 적재 행의 ``version`` 라벨. 시드의 ``1.0``과 달리 **사람이 올린 배치**임이 드러난다 —
#: ``source_ref``가 무엇을 근거로 들어왔는지를 말하고, 이 값이 언제 들어왔는지를 말한다.
def _import_version() -> str:
    return f"import.{datetime.now(UTC):%Y%m%dT%H%M%SZ}"


class _Spec:
    """한 종류의 CSV 열 규격 — 한도를 모델에서 끌어낸다(#1190와 같은 판단)."""

    def __init__(self, model: type, required: tuple[str, ...]) -> None:
        self.model = model
        self.required = required

    def length(self, column: str) -> int:
        return column_length(column, model=self.model)

    def numeric(self, column: str) -> tuple[int, int]:
        """``NUMERIC(p, s)``의 ``(p, s)``."""
        type_ = self.model.__table__.columns[column].type
        return (type_.precision, type_.scale)


_SPECS: dict[str, _Spec] = {
    "regulation_years": _Spec(
        RegulationYear,
        ("year", "z_factor_percent", "effective_from", "source_ref"),
    ),
    "reference_lines": _Spec(
        CiiReferenceLine,
        ("ship_type", "condition_expr", "capacity_rule", "a_raw", "c", "source_ref"),
    ),
    "rating_boundaries": _Spec(
        CiiRatingBoundary,
        (
            "ship_type",
            "condition_expr",
            "capacity_basis",
            "d1",
            "d2",
            "d3",
            "d4",
            "source_ref",
        ),
    ),
    "fuel_types": _Spec(FuelType, ("code", "display_name", "cf", "source_ref")),
}

#: ``fuel_types``의 선택 열 — ``OTHER`` 생성에만 필수가 된다(``PRD §3.4.2``).
_FUEL_OPTIONAL: tuple[str, ...] = ("effective_from",)


# ── 파일 단계 ────────────────────────────────────────────────────────────────


def read_rows(
    content: bytes, kind: str, *, content_type: str | None = None
) -> tuple[list[dict[str, str]], int]:
    """파일을 행 목록으로 읽는다. 둘째 값은 상한을 넘겨 잘라 낸 행 수다.

    파일 단위 문제(크기·형식·인코딩·필수 컬럼)는 ``voyage_import.read_rows``와 같은
    규약으로 ``ValidationError`` — 그 경우 한 행도 읽지 않는다.
    """
    _check_limits(content, content_type)
    reader = csv.DictReader(io.StringIO(_decode(content), newline=""))
    required = _SPECS[kind].required + (_FUEL_OPTIONAL if kind == "fuel_types" else ())
    missing = [column for column in required if column not in (reader.fieldnames or [])]
    if missing:
        raise ValidationError(
            f"필수 컬럼이 없습니다: {', '.join(missing)}",
            field="file",
            field_label="파일",
        )
    rows: list[dict[str, str]] = []
    truncated = 0
    for row in reader:
        if len(rows) >= MAX_ROWS:
            truncated += 1
            continue
        rows.append(row)
    return rows, truncated


# ── 행 단계 파서 ─────────────────────────────────────────────────────────────


def _text(row: dict[str, str], column: str, spec: _Spec) -> str:
    """문자 열 — escape한 뒤의 길이를 잰다(#1190와 같은 규칙)."""
    raw = (row.get(column) or "").strip()
    if raw == "":
        raise RowError(column, "값을 입력해 주세요.")
    value = sanitize(raw)
    limit = spec.length(column)
    if len(value) > limit:
        raise RowError(column, f"{limit}자까지 입력할 수 있습니다(지금 {len(value)}자).")
    return value


def _numeric(row: dict[str, str], column: str, spec: _Spec) -> Decimal:
    """숫자 열 — 수식 문자열·자릿수 초과를 여기서 걸는다.

    ``NUMERIC(p, s)``의 범위를 벗어나면 CUBRID가 저장 단계에서 거부하는데(-494),
    파서가 먼저 막아야 ``dry_run``이 실제 적재와 같은 판정을 낸다(#1190).
    """
    raw = (row.get(column) or "").strip()
    if raw == "":
        raise RowError(column, "값을 입력해 주세요.")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise RowError(column, f"숫자로 읽을 수 없습니다: {raw}") from exc
    if not value.is_finite():
        raise RowError(column, f"숫자로 읽을 수 없습니다: {raw}")
    precision, scale = spec.numeric(column)
    if -value.as_tuple().exponent > scale:
        raise RowError(column, f"소수 {scale}자리까지 입력할 수 있습니다.")
    if value != 0 and value.adjusted() + 1 > precision - scale:
        raise RowError(column, f"너무 큽니다(정수 {precision - scale}자리까지).")
    return value


def _date(row: dict[str, str], column: str, *, required: bool) -> date | None:
    raw = (row.get(column) or "").strip()
    if raw == "":
        if required:
            raise RowError(column, "값을 입력해 주세요.")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise RowError(column, "날짜로 읽을 수 없습니다(예: 2027-01-01).") from exc


def _int(row: dict[str, str], column: str) -> int:
    raw = (row.get(column) or "").strip()
    if raw == "":
        raise RowError(column, "값을 입력해 주세요.")
    try:
        return int(raw)
    except ValueError as exc:
        raise RowError(column, f"연도로 읽을 수 없습니다: {raw}") from exc


def _condition(row: dict[str, str], spec: _Spec) -> str:
    """``condition_expr`` — 계산 엔진이 읽는 문법인지 적재 전에 본다 (#2087).

    엔진은 그 선종의 활성 행 **전부**에 조건식을 평가하므로, 못 읽는 식이 한 행이라도
    활성으로 들어가면 그 선종의 CII 계산이 전부 409가 된다. 판정은 엔진과 **같은 함수**
    (:func:`~cii_platform.calc.capacity.parse_condition`)로 한다 — 문법을 여기 다시 적으면
    두 곳이 갈린다.
    """
    value = _text(row, "condition_expr", spec)
    try:
        interval = parse_condition(value)
    except ValueError as exc:
        raise RowError("condition_expr", _CONDITION_MESSAGE) from exc
    if interval.upper is not None and interval.lower >= interval.upper:
        raise RowError("condition_expr", "구간의 하한이 상한보다 작아야 합니다.")
    return value


def partition_problem(conditions: Sequence[str]) -> str | None:
    """한 선종의 활성 조건식들이 전 구간을 **빈틈·겹침 없이** 덮는지 본다 (#2087).

    덮으면 ``None``, 아니면 사용자에게 보일 사유를 돌려준다. 엔진은 선박마다 정확히
    한 행이 맞아야 계산한다(``select_reference_line`` · ``select_rating_boundary``) —
    0행이면 「해당 없음」, 2행이면 「모호함」으로 둘 다 409다.

    DB를 보지 않는 순수 함수다. 무엇을 넘길지(기존 활성 행 + 파일의 행)는 호출자가 정한다.
    """
    intervals: list[tuple[ConditionInterval, str]] = []
    for condition in conditions:
        try:
            intervals.append((parse_condition(condition), condition))
        except ValueError:
            return f"읽을 수 없는 조건식이 활성 행에 있습니다: {condition}"
    if not intervals:
        return "활성 행이 없습니다."
    if any(interval.axis is None for interval, _ in intervals):
        if len(intervals) == 1:
            return None
        others = ", ".join(text for interval, text in intervals if interval.axis is not None)
        return f"'all'은 다른 조건식과 함께 둘 수 없습니다 — 구간이 겹칩니다: {others}"
    axes = sorted({interval.axis for interval, _ in intervals if interval.axis is not None})
    if len(axes) > 1:
        return f"한 선종의 조건식이 서로 다른 축을 씁니다: {' · '.join(axes)}"
    axis = axes[0]
    ordered = sorted(intervals, key=lambda pair: pair[0].lower)
    if ordered[0][0].lower != 0:
        return f"{axis} {ordered[0][0].lower} 미만을 덮는 행이 없습니다."
    for (current, current_text), (following, following_text) in pairwise(ordered):
        if current.upper is None or current.upper > following.lower:
            return f"구간이 겹칩니다: '{current_text}' · '{following_text}'"
        if current.upper < following.lower:
            return f"{axis} {current.upper} 이상 {following.lower} 미만을 덮는 행이 없습니다."
    last = ordered[-1][0]
    if last.upper is not None:
        return f"{axis} {last.upper} 이상을 덮는 행이 없습니다."
    return None


def _parse_regulation_year(row: dict[str, str]) -> dict[str, object]:
    spec = _SPECS["regulation_years"]
    year = _int(row, "year")
    if not _YEAR_MIN <= year <= _YEAR_MAX:
        raise RowError("year", f"규정연도는 {_YEAR_MIN}~{_YEAR_MAX} 범위여야 합니다.")
    z = _numeric(row, "z_factor_percent", spec)
    if z < 0:  # chk_z_factor_nonneg(046) — 0도 형식상 유효하다(2019 대비 감축 없음 · #1347)
        raise RowError("z_factor_percent", "Z-factor는 음수일 수 없습니다.")
    return {
        "key": (year,),
        "year": year,
        "z_factor_percent": z,
        "effective_from": _date(row, "effective_from", required=True),
        "source_ref": _text(row, "source_ref", spec),
    }


def _parse_reference_line(row: dict[str, str]) -> dict[str, object]:
    spec = _SPECS["reference_lines"]
    ship_type = _text(row, "ship_type", spec)
    if ship_type not in VALID_SHIP_TYPES:
        raise RowError("ship_type", f"알 수 없는 선종입니다: {ship_type}")
    condition_expr = _condition(row, spec)
    capacity_rule = _text(row, "capacity_rule", spec)
    if capacity_rule not in ("DWT", "GT") and not _FIXED_RE.match(capacity_rule):
        raise RowError("capacity_rule", "DWT · GT · 'fixed 279000' 형태여야 합니다.")
    a_raw = _text(row, "a_raw", spec)
    try:
        # §9.2 — NaN·무한·비양수도 parse_imo_scientific이 여기서 걸러낸다. 변환 실패는
        # ValueError가 아니라 decimal.InvalidOperation(ArithmeticError 계열)으로 터진다.
        a_decimal = parse_imo_scientific(a_raw)
    except (ValueError, ArithmeticError) as exc:
        raise RowError("a_raw", f"IMO 계수로 읽을 수 없습니다: {a_raw}") from exc
    precision, scale = spec.numeric("a_decimal")
    if a_decimal.adjusted() + 1 > precision - scale:
        raise RowError("a_raw", f"변환값이 커서 저장할 수 없습니다: {a_decimal}")
    # 소수 자릿수도 다른 숫자 열(`_numeric`)과 같은 수준으로 본다 (#2087). 넘는 자리는
    # 저장 단계에서 조용히 깎여, 적재한 값과 계산이 읽는 값이 달라진다.
    if -a_decimal.as_tuple().exponent > scale:
        raise RowError("a_raw", f"변환값의 소수가 {scale}자리를 넘습니다: {a_decimal}")
    c = _numeric(row, "c", spec)
    if c < 0:  # chk_c_positive(046)
        raise RowError("c", "c는 음수일 수 없습니다.")
    return {
        "key": (ship_type, condition_expr),
        "ship_type": ship_type,
        "condition_expr": condition_expr,
        "capacity_rule": capacity_rule,
        "a_raw": a_raw,
        "a_decimal": a_decimal,
        "c": c,
        "source_ref": _text(row, "source_ref", spec),
    }


def _parse_rating_boundary(row: dict[str, str]) -> dict[str, object]:
    spec = _SPECS["rating_boundaries"]
    ship_type = _text(row, "ship_type", spec)
    if ship_type not in VALID_SHIP_TYPES:
        raise RowError("ship_type", f"알 수 없는 선종입니다: {ship_type}")
    condition_expr = _condition(row, spec)
    capacity_basis = _text(row, "capacity_basis", spec)
    if capacity_basis not in ("DWT", "GT"):
        raise RowError("capacity_basis", "DWT 또는 GT여야 합니다.")
    ds = {name: _numeric(row, name, spec) for name in ("d1", "d2", "d3", "d4")}
    if not (ds["d1"] < ds["d2"] < ds["d3"] < ds["d4"]):  # chk_d_order
        raise RowError("d1", "d1 < d2 < d3 < d4 순서여야 합니다.")
    return {
        "key": (ship_type, condition_expr),
        "ship_type": ship_type,
        "condition_expr": condition_expr,
        "capacity_basis": capacity_basis,
        **ds,
        "source_ref": _text(row, "source_ref", spec),
    }


def _parse_fuel_type(row: dict[str, str]) -> dict[str, object]:
    spec = _SPECS["fuel_types"]
    code = _text(row, "code", spec)
    cf = _numeric(row, "cf", spec)
    if cf <= 0:  # chk_cf_positive(046)
        raise RowError("cf", "CF는 0보다 커야 합니다.")
    # PRD §3.4.2 — OTHER 연료는 CF 출처 메모와 적용 시작일이 필수다. source_ref는
    # 이미 필수 컬럼이므로 여기서는 적용 시작일만 본다.
    return {
        "key": (code,),
        "code": code,
        "display_name": _text(row, "display_name", spec),
        "cf": cf,
        "effective_from": _date(row, "effective_from", required=code == "OTHER"),
        "source_ref": _text(row, "source_ref", spec),
    }


_PARSERS = {
    "regulation_years": _parse_regulation_year,
    "reference_lines": _parse_reference_line,
    "rating_boundaries": _parse_rating_boundary,
    "fuel_types": _parse_fuel_type,
}

#: 파일 안 키 중복 오류의 ``field`` — 각 종류의 키 첫 열 이름.
_KEY_FIELD = {
    "regulation_years": "year",
    "reference_lines": "ship_type",
    "rating_boundaries": "ship_type",
    "fuel_types": "code",
}


def _row_number(index: int) -> int:
    """원본 파일에서 보이는 행 번호(헤더 1행 기준) — §8.2와 같은 표기."""
    return index + 2


# ── 적재 ─────────────────────────────────────────────────────────────────────


async def _apply_fuel_types(
    session: AsyncSession, parsed: Sequence[tuple[int, dict[str, object]]], version: str
) -> tuple[int, int]:
    """``(적용된 행 수, 그중 기존 행을 갱신한 수)``를 돌려준다.

    ``fuel_type``의 갱신도 「적용」이다 — ``imported_count``가 신규 행만 세면
    사용자는 CF 개정 파일을 올리고 「아무것도 안 들어갔다」로 읽는다.
    """
    created = updated = 0
    for row_number, item in parsed:
        existing = await param_repo.get_fuel_type_by_code(session, item["code"])
        content_hash = compute_parameter_hash({"code": item["code"], "cf": item["cf"]})
        if existing is None:
            session.add(
                FuelType(
                    id=uuid.uuid4(),
                    code=item["code"],
                    display_name=item["display_name"],
                    cf=item["cf"],
                    source_ref=item["source_ref"],
                    effective_from=item["effective_from"],
                    version=version,
                    content_hash=content_hash,
                )
            )
            created += 1
        else:
            # §7.2 예외 — 제자리 갱신. content_hash가 갱신을 추적한다.
            existing.display_name = item["display_name"]
            existing.cf = item["cf"]
            existing.source_ref = item["source_ref"]
            if item["effective_from"] is not None:
                existing.effective_from = item["effective_from"]
            existing.version = version
            existing.content_hash = content_hash
            updated += 1
        # 행마다 flush — 저장 단계 거부가 **어느 행**인지 지목하게 한다(파일은 작다).
        await _flush_row(session, row_number)
    return created + updated, updated


async def _apply_versioned(
    session: AsyncSession,
    kind: str,
    parsed: Sequence[tuple[int, dict[str, object]]],
    version: str,
) -> tuple[int, int]:
    """``(새 행, 대체한 활성 행)`` 수를 돌려준다."""
    model = {
        "regulation_years": RegulationYear,
        "reference_lines": CiiReferenceLine,
        "rating_boundaries": CiiRatingBoundary,
    }[kind]
    getter = {
        "regulation_years": param_repo.get_regulation_year,
        "reference_lines": param_repo.get_active_reference_line,
        "rating_boundaries": param_repo.get_active_rating_boundary,
    }[kind]
    inserted = replaced = 0
    for row_number, item in parsed:
        existing = await getter(session, *item["key"])
        if existing is not None:
            existing.is_active = False  # 이행 행으로 남는다 — 값은 그대로 둔다
            replaced += 1
        session.add(
            model(
                id=uuid.uuid4(),
                **{column: value for column, value in item.items() if column != "key"},
                is_active=True,
                version=version,
            )
        )
        inserted += 1
        await _flush_row(session, row_number)
    return inserted, replaced


async def _partition_errors(
    session: AsyncSession, kind: str, parsed: Sequence[tuple[int, dict[str, object]]]
) -> list[dict[str, object]]:
    """적재 **뒤의** 선종별 활성 행이 전 구간을 덮는지 본다 (#2087).

    적재 뒤의 활성 행 = 파일의 행 + 파일에 같은 키가 없는 기존 활성 행이다
    (``_apply_versioned``가 끄는 것은 키가 같은 행뿐이다). ``dry_run``도 여기를 지난다 —
    실제 적재와 같은 판정이어야 한다(#1190).

    오류는 그 선종의 **파일 첫 행**에 붙인다. 구간은 여러 행이 함께 만드는 성질이라
    한 행을 지목할 수 없고, 사용자가 고칠 자리는 그 선종의 행들이다.
    """
    by_ship_type: dict[str, list[tuple[int, str]]] = {}
    for row_number, item in parsed:
        by_ship_type.setdefault(str(item["ship_type"]), []).append(
            (row_number, str(item["condition_expr"]))
        )
    found: list[dict[str, object]] = []
    for ship_type, rows in by_ship_type.items():
        in_file = {condition for _, condition in rows}
        kept = [
            existing.condition_expr
            for existing in await _PARTITIONED[kind](session, ship_type)
            if existing.condition_expr not in in_file
        ]
        problem = partition_problem([*kept, *(condition for _, condition in rows)])
        if problem is not None:
            found.append(
                {
                    "row": rows[0][0],
                    "field": "condition_expr",
                    "message": f"{ship_type}의 구간이 맞지 않습니다 — {problem}",
                }
            )
    return found


async def _flush_row(session: AsyncSession, row_number: int) -> None:
    """한 행을 flush — 저장 단계 거부를 행 번호와 함께 올린다.

    파서가 컬럼 한도를 전부 보므로 여기 오는 행은 없어야 한다(#1190와 같은 계약).
    오면 ``errors[]``의 행 지목이 사용자에게 필요한 전부이고, 원문은 로그로 남긴다.
    """
    try:
        await session.flush()
    except SQLAlchemyError as error:
        raise _SaveStageFailure(row_number, error) from error


class _SaveStageFailure(Exception):
    """저장 단계 거부를 행 번호와 함께 올린다 — ``errors[]`` 한 건이 된다."""

    def __init__(self, row_number: int, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.row_number = row_number
        self.cause = cause


async def import_parameters(
    session: AsyncSession,
    *,
    kind: str,
    content: bytes,
    content_type: str | None = None,
    dry_run: bool = False,
    user_id: str | None = None,
    ip_address: str | None = None,
) -> dict[str, object]:
    """규제 파라미터 CSV를 적재한다 (``API_SPEC §7.5`` · #673).

    ``dry_run``이면 **검증만 하고 아무것도 만들지 않는다** — ``imported_count``는
    「들어갈 수 있는 행 수」다. 판정이 실제 적재와 같아야 한다는 것은 ``§8.2``의
    #1190 규약을 그대로 따른다.
    """
    if kind not in KINDS:
        raise ValidationError(
            f"지원하지 않는 적재 종류입니다: {kind}",
            field="type",
            field_label="적재 종류",
        )

    rows, truncated = read_rows(content, kind, content_type=content_type)
    errors: list[dict[str, object]] = []
    parsed: list[tuple[int, dict[str, object]]] = []
    seen_keys: set[tuple[object, ...]] = set()

    for index, row in enumerate(rows):
        number = _row_number(index)
        try:
            item = _PARSERS[kind](row)
        except RowError as error:
            errors.append({"row": number, "field": error.field, "message": error.message})
            continue
        if item["key"] in seen_keys:
            errors.append(
                {
                    "row": number,
                    "field": _KEY_FIELD[kind],
                    "message": "파일 안에서 키가 중복됩니다 — 한 번만 넣어 주세요.",
                }
            )
            continue
        seen_keys.add(item["key"])
        parsed.append((number, item))

    if truncated:
        errors.append(
            {
                "row": MAX_ROWS + 2,
                "field": "file",
                "message": f"행 수 상한({MAX_ROWS})을 넘어 {truncated}행을 처리하지 않았습니다.",
            }
        )

    # 행이 전부 읽혔을 때만 구간을 본다 — 행 오류가 있으면 그 행이 빠진 채로 판정하게
    # 되어, 고치면 사라질 「빈틈」을 함께 보고한다.
    if not errors and kind in _PARTITIONED:
        errors.extend(await _partition_errors(session, kind, parsed))

    if dry_run or errors:
        return {
            "table": kind,
            "imported_count": 0 if errors else len(parsed),
            "replaced_count": 0,
            "errors": errors,
            "dry_run": dry_run,
        }

    # ⚠️ 오류가 없을 때만 여기 온다 — 전부 아니면 전무(IT-IMPORT-005).
    version = _import_version()
    try:
        if kind == "fuel_types":
            applied, replaced_count = await _apply_fuel_types(session, parsed, version)
        else:
            applied, replaced_count = await _apply_versioned(session, kind, parsed, version)
    except _SaveStageFailure as failure:
        await session.rollback()
        _log.warning(
            "파라미터 적재가 저장 단계(%d행)에서 거부됐다: %s",
            failure.row_number,
            failure.cause,
        )
        return {
            "table": kind,
            "imported_count": 0,
            "replaced_count": 0,
            "errors": [
                {"row": failure.row_number, "field": "file", "message": _SAVE_STAGE_MESSAGE}
            ],
            "dry_run": False,
        }

    await audit_repo.insert_event(
        session,
        action="PARAMETER_IMPORT",
        user_id=user_id,
        entity_type=kind,
        details={
            "imported_count": applied,
            "replaced_count": replaced_count,
            "version": version,
            "dry_run": False,
            # 값의 **출처**를 함께 남긴다 (`#1515`) — 행 수·판본만으로는 「무엇을 근거로
            # 바뀌었나」에 답할 수 없다. 고유값을 정렬해 두어 같은 파일이면 같은 목록이다.
            "source_refs": sorted({str(item["source_ref"]) for _, item in parsed}),
        },
        ip_address=ip_address,
    )
    # 트랜잭션 경계는 서비스가 정한다(get_session은 commit하지 않는다). 감사 로그와
    # 파라미터 행이 **한 트랜잭션**이어야 「적재했는데 기록이 없다」가 생기지 않는다.
    await session.commit()
    return {
        "table": kind,
        "imported_count": applied,
        "replaced_count": replaced_count,
        "errors": [],
        "dry_run": False,
    }
