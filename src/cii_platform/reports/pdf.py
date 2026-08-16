"""HTML → PDF (WeasyPrint, #361).

## 렌더링 수단 선정 근거

============  ==================================================================
 후보          판단
============  ==================================================================
 WeasyPrint    **채택.** 순수 Python 패키지 + Pango 런타임 라이브러리만 있으면 된다.
               HTML/CSS를 그대로 쓰므로 미리보기 화면과 문서가 같은 소스를 공유한다.
 Playwright    탈락. Chromium(≈300MB)과 브라우저 내려받기 단계가 필요하다. 이미지가
               런타임 전용(``python:3.12-slim``)으로 설계돼 있어 그 전제를 깬다.
 ReportLab     탈락. 시스템 의존성이 없는 것은 장점이나 레이아웃을 명령형으로 짜야
               해서 표·페이지 나눔 코드를 직접 들고 있어야 하고, 미리보기 HTML과
               PDF가 **서로 다른 코드**가 된다 — 두 출력이 갈릴 자리가 생긴다.
============  ==================================================================

## 한글 폰트

컨테이너에 ``fonts-nanum``(**SIL Open Font License 1.1**)을 설치한다. OFL은 임베딩과
재배포를 허용하므로 PDF에 서브셋으로 실려 나가도 문제가 없다.

``fonts-noto-cjk``는 한·중·일을 모두 담아 이미지가 ~300MB 늘어난다. 이 제품의 문서는
한국어이므로 한국어 폰트만 넣는다.

## 지연 import

WeasyPrint는 import 시점에 Pango를 연다. 이 모듈이 최상단에서 import하면 라이브러리가
없는 환경에서 **앱 전체가 뜨지 않고** CSV 내보내기까지 막힌다. 함수 안에서 import해
PDF 요청 하나만 실패시키고, 그 실패에 설치 안내를 담는다.
"""

from __future__ import annotations

from cii_platform.errors import AppError


class PdfUnavailableError(AppError):
    """PDF 렌더러를 쓸 수 없다. HTTP 500.

    **사용자 입력의 문제가 아니라 배포 환경의 문제**다. 요청을 고쳐도 해결되지
    않으므로 4xx가 아니다. CSV로 안내해 사용자가 막히지 않게 한다.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            "INTERNAL_ERROR",
            f"PDF 생성기를 사용할 수 없습니다. CSV 형식으로 내려받아 주세요. (원인: {detail})",
        )


def is_available() -> bool:
    """PDF 렌더링이 가능한 환경인가. 헬스 체크·진단용이다."""
    try:
        import weasyprint  # noqa: F401
    except Exception:  # pragma: no cover - 환경 의존
        return False
    return True


#: 한글 글리프 확인용 최소 문서. 초성·중성·종성이 모두 있는 글자를 쓴다.
_PROBE_HTML = '<html><body style="font-family: sans-serif">한글</body></html>'


def has_korean_font() -> bool:
    """한국어 글리프를 실제로 그릴 수 있는가.

    **폰트가 없으면 오류가 나지 않는다.** 렌더링은 성공하고 글자만 tofu(□□□)가 된다 —
    바이트 길이도, HTTP 상태도, 예외도 정상이라 배포 사고가 조용히 지나간다.

    WeasyPrint는 그 상황에서 ``.notdef glyph rendered for Unicode string unsupported
    by fonts`` 경고를 로거로 낸다. 그 경고를 잡아 **없는 것을 없다고** 말한다.

    진단용이다. 요청마다 부르지 않는다 — 매번 작은 문서를 렌더링하게 된다.
    """
    if not is_available():
        return False

    import logging

    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("weasyprint")
    handler = _Collector()
    logger.addHandler(handler)
    try:
        render_pdf(_PROBE_HTML)
    except Exception:  # pragma: no cover - 환경 의존
        return False
    finally:
        logger.removeHandler(handler)

    return not any("notdef" in record.getMessage() for record in records)


def render_pdf(html: str) -> bytes:
    """인쇄용 HTML을 PDF 바이트로 만든다.

    ``base_url``을 주지 않는다. 스타일은 문서에 인라인돼 있고 외부 자원이 없으므로
    상대 경로를 해석할 일이 없다 — 주면 오히려 렌더러가 로컬 파일을 읽을 수 있는
    경로가 열린다.
    """
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - 환경 의존
        raise PdfUnavailableError(str(exc)) from exc

    return HTML(string=html).write_pdf()
