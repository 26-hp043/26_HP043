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

from cii_platform.db.repositories import parameters as param_repo
from cii_platform.errors import AppError, ValidationError
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


def _decimal(row: dict[str, str], column: str, *, label: str) -> Decimal:
    raw = _text(row, column)
    if not raw:
        raise RowError(column, f"{label}이(가) 비어 있습니다.")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise RowError(column, f"{label}은(는) 숫자여야 합니다: {raw}") from exc
    if value < 0:
        raise RowError(column, f"{label}은(는) 0 이상이어야 합니다: {raw}")
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
        "port_name": _text(row, "port_name") or None,
        "lat": _optional_decimal(row, "lat", label="위도"),
        "lon": _optional_decimal(row, "lon", label="경도"),
        "distance_nm": _decimal(row, "distance_nm", label="이동 거리"),
        "fuel_type": fuel_type,
        "fuel_ton": _decimal(row, "fuel_ton", label="연료량"),
        "consumer_type": consumer_type,
    }


def _optional_decimal(row: dict[str, str], column: str, *, label: str) -> Decimal | None:
    if not _text(row, column):
        return None
    try:
        return Decimal(_text(row, column))
    except (InvalidOperation, ValueError) as exc:
        raise RowError(column, f"{label}은(는) 숫자여야 합니다.") from exc


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
    parsed: list[dict[str, object]] = []

    if truncated:
        errors.append(
            {
                "row": MAX_ROWS + 2,
                "field": "file",
                "message": f"{MAX_ROWS}행 상한을 넘겨 {truncated}행을 처리하지 않았습니다.",
            }
        )

    for index, row in enumerate(rows):
        try:
            parsed.append(parse_row(row, known_fuels))
        except RowError as error:
            errors.append({"row": index + 2, "field": error.field, "message": error.message})

    if dry_run:
        # **겹침은 여기서 보지 않는다.** 저장하지 않으므로 서로 겹치는 두 행이 파일 안에
        # 있어도 알 수 없고, 있는 척하면 거짓말이 된다. 그 사실을 응답 필드로 말한다.
        return {
            "imported_count": len(parsed),
            "skipped_count": len(errors),
            "errors": errors,
            "overlap_checked": False,
            "dry_run": True,
        }

    imported = 0
    for index, item in enumerate(parsed):
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
        except AppError as error:
            # 겹침·제원 문제 등은 **그 행만** 떨어뜨린다. 행 번호는 파일에서 보이는 번호다.
            errors.append({"row": index + 2, "field": "started_at", "message": str(error)})
            continue
        imported += 1

    return {
        "imported_count": imported,
        "skipped_count": len(errors),
        "errors": errors,
        "overlap_checked": True,
        "dry_run": False,
    }
