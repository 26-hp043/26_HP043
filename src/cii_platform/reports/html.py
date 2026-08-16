"""리포트 문서 → HTML (PRD §25, #361).

PDF는 이 HTML을 WeasyPrint로 렌더링해 만든다. **HTML을 중간에 두는 이유**는 셋이다.

1. PDF 라이브러리 API로 표를 그리면 레이아웃 코드가 라이브러리에 묶인다. 렌더러를
   바꾸는 날 문서 코드를 통째로 다시 써야 한다.
2. HTML은 **DOM 없이 문자열로 검증할 수 있다** — 한글이 들어갔는지, 면책이 있는지,
   표 열 수가 맞는지를 PDF 바이너리를 열지 않고 본다.
3. 브라우저 미리보기와 PDF가 **같은 소스**를 쓴다.

## 폰트를 이름으로 지정하지 않는다

컨테이너에 설치된 한국어 폰트(``fonts-nanum``)를 ``sans-serif``로 fontconfig가
해결하게 둔다. ``font-family: NanumGothic``처럼 이름을 박으면 폰트 패키지가 바뀔 때
**조용히 tofu(□□□)로** 렌더링된다 — 오류가 아니라 글자가 사라지는 방식으로 실패한다.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from cii_platform.reports.document import (
    DISCLAIMER,
    KeyValueSection,
    TableSection,
)

if TYPE_CHECKING:
    from cii_platform.reports.document import ReportDocument

#: 인쇄용 스타일. 외부 자원을 참조하지 않는다 — 렌더링 시점에 네트워크를 타면
#: 오프라인 시연에서 문서가 달라 보이고, 그 차이는 PDF에 굳어 남는다.
STYLESHEET = """
@page {
  size: A4;
  margin: 18mm 16mm 20mm;
  /* 면책을 모든 페이지 푸터에 둔다 — PRD §25.1 「표지·푸터 필수 노출」. */
  @bottom-center {
    content: "본 리포트는 참고용 예측값입니다. 규제 제출용 공식 문서가 아닙니다.";
    font-size: 7.5pt;
    color: #666;
  }
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-size: 7.5pt;
    color: #666;
  }
}
body { font-family: sans-serif; font-size: 9.5pt; color: #1a1a18; line-height: 1.5; }
h1 { font-size: 17pt; margin: 0 0 2mm; }
h2 { font-size: 11pt; margin: 7mm 0 2mm; padding-bottom: 1mm;
     border-bottom: 1px solid #c9c7be; }
.meta { margin: 0 0 6mm; font-size: 8.5pt; color: #5f5e5a; }
.meta span { margin-right: 5mm; }
.disclaim { margin: 0 0 6mm; padding: 2.5mm 3mm; border: 1px solid #c9c7be;
            background: #f8f8f6; font-size: 8.5pt; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 1.6mm 2mm; border-bottom: 1px solid #e3e2dc; text-align: left;
         vertical-align: top; }
th { font-weight: 600; background: #f8f8f6; }
/* 수치 열은 오른쪽 정렬 + 자릿수 고정폭 — 세로로 자릿수가 맞아야 읽힌다. */
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.label { color: #5f5e5a; width: 34%; }
.note { margin: 1.5mm 0 0; font-size: 8pt; color: #5f5e5a; }
.warnings { margin: 6mm 0 0; padding: 2.5mm 3mm; border: 1px solid #e3e2dc;
            font-size: 8.5pt; }
.warnings ul { margin: 1mm 0 0; padding-left: 4mm; }
/* 표가 페이지 경계에서 머리글만 남고 잘리는 것을 막는다. */
table { page-break-inside: auto; }
tr { page-break-inside: avoid; }
thead { display: table-header-group; }
h2 { page-break-after: avoid; }
"""


def _looks_numeric(value: str) -> bool:
    """수치 열 판정 — 오른쪽 정렬에만 쓴다.

    **값을 바꾸지 않는다.** 판정이 틀려도 정렬만 달라지므로, 여기서 실수해도 문서의
    내용은 그대로다. 숫자로 「고쳐」 쓰려 들면 그 순간 정밀도가 사라진다.
    """
    stripped = value.replace(",", "").replace("%", "").strip()
    if not stripped:
        return False
    body = stripped.split()[0]
    try:
        float(body)
    except ValueError:
        return False
    return True


def _cell(value: str, tag: str = "td") -> str:
    css = ' class="num"' if _looks_numeric(value) else ""
    return f"<{tag}{css}>{escape(value)}</{tag}>"


def _section_html(section: KeyValueSection | TableSection) -> str:
    parts = [f"<h2>{escape(section.title)}</h2>"]

    if isinstance(section, KeyValueSection):
        rows = "".join(
            f'<tr><td class="label">{escape(label)}</td>{_cell(value)}</tr>'
            for label, value in section.rows
        )
        parts.append(f"<table><tbody>{rows}</tbody></table>")
    else:
        head = "".join(_cell(header, "th") for header in section.headers)
        body = "".join(
            "<tr>" + "".join(_cell(cell) for cell in row) + "</tr>" for row in section.rows
        )
        parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")

    if section.note:
        parts.append(f'<p class="note">{escape(section.note)}</p>')
    return "".join(parts)


def render_html(document: ReportDocument) -> str:
    """문서를 인쇄용 HTML 한 장으로 만든다.

    모든 문자열을 ``escape``한다. 선박명·항구명은 사용자가 넣은 값이고, ``<script>``가
    든 이름이 리포트에 그대로 들어가면 미리보기 화면에서 실행된다.
    """
    document.validate()

    meta = "".join(
        f"<span>{escape(label)} <b>{escape(value)}</b></span>" for label, value in document.meta
    )
    sections = "".join(_section_html(section) for section in document.sections)

    warnings = ""
    if document.warnings:
        items = "".join(f"<li>{escape(w)}</li>" for w in document.warnings)
        warnings = f'<div class="warnings"><b>경고</b><ul>{items}</ul></div>'

    return (
        "<!DOCTYPE html>"
        '<html lang="ko"><head><meta charset="utf-8">'
        f"<title>{escape(document.title)}</title>"
        f"<style>{STYLESHEET}</style></head><body>"
        f"<h1>{escape(document.title)}</h1>"
        f'<p class="meta">{meta}</p>'
        # 표지 면책 — 푸터(@bottom-center)와 **둘 다** 둔다. PRD §25.1이 「표지·푸터」를
        # 함께 요구하고, 첫 장만 읽고 덮는 독자와 발췌 인쇄본 독자가 다르다.
        f'<p class="disclaim">{escape(DISCLAIMER)}</p>'
        f"{sections}{warnings}"
        "</body></html>"
    )
