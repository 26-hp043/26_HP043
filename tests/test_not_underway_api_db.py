"""not under way **쓰기 라우트 5종**의 HTTP 계약 (#828 ⑴).

## 왜 서비스 검사로는 부족한가

`test_not_underway_crud_db.py`가 쓰기 **규칙**(겹침·CF 스냅숏·소프트 삭제)을 이미
본다. 그런데 그 파일은 `services/not_underway.py`의 함수를 **직접 부른다** — 라우트를
지나지 않는다. 그래서 다음 다섯 가지는 어느 검사도 보고 있지 않았다.

* **201 Created** — 서비스는 상태 코드를 만들지 않는다. `status_code=201`을 지워도
  서비스 검사는 전부 통과한다.
* **PATCH의 `exclude_unset`** — 이것이 가장 위험하다. 없으면 **본문에 적지 않은 필드가
  `None`으로 전달**되어, 한 칸만 고치려던 요청이 나머지를 지우려 든다.
* **예외 → 상태 코드** 대응(409·422·404). 서비스는 파이썬 예외를 올릴 뿐이다.
* **CSRF** — 다섯 라우트 전부 `require_csrf`를 걸고 있는데, 그것이 실제로 막는지는
  확인된 적이 없다.
* **봉투 모양** — `{"data": ..., "meta": ...}`.

## 데이터를 남기지 않는다

`TestClient`는 **실제로 커밋한다**(트랜잭션 롤백 픽스처를 쓰지 않는다). 그래서 전용
선박을 만들고 `finally`에서 지운다 — 남기면 다음 실행의 겹침 판정과 리포트 집계가
이 행들을 본다.

케이스: (`TEST_PLAN §14.5` 정의 없음 — `#370`에서 신설된 기능이다)
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"


def _csrf(client: TestClient) -> dict[str, str]:
    """상태 변경 요청의 CSRF 헤더. 서버가 검증하는 경로는 **헤더뿐**이다(`API_SPEC §1.2`)."""
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _seed_vessel() -> str:
    """이 검사 전용 선박. IMO는 UNIQUE라 UUID에서 뽑아 충돌을 피한다."""
    from cii_platform.db.session import get_sessionmaker

    vessel_id = uuid4()
    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO vessel (id, imo_number, name, ship_type, deadweight, "
                "default_fuel_type) VALUES (:id, :imo, 'NU API TEST', 'BULK_CARRIER', "
                "50000, 'HFO')"
            ),
            {"id": vessel_id, "imo": f"9{vessel_id.int % 1000000:06d}"},
        )
        await s.commit()
    return str(vessel_id)


async def _cleanup(vessel_id: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "DELETE FROM not_underway_fuel_use WHERE period_id IN "
                "(SELECT id FROM not_underway_period WHERE vessel_id = :v)"
            ),
            {"v": UUID(vessel_id)},
        )
        await s.execute(
            text("DELETE FROM not_underway_period WHERE vessel_id = :v"),
            {"v": UUID(vessel_id)},
        )
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": UUID(vessel_id)})
        await s.commit()


def _period_body(**over) -> dict:
    body = {
        "period_type": "AT_ANCHOR",
        "started_at": "2026-08-10T00:00:00Z",
        "ended_at": "2026-08-12T00:00:00Z",
        "port_name": "Busan",
        "distance_nm": "0",
        "fuel_uses": [],
    }
    body.update(over)
    return body


async def test_create_period_route_returns_201_with_envelope(migrated_db, app_fresh_engine):
    """생성은 **201**이고 봉투는 `data`·`meta`다 (`API_SPEC §2.10`).

    서비스 검사는 이 숫자를 볼 수 없다 — `status_code=201`을 지워도 전부 통과한다.
    """
    vessel_id = await _seed_vessel()
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            response = client.post(
                f"/api/v1/vessels/{vessel_id}/not-underway-periods",
                json=_period_body(
                    fuel_uses=[{"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "3"}]
                ),
                headers=_csrf(client),
            )
            assert response.status_code == 201, response.text
            body = response.json()
            assert set(body) == {"data", "meta"}
            # CF는 **서버가 뜬다** — 화면이 보내면 사용자가 배출계수를 정하게 된다(`PRD §8.4`).
            assert body["data"]["fuel_uses"][0]["cf_used"]
    finally:
        await _cleanup(vessel_id)


async def test_patch_leaves_unsent_fields_alone(migrated_db, app_fresh_engine):
    """**본문에 없는 필드는 건드리지 않는다** — `exclude_unset`의 몫이다.

    이 라우트의 주 용도가 「진행 중 구간의 종료 확정」이라 **종료 시각 한 칸만** 보내는
    요청이 정상이다. `exclude_unset`이 없으면 그 요청이 `port_name`·`distance_nm`까지
    `None`으로 실어 보내, 한 칸을 고치려던 사용자가 나머지를 지운다.

    서비스 검사로는 잡히지 않는다 — 그 층은 이미 풀린 인자를 받기 때문이다.
    """
    vessel_id = await _seed_vessel()
    try:
        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            created = client.post(
                f"/api/v1/vessels/{vessel_id}/not-underway-periods",
                json=_period_body(ended_at=None, port_name="Busan", distance_nm="12.5"),
                headers=_csrf(client),
            )
            assert created.status_code == 201, created.text
            period_id = created.json()["data"]["id"]

            patched = client.patch(
                f"/api/v1/not-underway-periods/{period_id}",
                json={"ended_at": "2026-08-11T00:00:00Z"},
                headers=_csrf(client),
            )
            assert patched.status_code == 200, patched.text
            data = patched.json()["data"]
            assert data["port_name"] == "Busan", "보내지 않은 칸이 지워졌다"
            # 이 칸은 입력 에코라 Layer 1 문자열이 아니다 — 응답이 숫자로 나온다.
            assert float(data["distance_nm"]) == 12.5, data["distance_nm"]
            assert data["period_type"] == "AT_ANCHOR"
    finally:
        await _cleanup(vessel_id)


async def test_overlap_is_409_and_bad_enum_is_422(migrated_db, app_fresh_engine):
    """예외가 **상태 코드로** 옮겨진다. 서비스는 파이썬 예외를 올릴 뿐이다.

    겹침을 500으로 내면 사용자는 고칠 수 있는 입력을 「서버 오류」로 본다.
    """
    vessel_id = await _seed_vessel()
    try:
        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            url = f"/api/v1/vessels/{vessel_id}/not-underway-periods"
            assert client.post(url, json=_period_body(), headers=_csrf(client)).status_code == 201

            overlap = client.post(
                url,
                json=_period_body(
                    started_at="2026-08-11T00:00:00Z", ended_at="2026-08-13T00:00:00Z"
                ),
                headers=_csrf(client),
            )
            assert overlap.status_code == 409, overlap.text
            assert overlap.json()["error"]["code"]

            bad_enum = client.post(
                url, json=_period_body(period_type="SUNBATHING"), headers=_csrf(client)
            )
            assert bad_enum.status_code == 422, bad_enum.text
    finally:
        await _cleanup(vessel_id)


async def test_unknown_period_is_404_on_every_write_route(migrated_db, app_fresh_engine):
    """없는 구간을 고치거나 지우면 404다 — 조용한 200이 아니다."""
    missing = uuid4()
    with TestClient(app, base_url=_BASE) as client:
        client.post("/api/v1/auth/dev-login")
        headers = _csrf(client)
        assert (
            client.patch(
                f"/api/v1/not-underway-periods/{missing}",
                json={"port_name": "Busan"},
                headers=headers,
            ).status_code
            == 404
        )
        assert (
            client.delete(f"/api/v1/not-underway-periods/{missing}", headers=headers).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/not-underway-periods/{missing}/fuel-uses",
                json={"consumer_type": "AUX_ENGINE", "fuel_type": "HFO", "fuel_ton": "1"},
                headers=headers,
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/v1/not-underway-periods/{missing}/fuel-uses/{uuid4()}",
                headers=headers,
            ).status_code
            == 404
        )


async def test_fuel_use_routes_add_and_delete(migrated_db, app_fresh_engine):
    """연료 기록 추가는 **201**, 삭제는 200이다 (`API_SPEC §2.13`)."""
    vessel_id = await _seed_vessel()
    try:
        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            created = client.post(
                f"/api/v1/vessels/{vessel_id}/not-underway-periods",
                json=_period_body(),
                headers=_csrf(client),
            )
            period_id = created.json()["data"]["id"]

            added = client.post(
                f"/api/v1/not-underway-periods/{period_id}/fuel-uses",
                json={"consumer_type": "OIL_FIRED_BOILER", "fuel_type": "HFO", "fuel_ton": "2.5"},
                headers=_csrf(client),
            )
            assert added.status_code == 201, added.text
            # 추가는 **그 한 건만** 돌려준다(구간 전체가 아니다). CF는 서버가 뜬다.
            fuel_use_id = added.json()["data"]["id"]
            assert added.json()["data"]["cf_used"]

            removed = client.delete(
                f"/api/v1/not-underway-periods/{period_id}/fuel-uses/{fuel_use_id}",
                headers=_csrf(client),
            )
            assert removed.status_code == 200, removed.text
            assert removed.json()["data"] == {"id": fuel_use_id, "deleted": True}

            # 지운 것이 실제로 빠졌는지 **목록으로 다시 확인**한다 — 삭제 응답만 보면
            # 「지웠다고 말하지만 남아 있는」 경우를 잡지 못한다.
            listed = client.get(f"/api/v1/vessels/{vessel_id}/not-underway-periods")
            assert listed.status_code == 200, listed.text
            period = next(p for p in listed.json()["data"] if p["id"] == period_id)
            assert all(fu["id"] != fuel_use_id for fu in period["fuel_uses"])
    finally:
        await _cleanup(vessel_id)


async def test_csrf_header_is_required_on_every_write_route(migrated_db, app_fresh_engine):
    """다섯 라우트 전부 CSRF 헤더 없이는 통과하지 못한다 (`API_SPEC §1.2`).

    `require_csrf`는 걸려 있었지만 **그것이 실제로 막는지는 확인된 적이 없다.**
    의존성 하나가 빠져도 다른 어떤 검사도 알아채지 못한다.
    """
    missing = uuid4()
    with TestClient(app, base_url=_BASE) as client:
        client.post("/api/v1/auth/dev-login")
        calls = [
            ("post", f"/api/v1/vessels/{missing}/not-underway-periods", _period_body()),
            ("patch", f"/api/v1/not-underway-periods/{missing}", {"port_name": "X"}),
            ("delete", f"/api/v1/not-underway-periods/{missing}", None),
            (
                "post",
                f"/api/v1/not-underway-periods/{missing}/fuel-uses",
                {"consumer_type": "OIL_FIRED_BOILER", "fuel_type": "HFO", "fuel_ton": "1"},
            ),
            ("delete", f"/api/v1/not-underway-periods/{missing}/fuel-uses/{missing}", None),
        ]
        for method, url, payload in calls:
            kwargs = {} if payload is None else {"json": payload}
            response = getattr(client, method)(url, **kwargs)
            # 403이어야 한다 — 404(대상 없음)까지 가면 CSRF를 지나쳤다는 뜻이다.
            assert response.status_code == 403, f"{method.upper()} {url} → {response.status_code}"
