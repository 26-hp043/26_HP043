"""계산 이력 조회 서비스 (API_SPEC §1.9, #56).

**조율만 담당한다** (TECH_SPEC §16) — 쿼리는 ``db/repositories/calculation_run``이,
HTTP 처리는 라우트가 한다. 이 모듈은 저장소가 준 ``CalculationRun`` 행을 API 응답
형태로 바꾸고 페이지네이션 메타를 만든다.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cii_platform.db.repositories import calculation_run as calc_run_repo
from cii_platform.errors import ValidationError
from cii_platform.services.pagination import normalize_limit as _normalize_limit

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

    정책은 :mod:`cii_platform.services.pagination`이 소유한다 (`#818` ⑵).
    """
    return _normalize_limit(
        limit, default=calc_run_repo.DEFAULT_LIMIT, maximum=calc_run_repo.MAX_LIMIT
    )


#: 기상 보정을 **실제로 적용하는** 계산 종류 (`#2012`).
#:
#: 항차 계산(`VOYAGE_ESTIMATE`)은 ``weather_model``을 해시 재료로 싣지만 ``weather_factor``를
#: ``None``으로 고정한다 — 보정이 없다. 그 종류에 블록을 내면 「모델을 골랐는데 쓰지 않았다」로
#: 읽히므로 ``null``로 둔다. 기상을 적용하는 종류가 늘면 여기에 더한다.
_WEATHER_TYPES = frozenset({"SCENARIO"})

#: 기상 경고 코드의 머리 (``API_SPEC §1.6`` ``WEATHER_STALE`` · ``WEATHER_NONE_FALLBACK``).
_WEATHER_WARNING_PREFIX = "WEATHER_"


def _weather(run: CalculationRun) -> dict[str, object] | None:
    """이 계산이 **요청한** 기상 모델과 **실제로 쓴** 모델 · 스냅샷 · 기상 경고 (`#2012`).

    둘을 나눠 싣는 이유는 fallback이다(``PRD §11.6`` · `#62`) — 조회가 실패하면 요청은
    ``SIMPLE_RULE``인데 계산은 ``NONE``으로 돈다. 요청만 보이면 보정된 값으로 읽힌다.

    **저장된 값을 옮기기만 한다.** 요청은 ``result_json.weather_model_requested``, 실제 모델은
    ``result_json.scenarios[].weather_model_used``(한 요청은 한 번 조회한 기상으로 세 시나리오를
    모두 보정하므로 같은 값이다), 스냅샷은 ``weather_snapshot_id`` 컬럼이다.

    ⚠️ **요청 모델은 `#2012` 이후 계산에만 있다.** 그 전에는 입력 해시 재료로만 쓰이고
    저장되지 않았다 — 과거 행은 ``model_requested``가 ``null``(기록 없음)이다. 계산 결과는
    불변이라 되살리지 않는다. fallback 여부는 그때도 ``warnings``의
    ``WEATHER_NONE_FALLBACK``이 말한다.
    """
    if run.calculation_type not in _WEATHER_TYPES:
        return None
    result_json = run.result_json or {}
    scenarios = result_json.get("scenarios") or []
    used = next(
        (
            item["weather_model_used"]
            for item in scenarios
            if isinstance(item, dict) and item.get("weather_model_used")
        ),
        None,
    )
    warnings = [
        code
        for code in (run.warnings_json or [])
        if isinstance(code, str) and code.startswith(_WEATHER_WARNING_PREFIX)
    ]
    return {
        "model_requested": result_json.get("weather_model_requested"),
        "model_used": used,
        "snapshot_id": str(run.weather_snapshot_id) if run.weather_snapshot_id else None,
        "warnings": warnings,
    }


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
        "weather": _weather(run),
        "needs_recalc": run.needs_recalc,
        "created_at": _iso(run.created_at),
    }


#: ``sha256:`` + 64 hex (`TECH_SPEC §5.3` · `calc/hash.py`의 산출 형태).
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _require_hash(value: str | None, *, field: str, field_label: str) -> None:
    """해시 필터의 **형식**을 본다 — 존재는 보지 않는다 (`#1367`).

    형식이 틀린 값은 어떤 행과도 맞을 수 없으므로, 그대로 내려보내면 **빈 목록**이
    돌아온다. 「그런 계산이 없다」와 「해시를 잘못 적었다」가 같은 화면이 된다.
    존재 여부는 다른 축이다 — 형식이 맞는 해시로 아무것도 못 찾는 것은 정상이다.
    """
    if value is None:
        return
    if not _HASH_PATTERN.match(value):
        raise ValidationError(
            f"{field_label}는 `sha256:` + 64자리 16진수여야 합니다: {value}",
            field=field,
            field_label=field_label,
        )


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

    ``needs_recalc_total``은 **이 페이지가 아니라 필터 전체**의 값이다 (#1076).
    선박 상세의 「계산 이력」이 머리에 적는 「재계산 필요 N건」이 종전에는 받은
    페이지만 세어, 21번째 행부터 낡아 있어도 **「0건」으로 보였다** — 「낡은 것이
    없다」와 「아직 다 세어 보지 않았다」를 같은 모양으로 그린 자리다(`API_SPEC §1.9`).
    """
    if calculation_type is not None and calculation_type not in calc_run_repo.CALCULATION_TYPES:
        # `sort`(`services/fleet_summary.py`)와 같은 방식이다 — 저장소 안에서 두
        # 경로가 갈리면 화면은 어느 쪽 동작을 기대해야 할지 알 수 없다.
        raise ValidationError(
            f"종류는 {' · '.join(calc_run_repo.CALCULATION_TYPES)} 중 하나여야 합니다: "
            f"{calculation_type}",
            field="type",
            field_label="종류",
        )
    _require_hash(input_hash, field="input_hash", field_label="입력 해시")
    _require_hash(parameter_hash, field="parameter_hash", field_label="파라미터 해시")

    page_size = normalize_limit(limit)

    parsed_cursor = None
    if cursor is not None:
        parsed_cursor = calc_run_repo.decode_cursor(cursor)
        if parsed_cursor is None:
            raise ValidationError(
                "커서 형식이 올바르지 않습니다.",
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
                created_at=page[-1].created_at,
                calculation_run_id=page[-1].id,
            )
        )
        if has_more and page
        else None
    )

    needs_recalc_total = await calc_run_repo.count_needs_recalc_runs(
        session,
        input_hash=input_hash,
        parameter_hash=parameter_hash,
        calculation_type=calculation_type,
        vessel_id=vessel_id,
    )

    return [_to_dict(row) for row in page], {
        "next_cursor": next_cursor,
        "has_more": has_more,
        "needs_recalc_total": needs_recalc_total,
    }
