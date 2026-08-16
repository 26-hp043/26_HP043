"""리포트 생성 라우트 (API_SPEC §8.3~§8.4, #361).

**HTTP만 다룬다** (TECH_SPEC §16.1). 데이터 수집은 ``services.report``가, 렌더링은
``reports`` 패키지가 맡는다.

## 응답이 JSON이 아니다

이 저장소의 다른 라우트는 ``{"data": …, "meta": …}``를 돌려주지만, 여기는 **파일**을
내보낸다. 문서를 base64로 감싸 JSON에 넣으면 브라우저가 바로 저장하지 못하고,
33% 커진 문자열을 메모리에 통째로 들고 있어야 한다.

## CSV는 흘려보내고 PDF는 한 번에 만든다

CSV는 줄 단위로 만들 수 있어 ``StreamingResponse``로 흘린다. PDF는 페이지 나눔 때문에
문서 전체를 봐야 첫 페이지가 확정되므로 스트리밍이 성립하지 않는다 — 흉내만 내면
「스트리밍인데 첫 바이트가 끝에 나온다」가 된다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cii_platform.db.session import get_session
from cii_platform.errors import ValidationError
from cii_platform.reports.csv_export import iter_csv
from cii_platform.reports.document import ReportDocument
from cii_platform.reports.html import render_html
from cii_platform.reports.pdf import render_pdf
from cii_platform.services.report import build_annual_report, build_voyage_report

router = APIRouter(tags=["reports"])

#: 지원 포맷. ``html``은 화면 미리보기용이다 — `#362`가 PDF를 그리기 전에 같은
#: 문서를 보여 줘야 하고, PDF를 iframe에 넣으면 브라우저 뷰어마다 다르게 뜬다.
FORMATS = ("pdf", "csv", "html")


def _disposition(document: ReportDocument, extension: str) -> str:
    """``Content-Disposition``.

    ASCII ``filename``과 UTF-8 ``filename*``을 **둘 다** 보낸다. 한글 파일명만 보내면
    구형 클라이언트가 깨진 이름으로 저장하고, ASCII만 보내면 사용자가 받은 파일이
    ``annual-report-uuid.pdf``라 무엇인지 알 수 없다 (RFC 6266 §4.3).
    """
    ascii_name = f"{document.slug}.{extension}"
    utf8_name = quote(f"{document.title}.{extension}")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


def _respond(document: ReportDocument, fmt: str) -> Response:
    if fmt not in FORMATS:
        raise ValidationError(
            f"지원하지 않는 형식입니다: {fmt}. {' · '.join(FORMATS)} 중 하나여야 합니다.",
            field="format",
            field_label="형식",
        )

    if fmt == "csv":
        return StreamingResponse(
            iter_csv(document),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": _disposition(document, "csv")},
        )

    html = render_html(document)
    if fmt == "html":
        # 미리보기는 첨부가 아니라 화면에 그린다 — Content-Disposition을 붙이지 않는다.
        return Response(content=html, media_type="text/html; charset=utf-8")

    return Response(
        content=render_pdf(html),
        media_type="application/pdf",
        headers={"Content-Disposition": _disposition(document, "pdf")},
    )


@router.get("/voyages/{voyage_id}/report")
async def voyage_report_route(
    request: Request,
    voyage_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    format: Annotated[str, Query(description="pdf · csv · html")] = "pdf",
    as_of: Annotated[datetime | None, Query(description="기준 시각 (ISO 8601 UTC)")] = None,
) -> Response:
    """항차 완료 리포트를 생성한다 (API_SPEC §8.3 · PRD §25.2).

    진행 중 항차는 대상이 아니다 — 실적이 확정되지 않은 값으로 문서를 만들면 같은
    항차의 리포트가 시점마다 달라진다.
    """
    document = await build_voyage_report(session, voyage_id, as_of=as_of)
    return _respond(document, format)


@router.get("/vessels/{vessel_id}/annual-report")
async def annual_report_route(
    request: Request,
    vessel_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    year: Annotated[int | None, Query(description="규제연도. 기본 as_of 연도")] = None,
    format: Annotated[str, Query(description="pdf · csv · html")] = "pdf",
    as_of: Annotated[datetime | None, Query(description="기준 시각 (ISO 8601 UTC)")] = None,
) -> Response:
    """연간 실적 리포트를 생성한다 (API_SPEC §8.4 · PRD §25.3)."""
    document = await build_annual_report(session, vessel_id, year=year, as_of=as_of)
    return _respond(document, format)
