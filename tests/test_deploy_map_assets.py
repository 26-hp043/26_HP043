"""이슈 #1909 · 배포된 화면에서 **지도가 실제로 뜨는** 배선을 고정한다.

## 무엇이 깨져 있었나

운영(`https://bluelog-bx7.pages.dev`)에서 지도가 **한 번도 뜬 적이 없었다.** 원인이 둘
겹쳐 있었고 **둘 다 조용했다** — 배포는 성공하고, CI는 초록이고, 개발 서버에서는 뜬다.

⑴ **Cloudflare Pages가 ``Range`` 요청을 무시한다.** 실측(2026-09-25):
   ``curl -H 'Range: bytes=0-6' …/basemap/bluelog.pmtiles`` → ``200`` · 전체 15 MB ·
   ``accept-ranges`` 없음. ``/favicon.svg``도 같다 — 파일 크기 문제가 아니다.
   지도 타일은 PMTiles 아카이브 **파일 하나**에서 조각을 읽으므로(``#985``) byte
   serving이 없으면 ``pmtiles``가 *"Check that your storage backend supports HTTP Byte
   Serving"*로 멈춘다. ``hasBasemap()``은 ``206``이 아니면 「자산 없음」으로 접고
   (``#1144``), 화면은 **개략도로 떨어진다.** 고장이 보이지 않는다.

⑵ **빌드가 maplibre 타일 워커를 내보내지 않았다.** maplibre v6는 워커 주소를 런타임에
   조립하고(파일 이름이 삼항 연산으로 정해진다) 번들러가 그것을 정적으로 읽지 못한다.
   없는 자산을 부르면 SPA 폴백이 ``index.html``을 ``200``으로 돌려주므로 워커는 HTML을
   자바스크립트로 읽다 죽는다. ``#1144``가 적은 그대로 **maplibre는 오류를 내지 않고**
   지도는 회색 사각형으로 남는다.

## 왜 검사로 고정하는가

두 배선 모두 **지우거나 되돌려도 아무 검사가 빨개지지 않는다.** 개발 서버는 Range를
지원하고 워커 파일을 그대로 서빙하므로 ``e2e/map-smoke.spec.ts``도 통과한다 —
``#1322``·``#1290``·``#1331``과 같은 종류의 조용한 배선 결함이다.

산출물 쪽(워커 자산이 실제로 나왔는가)은 ``.github/workflows/ci.yml``의
「지도 타일 워커 자산 확인」 단계가 본다. 여기서는 **소스의 배선**을 본다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND = _ROOT / "frontend"
#: Pages Functions의 catch-all. 이 파일이 곧 `/basemap/*` 라우트다 — 별도 등록이 없다.
_BASEMAP_ROUTE = _FRONTEND / "functions" / "basemap" / "[[path]].ts"
_BASEMAP_LIB = _FRONTEND / "functions" / "_byteRange.ts"
_WORKER_MODULE = _FRONTEND / "src" / "features" / "map" / "mapLibreWorker.ts"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
#: 직접 `new maplibregl.Map(...)`을 부르는 곳. 전부 워커 주소를 먼저 정해야 한다.
_MAP_RENDERERS = (
    _FRONTEND / "src" / "features" / "map" / "mapLibreRenderer.ts",
    _FRONTEND / "src" / "features" / "map" / "playbackRenderer.ts",
)


def test_basemap_route_serves_byte_ranges():
    """`/basemap/*`에 Range(206)를 채우는 Function이 있다 (#1909 ⑴).

    이 파일이 없으면 Pages의 ``200`` 전체 응답이 그대로 나가고, 지도는 자산이 있는데도
    「없음」으로 접혀 개략도가 된다.
    """
    assert _BASEMAP_ROUTE.is_file(), f"{_BASEMAP_ROUTE} 가 없다 — Pages는 Range를 무시한다"
    route = _BASEMAP_ROUTE.read_text(encoding="utf-8")
    assert "parseByteRange" in route, "Range 해석이 빠졌다"
    assert "206" in route, "부분 응답 상태 코드가 없다"
    assert "416" in route, "만족시킬 수 없는 구간에 416으로 답해야 한다 (pmtiles가 다시 묻는다)"


def test_byte_range_parsing_lives_in_a_testable_module():
    """Range 해석이 `_` 접두 모듈에 있다 — Worker 런타임 없이 검사하기 위해서다."""
    assert _BASEMAP_LIB.is_file(), f"{_BASEMAP_LIB} 가 없다"
    assert (_FRONTEND / "functions" / "_byteRange.test.ts").is_file(), "순수 부분 검사가 없다"


def test_every_map_renderer_pins_the_worker_url():
    """지도를 만드는 모든 곳이 워커 주소를 **먼저** 정한다 (#1909 ⑵).

    한 곳이라도 빠지면 그 화면만 회색 사각형이 된다 — 그리고 오류가 나지 않는다.
    """
    assert _WORKER_MODULE.is_file(), f"{_WORKER_MODULE} 가 없다"
    module = _WORKER_MODULE.read_text(encoding="utf-8")
    assert "setWorkerUrl" in module, "maplibre에 워커 주소를 알려 주지 않는다"
    assert "?worker&url" in module, (
        "Vite가 워커를 자산으로 내보내게 하는 import가 없다 — 이것이 빠지면 "
        "dist/assets에 워커 파일이 생기지 않는다"
    )

    for renderer in _MAP_RENDERERS:
        text = renderer.read_text(encoding="utf-8")
        assert "new maplibregl.Map(" in text, (
            f"{renderer.name} 가 더 이상 지도를 만들지 않는다면 이 목록에서 빼라"
        )
        assert "ensureMapLibreWorker()" in text, (
            f"{renderer.name} 가 워커 주소를 정하지 않고 지도를 만든다"
        )


def test_ci_checks_that_the_worker_asset_was_emitted():
    """산출물에 워커가 들어갔는지 CI가 본다 (#1909 ⑵).

    소스 배선이 맞아도 번들러가 자산을 빠뜨리면 같은 고장이 돌아온다. 빌드·테스트는
    그때도 초록이므로 **산출물을 직접 보는 단계**가 필요하다.
    """
    ci = _CI.read_text(encoding="utf-8")
    assert "dist/assets/maplibre-gl-worker-" in ci, (
        "CI가 빌드 산출물에서 지도 워커를 확인하지 않는다"
    )
