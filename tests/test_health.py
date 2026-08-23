"""Health check 엔드포인트 계약 테스트 (#49).

API_SPEC §10(응답 형식)·§12(경로)·§1.1(prefix)을 CI가 지키도록 고정한다.
DB에 의존하지 않는다.
"""

import re
import tomllib
from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """명시적인 생명주기를 갖는 health 테스트 클라이언트.

    분당 한도는 ``conftest.py``의 ``_fresh_rate_limiter``가 매 테스트마다 새로
    끼운다 (`#651`) — 여기서 따로 뺄 필요가 없다.
    """
    with TestClient(app) as c:
        yield c


def test_health_returns_200_and_data_envelope(client: TestClient) -> None:
    # API_SPEC §10: {"data": {...}} 형태.
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert data["status"] == "ok"
    assert data["numpy_version"] == numpy.__version__
    # version은 semver 꼴이어야 한다. dist metadata가 없으면 pyproject 폴백이 받으므로
    # 이 assert는 두 경로 모두를 덮는다. 둘 다 실패한 "unknown"만 여기서 걸린다.
    # 폴백이 실제로 pyproject 값을 읽는지는 test_app_version_falls_back_to_pyproject가
    # 정확 비교로 확인한다.
    assert re.match(r"^\d+\.\d+", data["version"]), data["version"]


def test_health_has_no_meta_block(client: TestClient) -> None:
    # API_SPEC §10 응답은 §1.3.1의 meta(request_id/timestamp)를 요구하지 않는다.
    body = client.get("/api/v1/health").json()
    assert "meta" not in body


def test_bare_health_path_is_not_exposed(client: TestClient) -> None:
    """정본 경로는 ``/api/v1/health``다 (``API_SPEC §12``). prefix 없는 ``/health``는 없다.

    **404가 아니라 401이다 (#648).** 종전에는 `/health`가 공개 경로 목록에 있어
    미들웨어를 통과하고 라우팅에서 404가 났다 — 그 목록 항목은 ``API_SPEC §1.1``의
    **prefix를 생략한 축약 표기**를 문자 그대로 옮긴 것이었고, 실제 요청 경로는 항상
    ``/api/v1``을 달고 나오므로 **영원히 매치되지 않았다.**

    목록에서 빠진 지금은 **다른 미등록 경로와 똑같이** 401이다. 「노출되지 않는다」는
    더 강해졌다 — 그 경로만 응답이 다르지 않다.
    """
    assert client.get("/health").status_code == 401
    # 없는 경로와 구분되지 않는다 — 그 차이 자체가 신호가 된다.
    assert client.get("/nothing-here").status_code == 401
    # 정본 경로는 그대로 200이다.
    assert client.get("/api/v1/health").status_code == 200


def _pyproject_version() -> str:
    """테스트가 독립적으로 읽은 pyproject 버전.

    구현과 같은 경로 계산을 쓰지 않는다 — 이 파일 기준으로 따로 찾아야 구현이
    경로를 잘못 잡았을 때 드러난다.
    """
    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def test_app_version_falls_back_to_pyproject(monkeypatch: pytest.MonkeyPatch) -> None:
    """dist metadata가 없으면 pyproject의 버전을 그대로 읽는다."""
    import cii_platform.api.routes.health as health_mod

    def _raise(_name: str) -> str:
        raise PackageNotFoundError("cii-platform")

    health_mod._app_version.cache_clear()
    try:
        monkeypatch.setattr(health_mod, "_pkg_version", _raise)
        # semver 정규식이 아니라 정확 비교 — 형태만 보면 하드코딩된 "0.0.0"도 통과한다.
        assert health_mod._app_version() == _pyproject_version()
    finally:
        health_mod._app_version.cache_clear()


def test_app_version_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """두 번 불러도 실제 조회는 한 번만 일어난다."""
    import cii_platform.api.routes.health as health_mod

    calls = 0

    def _counting(_name: str) -> str:
        nonlocal calls
        calls += 1
        return "9.9.9"

    health_mod._app_version.cache_clear()
    try:
        monkeypatch.setattr(health_mod, "_pkg_version", _counting)
        assert health_mod._app_version() == "9.9.9"
        assert health_mod._app_version() == "9.9.9"
        assert calls == 1
    finally:
        health_mod._app_version.cache_clear()


# --- rng_canonical_test (#400) -------------------------------------------------


def test_health_includes_rng_canonical_test(client: TestClient) -> None:
    """API_SPEC §10이 규정한 필드가 응답에 있다 (#400).

    ``#43`` 완료 전까지 생략되던 필드다. 유예가 해소되어 구현됐으므로, 다시
    빠지지 않도록 여기서 고정한다.
    """
    data = client.get("/api/v1/health").json()["data"]
    assert "rng_canonical_test" in data


def test_health_rng_canonical_test_passes_in_this_environment(client: TestClient) -> None:
    """이 환경에서 canonical vector가 재현된다.

    ``"failed"``가 나오면 NumPy 버전이나 플랫폼이 바뀐 것이며 재현성 계약
    (``TECH_SPEC §5.4``) 위반이다 — 그대로 두면 Monte Carlo 결과가 환경마다 달라진다.
    """
    data = client.get("/api/v1/health").json()["data"]
    assert data["rng_canonical_test"] == "passed"


def test_health_survives_rng_validation_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검증이 실패해도 health가 500이 되지 않고 status는 ok를 유지한다 (#400).

    **이 테스트가 이 필드 설계의 핵심을 고정한다.** 진단 필드 하나 때문에 health가
    500이 되면 오케스트레이터가 컨테이너를 죽인다 — 재현성 문제를 보고하려다
    가용성을 깎는다. 또 RNG 불일치는 재시작으로 해결되지 않으므로(NumPy 버전은
    이미지에 고정) ``status``를 내리면 무한 재시작 루프가 된다.
    """
    from cii_platform.api.routes import health as health_module

    def _boom() -> None:
        raise AssertionError("RNG mismatch at index 0")

    monkeypatch.setattr(health_module, "validate_rng", _boom)
    # 프로세스 캐시를 비워 patch가 반영되게 한다.
    health_module._rng_canonical_test.cache_clear()
    try:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["rng_canonical_test"] == "failed"
        # status는 liveness 신호다 — 재현성 실패로 내리지 않는다.
        assert data["status"] == "ok"
    finally:
        # 다른 테스트가 캐시된 "failed"를 보지 않게 되돌린다.
        health_module._rng_canonical_test.cache_clear()


def test_rng_canonical_test_is_cached_per_process() -> None:
    """프로세스당 1회만 계산한다 (#400).

    canonical vector는 NumPy 버전·플랫폼에서 결정되며 프로세스 수명 동안 바뀌지
    않는다. health는 로드 밸런서가 주기적으로 호출하므로 매 요청 난수를 뽑지 않는다.
    """
    from cii_platform.api.routes import health as health_module

    health_module._rng_canonical_test.cache_clear()
    calls = {"n": 0}
    original = health_module.validate_rng

    def _counting() -> None:
        calls["n"] += 1
        original()

    health_module.validate_rng = _counting  # type: ignore[assignment]
    try:
        health_module._rng_canonical_test()
        health_module._rng_canonical_test()
        health_module._rng_canonical_test()
        assert calls["n"] == 1
    finally:
        health_module.validate_rng = original  # type: ignore[assignment]
        health_module._rng_canonical_test.cache_clear()


# --- pdf_korean_font (#689) ----------------------------------------------------


def test_health_includes_pdf_korean_font(client: TestClient) -> None:
    """API_SPEC §10이 규정한 필드가 응답에 있다 (`#689`).

    이 필드가 없던 동안 **배포·시연 환경에서 폰트 부재를 볼 수단이 하나도 없었다.**
    PDF는 200으로 나가고 한글만 □가 되므로, 응답을 봐서는 알 수 없었다.
    """
    data = client.get("/api/v1/health").json()["data"]
    assert "pdf_korean_font" in data
    assert data["pdf_korean_font"] in {"ok", "missing", "unavailable"}


def test_health_survives_missing_korean_font(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """폰트가 없어도 health는 200이고 ``status``는 ``ok``를 유지한다 (`#689`).

    ``rng_canonical_test``와 같은 규약이다 (`#400`). 프로세스는 살아 있고 CSV·HTML
    리포트는 정상으로 나가므로 liveness를 내릴 이유가 없다. 내리면 오케스트레이터가
    컨테이너를 죽이는데, **재시작으로는 폰트가 생기지 않는다.**
    """
    from cii_platform.api.routes import health as health_module

    monkeypatch.setattr(health_module.pdf_module, "is_available", lambda: True)
    monkeypatch.setattr(health_module.pdf_module, "korean_font_available", lambda: False)
    health_module._pdf_korean_font.cache_clear()
    try:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["pdf_korean_font"] == "missing"
        assert data["status"] == "ok"
    finally:
        health_module._pdf_korean_font.cache_clear()


def test_pdf_korean_font_distinguishes_renderer_from_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """렌더러 부재와 폰트 부재를 한 값으로 뭉치지 않는다 (`#689`).

    둘은 **설치해야 할 것이 다르다** — 하나는 ``libpango``, 하나는 ``fonts-nanum``이다.
    같은 값으로 내면 이 필드를 보고도 무엇을 해야 하는지 알 수 없다.
    """
    from cii_platform.api.routes import health as health_module

    monkeypatch.setattr(health_module.pdf_module, "is_available", lambda: False)
    health_module._pdf_korean_font.cache_clear()
    try:
        assert health_module._pdf_korean_font() == "unavailable"
    finally:
        health_module._pdf_korean_font.cache_clear()


def test_pdf_korean_font_survives_a_probe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """판정이 예외를 던져도 health가 500이 되지 않는다 (`#689`).

    폰트 판정은 실제로 문서를 렌더링한다 — 렌더러가 깨진 환경에서 무엇이 튀어나올지
    보장할 수 없다. **진단 필드 하나 때문에 가용성을 깎지 않는다** (`#400`과 같은 판단).
    """
    from cii_platform.api.routes import health as health_module

    def _boom() -> bool:
        raise RuntimeError("Pango가 세그폴트로 죽었다")

    monkeypatch.setattr(health_module.pdf_module, "is_available", lambda: True)
    monkeypatch.setattr(health_module.pdf_module, "korean_font_available", _boom)
    health_module._pdf_korean_font.cache_clear()
    try:
        assert health_module._pdf_korean_font() == "unavailable"
    finally:
        health_module._pdf_korean_font.cache_clear()


def test_pdf_korean_font_is_cached_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """프로세스당 1회만 판정한다 (`#689`).

    판정에 프로브 문서 렌더링이 들어간다. health는 로드 밸런서가 주기적으로
    호출하므로, 캐시하지 않으면 **헬스 체크마다 PDF를 한 장씩 그린다.**
    """
    from cii_platform.api.routes import health as health_module

    calls = {"n": 0}

    def _counting() -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(health_module.pdf_module, "is_available", lambda: True)
    monkeypatch.setattr(health_module.pdf_module, "korean_font_available", _counting)
    health_module._pdf_korean_font.cache_clear()
    try:
        assert health_module._pdf_korean_font() == "ok"
        assert health_module._pdf_korean_font() == "ok"
        assert health_module._pdf_korean_font() == "ok"
        assert calls["n"] == 1
    finally:
        health_module._pdf_korean_font.cache_clear()
