"""not under way 구간 CSV 가져오기 (``API_SPEC §8.2`` · `#765`).

## 왜 CSV인가

`PRD §21`의 「실제 선사 데이터 연동」은 셋 중 하나로 열 수 있다 — 수신용 REST API ·
스케줄 가져오기 · **CSV 확장**. 앞의 둘은 **상대가 정해지지 않으면 설계할 수 없다**
(중소선사의 시스템이 제각각이고 표준 스키마가 없다). CSV는 파서가 이미 있고, 실제로
막혀 있던 것(정박 구간을 대량으로 넣을 경로)을 바로 연다.

## 왜 정박 구간이 먼저인가

`API_SPEC §2.9` 각주가 *「CSV 가져오기(`§8.2`)는 항차만 다루므로 이 경로를 대신하지
않는다」*고 적어 두었다. 정박 연료는 **CII의 분자에 들어간다**(`MEPC.412(84) §4.2`
"both under way and not under way"). 한 건씩 넣는 화면뿐이면 한 해치를 넣는 데 수십 번을
눌러야 하고, 그래서 **안 넣게 된다** — 그 결과가 「정박해도 등급이 안 떨어지는」 상태다.

## 항차 CSV와 같은 규칙, 다른 규칙

| | 항차(`voyage_import`) | 정박 구간(이 모듈) |
|---|---|---|
| 파일 한계·인코딩·행 상한 | 같다 (그 모듈 것을 그대로 쓴다) | |
| 부분 실패 | **부분 성공** — 되는 행은 넣고 나머지는 사유를 돌려준다 | 같다 |
| 중복 | 항차 번호가 겹치면 **거부** | **시간대가 겹치는 구간은 거부** — 연료가 두 번 세어진다 |

중복을 **갱신이 아니라 거부**로 두는 이유는 같다 — 이미 확정된 실적을 파일 한 번으로
조용히 바꾸면, 무엇이 바뀌었는지 아무도 모른다. 고치려면 화면에서 그 행을 연다.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from cii_platform.api.schemas.bounds import NOT_UNDERWAY_FUEL
from cii_platform.db.models.not_underway_period import NotUnderwayPeriod
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.errors import AppError, ConflictError, ValidationError
from cii_platform.services.not_underway import (
    CONSUMER_TYPES,
    PERIOD_TYPES,
    create_period,
)
from cii_platform.services.voyage_import import (
    INSTANT_EXAMPLE,
    MAX_ROWS,
    RowError,
    _check_limits,
    _decode,
    _skipped_count,
    column_length,
    save_stage_row_error,
)

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from sqlalchemy.ext.asyncio import AsyncSession

#: 필수 컬럼. 구간을 만들려면 이 넷이 있어야 한다 — 나머지는 비워도 계산이 성립한다.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "period_type",
    "started_at",
    "distance_nm",
    "fuel_type",
    "fuel_ton",
)

#: 선택 컬럼. 비어 있으면 ``None``이다.
#:
#: - ``ended_at``: **진행 중인 구간**은 끝이 없다(지금 정박해 있는 배)
#: - ``consumer_type``: 비면 ``AUX_ENGINE`` — 정박 중 연료의 대부분이 보조기관이다
#: - ``port_name``·``lat``·``lon``: 위치는 계산에 쓰지 않고 표시용이다
OPTIONAL_COLUMNS: tuple[str, ...] = (
    "ended_at",
    "consumer_type",
    "port_name",
    "lat",
    "lon",
)

#: ``consumer_type``이 비었을 때의 값. `DB_SCHEMA §2.18`이 NOT NULL이라 무언가는 정해야 한다.
DEFAULT_CONSUMER_TYPE = "AUX_ENGINE"


def _text(row: dict[str, str], column: str) -> str:
    return (row.get(column) or "").strip()


#: 정박 연료·거리 컬럼 `NUMERIC(12,2)`의 저장 범위 (`schemas/bounds.py`와 같은 값 · #1086).
_FUEL_MIN = NOT_UNDERWAY_FUEL["ge"]
_NUMERIC_MAX = NOT_UNDERWAY_FUEL["le"]


def _decimal(row: dict[str, str], column: str, *, label: str, positive: bool = False) -> Decimal:
    """``NUMERIC(12,2)``에 담을 수 있는 값만 받는다 (#1086 ⑤ · `schemas/bounds.py`).

    ``positive``면 0도 거부한다 — ``fuel_ton``은 DB가 ``> 0``을 요구하고, 종전에는 ``< 0``만
    막아 ``0``이 **행 오류가 아니라 IntegrityError 500**이 됐다. 앞 행은 이미 커밋된 뒤라
    다시 올리면 「겹침」으로 막혔다. 거리는 0이 정상값이다(접안·묘박).
    """
    raw = _text(row, column)
    if not raw:
        raise RowError(column, f"{label}이(가) 비어 있습니다.")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise RowError(column, f"{label}은(는) 숫자여야 합니다: {raw}") from exc
    if not value.is_finite():
        raise RowError(column, f"{label}은(는) 숫자여야 합니다: {raw}")
    if positive and value < _FUEL_MIN:
        raise RowError(column, f"{label}은(는) {_FUEL_MIN} 이상이어야 합니다: {raw}")
    if not positive and value < 0:
        raise RowError(column, f"{label}은(는) 0 이상이어야 합니다: {raw}")
    if value > _NUMERIC_MAX:
        raise RowError(column, f"{label}이(가) 너무 큽니다(최대 {_NUMERIC_MAX}): {raw}")
    return value


def _instant(row: dict[str, str], column: str, *, label: str, required: bool) -> datetime | None:
    """시간대가 붙은 ISO 8601만 받는다 (`#906`과 같은 규칙).

    시간대 없는 값을 받아 서버 시간대로 읽으면 **9시간 어긋난 구간**이 들어가고, 그것이
    어느 규제연도에 속하는지까지 갈린다.
    """
    raw = _text(row, column)
    if not raw:
        if required:
            raise RowError(column, f"{label}이(가) 비어 있습니다.")
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RowError(column, f"{label} 형식이 올바르지 않습니다(예: {INSTANT_EXAMPLE}).") from exc
    if parsed.tzinfo is None:
        raise RowError(column, f"{label}에는 시간대가 필요합니다(예: {INSTANT_EXAMPLE}).")
    return parsed


def parse_row(row: dict[str, str], known_fuels: set[str]) -> dict[str, object]:
    """한 행을 구간 하나로 읽는다. 값이 안 되면 :class:`RowError`."""
    period_type = _text(row, "period_type").upper()
    if period_type not in PERIOD_TYPES:
        raise RowError(
            "period_type",
            f"구간 유형은 다음 중 하나여야 합니다: {', '.join(PERIOD_TYPES)}.",
        )

    consumer_type = (_text(row, "consumer_type") or DEFAULT_CONSUMER_TYPE).upper()
    if consumer_type not in CONSUMER_TYPES:
        raise RowError(
            "consumer_type",
            f"소비원은 다음 중 하나여야 합니다: {', '.join(CONSUMER_TYPES)}.",
        )

    fuel_type = _text(row, "fuel_type").upper()
    if fuel_type not in known_fuels:
        raise RowError("fuel_type", f"알 수 없는 연료 종류입니다: {fuel_type or '(빈 값)'}")

    started_at = _instant(row, "started_at", label="시작 시각", required=True)
    ended_at = _instant(row, "ended_at", label="종료 시각", required=False)
    if ended_at is not None and started_at is not None and ended_at <= started_at:
        raise RowError("ended_at", "종료 시각은 시작 시각보다 뒤여야 합니다.")

    return {
        "period_type": period_type,
        "started_at": started_at,
        "ended_at": ended_at,
        "port_name": _port_name(row),
        "lat": _optional_decimal(row, "lat", label="위도"),
        "lon": _optional_decimal(row, "lon", label="경도"),
        "distance_nm": _decimal(row, "distance_nm", label="이동 거리"),
        "fuel_type": fuel_type,
        "fuel_ton": _decimal(row, "fuel_ton", label="연료량", positive=True),
        "consumer_type": consumer_type,
    }


#: 좌표의 도메인 한도 — **수기 API와 같은 값**이다(``api/schemas/not_underway.py``의
#: ``Field(ge=-90, le=90)`` · ``Field(ge=-180, le=180)``). 종전에는 CSV 경로만 한도가
#: 없어 ``lat=1e9``가 파서를 통과하고 ``NUMERIC(9,6)``에서 죽었다 — `#1190`이 속력에서
#: 짚은 것과 **같은 종류**(경로마다 한도가 갈린다)라 함께 맞춘다.
_COORDINATE_BOUNDS: dict[str, tuple[Decimal, Decimal]] = {
    "lat": (Decimal(-90), Decimal(90)),
    "lon": (Decimal(-180), Decimal(180)),
}


def _optional_decimal(row: dict[str, str], column: str, *, label: str) -> Decimal | None:
    raw = _text(row, column)
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise RowError(column, f"{label}은(는) 숫자여야 합니다.") from exc
    if not value.is_finite():
        raise RowError(column, f"{label}은(는) 숫자여야 합니다: {raw}")
    low, high = _COORDINATE_BOUNDS[column]
    if not low <= value <= high:
        raise RowError(column, f"{label}은(는) {low} 이상 {high} 이하여야 합니다: {raw}")
    return value


def _port_name(row: dict[str, str]) -> str | None:
    """정박 항만명. 길이는 **모델에서** 온다 (#1190).

    ⚠️ `#1190` 본문이 이 컬럼을 ``300``자로 적었는데 실제는 ``String(200)``이다 —
    :func:`~cii_platform.services.voyage_import.column_length`가 모델을 읽으므로 본문의
    수치를 옮겨 적지 않는다. 200자를 넘는 값은 CUBRID가 잘라 넣지 않고 거부한다.
    """
    raw = _text(row, "port_name")
    if not raw:
        return None
    limit = column_length("port_name", model=NotUnderwayPeriod)
    if len(raw) > limit:
        raise RowError("port_name", f"{limit}자까지 입력할 수 있습니다(지금 {len(raw)}자).")
    return raw


def read_rows(content: bytes, *, content_type: str | None = None) -> tuple[list[dict], int]:
    """파일을 행 목록으로. 파일 단위 한계는 항차 CSV와 **같은 함수**를 쓴다."""
    _check_limits(content, content_type)
    reader = csv.DictReader(io.StringIO(_decode(content), newline=""))

    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
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


def _error_field(error: AppError) -> str | None:
    """저장 단계 오류가 **어느 칸**의 문제인지 고른다 (#1087).

    종전에는 종류와 무관하게 ``"started_at"`` 하나로 고정이었다. 화면은 이 값을 보고
    해당 입력 칸 아래에 메시지를 붙이므로(``API_SPEC §1.3.2``), 연료 문제를 시작
    시각 칸에 붙이면 **사용자가 엉뚱한 칸을 고치려 든다.**

    ``ValidationError``는 이미 ``details[].field``에 자기 칸을 싣고 있으니 그것을
    그대로 쓴다 — 여기서 종류별 표를 다시 만들면 원본과 갈린다. 겹침
    (``ConflictError``)만 표에 없는데, 그것은 구간의 **시간대** 문제이므로 시작
    시각을 가리킨다. 그 밖(선박 없음 등)은 **CSV에 대응하는 칸이 없으므로**
    ``None``이다 — 없는 칸을 지어내면 화면이 붙일 데가 없다.

    ⚠️ **``details`` 갈래는 지금 CSV 경로로 닿지 않는다.** :func:`parse_row`가
    ``period_type``·``consumer_type``·``fuel_type``을 ``create_period``와 **같은
    기준으로 먼저** 보기 때문에, 그 셋은 저장 단계에 도달하기 전에 걸린다. 그래도
    이 갈래를 첫자리에 두는 것은 **두 곳의 검사가 갈리는 날**이 규칙이 필요한 날이기
    때문이다 — 그때 ``started_at``으로 뭉뚱그리면 결함이 조용해진다. 닿지 않는 갈래를
    검사 없이 두지 않으려고 순수 함수 단위로 고정해 두었다
    (``test_not_underway_import_db.py::test_error_field_prefers_the_error_s_own_column``).
    """
    for detail in error.details or []:
        field = detail.get("field")
        if isinstance(field, str):
            return field
    if isinstance(error, ConflictError):
        return "started_at"
    return None


async def import_not_underway_periods(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    content: bytes,
    content_type: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """CSV를 읽어 정박 구간을 만든다 (``API_SPEC §8.2`` · `#765`).

    **부분 성공**이다 — 되는 행은 넣고, 안 되는 행은 사유와 행 번호를 돌려준다. 파일
    하나가 통째로 거부되는 것은 파일 단위 문제(크기·인코딩·필수 컬럼)뿐이다.

    **시간대가 겹치는 구간은 거부한다.** `create_period`가 이미 그 검사를 하고 있고,
    여기서는 그 실패를 **행 단위 오류**로 옮긴다 — 한 행 때문에 전체가 죽지 않는다.
    겹치는 구간을 받으면 같은 연료가 두 번 세어져 분자가 부풀고, 그 사실이 화면에
    드러나지 않는다.
    """
    rows, truncated = read_rows(content, content_type=content_type)
    known_fuels = {row.code for row in await param_repo.list_active_fuel_types(session)}

    errors: list[dict[str, object]] = []
    # **원본 행 번호를 함께 들고 간다** (#1087). 종전에는 파싱 성공분만 담아
    # ``enumerate(parsed)``로 번호를 다시 세었는데, 앞에서 한 행이라도 파싱에
    # 실패하면 그 뒤 저장 오류가 전부 **위쪽 행 번호**로 보고됐다.
    parsed: list[tuple[int, dict[str, object]]] = []

    if truncated:
        errors.append(
            {
                "row": MAX_ROWS + 2,
                "field": "file",
                "message": f"{MAX_ROWS}행 상한을 넘겨 {truncated}행을 처리하지 않았습니다.",
            }
        )

    for index, row in enumerate(rows):
        # 행 번호는 **파일에서 보이는 번호**다 — 헤더가 1행이므로 +2.
        row_number = index + 2
        try:
            parsed.append((row_number, parse_row(row, known_fuels)))
        except RowError as error:
            errors.append({"row": row_number, "field": error.field, "message": error.message})

    if dry_run:
        # **겹침은 여기서 보지 않는다.** 저장하지 않으므로 서로 겹치는 두 행이 파일 안에
        # 있어도 알 수 없고, 있는 척하면 거짓말이 된다. 그 사실을 응답 필드로 말한다.
        return {
            "imported_count": len(parsed),
            "skipped_count": _skipped_count(errors, truncated),
            "errors": errors,
            "overlap_checked": False,
            "dry_run": True,
        }

    imported = 0
    for row_number, item in parsed:
        try:
            await create_period(
                session,
                vessel_id,
                period_type=str(item["period_type"]),
                started_at=item["started_at"],  # type: ignore[arg-type]
                ended_at=item["ended_at"],  # type: ignore[arg-type]
                port_name=item["port_name"],  # type: ignore[arg-type]
                lat=item["lat"],  # type: ignore[arg-type]
                lon=item["lon"],  # type: ignore[arg-type]
                distance_nm=item["distance_nm"],  # type: ignore[arg-type]
                regulation_year=None,
                voyage_id=None,
                fuel_uses=[
                    {
                        "fuel_type": item["fuel_type"],
                        "fuel_ton": item["fuel_ton"],
                        "consumer_type": item["consumer_type"],
                    }
                ],
            )
        except (AppError, SQLAlchemyError) as error:
            # 겹침·제원 문제 등은 **그 행만** 떨어뜨린다. 행 번호는 ``parsed``의 위치가
            # 아니라 **원본 파일의 행 번호**다 (#1087).
            #
            # ``SQLAlchemyError``까지 받는 것은 `#1190`이다 — ``except AppError``는
            # ``ProgrammingError(-494)``를 **못 잡았다**. `db/cubrid_errors.py`가
            # ``IntegrityError``로 옮기는 것은 ``-517``·``-922``·``-924``·``-225``뿐이고
            # ``-494``는 성질이 달라(PostgreSQL에서도 ``DataError``였다) 그 목록에 넣지
            # 않는다. 대신 **여기서 행 오류로 받는다** — 항차 경로와 같은 함수다.
            field = _error_field(error) if isinstance(error, AppError) else None
            errors.append(await save_stage_row_error(session, row_number, error, field=field))
            continue
        imported += 1

    return {
        "imported_count": imported,
        "skipped_count": _skipped_count(errors, truncated),
        "errors": errors,
        "overlap_checked": True,
        "dry_run": False,
    }
