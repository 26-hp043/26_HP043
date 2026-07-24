"""Health check 엔드포인트 계약 테스트 (#49).

API_SPEC §10(응답 형식)·§12(경로)·§1.1(prefix)을 CI가 지키도록 고정한다.
DB에 의존하지 않는다.
"""

import re

import numpy
from fastapi.testclient import TestClient

from cii_platform.api.main import app

client = TestClient(app)


def test_health_returns_200_and_data_envelope() -> None:
    # API_SPEC §10: {"data": {...}} 형태.
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert data["status"] == "ok"
    assert data["numpy_version"] == numpy.__version__
    # version은 semver 꼴이어야 한다. importlib.metadata 값과 대조하면 구현을
    # 되풀이하는 동어반복이라, 형태를 검증해 "unknown" 폴백(패키지명 불일치·설치
    # 형태 변화)을 CI가 잡도록 한다. _app_version()의 조용한 실패 방지.
    assert re.match(r"^\d+\.\d+", data["version"]), data["version"]


def test_health_has_no_meta_block() -> None:
    # API_SPEC §10 응답은 §1.3.1의 meta(request_id/timestamp)를 요구하지 않는다.
    body = client.get("/api/v1/health").json()
    assert "meta" not in body


def test_health_omits_rng_canonical_test_until_issue_43() -> None:
    # D7: PCG64DXSM canonical vector 검증(#43) 미구현이라 거짓 "passed" 대신 생략.
    data = client.get("/api/v1/health").json()["data"]
    assert "rng_canonical_test" not in data


def test_bare_health_path_is_not_exposed() -> None:
    # API_SPEC §1.1/§12: 정본 경로는 /api/v1/health. prefix 없는 /health는 없다.
    assert client.get("/health").status_code == 404
