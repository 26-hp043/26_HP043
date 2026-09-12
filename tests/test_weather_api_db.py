"""기상 스냅샷 조회 API (``API_SPEC §9.1`` · `#767`).

`#591`이 2026-08-23에 이 절을 유예했다 — *「누가 부를 수 있는지를 먼저 정해야 하고, 그것은
어드민 범위에 걸린다」*. `#808`이 「사내 도구 · 로그인 사용자 공유」로 확정하면서 그 전제가
사라져 **조회만** 열었다. 수동 갱신(`§9.2`)은 **열지 않는다** — 사용자가 외부 API 호출을
직접 일으키는 유일한 경로이기 때문이고, 그 판정은 `API_SPEC §9.2`가 적고 있다.

여기서 보는 것 넷이다.

1. **저장된 것을 그대로 보여 준다** — 격자 반올림으로 찾고, 응답 모양이 `§9.1` 그대로인가
2. **신선도** — 6시간·24시간 경계에서 `FRESH`·`STALE`·`EXPIRED`가 갈리는가
3. **만료된 값도 돌려주는가** — 이 엔드포인트는 「계산에 쓸 값」이 아니라 「저장된 것」을
   보여 준다. 계산이 왜 보정 없이 돌았는지 설명하려면 그 값이 거기 있다는 사실이 답이다
4. **열지 않은 것은 정말 없는가** — `POST /weather/refresh`가 404인가

케이스: AT-WX-001 ~ AT-WX-007 (`TEST_PLAN §4.10`)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.db.repositories import weather as weather_repo
from cii_platform.services.weather import round_to_grid

#: 데모 데이터와 겹치지 않는 좌표. 격자 반올림 뒤에도 고유하다.
LAT, LON = Decimal("-21.37"), Decimal("57.53")
#: 이 파일이 심는 행의 표식. 정리할 때 **이것만** 지운다.
SOURCE = "test_weather_api"


@pytest_asyncio.fixture
async def seeded(migrated_db, app_fresh_engine):
    """앱과 **같은 엔진**으로 심는다.

    ``conn`` 픽스처의 세션은 롤백되는 트랜잭션 안이라 ``TestClient``(다른 연결)에서는
    보이지 않는다 — 처음에 그렇게 짰다가 셋이 404를 받았다. 끝나고 **이 파일이 심은
    행만** 지운다(``source``로 고른다).
    """
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()

    async def seed(*, age_hours: float, lat: Decimal = LAT, lon: Decimal = LON):
        async with sessionmaker() as db:
            await weather_repo.insert_snapshot(
                db,
                lat=lat,
                lon=lon,
                lat_rounded=round_to_grid(lat),
                lon_rounded=round_to_grid(lon),
                fetched_at=datetime.now(UTC) - timedelta(hours=age_hours),
                wave_height_m=Decimal("2.50"),
                wave_direction_deg=Decimal("45"),
                wave_period_s=Decimal("7.0"),
                wind_speed_ms=Decimal("8.40"),
                wind_direction_deg=Decimal("90"),
                source=SOURCE,
            )
            await db.commit()

    yield seed

    async with sessionmaker() as db:
        await db.execute(text("DELETE FROM weather_snapshot WHERE source = :s"), {"s": SOURCE})
        await db.commit()


def _client(client: TestClient) -> TestClient:
    client.post(f"{API_V1_PREFIX}/auth/dev-login", json={})
    return client


async def test_snapshot_is_returned_in_the_spec_shape(seeded):
    """AT-WX-001 — `§9.1` 응답 모양. 저장한 값이 그대로 나온다."""
    await seeded(age_hours=1.0)

    with TestClient(app, base_url="https://testserver") as client:
        _client(client)
        resp = client.get(
            f"{API_V1_PREFIX}/weather/snapshot", params={"lat": float(LAT), "lon": float(LON)}
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["wave_height_m"] == 2.5
    assert data["wind_speed_ms"] == 8.4
    assert data["source"] == SOURCE
    assert data["freshness"] == "FRESH"
    assert 0.9 < data["age_hours"] < 1.2
    # `§9.1` 예시의 키가 빠짐없이 있는가 — 화면이 없는 필드를 읽으면 조용히 undefined다.
    assert set(data) == {
        "lat",
        "lon",
        "fetched_at",
        "wave_height_m",
        "wave_direction_deg",
        "wave_period_s",
        "wind_speed_ms",
        "wind_direction_deg",
        "source",
        "age_hours",
        "freshness",
    }


async def test_freshness_follows_the_same_hours_as_the_fallback_chain(seeded):
    """AT-WX-002 — 6시간·24시간 경계 (`PRD §11.6`과 같은 값)."""
    cases = [(3.0, "FRESH"), (12.0, "STALE"), (30.0, "EXPIRED")]
    for offset, (age, expected) in enumerate(cases):
        lat = LAT + Decimal(offset)
        await seeded(age_hours=age, lat=lat)

        with TestClient(app, base_url="https://testserver") as client:
            _client(client)
            resp = client.get(
                f"{API_V1_PREFIX}/weather/snapshot", params={"lat": float(lat), "lon": float(LON)}
            )

        assert resp.json()["data"]["freshness"] == expected, (age, resp.text)


async def test_expired_snapshot_is_still_returned(seeded):
    """AT-WX-003 — 만료돼도 돌려준다. 「없다」와 「낡았다」는 다른 답이다."""
    await seeded(age_hours=48.0)

    with TestClient(app, base_url="https://testserver") as client:
        _client(client)
        resp = client.get(
            f"{API_V1_PREFIX}/weather/snapshot", params={"lat": float(LAT), "lon": float(LON)}
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["freshness"] == "EXPIRED"


async def test_missing_snapshot_is_404(migrated_db, app_fresh_engine):
    """AT-WX-004 — 저장된 것이 없으면 404다(빈 값을 지어내지 않는다)."""
    with TestClient(app, base_url="https://testserver") as client:
        _client(client)
        resp = client.get(f"{API_V1_PREFIX}/weather/snapshot", params={"lat": 11.5, "lon": -170.5})

    assert resp.status_code == 404, resp.text
    assert "기상" in resp.json()["error"]["message"]


async def test_manual_refresh_is_not_open(migrated_db, app_fresh_engine):
    """AT-WX-005 — `§9.2`는 열지 않았다. 라우트가 **정말 없어야** 한다."""
    with TestClient(app, base_url="https://testserver") as client:
        _client(client)
        resp = client.post(
            f"{API_V1_PREFIX}/weather/refresh", params={"lat": float(LAT), "lon": float(LON)}
        )

    assert resp.status_code == 404, resp.text


async def test_unauthenticated_request_is_rejected(migrated_db, app_fresh_engine):
    """AT-WX-006 — 로그인 경계. 내부용이라 미인증에게 열지 않는다."""
    with TestClient(app, base_url="https://testserver") as client:
        resp = client.get(
            f"{API_V1_PREFIX}/weather/snapshot", params={"lat": float(LAT), "lon": float(LON)}
        )

    assert resp.status_code == 401, resp.text


async def test_out_of_range_coordinates_are_422(migrated_db, app_fresh_engine):
    """AT-WX-007 — VAL-007 좌표 범위. 문구는 한국어다(`#900`)."""
    with TestClient(app, base_url="https://testserver") as client:
        _client(client)
        resp = client.get(f"{API_V1_PREFIX}/weather/snapshot", params={"lat": 95, "lon": 0})

    assert resp.status_code == 422, resp.text
    detail = resp.json()["error"]["details"][0]
    assert detail["field_label"] == "위도"
