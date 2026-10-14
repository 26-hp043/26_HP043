"""달력 끝의 시각이 **어느 HTTP 경로에서도 500이 아니라 422**다 (`#2474`).

``0001-01-01T00:00:00+09:00``·``9999-12-31T23:59:59-05:00``은 UTC로 옮기면 0년·10000년이라
``astimezone(UTC)``가 ``OverflowError``를 냈고, 그 예외는 검증 오류로 바뀌지 않아 오류
처리기가 500으로 돌렸다. 본문 시각(``Instant`` · 정박 구간)과 쿼리 ``as_of``(일곱 경로)가
같은 자리에서 터졌다.

DB 없는 쪽(스키마 · CSV 파서 · ``resolve_as_of``)은 ``test_calendar_edge_instants.py``가
본다. 여기서는 **실제 응답 상태 코드**만 본다 — 라우트·의존성·오류 처리기를 다 지나야
500인지 422인지가 정해진다. 이 파일은 고친 모듈을 import하지 않는다 — 고치기 전 코드에서
그대로 돌려 500을 확인할 수 있게 한다.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"

EDGES = [
    pytest.param("0001-01-01T00:00:00+09:00", id="0001년+09:00"),
    pytest.param("9999-12-31T23:59:59-05:00", id="9999년-05:00"),
    # `#2487` — UTC로는 옮겨지지만 한국 시간으로 옮기면 넘친다(연도 생략 쿼리가 500이었다)
    pytest.param("9999-12-31T15:00:00Z", id="9999년-KST로-넘침"),
]


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _seed() -> tuple[str, str]:
    """이 검사 전용 선박과 **완료된** 항차 한 건. IMO는 UNIQUE라 UUID에서 뽑는다.

    항차 리포트는 완료되지 않은 항차를 ``as_of``를 보기 전에 422로 거절한다 — 초안이면
    이 검사가 ``as_of``까지 닿지 못한 채 「422」로 지나간다(실제로 그랬다).
    """
    from cii_platform.db.session import get_sessionmaker

    vessel_id, voyage_id = uuid4(), uuid4()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                "default_fuel_type) VALUES (:id, :imo, 'EDGE TEST', 'BULK_CARRIER', "
                "50000, 'HFO')"
            ),
            {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
        )
        await s.execute(
            text(
                "INSERT INTO voyage (id, vessel_id, status, departure_port_name, "
                "arrival_port_name, planned_distance_nm, planned_speed_kn, "
                "annual_inclusion_policy, created_from) "
                "VALUES (:id, :v, 'COMPLETED', 'Busan', 'Singapore', 3000, 14, "
                "'EXCLUDE', 'MANUAL')"
            ),
            {"id": voyage_id, "v": vessel_id},
        )
        await s.commit()
    return str(vessel_id), str(voyage_id)


async def _cleanup(vessel_id: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    v = UUID(vessel_id)
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "DELETE FROM not_underway_fuel_use WHERE period_id IN "
                "(SELECT id FROM not_underway_period WHERE vessel_id = :v)"
            ),
            {"v": v},
        )
        await s.execute(text("DELETE FROM not_underway_period WHERE vessel_id = :v"), {"v": v})
        await s.execute(
            text(
                "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
                "(SELECT id FROM voyage WHERE vessel_id = :v)"
            ),
            {"v": v},
        )
        await s.execute(text("DELETE FROM voyage WHERE vessel_id = :v"), {"v": v})
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": v})
        await s.commit()


#: 쿼리 ``as_of``를 받는 GET 경로 전부 — ``API_SPEC``의 ``as_of`` 계약을 쓰는 자리.
_AS_OF_PATHS = [
    "/api/v1/fleet/summary",
    "/api/v1/fleet/notifications",
    "/api/v1/vessels/{vessel}/cii-history",
    "/api/v1/vessels/{vessel}/cii/current",
    "/api/v1/vessels/{vessel}/cii/ytd-series",
    "/api/v1/voyages/{voyage}/report",
    "/api/v1/vessels/{vessel}/annual-report",
]


@pytest.mark.parametrize("raw", EDGES)
async def test_calendar_edge_instants_are_422_on_every_path(migrated_db, app_fresh_engine, raw):
    vessel_id, voyage_id = await _seed()
    try:
        # 서버 예외를 그대로 올리지 않게 한다 — 운영처럼 상태 코드로 본다.
        with TestClient(app, base_url=_BASE, raise_server_exceptions=False) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            headers = _csrf(client)
            seen: dict[str, object] = {}

            def code_of(resp) -> object:
                """422면 그 이유가 이 시각인지까지 본다 — 다른 검증(초안 항차 등)으로 난
                422가 섞이면 「500이 아니다」만 보고 지나간다. 문구는 정본 문구가 아니라
                성질(범위를 벗어난다)로 본다(`AGENTS §4.6`)."""
                if resp.status_code != 422:
                    return resp.status_code
                return 422 if "9999-12-30까지만" in resp.text else ("다른 422", resp.text[:200])

            nu_base = f"/api/v1/vessels/{vessel_id}/not-underway-periods"
            seen["정박 생성"] = code_of(
                client.post(
                    nu_base,
                    json={
                        "period_type": "AT_ANCHOR",
                        "started_at": raw,
                        "port_name": "Busan",
                        "distance_nm": "0",
                        "fuel_uses": [],
                    },
                    headers=headers,
                )
            )

            created = client.post(
                nu_base,
                json={
                    "period_type": "AT_ANCHOR",
                    "started_at": "2026-08-10T00:00:00Z",
                    "ended_at": "2026-08-12T00:00:00Z",
                    "port_name": "Busan",
                    "distance_nm": "0",
                    "fuel_uses": [],
                },
                headers=headers,
            )
            assert created.status_code == 201, created.text
            seen["정박 수정"] = code_of(
                client.patch(
                    f"/api/v1/not-underway-periods/{created.json()['data']['id']}",
                    json={"ended_at": raw},
                    headers=headers,
                )
            )

            seen["항차 생성"] = code_of(
                client.post(
                    f"/api/v1/vessels/{vessel_id}/voyages",
                    json={
                        "voyage_no": "V-EDGE",
                        "departure_port_name": "Busan",
                        "arrival_port_name": "Singapore",
                        "planned_distance_nm": "3000",
                        "planned_speed_kn": "14",
                        "planned_departure_at": raw,
                        "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": "100"}],
                    },
                    headers=headers,
                )
            )

            seen["연간 시뮬레이션"] = code_of(
                client.post(
                    "/api/v1/annual-simulations",
                    json={
                        "vessel_id": vessel_id,
                        "regulation_year": 2026,
                        "target_rating": "C",
                        "as_of": raw,
                    },
                    headers=headers,
                )
            )

            for path in _AS_OF_PATHS:
                url = path.format(vessel=vessel_id, voyage=voyage_id)
                seen[path] = code_of(client.get(url, params={"as_of": raw}))

        # 한 경로라도 500이면 어느 경로인지 한 번에 보이게 모아서 단언한다.
        assert all(code == 422 for code in seen.values()), seen
    finally:
        await _cleanup(vessel_id)


@pytest.mark.parametrize("offset", ["+23:59", "-13:00"])
async def test_not_underway_offsets_out_of_range_are_422(migrated_db, app_fresh_engine, offset):
    """정박 생성 본문 · 목록 쿼리의 범위 밖 오프셋이 500이 아니라 422다 (`#2503`)."""
    vessel_id, _ = await _seed()
    try:
        with TestClient(app, base_url=_BASE, raise_server_exceptions=False) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            base = f"/api/v1/vessels/{vessel_id}/not-underway-periods"
            created = client.post(
                base,
                json={
                    "period_type": "AT_ANCHOR",
                    "started_at": f"2026-08-10T00:00:00{offset}",
                    "port_name": "Busan",
                    "distance_nm": "0",
                    "fuel_uses": [],
                },
                headers=_csrf(client),
            )
            listed = client.get(base, params={"started_from": f"2026-08-10T00:00:00{offset}"})
        assert created.status_code == 422, created.text
        assert created.json()["error"]["details"][0]["field"] == "started_at"
        # 쿼리 필터는 같은 순간의 UTC로 맞춰 거른다 — 오프셋이 달라도 오류가 아니다.
        assert listed.status_code == 200, listed.text
    finally:
        await _cleanup(vessel_id)
