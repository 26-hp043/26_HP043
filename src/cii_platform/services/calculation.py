"""계산 이력 조회 서비스 (API_SPEC §1.9, #56).

**조율만 담당한다** (TECH_SPEC §16) — 쿼리는 ``db/repositories/calculation_run``이,
HTTP 처리는 라우트가 한다. 이 모듈은 저장소가 준 ``CalculationRun`` 행을 API 응답
형태로 바꾸고 페이지네이션 메타를 만든다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cii_platform.db.repositories import calculation_run as calc_run_repo
from cii_platform.errors import ValidationError

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from cii_platform.db.models.calculation_run import CalculationRun

#: API_SPEC §1.9 응답의 ``result_summary`` — result_json에서 뽑는 키.
#: 기능① 응답의 ``data`` 블록(§4.1)과 같다. 키가 없으면 값 자체를 생략한다
#: (SCENARIO 등 다른 타입은 아직 쓰지 않으므로, 도입 시 여기를 확장한다).
_SUMMARY_KEYS = ("attained_cii", "estimated_rating")


def _iso(value) -> str | None:
    """``created_at``을 ISO8601 문자열로 만든다 (vessel · voyage와 같은 포맷)."""
    return None if value is None else value.isoformat()


def normalize_limit(limit: int | None) -> int:
    """``limit`` 쿼리 파라미터를 정규화한다 (API_SPEC §1.9 「기본 20, 최대 100」).

    **초과값을 오류로 만들지 않고 잘라 낸다** — 목록 조회에서 큰 ``limit``은 공격이
    아니라 오해인 경우가 대부분이다(vessel §2.1과 같은 정책). 반면 1 미만(0, 음수)은
    ``ValidationError`` — 0건 페이지가 의미가 없어 오타로 보기 때문이다.
    """
    if limit is None:
        return calc_run_repo.DEFAULT_LIMIT
    if limit < 1:
        raise ValidationError(
            "limit은 1 이상이어야 합니다.", field="limit", field_label="페이지 크기"
        )
    return min(limit, calc_run_repo.MAX_LIMIT)


def _to_dict(run: CalculationRun) -> dict[str, object]:
    """``CalculationRun`` 행을 API_SPEC §1.9 ``data[]`` 항목으로 바꾼다."""
    result_json = run.result_json or {}
    result_summary = {key: result_json[key] for key in _SUMMARY_KEYS if key in result_json}
    return {
        "calculation_run_id": str(run.id),
        "calculation_type": run.calculation_type,
        "vessel_id": str(run.vessel_id),
        "voyage_id": str(run.voyage_id) if run.voyage_id else None,
        "input_hash": run.input_hash,
        "parameter_hash": run.parameter_hash,
        "model_version": run.model_version,
        "result_summary": result_summary,
        "created_at": _iso(run.created_at),
    }


async def list_calculation_runs(
    session: AsyncSession,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    input_hash: str | None = None,
    parameter_hash: str | None = None,
    calculation_type: str | None = None,
    vessel_id: UUID | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """계산 이력 목록과 페이지네이션 메타를 반환한다 (API_SPEC §1.9).

    저장소가 ``limit + 1``건을 주므로 초과분의 존재 여부가 곧 ``has_more``다.
    ``next_cursor``는 다음 페이지가 있을 때만 채운다 — 커서를 반복해서 쓰면
    클라이언트가 무한 루프에 빠질 수 있다(§1.9).
    """
    page_size = normalize_limit(limit)

    parsed_cursor = None
    if cursor is not None:
        parsed_cursor = calc_run_repo.decode_cursor(cursor)
        if parsed_cursor is None:
            raise ValidationError(
                "cursor 형식이 올바르지 않습니다.",
                field="cursor",
                field_label="커서",
            )

    rows = await calc_run_repo.list_runs(
        session,
        limit=page_size,
        cursor=parsed_cursor,
        input_hash=input_hash,
        parameter_hash=parameter_hash,
        calculation_type=calculation_type,
        vessel_id=vessel_id,
    )

    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = (
        calc_run_repo.encode_cursor(
            calc_run_repo.CalcRunCursor(
                created_at=page[-1].created_at.isoformat(),
                calculation_run_id=str(page[-1].id),
            )
        )
        if has_more and page
        else None
    )

    return [_to_dict(row) for row in page], {
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
