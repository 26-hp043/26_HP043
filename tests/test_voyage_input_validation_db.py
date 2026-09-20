"""항차·선박 쓰기 입구의 입력 검증 — **500이 나던 자리** (`#1332`).

## 무엇을 막는가

`API_SPEC §1.4`는 사용자가 고칠 수 있는 입력에 4xx를 정한다. 그런데 다섯 자리에서
검사가 없어 **FK 위반이 그대로 올라와 500**이 되거나, 더 나쁘게는 **아무 일도
없었다는 듯 통과**했다.

===============================================  ==================================
 없는 선박으로 항차 생성                           500 → **404**
 **삭제된 선박**에 항차 생성                       201 → **404**
 seed에 없는 `regulation_year`(VAL-005)           201 → **409**
 `status`·`annual_inclusion_policy` 필터 오타      빈 목록 → **422**
 없는 `default_fuel_type`으로 선박 등록·수정       500 → **422**
===============================================  ==================================

**빈 목록이 가장 조용하다.** 오타를 내면 200 + 빈 배열이 돌아오고 화면에서는 「그런
항차가 없다」와 같은 모양이 된다 — 선박 목록의 ``ship_type``은 처음부터 422였다.

## 왜 HTTP로 보는가

`test_voyages_api.py`는 저장소를 대역으로 갈아 끼운다 — **FK가 없으므로 500이 나던
경로를 재현할 수 없다.** 여기서는 실제 DB에 붙어 상태 코드를 본다(`#433`의 교훈 —
응답은 HTTP에서 확인한다).

## 데이터를 남기지 않는다

``TestClient``는 실제로 커밋한다. 전용 IMO로 만들고 ``finally``에서 항차 → 선박 순으로
지운다.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import API_V1_PREFIX, app

_BASE = "https://testserver"

#: seed에 없는 연도 (`db/seed.py`는 2023~2030). VAL-005가 잡아야 하는 값이다.
UNSEEDED_YEAR = 2031


def _imo() -> str:
    """이 검사 전용 IMO — 시드(``0``·``9`` 시작)와 겹치지 않게 ``7``로 시작한다."""
    return f"7{uuid.uuid4().int % 1_000_000:06d}"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


_VOYAGE = {
    "departure_port_name": "BUSAN",
    "arrival_port_name": "SINGAPORE",
    "planned_distance_nm": 2470.2,
    "planned_speed_kn": 14,
    "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 331}],
}


async def _cleanup(vessel_id: str) -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text("DELETE FROM voyage WHERE vessel_id = :v"), {"v": uuid.UUID(vessel_id)}
        )
        await s.execute(text("DELETE FROM vessel WHERE id = :v"), {"v": uuid.UUID(vessel_id)})
        await s.commit()


def _new_vessel(client: TestClient, name: str) -> str:
    created = client.post(
        f"{API_V1_PREFIX}/vessels",
        json={"imo_number": _imo(), "name": name, "ship_type": "BULK_CARRIER"},
        headers=_csrf(client),
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


async def test_a_missing_vessel_is_404_not_500(migrated_db, app_fresh_engine):
    """없는 선박에 항차를 만들면 **404**다 — 종전에는 FK 위반이 500으로 나갔다."""
    with TestClient(app, base_url=_BASE) as client:
        assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
        response = client.post(
            f"{API_V1_PREFIX}/vessels/{uuid.uuid4()}/voyages",
            json=_VOYAGE,
            headers=_csrf(client),
        )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_a_deleted_vessel_accepts_nothing(migrated_db, app_fresh_engine):
    """⚠️ **삭제된 선박에 항차가 생겼다** — 201이었다.

    ``GET /vessels/{id}``는 404인데 ``POST .../voyages``는 201이고
    ``GET .../voyages``는 목록을 돌려줬다 — **같은 리소스가 상태에 따라 있기도 없기도**
    했다. 목록까지 함께 보는 것이 요점이다: 생성만 막으면 조회에서 다시 갈린다.
    """
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            vessel_id = _new_vessel(client, "DELETED VESSEL TEST")
            deleted = client.delete(f"{API_V1_PREFIX}/vessels/{vessel_id}", headers=_csrf(client))
            assert deleted.status_code in (200, 204), deleted.text

            created = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages",
                json=_VOYAGE,
                headers=_csrf(client),
            )
            assert created.status_code == 404, created.text

            listed = client.get(f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages")
            assert listed.status_code == 404, listed.text
    finally:
        if vessel_id:
            await _cleanup(vessel_id)


async def test_an_unseeded_regulation_year_is_409(migrated_db, app_fresh_engine):
    """VAL-005 — 규정 파라미터에 없는 연도는 **409**다 (`API_SPEC §1.4`).

    종전에는 스키마의 범위 검사(2019~2050)만 있어 **2031년 항차가 201로 저장**됐고,
    `INCLUDE_AS_PLAN` 전환까지 통과한 뒤 **CII 조회에서 409**가 나 사용자는 서버
    문제로 읽었다. 고칠 수 있는 입력이라면 **입력받는 자리에서** 말해야 한다.
    """
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            vessel_id = _new_vessel(client, "VAL005 TEST")

            created = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages",
                json={**_VOYAGE, "regulation_year": UNSEEDED_YEAR},
                headers=_csrf(client),
            )
            assert created.status_code == 409, created.text
            assert created.json()["error"]["code"] == "PARAMETER_ERROR"

            # 수정 경로도 같다 — 한쪽만 막으면 「만들 때는 안 되는데 고칠 때는 되는」
            # 상태가 된다.
            ok = client.post(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages",
                json=_VOYAGE,
                headers=_csrf(client),
            )
            assert ok.status_code == 201, ok.text
            patched = client.patch(
                f"{API_V1_PREFIX}/voyages/{ok.json()['data']['id']}",
                json={"regulation_year": UNSEEDED_YEAR},
                headers=_csrf(client),
            )
            assert patched.status_code == 409, patched.text
    finally:
        if vessel_id:
            await _cleanup(vessel_id)


@pytest.mark.parametrize(
    ("param", "value"),
    [("status", "PLANNEDD"), ("annual_inclusion_policy", "INCLUDE")],
)
async def test_an_unknown_list_filter_is_422_not_an_empty_list(
    migrated_db, app_fresh_engine, param, value
):
    """⚠️ **빈 목록은 답이 아니다.**

    값이 틀리면 맞는 행이 없어 200 + 빈 배열이 돌아오고, 화면에서는 「그런 항차가
    없다」와 **같은 모양**이 된다. 선박 목록의 ``ship_type``은 처음부터 422였다 —
    같은 저장소 안에서 두 경로가 갈려 있었다.
    """
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            vessel_id = _new_vessel(client, "FILTER TEST")

            response = client.get(
                f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages", params={param: value}
            )

            assert response.status_code == 422, response.text
            assert response.json()["error"]["details"][0]["field"] == param
    finally:
        if vessel_id:
            await _cleanup(vessel_id)


async def test_the_inclusion_policy_filter_actually_filters(migrated_db, app_fresh_engine):
    """`§3.1` 표에 있던 필터가 **조용히 버려지고 있었다** (`#1332`).

    라우트가 선언하지 않은 쿼리를 FastAPI는 오류 없이 버린다 — 문서대로
    ``?annual_inclusion_policy=INCLUDE_AS_PLAN``을 보낸 호출자는 **필터가 걸린 줄 알고
    전체 목록**을 받았다.

    **거르는 쪽과 걸러지는 쪽을 함께 본다** — 「빈 목록이 온다」만 보면 필터가 무엇을
    해도(예: 늘 0건) 통과한다.
    """
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200
            vessel_id = _new_vessel(client, "POLICY FILTER TEST")
            base = f"{API_V1_PREFIX}/vessels/{vessel_id}/voyages"

            created = client.post(base, json=_VOYAGE, headers=_csrf(client))
            assert created.status_code == 201, created.text

            excluded = client.get(base, params={"annual_inclusion_policy": "EXCLUDE"})
            assert excluded.status_code == 200, excluded.text
            assert len(excluded.json()["data"]) == 1

            as_plan = client.get(base, params={"annual_inclusion_policy": "INCLUDE_AS_PLAN"})
            assert as_plan.status_code == 200, as_plan.text
            assert as_plan.json()["data"] == []
    finally:
        if vessel_id:
            await _cleanup(vessel_id)


async def test_an_unknown_default_fuel_type_is_422_not_500(migrated_db, app_fresh_engine):
    """없는 ``default_fuel_type``은 **422**다 — 종전에는 FK 위반이 500이었다.

    같은 파일의 ``ship_type``(VAL-004)은 처음부터 422였다. 사용자가 고칠 수 있는
    입력을 「서버 오류」로 보이게 하면 고칠 생각을 하지 않는다.
    """
    vessel_id: str | None = None
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post(f"{API_V1_PREFIX}/auth/dev-login", json={}).status_code == 200

            created = client.post(
                f"{API_V1_PREFIX}/vessels",
                json={
                    "imo_number": _imo(),
                    "name": "FUEL TYPE TEST",
                    "ship_type": "BULK_CARRIER",
                    "default_fuel_type": "UNOBTAINIUM",
                },
                headers=_csrf(client),
            )
            assert created.status_code == 422, created.text
            assert created.json()["error"]["details"][0]["field"] == "default_fuel_type"

            # 수정 경로도 같다.
            vessel_id = _new_vessel(client, "FUEL TYPE PATCH TEST")
            patched = client.patch(
                f"{API_V1_PREFIX}/vessels/{vessel_id}",
                json={"default_fuel_type": "UNOBTAINIUM"},
                headers=_csrf(client),
            )
            assert patched.status_code == 422, patched.text
    finally:
        if vessel_id:
            await _cleanup(vessel_id)
