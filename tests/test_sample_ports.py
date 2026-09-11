"""샘플 항만 · 좌표 기반 추정 거리 (API_SPEC §3.8 · §3.9 · #760 · `PRD §15.1` · `§15.2`).

`PRD §15.1`이 MUST로 둔 「샘플 항만 테이블」이 없어, 시연 참석자가 첫 항차를 넣을 때
항만 좌표를 직접 찾아 넣어야 했다. 여기서 잠그는 것은 셋이다.

1. **데모 항로의 항만이 전부 목록에 있다** — 시연에서 쓰는 항로를 목록에서 고를 수 없으면
   목록을 둔 의미가 없다. 시드에 항만이 늘면 여기서 드러난다
2. **값이 원본(WPI)에서 온 그대로다** — 몇 곳을 원본 표기(도·분)로 고정한다. 누가 손으로
   고치면 원본과 갈라진 것이 드러난다
3. **추정 거리는 기능②와 같은 식이다** — 식이 두 벌이 되면 한쪽만 고쳐진다
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.calc.distance import great_circle_distance_nm
from cii_platform.db.demo_seed import SEED_VOYAGES, SEED_VOYAGES_WATCH
from cii_platform.services.sample_ports import (
    METHOD_GREAT_CIRCLE,
    SAMPLE_PORTS,
    estimate_distance,
    list_sample_ports,
)


def _dm(degrees: int, minutes: int, hemisphere: str) -> Decimal:
    """WPI 원본 표기(도·분)를 소수 4자리로 — 서비스가 옮긴 방식과 같다."""
    value = Decimal(degrees) + Decimal(minutes) / Decimal(60)
    value = value.quantize(Decimal("0.0001"))
    return -value if hemisphere in ("S", "W") else value


def test_every_demo_voyage_port_is_in_the_list():
    names = {p.name for p in SAMPLE_PORTS}
    used = {
        str(v[key])
        for v in (*SEED_VOYAGES, *SEED_VOYAGES_WATCH)
        for key in ("departure_port_name", "arrival_port_name")
    }
    assert used, "사전 조건: 데모 항차가 항만명을 가진다"
    assert used <= names, f"데모 항로인데 목록에 없는 항만: {sorted(used - names)}"


def test_rows_are_unique_and_in_range():
    assert len({p.name for p in SAMPLE_PORTS}) == len(SAMPLE_PORTS)
    assert len({p.locode for p in SAMPLE_PORTS}) == len(SAMPLE_PORTS)
    assert len({p.wpi_number for p in SAMPLE_PORTS}) == len(SAMPLE_PORTS)
    for p in SAMPLE_PORTS:
        assert -90 <= Decimal(p.lat) <= 90 and -180 <= Decimal(p.lon) <= 180, p
        assert p.name == p.name.upper() and p.name_ko, p


@pytest.mark.parametrize(
    ("name", "lat", "lon"),
    [
        # WPI(Pub. 150) 원본 표기 그대로 — 2026-09-12 조회
        ("BUSAN", _dm(35, 6, "N"), _dm(129, 2, "E")),  # #60390 35°06'00"N 129°02'00"E
        ("SINGAPORE", _dm(1, 17, "N"), _dm(103, 51, "E")),  # #50000 Keppel 1°17'N 103°51'E
        ("ROTTERDAM", _dm(51, 54, "N"), _dm(4, 29, "E")),  # #31140
        ("SANTOS", _dm(23, 57, "S"), _dm(46, 18, "W")),  # #12970 — 남·서반구 부호
    ],
)
def test_coordinates_match_the_source(name, lat, lon):
    port = next(p for p in SAMPLE_PORTS if p.name == name)
    assert (Decimal(port.lat), Decimal(port.lon)) == (lat, lon)


def test_estimate_uses_the_same_formula_as_route_comparison():
    busan = next(p for p in SAMPLE_PORTS if p.name == "BUSAN")
    singapore = next(p for p in SAMPLE_PORTS if p.name == "SINGAPORE")
    args = (Decimal(busan.lat), Decimal(busan.lon), Decimal(singapore.lat), Decimal(singapore.lon))

    result = estimate_distance(*args)

    assert result == {
        "distance_nm": float(great_circle_distance_nm(*args)),
        "method": METHOD_GREAT_CIRCLE,
    }
    # 부산–싱가포르 대권거리는 2,500해리 안팎이다 — 식이 아니라 단위가 틀리면 여기서 드러난다.
    assert 2_300 < result["distance_nm"] < 2_700


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url="https://testserver") as c:
        c.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
        yield c


def test_list_endpoint_returns_the_list(client):
    resp = client.get(f"{API_V1_PREFIX}/ports/samples")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data == list_sample_ports()
    assert set(data[0]) == {"locode", "name", "name_ko", "country_code", "lat", "lon"}
    assert isinstance(data[0]["lat"], float), "좌표는 CRUD 층 수치라 JSON 숫자다(§1.7)"


def test_distance_endpoint(client):
    resp = client.get(
        f"{API_V1_PREFIX}/ports/great-circle",
        params={"from_lat": "35.1", "from_lon": "129.0333", "to_lat": "1.2833", "to_lon": "103.85"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["method"] == "GREAT_CIRCLE"
    assert body["distance_nm"] == float(
        great_circle_distance_nm(
            Decimal("35.1"), Decimal("129.0333"), Decimal("1.2833"), Decimal("103.85")
        )
    )


def test_distance_endpoint_rejects_out_of_range_coordinates_in_korean(client):
    """VAL-007 — 범위 밖 좌표는 422. 문구는 한국어다(`API_SPEC §1.3.2` · #900)."""
    resp = client.get(
        f"{API_V1_PREFIX}/ports/great-circle",
        params={"from_lat": "95", "from_lon": "0", "to_lat": "0", "to_lon": "0"},
    )

    assert resp.status_code == 422
    detail = resp.json()["error"]["details"][0]
    assert detail["field"] == "from_lat"
    assert detail["message"] == "출발지 위도는 90 이하여야 합니다."


def test_list_route_is_not_mistaken_for_anything_else(client):
    """경로가 등록돼 있고 인증이 필요하다 — 비로그인은 401이다(목록도 인증 뒤에 둔다)."""
    client.cookies.clear()
    assert client.get(f"{API_V1_PREFIX}/ports/samples").status_code == 401
