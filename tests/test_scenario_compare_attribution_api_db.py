"""항차를 두고 한 시나리오 비교의 귀결 셋을 **HTTP로** 본다 (`#2217` · 2026-10-08 결정 1·2·3).

비교 요청이 대상 항차를 밝히면 계산 이력이 그 항차에 붙는다(`API_SPEC §5.1`). 그러면서 종전에는
비교와 무관하던 규칙 셋이 비교에도 걸린다. 사용자가 지나는 길 그대로 간다 — 응답 조립까지
본다(엔진·서비스 검사는 응답에 실리는 값을 보지 못한다).

1. **삭제** — 비교가 붙은 초안(`DRAFT`)은 물리 삭제할 수 없다(409 · `API_SPEC §3.7` `[#313]`).
   취소(`CANCELLED`)로 바꿔도 같다.
2. **재계산 필요 표시** — 시나리오 채택은 그 항차의 비교 이력을 표시하지 않는다. 항차 CII
   추정은 표시한다. 계획값을 직접 고치는 `PATCH`는 비교 이력에도 표시한다(`PRD §8.4`).
3. **채택 대상** — 항차 X를 두고 한 비교는 X에만 채택할 수 있다(`API_SPEC §5.2`). 붙지 않은
   비교는 종전대로다.
"""

from __future__ import annotations

from uuid import UUID

from conftest import insert_returning_id
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"

IMO = "7200620"

PAYLOAD = {
    "regulation_year": 2026,
    "current_speed_kn": 14.0,
    "fuel_type": "HFO",
    "base_daily_foc_ton": 35.0,
    "direct_distance_nm": 11000.0,
}


async def _vessel(session) -> str:
    vessel_id = await insert_returning_id(
        session,
        "INSERT INTO vessel (imo_number, name, ship_type, gross_tonnage, deadweight, "
        "reference_speed_kn, default_fuel_type) "
        "VALUES (:imo, 'ATTRIBUTION TEST', 'BULK_CARRIER', 30000, 50000, 14.0, 'HFO') "
        "RETURNING id",
        {"imo": IMO},
    )
    await session.commit()
    return vessel_id


async def _voyage(session, vessel_id: str, status: str) -> str:
    policy = "EXCLUDE" if status == "DRAFT" else "INCLUDE_AS_PLAN"
    voyage_id = await insert_returning_id(
        session,
        "INSERT INTO voyage (vessel_id, status, annual_inclusion_policy, regulation_year, "
        " departure_port_name, arrival_port_name, planned_distance_nm, planned_speed_kn, "
        " planned_departure_at, created_from) "
        "VALUES (:vid, :status, :policy, 2026, 'BUSAN', 'ROTTERDAM', 11000, 14, "
        " '2026-03-01T00:00:00Z', 'MANUAL') RETURNING id",
        {"vid": vessel_id, "status": status, "policy": policy},
    )
    await session.execute(
        text(
            "INSERT INTO voyage_fuel_use (voyage_id, fuel_type, planned_fuel_ton, cf_used, source) "
            "VALUES (:id, 'HFO', 1100, 3.114, 'USER_INPUT')"
        ),
        {"id": voyage_id},
    )
    await session.commit()
    return voyage_id


async def _cleanup(session, vessel_id: str) -> None:
    await session.execute(
        text("DELETE FROM voyage_scenario WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    # calculation_run은 immutable 트리거가 DELETE를 막는다 — 잠시 끄고 즉시 복구한다
    # (`test_scenario_compare_db.py`와 같은 패턴).
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS INACTIVE"))
    await session.execute(
        text("DELETE FROM calculation_run WHERE vessel_id = :vid"), {"vid": vessel_id}
    )
    await session.execute(text("ALTER TRIGGER trg_calcrun_no_delete STATUS ACTIVE"))
    await session.execute(
        text(
            "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
            "(SELECT id FROM voyage WHERE vessel_id = :vid)"
        ),
        {"vid": vessel_id},
    )
    await session.execute(text("DELETE FROM voyage WHERE vessel_id = :vid"), {"vid": vessel_id})
    await session.execute(text("DELETE FROM vessel WHERE id = :vid"), {"vid": vessel_id})
    await session.execute(text("DELETE FROM audit_log"))
    await session.execute(
        text(
            "DELETE FROM user_session WHERE user_id IN "
            "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
        )
    )
    await session.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
    await session.commit()


async def _needs_recalc(session, run_id: str) -> int:
    """BOOLEAN이 SMALLINT로 내려간다 — 1/0으로 본다(`#1058`)."""
    row = await session.execute(
        text("SELECT needs_recalc FROM calculation_run WHERE id = :id"), {"id": UUID(run_id)}
    )
    return int(row.scalar_one())


def _login(client: TestClient) -> dict[str, str]:
    assert client.post("/api/v1/auth/dev-login").status_code == 200
    return {"X-CSRF-Token": client.cookies.get("csrf") or ""}


def _compare(client: TestClient, headers, vessel_id: str, **extra) -> dict:
    response = client.post(
        "/api/v1/scenarios/compare",
        json={"vessel_id": vessel_id, **PAYLOAD, **extra},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _scenario_id(compared: dict, scenario_type: str) -> str:
    return next(
        item["scenario_id"]
        for item in compared["data"]["scenarios"]
        if item["scenario_type"] == scenario_type
    )


def _adopt(client: TestClient, headers, scenario_id: str, voyage_id: str, **extra):
    return client.post(
        f"/api/v1/scenarios/{scenario_id}/adopt",
        json={"target_voyage_id": voyage_id, **extra},
        headers=headers,
    )


async def test_비교가_붙은_초안은_지울_수_없고_취소해도_같다(migrated_db, app_fresh_engine):
    """결정 1 — 초안에서 한 비교도 그 항차에 붙고, 붙은 뒤의 삭제는 409다.

    화면에서 초안에 계산 이력이 붙는 길은 이 비교가 처음이다(항차 CII 추정의 「계획 저장」은
    계획 상태로 바꾼 뒤에 붙인다). 500(`fk_calculation_run_voyage` 위반)이 아니라 409여야 하고,
    항차 행은 남는다.
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _vessel(s)
            draft_id = await _voyage(s, vessel_id, "DRAFT")
            untouched_id = await _voyage(s, vessel_id, "DRAFT")

        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)

            compared = _compare(client, headers, vessel_id, voyage_id=draft_id)
            assert UUID(compared["data"]["voyage_id"]) == UUID(draft_id)

            refused = client.delete(f"/api/v1/voyages/{draft_id}", headers=headers)
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "CONFLICT"

            # 취소로 바꿔도 풀리지 않는다 — 취소 상태도 같은 판정을 받는다.
            cancelled = client.post(
                f"/api/v1/voyages/{draft_id}/transition",
                json={"to_status": "CANCELLED"},
                headers=headers,
            )
            assert cancelled.status_code == 200, cancelled.text
            still_refused = client.delete(f"/api/v1/voyages/{draft_id}", headers=headers)
            assert still_refused.status_code == 409, still_refused.text

            # 비교가 붙지 않은 초안은 종전대로 지워진다 — 막는 것은 「붙은」 초안뿐이다.
            deleted = client.delete(f"/api/v1/voyages/{untouched_id}", headers=headers)
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["data"]["hard_delete"] is True

        async with sessionmaker() as s:
            remaining = await s.execute(
                text("SELECT id FROM voyage WHERE vessel_id = :vid"), {"vid": vessel_id}
            )
            assert [UUID(str(row[0])) for row in remaining] == [UUID(draft_id)]
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
        await get_engine().dispose()


async def test_채택은_그_항차의_비교_이력을_재계산_필요로_표시하지_않는다(
    migrated_db, app_fresh_engine
):
    """결정 2 — 비교 둘 가운데 하나를 채택하고, 되돌아가 다른 비교를 채택한다.

    채택한 비교도, 채택 전에 견줘 본 비교도 새 계획의 근거다. 표시는 지울 수 없으므로
    「방금 채택한 한 건만」 빼면 두 번째 채택에서 채택된 비교에 표시가 남는다 — 그래서 두 번
    채택한다. 항차 CII 추정은 옛 계획값으로 계산한 결과라 표시되고, 응답의 건수는 그것만 센다.
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _vessel(s)
            voyage_id = await _voyage(s, vessel_id, "PLANNED")

        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)

            first = _compare(client, headers, vessel_id, voyage_id=voyage_id)
            second = _compare(
                client, headers, vessel_id, voyage_id=voyage_id, direct_distance_nm=10500.0
            )
            runs = [first["calculation_run_id"], second["calculation_run_id"]]

            # 계산 이력이 비교뿐이면 새로 표시된 것이 없다.
            adopted = _adopt(client, headers, _scenario_id(second, "SLOW_STEAMING"), voyage_id)
            assert adopted.status_code == 200, adopted.text
            assert adopted.json()["data"]["invalidated_calculation_runs"] == 0
            async with sessionmaker() as s:
                assert [await _needs_recalc(s, run_id) for run_id in runs] == [0, 0]

            # 항차 CII 추정이 붙어 있으면 그것은 표시한다 — 건수는 그것만 센다.
            estimated = client.post(
                "/api/v1/calculations/voyage-cii",
                json={
                    "vessel_id": vessel_id,
                    "regulation_year": 2026,
                    "distance_nm": 11000,
                    "speed_kn": 14,
                    "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 1100}],
                    "voyage_id": voyage_id,
                },
                headers=headers,
            )
            assert estimated.status_code == 200, estimated.text
            estimate_run = estimated.json()["calculation_run_id"]

            # 되돌아가 앞서 돌린 비교를 채택한다.
            readopted = _adopt(client, headers, _scenario_id(first, "DIRECT"), voyage_id)
            assert readopted.status_code == 200, readopted.text
            assert readopted.json()["data"]["invalidated_calculation_runs"] == 1
            async with sessionmaker() as s:
                assert [await _needs_recalc(s, run_id) for run_id in runs] == [0, 0]
                assert await _needs_recalc(s, estimate_run) == 1
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
        await get_engine().dispose()


async def test_계획값을_직접_고치면_비교_이력에도_재계산_필요가_붙는다(
    migrated_db, app_fresh_engine
):
    """결정 2의 다른 쪽 — `PATCH /voyages/{id}`는 종전대로다.

    사용자가 계획값을 손으로 고치면 비교의 전제가 바뀐 것이다. 채택이 비교 이력을 빼는 것과
    **같은 함수의 다른 호출**이라, 한쪽을 고치다 다른 쪽까지 빠지지 않게 나란히 둔다.
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _vessel(s)
            voyage_id = await _voyage(s, vessel_id, "PLANNED")

        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)

            attached = _compare(client, headers, vessel_id, voyage_id=voyage_id)
            loose = _compare(client, headers, vessel_id, direct_distance_nm=9000.0)

            patched = client.patch(
                f"/api/v1/voyages/{voyage_id}", json={"planned_speed_kn": 12.5}, headers=headers
            )
            assert patched.status_code == 200, patched.text

            async with sessionmaker() as s:
                assert await _needs_recalc(s, attached["calculation_run_id"]) == 1
                # 항차를 밝히지 않은 비교는 어느 항차의 계획과도 이어져 있지 않다.
                assert await _needs_recalc(s, loose["calculation_run_id"]) == 0
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
        await get_engine().dispose()


async def test_항차를_두고_한_비교는_그_항차에만_채택할_수_있다(migrated_db, app_fresh_engine):
    """결정 3 — X를 두고 한 비교를 Y에 반영하려는 요청은 422다.

    받아 주면 한 비교가 X의 리포트에는 「가장 최근 비교」로, Y의 리포트에는 「채택한 비교」로
    실린다. 거절은 계획값을 바꾸기 **전에** 난다 — Y의 계획이 그대로인지 함께 본다. 새 항차를
    만드는 모드도 채택이 다른 항차에 이어지므로 같은 거절이다. 항차를 밝히지 않은 비교는
    종전대로 어느 계획 항차에나 반영된다.
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    vessel_id = None
    try:
        async with sessionmaker() as s:
            vessel_id = await _vessel(s)
            x_id = await _voyage(s, vessel_id, "PLANNED")
            y_id = await _voyage(s, vessel_id, "PLANNED")

        with TestClient(app, base_url=_BASE) as client:
            headers = _login(client)

            of_x = _compare(client, headers, vessel_id, voyage_id=x_id, direct_distance_nm=9800.0)
            slow_of_x = _scenario_id(of_x, "SLOW_STEAMING")

            crossed = _adopt(client, headers, slow_of_x, y_id)
            assert crossed.status_code == 422, crossed.text
            assert crossed.json()["error"]["details"][0]["field"] == "target_voyage_id"

            created = _adopt(
                client,
                headers,
                slow_of_x,
                x_id,
                adopt_mode="CREATE_NEW_VOYAGE",
                departure_port_name="BUSAN",
                arrival_port_name="SINGAPORE",
                planned_departure_at="2026-05-01T00:00:00Z",
            )
            assert created.status_code == 422, created.text
            assert created.json()["error"]["details"][0]["field"] == "target_voyage_id"

            async with sessionmaker() as s:
                plan = await s.execute(
                    text("SELECT planned_distance_nm FROM voyage WHERE id = :id"),
                    {"id": UUID(y_id)},
                )
                assert plan.scalar_one() == 11000
                adopted_rows = await s.execute(
                    text(
                        "SELECT COUNT(*) FROM voyage_scenario "
                        "WHERE vessel_id = :vid AND is_adopted = 1"
                    ),
                    {"vid": UUID(vessel_id)},
                )
                assert adopted_rows.scalar_one() == 0
                voyages = await s.execute(
                    text("SELECT COUNT(*) FROM voyage WHERE vessel_id = :vid"),
                    {"vid": UUID(vessel_id)},
                )
                assert voyages.scalar_one() == 2

            own = _adopt(client, headers, slow_of_x, x_id)
            assert own.status_code == 200, own.text
            assert UUID(own.json()["data"]["voyage_id"]) == UUID(x_id)

            # 항차를 밝히지 않은 비교 — 붙은 항차가 없어 어느 계획 항차에나 반영된다.
            loose = _compare(client, headers, vessel_id, direct_distance_nm=9000.0)
            assert loose["data"]["voyage_id"] is None
            free = _adopt(client, headers, _scenario_id(loose, "DIRECT"), y_id)
            assert free.status_code == 200, free.text
            assert UUID(free.json()["data"]["voyage_id"]) == UUID(y_id)
    finally:
        if vessel_id:
            async with sessionmaker() as s:
                await _cleanup(s, vessel_id)
        await get_engine().dispose()
