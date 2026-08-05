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


def test_health_omits_rng_canonical_test_until_issue_43(client: TestClient) -> None:
    # D7: PCG64DXSM canonical vector 검증(#43) 미구현이라 거짓 "passed" 대신 생략.
    data = client.get("/api/v1/health").json()["data"]
    assert "rng_canonical_test" not in data


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
