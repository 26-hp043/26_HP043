"""항차 CSV 가져오기 (API_SPEC §8.2, #60).

**데이터를 넣을 경로 하나를 연다.** 지금 서비스는 시드로 들어간 항차로만 도는데,
`PRD §6.2 SCR-007`이 대량 입력을 CSV 경로로 설계해 두고 그 CSV가 없었다.

## 부분 성공을 허용한다

``API_SPEC §8.2`` 응답이 ``imported_count`` · ``skipped_count`` · ``errors[]`` 셋이므로,
**틀린 행 하나 때문에 파일 전체를 되돌리지 않는다.** 1,000행 파일에서 3행이 틀렸을 때
전부 거부하면 사용자는 어느 3행인지 알아내려고 같은 업로드를 반복하게 된다. 대신
**어느 행의 어느 칸이 왜 틀렸는지**를 그대로 돌려준다.

(파라미터 import(``§7.5``)의 「실패 시 롤백」(``TEST_PLAN §3.5`` · ``IT-IMPORT-005``)은
이쪽과 다른 계약이다 —
규정 파라미터는 일부만 들어가면 계산 근거가 반쪽이 되므로 전부 아니면 전무여야 한다.)

## 수식 주입을 두 방향으로 막는다

``API_SPEC §8.2`` 보안 표가 규정한 그대로다.

=================  =========================================================
 문자 열            ``=``·``+``·``-``·``@``로 시작하면 ``'``를 앞에 붙인다
 숫자 열            numeric parser로 검증한다 — ``=1+1``은 **값이 아니라 오류**다
=================  =========================================================

문자 열에서 「수식인지」를 판정하지 않고 **시작 문자만** 보는 이유는
:func:`~cii_platform.reports.csv_export.sanitize`의 docstring에 있다 — 판정기를 두면
판정기 자체가 취약점이 된다. 내보내기와 **같은 함수**를 쓴다: 규칙이 두 곳에 생기면
한쪽만 고쳐지는 날이 온다.

## 들어온 항차의 상태

``status=DRAFT`` · ``annual_inclusion_policy=EXCLUDE`` · ``created_from=IMPORT``.
앞의 둘은 수기 생성(``API_SPEC §3.3``)과 같다 — **CSV로 들어왔다는 이유로 연간 집계에
바로 들어가면 안 된다.** 집계 편입은 상태 전환(``§3.5``)이 결정한다.

``created_from``만 다르다(``DB_SCHEMA §2.2``의 5값 중 ``IMPORT``). 나중에 「이 항차는
어디서 왔나」를 물을 수 있어야 한다.

## 출항·도착 예정 시각 — 선택 컬럼 (#906)

종전에는 두 시각을 받는 컬럼이 없어 **가져온 항차는 늘 시각이 비었다.** 시각이 없는
항차는 진행 중으로 옮겨도 시뮬레이션 시계가 누적을 **0으로** 만든다(``#873`` ·
``services/simulation_clock.py``). 화면 경로는 ``#873``이 메웠고, 여기서 CSV 경로를 맞춘다.

- **선택 컬럼이다** — API(``§3.3``)에서도 선택이고 화면도 필수로 두지 않았다. 필수로 두면
  기존 파일이 전부 거부되고, 경로마다 규칙이 갈린다
- **시간대를 요구한다** — ``2026-09-12T09:00:00+09:00`` 또는 ``…Z``. 시간대 없는 값을 UTC로
  읽으면 한국 시각으로 적은 사람의 항차가 **9시간 어긋난다.** 추측하지 않고 행 오류로 낸다
- 저장은 UTC다(``DB_SCHEMA §0.1`` [X-6])
- 출항 예정 시각이 빈 채 들어간 행 수를 응답에 싣는다(``missing_departure_count``) — 들어간
  것은 맞지만 진행 중 누적에 기여하지 않는다는 사실을 화면이 알린다
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from cii_platform.api.schemas.bounds import DISTANCE, SPEED, VOYAGE_FUEL
from cii_platform.db.models.voyage import Voyage
from cii_platform.db.repositories import parameters as param_repo
from cii_platform.errors import AppError, ValidationError
from cii_platform.reports.csv_export import sanitize
from cii_platform.services.voyage import create_voyage

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

#: ``API_SPEC §8.2`` 보안 제한 — 최대 파일 크기.
MAX_FILE_BYTES = 5 * 1024 * 1024

#: ``API_SPEC §8.2`` 보안 제한 — 최대 행 수(헤더 제외).
MAX_ROWS = 1_000

#: ``API_SPEC §8.2`` 보안 제한 — 허용 Content-Type.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"text/csv", "application/vnd.ms-excel"})

#: ``API_SPEC §8.2`` 필수 컬럼 7종.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "voyage_no",
    "departure_port_name",
    "arrival_port_name",
    "planned_distance_nm",
    "planned_speed_kn",
    "fuel_type",
    "planned_fuel_ton",
)


#: ``API_SPEC §8.2`` 선택 컬럼 — 비어 있으면 ``None``(#906).
OPTIONAL_COLUMNS: tuple[str, ...] = ("planned_departure_at", "planned_arrival_at")

#: 시각 칸의 예. 오류 문구와 화면 안내가 같은 예를 쓴다.
INSTANT_EXAMPLE = "2026-09-12T09:00:00+09:00"


class RowError(Exception):
    """행 하나의 실패. 응답 ``errors[]`` 한 건이 된다."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


#: 저장 단계가 행을 거부했을 때 사용자에게 보일 문구. **드라이버 메시지를 그대로
#: 내보내지 않는다** — ``Cannot coerce '10000' to type numeric. (errno=-494)``는
#: 사용자가 고칠 칸을 알려 주지 않고 내부 구조를 드러낸다.
SAVE_STAGE_MESSAGE = "저장 단계에서 거부됐습니다. 값을 확인해 주세요."


async def save_stage_row_error(
    session: AsyncSession,
    row_number: int,
    error: BaseException,
    *,
    field: str | None,
) -> dict[str, object]:
    """저장 단계 실패를 ``errors[]`` 한 건으로 바꾼다 (``API_SPEC §8.2`` · #1190).

    **항차·정박 두 종류가 이 함수를 함께 쓴다.** 규약이 두 곳에 생기면 한쪽만 고쳐지는
    날이 온다 — 실제로 그렇게 갈려 있었다(정박은 부분 성공, 항차는 500).

    :class:`~cii_platform.errors.AppError`는 사용자에게 보일 문구를 스스로 들고 있으므로
    그대로 쓰고, 그 밖(드라이버·ORM)은 :data:`SAVE_STAGE_MESSAGE`로 덮고 **원문은 로그로**
    남긴다. 파서가 컬럼 한도를 모두 보므로 값 때문에 여기 오는 행은 없어야 한다 — 오면
    파서에 구멍이 있다는 뜻이라 로그가 필요하다.

    ``rollback``은 **DB 단계 실패에만** 한다. 드라이버가 거부한 행은 트랜잭션을 못 쓰는
    상태로 남기므로 되돌리지 않으면 **그 뒤 행이 전부 같은 이유로 죽는다** — 한 행의
    실패가 파일의 실패가 되어 부분 성공이 다시 무너진다. 호출부에 맡기면 잊을 수 있는
    자리라 여기서 한다.

    ``AppError``에는 하지 않는다. 겹침·제원 같은 검증은 :func:`create_voyage` ·
    ``create_period``가 **쓰기 전에** 보므로 트랜잭션이 깨끗하고, 여기서 한 번 더
    되돌리면 아직 커밋되지 않은 **정상 상태까지** 지운다. 정박 경로가 이 규약 없이도
    부분 성공을 해 오던 자리이므로 그 동작을 바꾸지 않는다.
    """
    if isinstance(error, AppError):
        return {"row": row_number, "field": field, "message": str(error)}
    await session.rollback()
    _log.warning(
        "CSV 저장 단계가 %d행을 거부했다 — 파서가 먼저 막지 못한 값이다: %s",
        row_number,
        error,
    )
    return {"row": row_number, "field": field, "message": SAVE_STAGE_MESSAGE}


def _decode(content: bytes) -> str:
    """UTF-8로 읽는다. BOM은 있어도 없어도 된다 (``API_SPEC §8.2``).

    ``utf-8-sig``는 BOM이 있으면 벗기고 없으면 그냥 UTF-8로 읽는다. Excel이 저장한
    CSV는 BOM을 붙이는 경우가 많고, 벗기지 않으면 **첫 컬럼명이 ``\\ufeffvoyage_no``가
    되어 「필수 컬럼 없음」으로 거부된다.**
    """
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "UTF-8로 저장된 CSV만 가져올 수 있습니다. 파일 인코딩을 확인해 주세요.",
            field="file",
            field_label="파일",
        ) from exc


def _check_limits(content: bytes, content_type: str | None) -> None:
    """파일 단위 거부 — 여기서 걸리면 **한 행도 읽지 않는다.**"""
    if len(content) > MAX_FILE_BYTES:
        raise ValidationError(
            f"파일이 너무 큽니다. 최대 {MAX_FILE_BYTES // (1024 * 1024)}MB까지 가져올 수 있습니다.",
            field="file",
            field_label="파일",
        )
    # Content-Type은 `text/csv; charset=utf-8`처럼 파라미터가 붙어 온다.
    if content_type is not None:
        base = content_type.split(";")[0].strip().lower()
        if base and base not in ALLOWED_CONTENT_TYPES:
            raise ValidationError(
                f"CSV 파일만 가져올 수 있습니다 (받은 형식: {base}).",
                field="file",
                field_label="파일",
            )


#: 숫자 열마다 **그 열이 들어가는 컬럼의** 저장 범위를 쓴다 (`schemas/bounds.py` · #1190 ⑴).
#:
#: 종전에는 세 열 모두 :data:`~cii_platform.api.schemas.bounds.DISTANCE` 하나를 썼다
#: (#1086 ⑥). 거리·연료는 그 안에 들지만 **속력은 아니다** — ``planned_speed_kn``은
#: ``NUMERIC(6,2)``라 최대 ``9999.99``인데 거리 한도는 ``9999999999.99``다. 그래서
#: ``10000``이 파서를 통과해 저장 단계에서 ``ProgrammingError(-494)``가 됐고, 행 단위
#: 처리가 없어 **500 + 앞 행 잔존**이 됐다. 수기 API는 같은 값을 ``Field(**SPEED)``로
#: 막는다 — **경로마다 한도가 갈려 있었다.**
_NUMERIC_BOUNDS: dict[str, dict[str, Decimal]] = {
    "planned_distance_nm": DISTANCE,
    "planned_speed_kn": SPEED,
    "planned_fuel_ton": VOYAGE_FUEL,
}

#: 하한이 **저장 형식이 아니라 도메인**에서 오는 열의 문구. 값 자체는 위 표가 들고 있고
#: (``SPEED["ge"] == 1.0``), 여기서는 사용자에게 보일 말만 바꾼다 — 「1.0 이상이어야
#: 합니다」로는 무엇의 1.0인지 알 수 없다. VAL-009 (`PRD §9.1`).
_MIN_MESSAGES: dict[str, str] = {
    "planned_speed_kn": "속도는 1.0노트 이상이어야 합니다.",
}


def _numeric(row: dict[str, str], column: str) -> Decimal:
    """숫자 열을 ``Decimal``로. **수식 문자열은 여기서 걸린다.**

    ``float``이 아니라 ``Decimal``인 이유는 저장 컬럼이 ``NUMERIC``이기 때문이다 —
    ``float``으로 한 번 거치면 ``0.1``이 ``0.1000000000000000055``가 되어 들어간다.

    한도는 :data:`_NUMERIC_BOUNDS`가 **열마다** 준다. 저장 단계에 값 때문에 죽는 행이
    도달하지 않는 것이 이 함수의 계약이다 — 그 계약이 있어야 ``dry_run``이 실제
    가져오기와 같은 답을 낼 수 있다 (#1190).
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
    bounds = _NUMERIC_BOUNDS[column]
    # VAL-002 — 거리·연료·속력은 0보다 커야 한다 (`PRD §9.1`). 그리고 **DB가 담을 수
    # 있어야** 한다 (#1086 ⑥) — `0.001`은 `NUMERIC(12,2)`에서 0.00으로 반올림돼 500이었다.
    if value <= 0:
        raise RowError(column, "0보다 커야 합니다.")
    if value < bounds["ge"]:
        raise RowError(column, _MIN_MESSAGES.get(column, f"{bounds['ge']} 이상이어야 합니다."))
    if value > bounds["le"]:
        raise RowError(column, f"너무 큽니다(최대 {bounds['le']}).")
    return value


def column_length(column: str, *, model: type = Voyage) -> int:
    """``String`` 컬럼의 길이를 **모델에서** 끌어낸다 (#1190).

    손으로 적으면 스키마가 바뀐 날 갈린다 — 실제로 `#1190` 본문이 정박 ``port_name``을
    300자로 적었는데 모델은 ``String(200)``이다. 정본과 코드 중 **코드가 컬럼을 안다.**
    """
    type_ = model.__table__.columns[column].type
    length = getattr(type_, "length", None)
    if not isinstance(length, int):  # pragma: no cover - 문자 컬럼에만 쓴다
        msg = f"{model.__name__}.{column}은 길이가 있는 문자 컬럼이 아니다: {type_!r}"
        raise TypeError(msg)
    return length


def _text(row: dict[str, str], column: str) -> str:
    """문자 열을 escape해서 돌려준다. 빈 값은 행 오류다.

    **길이는 escape한 뒤에 본다** (#1190). :func:`sanitize`가 수식 문자로 시작하는 값
    앞에 ``'``를 붙이므로, 컬럼 길이에 딱 맞는 값이 escape 한 글자 때문에 넘칠 수 있다 —
    실제로 저장되는 문자열을 재야 한다. CUBRID는 넘는 값을 잘라 넣지 않고 거부한다.
    """
    raw = (row.get(column) or "").strip()
    if raw == "":
        raise RowError(column, "값을 입력해 주세요.")
    value = sanitize(raw)
    limit = column_length(column)
    if len(value) > limit:
        raise RowError(column, f"{limit}자까지 입력할 수 있습니다(지금 {len(value)}자).")
    return value


def _instant(row: dict[str, str], column: str) -> datetime | None:
    """선택 시각 칸을 UTC ``datetime``으로. 비었으면 ``None``.

    **시간대가 없으면 행 오류다** — 모듈 설명 참조. 수식 문자열(``=NOW()``)은 시각으로
    읽히지 않아 여기서 걸린다 — 숫자 열과 같은 방향(값이 아니라 오류)이다.
    """
    raw = (row.get(column) or "").strip()
    if raw == "":
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RowError(column, f"시각으로 읽을 수 없습니다(예: {INSTANT_EXAMPLE}).") from exc
    if value.tzinfo is None:
        raise RowError(column, f"시간대가 필요합니다(예: {INSTANT_EXAMPLE}).")
    return value.astimezone(UTC)


def parse_row(row: dict[str, str], known_fuels: set[str]) -> dict[str, object]:
    """행 하나를 ``create_voyage`` 인자로 옮긴다. 실패는 :class:`RowError`.

    **연료 코드는 마스터와 대조한다.** ``create_voyage``도 같은 검사를 하지만, 거기서
    걸리면 ``ValidationError``가 되어 **어느 행인지**가 사라진다. 행 번호를 붙일 수 있는
    자리에서 먼저 본다.
    """
    fuel_type = (row.get("fuel_type") or "").strip()
    if fuel_type == "":
        raise RowError("fuel_type", "값을 입력해 주세요.")
    if fuel_type not in known_fuels:
        # VAL-006 — active fuel_type이어야 한다.
        raise RowError("fuel_type", f"지원하지 않는 연료입니다: {fuel_type}")

    # VAL-009(속도 ≥ 1.0kn · `PRD §9.1`)는 `_numeric`이 본다 — `SPEED["ge"]`가 그 값이고
    # 문구는 `_MIN_MESSAGES`에 있다. 여기서 한 번 더 보면 한도가 두 곳에 생긴다 (#1190).
    speed = _numeric(row, "planned_speed_kn")

    return {
        "voyage_no": _text(row, "voyage_no"),
        "departure_port_name": _text(row, "departure_port_name"),
        "arrival_port_name": _text(row, "arrival_port_name"),
        "planned_distance_nm": _numeric(row, "planned_distance_nm"),
        "planned_speed_kn": speed,
        "fuel_type": fuel_type,
        "planned_fuel_ton": _numeric(row, "planned_fuel_ton"),
        "planned_departure_at": _instant(row, "planned_departure_at"),
        "planned_arrival_at": _instant(row, "planned_arrival_at"),
    }


def read_rows(
    content: bytes, *, content_type: str | None = None
) -> tuple[list[dict[str, str]], int]:
    """파일을 행 목록으로 읽는다. 돌려주는 둘째 값은 **상한을 넘겨 잘라 낸 행 수**다.

    파일 단위 문제(크기·형식·인코딩·필수 컬럼)는 여기서 ``ValidationError``다 —
    그 경우 **한 행도 읽지 않는다.**

    행 수 상한은 파일을 거부하지 않고 **자른다**(``TEST_PLAN`` IT-CSV-003
    「1000행까지만 처리, 초과분 skip」). 다만 **잘랐다는 사실을 값으로 돌려준다** —
    조용히 자르면 1,001행을 올린 사용자는 마지막 한 행이 없어진 것을 모른다.

    상한을 **읽은 뒤가 아니라 읽는 중에** 본다. 다 읽고 나서 세면 상한의 목적(자원
    보호)이 사라진다.
    """
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


async def import_voyages(
    session: AsyncSession,
    vessel_id: UUID,
    *,
    content: bytes,
    content_type: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """CSV를 읽어 항차를 만든다 (``API_SPEC §8.2``).

    ``dry_run``이면 **검증만 하고 아무것도 만들지 않는다.** 1,000행짜리 파일을 올리기
    전에 「몇 행이 걸리는지」를 먼저 볼 수 있어야 한다 — 그 확인 없이 올리면 부분 성공
    상태에서 무엇을 고쳐 다시 올려야 하는지 사용자가 계산해야 한다.

    반환값은 §8.2 그대로 ``imported_count`` · ``skipped_count`` · ``errors[]`` ·
    ``missing_departure_count``이며, ``dry_run``일 때 ``imported_count``는 **들어갈 수 있는
    행 수**다(``missing_departure_count``도 들어갈 행 가운데의 수다).
    """
    rows, truncated = read_rows(content, content_type=content_type)
    known_fuels = {row.code for row in await param_repo.list_active_fuel_types(session)}

    errors: list[dict[str, object]] = []
    # **원본 행 번호를 함께 들고 간다** (#1087과 같은 이유). 파싱 성공분만 담아
    # ``enumerate(parsed)``로 번호를 다시 세면, 앞에서 한 행이라도 파싱에 실패했을 때
    # 그 뒤 저장 오류가 전부 **위쪽 행 번호**로 보고된다.
    parsed: list[tuple[int, dict[str, object]]] = []

    if truncated:
        # 잘라 낸 사실을 오류 목록에 남긴다. 개수만 맞추고 말하지 않으면 **사용자는
        # 마지막 행들이 없어진 것을 모른 채 「전부 들어갔다」로 읽는다.**
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

    # 들어가는 행 가운데 출항 예정 시각이 빈 수 — 진행 중 누적에 0으로 기여한다 (#906).
    missing_departure = sum(1 for _, item in parsed if item["planned_departure_at"] is None)

    if dry_run:
        return {
            "imported_count": len(parsed),
            "skipped_count": len(errors),
            "errors": errors,
            "missing_departure_count": missing_departure,
            "dry_run": True,
        }

    imported = 0
    stored_missing_departure = 0
    for row_number, item in parsed:
        try:
            await create_voyage(
                session,
                vessel_id,
                voyage_no=item["voyage_no"],
                departure_port_name=item["departure_port_name"],
                departure_lat=None,
                departure_lon=None,
                arrival_port_name=item["arrival_port_name"],
                arrival_lat=None,
                arrival_lon=None,
                planned_distance_nm=item["planned_distance_nm"],
                # CSV의 거리는 사람이 적은 숫자다 (#1256). 좌표 열이 없으니 추정일 수 없고,
                # 「어느 경로로 들어왔나」는 `created_from="IMPORT"`가 이미 답한다.
                planned_distance_source="USER_INPUT",
                planned_speed_kn=item["planned_speed_kn"],
                planned_departure_at=item["planned_departure_at"],
                planned_arrival_at=item["planned_arrival_at"],
                regulation_year=None,
                fuel_uses=[
                    {
                        "fuel_type": item["fuel_type"],
                        "planned_fuel_ton": item["planned_fuel_ton"],
                        "source": "IMPORT",
                    }
                ],
                notes=None,
                created_from="IMPORT",
            )
        except (AppError, SQLAlchemyError) as error:
            # **그 행만** 떨어뜨린다 (#1190). 정박 구간 경로와 같은 함수·같은 규약이다.
            # ``SQLAlchemyError``까지 받는 것은 ``AppError``만으로는 부족해서다 —
            # ``ProgrammingError(-494)``는 ``AppError``가 아니라 그대로 올라가 500이 됐고,
            # `create_voyage`가 행마다 커밋하므로 **앞 행은 저장된 채 남았다.**
            errors.append(await save_stage_row_error(session, row_number, error, field=None))
            continue
        imported += 1
        if item["planned_departure_at"] is None:
            stored_missing_departure += 1

    return {
        "imported_count": imported,
        # **실제로 들어간 행 가운데의 수**다. 저장 단계에서 떨어진 행을 여기 세면
        # 「들어갔지만 시각이 없다」는 뜻이 무너진다 (#906 · #1090과 같은 종류).
        "missing_departure_count": stored_missing_departure,
        "skipped_count": len(errors),
        "errors": errors,
        "dry_run": False,
    }
