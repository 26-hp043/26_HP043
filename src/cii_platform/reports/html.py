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
    from collections.abc import Sequence

    from cii_platform.reports.document import ReportDocument

#: 표지 워드마크. `frontend/public/brand/bluelog-logo-dark.svg`를 **그대로** 박아 둔다.
#:
#: 파일을 런타임에 읽지 않는다 — 백엔드 이미지에 ``frontend/public/``이 들어간다는 보장이
#: 없고, 없는 날 리포트가 **로고 없이 조용히** 렌더링된다. 박아 두면 자산과 갈라질 수
#: 있으므로 ``tests/test_reports.py``의 동기화 검사가 그 갈림을 잡는다.
#:
#: 흰 워드마크(``-dark``)를 쓰는 이유는 띠가 네이비이기 때문이다. 띠 위 대비 실측 —
#: ``#F2F7FC`` 12.09 · ``#6BA9F7`` 5.36 · ``#FFFFFF`` 13.03 (``DESIGN_SYSTEM §0.2``
#: 제약 1·6 — 띠가 이 문서의 가장 어두운 면이라 그 면을 기준으로 잰다).
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 298.3 96.0" width="298.3" height="96.0" role="img" aria-label="BlueLog"><g transform="translate(0.00 20.00) scale(0.075574) translate(-91.00 741.00)"><defs><clipPath id="L2k"><path d="M91 0H355C518 0 641 -69 641 -218C641 -317 583 -374 503 -393V-397C566 -420 604 -489 604 -558C604 -696 488 -741 336 -741H91ZM239 -439V-627H327C416 -627 460 -601 460 -536C460 -477 420 -439 326 -439ZM239 -114V-330H342C444 -330 497 -299 497 -227C497 -150 442 -114 342 -114Z"/></clipPath></defs><g clip-path="url(#L2k)"><rect x="71.0" y="-761.0" width="590.0" height="781.0" fill="#FFFFFF"/><path d="M 20 -385 C 110 -434 232 -430 336 -385 C 440 -340 562 -336 720 -385 L 720 240 L 20 240 Z" fill="#6BA9F7"/></g></g><g transform="translate(61.57 60.00) scale(0.060027)"><g fill="#F2F7FC"><path d="M91 0H355C518 0 641 -69 641 -218C641 -317 583 -374 503 -393V-397C566 -420 604 -489 604 -558C604 -696 488 -741 336 -741H91ZM239 -439V-627H327C416 -627 460 -601 460 -536C460 -477 420 -439 326 -439ZM239 -114V-330H342C444 -330 497 -299 497 -227C497 -150 442 -114 342 -114Z"/><path d="M887 14C921 14 945 8 962 1L944 -108C934 -106 930 -106 924 -106C910 -106 895 -117 895 -151V-798H748V-157C748 -53 784 14 887 14Z"/><path d="M1218 14C1295 14 1348 -24 1396 -81H1400L1411 0H1531V-560H1384V-182C1346 -132 1316 -112 1271 -112C1216 -112 1191 -142 1191 -229V-560H1045V-211C1045 -70 1097 14 1218 14Z"/><path d="M1920 14C1989 14 2060 -10 2115 -48L2065 -138C2024 -113 1985 -100 1940 -100C1856 -100 1796 -147 1784 -238H2129C2133 -252 2136 -279 2136 -306C2136 -462 2056 -574 1902 -574C1769 -574 1641 -461 1641 -280C1641 -95 1763 14 1920 14ZM1781 -337C1793 -418 1845 -460 1904 -460C1977 -460 2010 -412 2010 -337Z"/></g><g fill="#6BA9F7"><path d="M2257 0H2706V-124H2405V-741H2257Z"/><path d="M3045 14C3185 14 3314 -94 3314 -280C3314 -466 3185 -574 3045 -574C2904 -574 2776 -466 2776 -280C2776 -94 2904 14 3045 14ZM3045 -106C2968 -106 2926 -174 2926 -280C2926 -385 2968 -454 3045 -454C3121 -454 3164 -385 3164 -280C3164 -174 3121 -106 3045 -106Z"/><path d="M3622 243C3809 243 3927 157 3927 44C3927 -54 3853 -96 3718 -96H3622C3557 -96 3534 -112 3534 -141C3534 -165 3544 -177 3558 -190C3583 -181 3609 -177 3630 -177C3751 -177 3847 -240 3847 -367C3847 -402 3836 -433 3822 -452H3917V-560H3716C3692 -568 3663 -574 3630 -574C3512 -574 3405 -503 3405 -372C3405 -306 3441 -253 3480 -225V-221C3446 -197 3418 -158 3418 -117C3418 -70 3439 -41 3469 -22V-17C3416 12 3389 52 3389 99C3389 198 3490 243 3622 243ZM3630 -268C3582 -268 3543 -305 3543 -372C3543 -437 3581 -473 3630 -473C3680 -473 3719 -437 3719 -372C3719 -305 3680 -268 3630 -268ZM3644 149C3563 149 3511 123 3511 77C3511 53 3522 31 3547 11C3568 16 3591 18 3624 18H3693C3753 18 3786 29 3786 69C3786 112 3729 149 3644 149Z"/></g></g></svg>"""  # noqa: E501 — 자산을 **그대로** 박는다. 줄을 접으면 문자열이 달라져 동기화 검사가 깨진다.

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
/* 표지 브랜드 띠 (`#2001`). **본문 흐름에 둔다** — `@page` 머리글에 두면 페이지마다
   네이비가 인쇄된다. 문서 맨 앞 한 번으로 표식은 충분하다. 내용 폭에 맞추고 재단선까지
   늘리지 않는다 — 가정용 프린터의 여백에서 잘린 띠가 더 나쁘게 보인다. */
.cover { display: flex; align-items: center; height: 6mm; margin: 0 0 5mm;
         padding: 0 3mm; background: #16305C; }
/* 자산의 width·height 속성을 CSS가 덮는다 — 자산 파일은 그대로 두고 크기만 여기서 정한다. */
.cover svg { display: block; height: 4mm; width: auto; }
body { font-family: sans-serif; font-size: 9.5pt; color: #1a1a18; line-height: 1.5; }
/* `DESIGN_SYSTEM §3` — 굵기는 400·500만 쓴다. **기본값에 맡기지 않는다** (`#2003`):
   HTML 기본 스타일이 `h1`·`h2`·`b`·`th`를 굵게 그리므로, 선언이 없으면 `§3` 밖의 `700`이
   조용히 인쇄된다. 종전이 그 상태였다.
   ⚠️ 인쇄 스택(`fonts-nanum`)에는 Medium이 없어 `500`은 지금 Regular로 떨어진다. 스택이
   Medium을 갖는 날 이 선언이 그대로 의도대로 산다. */
h1, h2, b { font-weight: 500; }
h1 { font-size: 17pt; margin: 0 0 2mm; }
/* 굵기가 빠지면 11pt는 본문 9.5pt와 1.5pt 차이뿐이라 제목이 서지 않는다. 3pt로 벌린다.
   인쇄 크기는 `§3` 소관이 아니다 — `§3` 표는 px 화면 스케일이고 여기는 pt 인쇄 스케일이다. */
h2 { font-size: 12.5pt; margin: 7mm 0 2mm; padding-bottom: 1mm;
     border-bottom: 1px solid #c9c7be; }
/* 표지 메타 — 라벨과 값을 **크기와 색조 둘**로 가른다 (`#2003`). 굵기를 쓸 수 없는 자리라
   한 채널만 쓰면 구분이 물러진다(색조만 쓴 시안이 흑백 확대에서 그랬다). 주 채널은 여전히
   **순서**다 — 라벨이 값 앞에 온다. 색이 단독으로 뜻을 지지 않으므로 `§14`에 걸리지 않는다. */
.meta { margin: 0 0 6mm; font-size: 8pt; color: #5f5e5a; }
.meta b { font-size: 9.5pt; color: #1a1a18; }
.meta span { margin-right: 5mm; }
.disclaim { margin: 0 0 6mm; padding: 2.5mm 3mm; border: 1px solid #c9c7be;
            background: #f8f8f6; font-size: 8.5pt; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 1.6mm 2mm; border-bottom: 1px solid #e3e2dc; text-align: left;
         vertical-align: top; }
/* `DESIGN_SYSTEM §3` — 「굵기는 400·500만 쓴다」. 종전 `600`은 그 표에 없는 값이었고
   프런트엔드 가드가 닿지 않는 자리라 남아 있었다 (`#2001`).
   ⚠️ **인쇄 스택에는 Medium이 없다** — 컨테이너가 싣는 것은 `fonts-nanum`(Regular·Bold)
   뿐이라 실측상 `500`은 Regular로, 종전의 `600`은 Bold로 떨어졌다. 머리글을 가르는 일은
   아래 면(`#f8f8f6`)이 이미 하고 있다. 스택이 Medium을 갖는 날 이 선언이 그대로 산다. */
th { font-weight: 500; background: #f8f8f6; }
/* 수치 열은 오른쪽 정렬 + 자릿수 고정폭 — 세로로 자릿수가 맞아야 읽힌다. */
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.label { color: #5f5e5a; width: 34%; }
.note { margin: 1.5mm 0 0; font-size: 8pt; color: #5f5e5a; }
.warnings { margin: 6mm 0 0; padding: 2.5mm 3mm; border: 1px solid #e3e2dc;
            font-size: 8.5pt; }
.warnings ul { margin: 1mm 0 0; padding-left: 4mm; }
/* 「경고」도 굵기를 못 쓴다. 줄을 바꿔 세우고 자간으로 표제임을 알린다. */
.warnings b { display: block; margin-bottom: 1.2mm; color: #1a1a18;
              letter-spacing: 0.08em; }
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


#: 값이 없다는 표기 (``DESIGN_SYSTEM §4.2`` · ``services/report.py``의 ``_display``).
#: 열 종류를 판정할 때 **세지 않는다** — 빈칸 하나가 수치 열을 문자 열로 뒤집으면 그 표의
#: 자릿수가 통째로 어긋난다. ``tests/test_reports.py``가 이 값이 문서 쪽과 같은지 본다.
MISSING_VALUE = "—"


def _cell(value: str, tag: str = "td") -> str:
    css = ' class="num"' if _looks_numeric(value) else ""
    return f"<{tag}{css}>{escape(value)}</{tag}>"


def _numeric_column(cells: Sequence[str]) -> bool:
    """열 **전체**가 수치인가 (`#2004`).

    스타일시트가 적어 둔 것은 「수치 **열**은 오른쪽 정렬 — 세로로 자릿수가 맞아야
    읽힌다」인데, 구현은 **셀마다 따로** 판정하고 있었다. 그래서 둘이 어긋났다.

    * 머리글이 자기 열과 반대쪽에 붙었다 — 「실적 CII」는 글자라 왼쪽, 그 아래 ``6.98``은
      숫자라 오른쪽. 자릿수를 맞춰 읽으라는 정렬인데 그 기준선이 머리글에서 끊겼다.
    * 같은 열 안에서도 ``—`` 하나가 줄을 흐트러뜨렸다.

    ``TableSection.kinds``를 쓰지 않는다. 그 선언은 **CSV 직렬화**를 위한 것이고(`#1247`),
    정렬과 뜻이 다르다 — 「완료 항차」는 ``3 (+진행 중 1)`` 꼴이 섞인다는 이유로
    ``string``으로 선언돼 있지만 읽는 사람에게는 수치 열이다. 선언에 두 번째 뜻을 얹으면
    한쪽을 고칠 때 다른 쪽이 조용히 움직인다.
    """
    present = [cell for cell in cells if cell.strip() and cell.strip() != MISSING_VALUE]
    return bool(present) and all(_looks_numeric(cell) for cell in present)


def _aligned(value: str, tag: str, numeric: bool) -> str:
    """열 판정을 받아 그리는 셀. 머리글과 값이 **같은 판정**을 쓴다."""
    css = ' class="num"' if numeric else ""
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
        # 열마다 한 번 판정하고 머리글과 값이 그 하나를 함께 쓴다 (`#2004`).
        numeric = [
            _numeric_column([row[index] for row in section.rows])
            for index in range(len(section.headers))
        ]
        head = "".join(
            _aligned(header, "th", is_num)
            for header, is_num in zip(section.headers, numeric, strict=True)
        )
        body = "".join(
            "<tr>"
            + "".join(
                _aligned(cell, "td", is_num) for cell, is_num in zip(row, numeric, strict=True)
            )
            + "</tr>"
            for row in section.rows
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
        # 로고는 **우리 자산**이라 escape하지 않는다 — 사용자 입력이 섞이지 않는 유일한
        # 마크업이다. 여기에 문서에서 온 값을 넣으면 그 순간 이 예외가 구멍이 된다.
        f'<div class="cover">{LOGO_SVG}</div>'
        f"<h1>{escape(document.title)}</h1>"
        f'<p class="meta">{meta}</p>'
        # 표지 면책 — 푸터(@bottom-center)와 **둘 다** 둔다. PRD §25.1이 「표지·푸터」를
        # 함께 요구하고, 첫 장만 읽고 덮는 독자와 발췌 인쇄본 독자가 다르다.
        f'<p class="disclaim">{escape(DISCLAIMER)}</p>'
        f"{sections}{warnings}"
        "</body></html>"
    )
