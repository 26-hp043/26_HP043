"""자료 내보내기 라우트 (API_SPEC §8.1, #59).

**HTTP만 다룬다** (TECH_SPEC §16.1). 어떤 열을 어디서 뽑을지는
``services.data_export``가 정하고, CSV로 펴는 일은 ``reports.csv_export``가 맡는다.

## 별도 모듈인 이유

`§8.1`은 항차·계산·시뮬레이션 **세 종류**를 엔드포인트 하나로 덮는다. ``voyages.py``에
두면 계산·시뮬레이션 조회가 항차 모듈에 들어가고, ``reports.py``에 두면 「문서 생성」과
「원본 자료 내보내기」가 섞인다. 둘은 만드는 것이 다르다 — 리포트는 **사람이 읽는
문서**(제목·면책·구간)이고 여기는 **다시 가져올 수 있는 표**다.

## CSV만 파일이다

``format=csv``는 ``StreamingResponse`` + ``Content-Disposition``으로 내려보낸다.
``format=json``은 **첨부가 아니라** 이 저장소의 표준 봉투(``{"data": …, "meta": …}``)
그대로다 — JSON은 브라우저가 저장할 대상이 아니라 화면·스크립트가 읽는 형태다.
(`§8.3`의 「이 절은 파일을 내보낸다」는 PDF·CSV **문서** 이야기다.)
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.api.timefmt import iso_utc_now
from cii_platform.db.session import get_session
from cii_platform.errors import ValidationError
from cii_platform.reports.csv_export import iter_table_csv
from cii_platform.services.data_export import (
    EXPORT_FORMATS,
    ExportTable,
    build_export,
)

router = APIRouter(tags=["exports"])


def _meta(request: Request, **extra: object) -> dict[str, object]:
    state = getattr(request, "state", None)
    return {
        **extra,
        "request_id": getattr(state, "request_id", None),
        "timestamp": getattr(state, "timestamp", None) or iso_utc_now(),
    }


def _disposition(table: ExportTable) -> str:
    """``attachment; filename="voyages_2026.csv"`` (``API_SPEC §8.1`` 응답 예시).

    ASCII ``filename``과 UTF-8 ``filename*``을 **둘 다** 보낸다 (RFC 6266 §4.3) —
    ``reports.py``와 같은 규칙이다. 지금은 파일명이 ASCII뿐이지만, 한쪽만 보내는
    습관을 남기면 선박명을 붙이는 날 깨진다.
    """
    name = f"{table.filename_stem}.csv"
    return f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"


@router.get("/vessels/{vessel_id}/export")
async def export_vessel_data_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    type: Annotated[str, Query(description="voyages · calculations · simulations")],
    year: Annotated[int | None, Query(description="기준연도 필터")] = None,
    format: Annotated[str, Query(description="csv (기본) · json")] = "csv",
) -> Response:
    """선박 자료를 CSV/JSON으로 내보낸다 (``API_SPEC §8.1``).

    **vessel-scoped다** — ``/voyages/export``가 아니다. 가져오기(`§8.2`)와 같은 이유로
    선박을 경로가 정한다: 자료에 선박 식별자를 실어도 경로와 다르면 무엇을 따를지
    정해야 하고, 경로 하나로 두면 그 물음이 생기지 않는다.

    ``type``은 **필수다**(`§8.1` 표). 기본값을 두면 사용자가 계산 이력을 받으려다
    항차 파일을 받고도 알아채지 못한다.
    """
    if format not in EXPORT_FORMATS:
        raise ValidationError(
            f"지원하지 않는 형식입니다: {format}. {' · '.join(EXPORT_FORMATS)} 중 하나여야 합니다.",
            field="format",
            field_label="형식",
        )

    table = await build_export(session, vessel_id, type=type, year=year)

    if format == "json":
        return Response(
            content=_json_body(request, table),
            media_type="application/json",
        )

    return StreamingResponse(
        iter_table_csv(list(table.columns), table.rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _disposition(table)},
    )


def _json_body(request: Request, table: ExportTable) -> str:
    """표준 봉투를 문자열로 만든다.

    ``JSONResponse``가 아니라 문자열인 이유는 **행 수를 ``meta``에 함께 실기** 위해서다 —
    받은 쪽이 파일이 잘렸는지 판단할 근거가 있어야 한다.
    """
    import json

    body = {
        "data": {
            "type": table.type,
            "year": table.year,
            "columns": list(table.columns),
            "rows": table.as_dicts(),
        },
        "meta": _meta(request, row_count=len(table.rows)),
    }
    return json.dumps(body, ensure_ascii=False)
