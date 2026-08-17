"""항차 CSV 가져오기 (API_SPEC §8.2, #60).

**데이터를 넣을 경로 하나를 연다.** 지금 서비스는 시드로 들어간 항차로만 도는데,
`PRD §6.2 SCR-007`이 대량 입력을 CSV 경로로 설계해 두고 그 CSV가 없었다.

## 부분 성공을 허용한다

``API_SPEC §8.2`` 응답이 ``imported_count`` · ``skipped_count`` · ``errors[]`` 셋이므로,
**틀린 행 하나 때문에 파일 전체를 되돌리지 않는다.** 1,000행 파일에서 3행이 틀렸을 때
전부 거부하면 사용자는 어느 3행인지 알아내려고 같은 업로드를 반복하게 된다. 대신
**어느 행의 어느 칸이 왜 틀렸는지**를 그대로 돌려준다.

(파라미터 import(``§7.5``)의 「실패 시 롤백」(``TEST_PLAN §3.5``)은 이쪽과 다른 계약이다 —
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
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from cii_platform.db.repositories import parameters as param_repo
from cii_platform.errors import ValidationError
from cii_platform.reports.csv_export import sanitize
from cii_platform.services.voyage import create_voyage

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

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


class RowError(Exception):
    """행 하나의 실패. 응답 ``errors[]`` 한 건이 된다."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


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


def _numeric(row: dict[str, str], column: str) -> Decimal:
    """숫자 열을 ``Decimal``로. **수식 문자열은 여기서 걸린다.**

    ``float``이 아니라 ``Decimal``인 이유는 저장 컬럼이 ``NUMERIC``이기 때문이다 —
    ``float``으로 한 번 거치면 ``0.1``이 ``0.1000000000000000055``가 되어 들어간다.
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
    # VAL-002 — 거리·연료는 0보다 커야 한다 (`PRD §9.1`).
    if value <= 0:
        raise RowError(column, "0보다 커야 합니다.")
    return value


def _text(row: dict[str, str], column: str) -> str:
    """문자 열을 escape해서 돌려준다. 빈 값은 행 오류다."""
    raw = (row.get(column) or "").strip()
    if raw == "":
        raise RowError(column, "값을 입력해 주세요.")
    return sanitize(raw)


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

    speed = _numeric(row, "planned_speed_kn")
    # VAL-009 — 속도는 1.0kn 이상 (`PRD §9.1`). 0 초과 검사만으로는 부족하다.
    if speed < Decimal("1.0"):
        raise RowError("planned_speed_kn", "속도는 1.0노트 이상이어야 합니다.")

    return {
        "voyage_no": _text(row, "voyage_no"),
        "departure_port_name": _text(row, "departure_port_name"),
        "arrival_port_name": _text(row, "arrival_port_name"),
        "planned_distance_nm": _numeric(row, "planned_distance_nm"),
        "planned_speed_kn": speed,
        "fuel_type": fuel_type,
        "planned_fuel_ton": _numeric(row, "planned_fuel_ton"),
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

    반환값은 §8.2 그대로 ``imported_count`` · ``skipped_count`` · ``errors[]``이며,
    ``dry_run``일 때 ``imported_count``는 **들어갈 수 있는 행 수**다.
    """
    rows, truncated = read_rows(content, content_type=content_type)
    known_fuels = {row.code for row in await param_repo.list_active_fuel_types(session)}

    errors: list[dict[str, object]] = []
    parsed: list[dict[str, object]] = []

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
        try:
            parsed.append(parse_row(row, known_fuels))
        except RowError as error:
            # 행 번호는 **파일에서 보이는 번호**다 — 헤더가 1행이므로 +2.
            errors.append({"row": index + 2, "field": error.field, "message": error.message})

    if dry_run:
        return {
            "imported_count": len(parsed),
            "skipped_count": len(errors),
            "errors": errors,
            "dry_run": True,
        }

    imported = 0
    for item in parsed:
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
            planned_speed_kn=item["planned_speed_kn"],
            planned_departure_at=None,
            planned_arrival_at=None,
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
        imported += 1

    return {
        "imported_count": imported,
        "skipped_count": len(errors),
        "errors": errors,
        "dry_run": False,
    }
