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
    """명시적인 생명주기를 갖는 health 테스트 클라이언트."""
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
    # API_SPEC §1.1/§12: 정본 경로는 /api/v1/health. prefix 없는 /health는 없다.
    assert client.get("/health").status_code == 404


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
