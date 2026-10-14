"""NUL 문자 입력은 500이 아니라 422로 거절된다 (``#2501``).

DB 드라이버(pycubrid)는 NUL이 든 문자열 파라미터를 ``ProgrammingError``로 거부한다.
종전에는 어디서도 잡지 않아 **비로그인 로그인·가입을 포함한 모든 문자열 입력이 500**이었다.
고치는 자리는 필드가 아니라 요청이 라우트에 닿기 전 한 곳이다(``api/nul_guard.py``) — 그래서
이 검사도 **대표 경로**로 그 한 자리가 닫혔음을 본다. CSV 셀은 본문이 JSON이 아니므로
각 import 파서가 행 오류로 돌린다.

``TestClient``는 실제로 커밋하지만 이 검사는 NUL을 거절하는 경로만 두드려 **데이터를
남기지 않는다**(선박 생성도 422로 끝난다).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.api.nul_guard import NUL_MESSAGE

_BASE = "https://testserver"
_V1 = "/api/v1"


def _assert_nul_422(response, *, field: str | None = None) -> None:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == NUL_MESSAGE
    assert response.json()["meta"]["request_id"]
    if field is not None:
        assert error["details"][0]["field"] == field


@pytest.fixture
def anon(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as client:
        yield client


@pytest.fixture
def client(anon):
    assert anon.post(f"{_V1}/auth/dev-login", json={}).status_code == 200
    anon.headers["X-CSRF-Token"] = anon.cookies.get("csrf", "")
    return anon


def test_비로그인_로그인의_이메일_NUL(anon):
    _assert_nul_422(
        anon.post(f"{_V1}/auth/login", json={"email": "a\x00b@example.com", "password": "x"}),
        field="email",
    )


@pytest.mark.parametrize(
    "content_type",
    ["application/problem+json", "application/vnd.api+json", "Application/JSON; charset=utf-8"],
)
def test_json_계열_미디어_타입도_가드를_지난다(anon, content_type):
    """`+json` 계열은 FastAPI가 JSON으로 읽는다 — 접두사만 보면 가드를 우회해 500이었다."""
    import json as _json

    _assert_nul_422(
        anon.post(
            f"{_V1}/auth/login",
            content=_json.dumps({"email": "a\x00b@example.com", "password": "x"}),
            headers={"content-type": content_type},
        ),
        field="email",
    )


def test_지나치게_깊은_중첩은_가드가_아니라_검증기가_맡는다(anon):
    """NUL이 든 아주 깊은 본문에서 `RecursionError`로 500이 나지 않는다."""
    body = "[" * 100_000 + '"\\u0000"' + "]" * 100_000
    resp = anon.post(
        f"{_V1}/auth/login", content=body, headers={"content-type": "application/json"}
    )
    assert resp.status_code != 500, resp.text


def test_비로그인_가입의_이메일_NUL(anon):
    _assert_nul_422(
        anon.post(
            f"{_V1}/auth/signup", json={"email": "a\x00b@example.com", "password": "Passw0rd!xyz"}
        ),
        field="email",
    )


def test_쿼리_문자열의_NUL(client):
    _assert_nul_422(client.get(f"{_V1}/vessels?search=%00"), field="search")
    _assert_nul_422(client.get(f"{_V1}/vessels", params={"search": "a\x00b"}), field="search")


def test_선박_생성_본문의_NUL은_경로를_가리킨다(client):
    body = {
        "imo_number": "9074729",
        "name": "A\x00B",
        "ship_type": "BULK_CARRIER",
        "gross_tonnage": "30000",
        "deadweight": "50000",
        "default_fuel_type": "HFO",
    }
    _assert_nul_422(client.post(f"{_V1}/vessels", json=body), field="name")


def test_중첩_배열_안의_NUL(client):
    body = {"fuel_uses": [{"fuel_type": "H\x00FO", "fuel_ton": "1"}]}
    _assert_nul_422(
        client.post(f"{_V1}/calculations/voyage-cii", json=body),
        field="fuel_uses[0].fuel_type",
    )


def test_NUL_없는_요청은_그대로_지나간다(client):
    assert client.get(f"{_V1}/vessels", params={"search": "없는이름"}).status_code == 200
    # 파싱할 수 없는 JSON은 이 미들웨어가 아니라 기존 검증기가 다룬다.
    response = client.post(
        f"{_V1}/vessels", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"] != NUL_MESSAGE


def test_이스케이프된_역슬래시는_NUL이_아니다(anon):
    """``\\\\u0000``(역슬래시 + 글자)은 NUL이 아니다 — 본문 문자열 검색으로 오탐하지 않는다."""
    response = anon.post(
        f"{_V1}/auth/login", json={"email": "a\\u0000b@example.com", "password": "x"}
    )
    assert response.status_code != 500
    assert response.json()["error"]["message"] != NUL_MESSAGE


def test_인증_없는_보호_경로는_NUL보다_401이_먼저다(anon):
    assert anon.get(f"{_V1}/vessels?search=%00").status_code == 401


_HEADER = (
    "voyage_no,departure_port_name,arrival_port_name,planned_distance_nm,planned_speed_kn,"
    "fuel_type,planned_fuel_ton,planned_departure_at,planned_arrival_at\n"
)


def test_항차_CSV_셀의_NUL은_행_오류(client):
    vessels = client.get(f"{_V1}/vessels").json()["data"]
    vessel_id = vessels[0]["id"]
    body = (
        _HEADER
        + "V\x001,Busan,Singapore,3000,14,HFO,100,2026-09-01T00:00:00Z,2026-09-10T00:00:00Z\n"
    )
    response = client.post(
        f"{_V1}/vessels/{vessel_id}/import",
        params={"dry_run": "true"},
        data={"type": "voyages"},
        files={"file": ("a.csv", body.encode(), "text/csv")},
    )
    assert response.status_code != 500, response.text
    errors = response.json()["data"]["errors"]
    assert errors
    assert errors[0]["row"] == 2
    assert "NUL" in errors[0]["message"]
