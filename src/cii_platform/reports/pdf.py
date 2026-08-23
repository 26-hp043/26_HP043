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

**폰트가 없으면 PDF를 내주지 않는다** (`#689`). 컨테이너·CI에는 폰트가 들어 있으나
호스트 ``.venv``로 직접 띄우는 경로(``scripts/demo_up.sh``)에는 없었고, 그 서버가
**면책 문구가 □인 문서를 200으로** 내보내고 있었다. 판정 근거는 ``TECH_SPEC §19.4``에
적었다.

## 지연 import

WeasyPrint는 import 시점에 Pango를 연다. 이 모듈이 최상단에서 import하면 라이브러리가
없는 환경에서 **앱 전체가 뜨지 않고** CSV 내보내기까지 막힌다. 함수 안에서 import해
PDF 요청 하나만 실패시키고, 그 실패에 설치 안내를 담는다.
"""

from __future__ import annotations

from functools import lru_cache

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

    **진단용이다. 요청마다 부르지 않는다** — 매번 작은 문서를 렌더링하게 된다.
    요청 경로에서는 프로세스당 1회로 묶은 :func:`korean_font_available`을 쓴다 (`#689`).

    프로브는 :func:`_render`로 그린다. :func:`render_pdf`를 쓰면 그쪽이 다시 이 판정을
    물어 **무한 재귀**가 된다 (`#689`).
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
        _render(_PROBE_HTML)
    except Exception:  # pragma: no cover - 환경 의존
        return False
    finally:
        logger.removeHandler(handler)

    return not any("notdef" in record.getMessage() for record in records)


@lru_cache(maxsize=1)
def korean_font_available() -> bool:
    """한국어 글리프를 그릴 수 있는가 — **요청 경로에서 쓰는 캐시된 판정** (`#689`).

    :func:`has_korean_font`는 부를 때마다 프로브 문서를 렌더링한다. 그대로 요청마다
    부르면 PDF 한 건에 렌더링이 두 번 일어난다. 설치된 폰트는 **프로세스 수명 동안
    바뀌지 않으므로** 1회만 판정한다 — ``health.py``의 ``_rng_canonical_test``가
    같은 이유로 쓰는 방식이다 (`#400`).

    **폰트를 설치한 뒤에는 서버를 다시 시작해야 반영된다.** 캐시를 요청마다 무르면
    이 함수를 두는 의미가 없고, 폰트 설치는 배포·기동 시점의 일이지 운영 중에
    일어나는 일이 아니다. 기동 점검(``scripts/demo_up.sh``)이 그 시점에 잡는다.
    """
    return has_korean_font()


def render_pdf(html: str) -> bytes:
    """인쇄용 HTML을 PDF 바이트로 만든다.

    **한국어 폰트가 없으면 렌더링하지 않고 거부한다** (`#689`). 종전에는 그 상태에서도
    ``200``과 유효한 ``%PDF-1.7``이 나갔고, 문서 안에서 한글만 tofu(□)가 됐다 — 그중에
    ``PRD §18.2``의 면책 문구가 있다. **읽을 수 없는 면책이 실린 문서는 리포트가 아니다.**

    렌더러 자체가 없을 때와 **같은 방식**으로 다룬다(``PdfUnavailableError`` → 500 +
    CSV 안내). 둘 다 사용자 입력의 문제가 아니라 배포 환경의 문제이고, 요청을 고쳐도
    해결되지 않는다 (`TECH_SPEC §19.3`·`§19.4`).

    검사 순서를 ``is_available()`` 먼저로 둔다. 렌더러가 없으면 :func:`has_korean_font`도
    ``False``를 돌려주므로, 순서를 바꾸면 **Pango가 없는 환경에 폰트 문제라고 말하게
    된다.** 그 경우는 :func:`_render`가 실제 import 오류를 그대로 담아 낸다.

    ``base_url``을 주지 않는다. 스타일은 문서에 인라인돼 있고 외부 자원이 없으므로
    상대 경로를 해석할 일이 없다 — 주면 오히려 렌더러가 로컬 파일을 읽을 수 있는
    경로가 열린다.
    """
    if is_available() and not korean_font_available():
        raise PdfUnavailableError(
            "한국어 폰트가 설치돼 있지 않아 한글이 □로 렌더링됩니다. "
            "서버에 fonts-nanum을 설치한 뒤 다시 시작하십시오 "
            "(sudo apt-get install -y fonts-nanum && fc-cache -f)."
        )
    return _render(html)


def _render(html: str) -> bytes:
    """폰트 판정을 거치지 않고 실제로 렌더링한다.

    :func:`has_korean_font`의 프로브가 이 경로로 들어온다 — :func:`render_pdf`를 쓰면
    폰트 판정이 다시 프로브를 부르는 **무한 재귀**가 된다 (`#689`).

    **이 함수를 요청 경로에서 직접 쓰지 않는다.** 폰트 검사를 건너뛰는 것이 목적이
    아니라, 검사 자신이 쓸 자리를 만드는 것이 목적이다.
    """
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - 환경 의존
        raise PdfUnavailableError(str(exc)) from exc

    return HTML(string=html).write_pdf()
