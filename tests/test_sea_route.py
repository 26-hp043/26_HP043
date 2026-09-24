"""공개 해상 경로망 위의 바닷길 (`#1300` · `API_SPEC §3.11` · `PRD §5.2`) — **DB 없이 돈다.**

`searoute`가 번들한 Eurostat 경로망을 실제로 읽는다(첫 호출에 그래프를 올려 수 초 걸린다).
여기서 잠그는 것은 넷이다.

1. **선의 양 끝이 입력 좌표 그대로다** — 붙이지 않으면 마커와 선 끝이 떨어져 보인다
2. **길이가 대권거리보다 짧지 않다** — 육지를 돌아가는 선이 최단 경로보다 짧으면 지어낸 선이다
3. **경유지를 지난다** — 우회 선은 「출발 → 경유지 → 목적항」이다
4. **날짜변경선에서 되돌아가지 않는다** — 이음새를 포함해 이웃한 점의 경도 차가 180° 안이다

계산 거리(`§3.9`)는 건드리지 않는다 — 이 선은 표시용이다(`TECH_SPEC §5.4`).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fakes import FAKE_SESSION_TOKEN, install_fake_auth
from fastapi.testclient import TestClient

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.calc.distance import great_circle_distance_nm
from cii_platform.services import sea_route as sea_route_mod
from cii_platform.services.sea_route import (
    SOURCE,
    SeaRouteNotFoundError,
    sea_route_line,
    serialize_line,
    warm_up,
)

BUSAN = (Decimal("35.1"), Decimal("129.0333"))
SINGAPORE = (Decimal("1.2833"), Decimal("103.85"))
ROTTERDAM = (Decimal("51.9244"), Decimal("4.4778"))
LOS_ANGELES = (Decimal("33.7"), Decimal("-118.2"))
HONOLULU = (Decimal("21.3"), Decimal("-157.87"))


def _lon_steps(coords) -> list[float]:
    return [b[0] - a[0] for a, b in zip(coords[:-1], coords[1:], strict=True)]


def test_line_starts_and_ends_at_the_inputs():
    line = sea_route_line([BUSAN, SINGAPORE])

    assert line.legs == 1
    assert len(line.coordinates) > 2, "경로망을 지났다면 양 끝 사이에 노드가 있다"
    assert line.coordinates[0] == (float(BUSAN[1]), float(BUSAN[0]))
    assert line.coordinates[-1] == (float(SINGAPORE[1]), float(SINGAPORE[0]))


def test_length_is_not_shorter_than_the_great_circle():
    line = sea_route_line([BUSAN, ROTTERDAM])
    gc = great_circle_distance_nm(*BUSAN, *ROTTERDAM)

    # 수에즈를 도는 길이 유라시아를 가로지르는 최단 경로보다 짧을 수 없다.
    assert line.length_nm > gc
    assert line.length_nm == line.length_nm.quantize(Decimal("0.01"))


def test_same_line_twice():
    """경로망·알고리즘이 고정이라 같은 입력은 같은 선이다 — 캐시 유무와 무관하게."""
    assert sea_route_line([BUSAN, SINGAPORE]) == sea_route_line([BUSAN, SINGAPORE])


def test_same_point_is_a_single_point_not_a_detour():
    """라이브러리는 같은 점도 가까운 노드까지 갔다 오는 선(≈20nm)을 낸다 — 그것은 항로가 아니다."""
    line = sea_route_line([BUSAN, BUSAN])

    assert line.coordinates == ((float(BUSAN[1]), float(BUSAN[0])),)
    assert line.length_nm == Decimal("0.00")


def test_waypoint_line_passes_through_the_waypoint_and_sums_the_legs():
    direct = sea_route_line([BUSAN, ROTTERDAM])
    via = sea_route_line([BUSAN, SINGAPORE, ROTTERDAM])

    assert via.legs == 2
    assert (float(SINGAPORE[1]), float(SINGAPORE[0])) in via.coordinates
    assert via.coordinates[0] == direct.coordinates[0]
    assert via.coordinates[-1] == direct.coordinates[-1]
    first = sea_route_line([BUSAN, SINGAPORE])
    second = sea_route_line([SINGAPORE, ROTTERDAM])
    assert via.length_nm == first.length_nm + second.length_nm
    # 이음새의 점 하나가 겹치므로 둘의 합에서 하나가 빠진다.
    assert len(via.coordinates) == len(first.coordinates) + len(second.coordinates) - 1


def test_crossing_the_date_line_does_not_turn_back():
    """부산 → 로스앤젤레스는 태평양을 건넌다 — 경도가 180을 넘어 이어진다(MapLibre가 허용한다)."""
    line = sea_route_line([BUSAN, LOS_ANGELES])

    assert all(abs(step) < 180 for step in _lon_steps(line.coordinates))
    assert max(lon for lon, _ in line.coordinates) > 180


def test_joining_legs_across_the_date_line_keeps_the_same_copy():
    """구간 둘을 이을 때 두 번째 구간이 원래 경도(`-157`)로 돌아가면 지구를 한 바퀴 되돌아간다."""
    line = sea_route_line([BUSAN, HONOLULU, LOS_ANGELES])

    assert all(abs(step) < 180 for step in _lon_steps(line.coordinates))
    assert (float(HONOLULU[1]) + 360.0, float(HONOLULU[0])) in line.coordinates


def test_no_path_is_a_failure_not_a_straight_line(monkeypatch):
    """라이브러리는 경로가 없으면 **경고 + 두 점 직선**이다 — 직선은 바닷길이 아니라 실패다."""
    import warnings

    import searoute
    from geojson import Feature, LineString

    def fake_searoute(origin, destination, **_kwargs):
        # `utils.raise_warn_no_path`와 같은 방식 — 경고를 내고 직선을 돌려준다.
        warnings.warn("No path found between the points", UserWarning, stacklevel=2)
        return Feature(
            geometry=LineString([origin, destination]),
            properties={"length": 1.0, "units": "naut", "duration_hours": 0.0},
        )

    monkeypatch.setattr(searoute, "searoute", fake_searoute)
    sea_route_mod._leg.cache_clear()
    try:
        with pytest.raises(SeaRouteNotFoundError):
            sea_route_line(
                [(Decimal("70.5"), Decimal("-100.5")), (Decimal("70.5"), Decimal("20.5"))]
            )
    finally:
        sea_route_mod._leg.cache_clear()


def test_warm_up_loads_once_and_never_raises(monkeypatch):
    """기동 워밍은 실패해도 예외를 내지 않는다 — 기동을 막을 이유가 아니다."""
    assert warm_up() is True

    import searoute

    def broken():
        raise RuntimeError("데이터 파일이 없다")

    monkeypatch.setattr(searoute, "setup_M", broken)
    assert warm_up() is False


def test_too_few_points_is_an_error():
    with pytest.raises(ValueError):
        sea_route_line([BUSAN])


def test_serialized_shape():
    body = serialize_line(sea_route_line([BUSAN, SINGAPORE]))

    assert set(body) == {"coordinates", "length_nm", "legs", "source"}
    assert body["source"] == SOURCE
    assert isinstance(body["length_nm"], float)
    assert all(len(pair) == 2 for pair in body["coordinates"])


# --- API -----------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from cii_platform.auth.session import SESSION_COOKIE_NAME

    install_fake_auth(monkeypatch)
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE_NAME, FAKE_SESSION_TOKEN)
        yield c


ENDPOINT = f"{API_V1_PREFIX}/ports/sea-route"
QUERY = {"from_lat": "35.1", "from_lon": "129.0333", "to_lat": "1.2833", "to_lon": "103.85"}


def test_endpoint_returns_the_line(client):
    resp = client.get(ENDPOINT, params=QUERY)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data == serialize_line(sea_route_line([BUSAN, SINGAPORE]))
    assert data["legs"] == 1


def test_endpoint_with_a_waypoint(client):
    resp = client.get(ENDPOINT, params={**QUERY, "via_lat": "21.3", "via_lon": "-157.87"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["legs"] == 2


def test_endpoint_rejects_half_a_waypoint_in_korean(client):
    resp = client.get(ENDPOINT, params={**QUERY, "via_lat": "21.3"})

    assert resp.status_code == 422
    detail = resp.json()["error"]["details"][0]
    assert detail["field"] == "via_lon"
    assert "함께" in resp.json()["error"]["message"]


def test_endpoint_rejects_out_of_range_coordinates_in_korean(client):
    """VAL-007 — `§3.9`와 같은 문구 규칙(`API_SPEC §1.3.2`)."""
    resp = client.get(ENDPOINT, params={**QUERY, "via_lat": "0", "via_lon": "181"})

    assert resp.status_code == 422
    detail = resp.json()["error"]["details"][0]
    assert detail["field"] == "via_lon"
    assert detail["message"] == "경유지 경도는 180 이하여야 합니다."


def test_endpoint_returns_404_when_the_network_has_no_path(client, monkeypatch):
    """`§3.10`과 같은 갈래 — 찾지 못한 것은 404이고 직선을 내보내지 않는다."""

    async def no_path(_points):
        raise SeaRouteNotFoundError("막혔다")

    from cii_platform.api.routes import ports as ports_routes

    monkeypatch.setattr(ports_routes, "sea_route_line_async", no_path)
    resp = client.get(ENDPOINT, params=QUERY)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"
    assert "바닷길" in resp.json()["error"]["message"]


def test_endpoint_needs_a_session(client):
    client.cookies.clear()
    assert client.get(ENDPOINT, params=QUERY).status_code == 401
