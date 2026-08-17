"""감사 로그 — 항차 확정·계산 실행 (TECH_SPEC §13.1, #65).

**감사 로그의 목적은 「누가 언제 무엇을」에 답하는 것**이고, 그 답이 필요한 순간은
보통 한참 뒤다. 그래서 기록이 빠졌다는 사실은 **필요해질 때까지 드러나지 않는다.**

`TECH_SPEC §13.1`이 기록 대상으로 지목한 셋 중 둘을 여기서 잠근다.

============================  ==============================================
 항차 확정(CONFIRMED 전환)     `#65`가 이번에 붙였다
 계산 실행                     `#277`이 이미 붙였으나 **테스트가 없었다**
 파라미터 변경                 **변경 경로 자체가 아직 없다** (`§7.5` import, `#444`)
============================  ==============================================

세 번째는 기능이 없으므로 케이스도 `#444`로 옮겼다 (`TEST_PLAN §14.5`) — 여기서는
그 ID를 인용하지 않는다. **인용만으로도 커버리지 게이트가 「덮였다」로 읽는다.**

## 라우트를 지나가야 의미가 있다

서비스만 부르면 「기록하는 함수가 있다」까지만 확인된다. 이 저장소가 반복해서 만난
형태가 **구현은 있고 부르는 곳이 없는 상태**라, 실제 요청을 보내 확인한다.

케이스 (`TEST_PLAN §14.5`):
    IT-AUDIT-001 · IT-AUDIT-003
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"

#: 데모 seed의 BULK_CARRIER 1번 선박 — 규정 파라미터가 갖춰진 조합이다.
DEMO_VESSEL = "00000000-0000-4000-8000-000000000001"


def _csrf(client: TestClient) -> dict[str, str]:
    """상태 변경 요청의 CSRF 헤더.

    서버가 검증하는 경로는 **헤더뿐**이다(`API_SPEC §1.2`) — 쿠키에 실린 원문을
    `X-CSRF-Token`으로 옮겨 싣는다. 화면(`apiProvider.csrfHeaders`)이 하는 일과 같다.
    """
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _fetch_events(session, action: str) -> list:
    rows = await session.execute(
        text(
            "SELECT user_id, entity_type, entity_id, details_json, ip_address "
            'FROM audit_log WHERE action = :action ORDER BY "timestamp" DESC'
        ),
        {"action": action},
    )
    return rows.mappings().all()


async def _cleanup(voyage_id: str | None = None) -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(text("DELETE FROM audit_log"))
        if voyage_id is not None:
            await s.execute(
                text("DELETE FROM voyage_fuel_use WHERE voyage_id = CAST(:id AS uuid)"),
                {"id": voyage_id},
            )
            await s.execute(
                text("DELETE FROM voyage WHERE id = CAST(:id AS uuid)"), {"id": voyage_id}
            )
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = 'dev@localhost')"
            )
        )
        await s.execute(text("DELETE FROM app_user WHERE email = 'dev@localhost'"))
        await s.commit()
    await get_engine().dispose()


async def _seed_completed_voyage(voyage_id: str) -> None:
    """확정 직전 상태의 항차를 만든다.

    ``COMPLETED → CONFIRMED``는 **실적이 완전할 때만** 통과하므로
    (`API_SPEC §3.5` 가드), 실거리·실연료를 채워 둔다.
    """
    from cii_platform.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        await s.execute(
            text(
                "INSERT INTO voyage (id, vessel_id, voyage_no, status, "
                " annual_inclusion_policy, regulation_year, departure_port_name, "
                " arrival_port_name, planned_distance_nm, actual_distance_nm, "
                " planned_speed_kn, created_from) "
                "VALUES (CAST(:id AS uuid), CAST(:vid AS uuid), 'V-AUDIT-1', 'COMPLETED', "
                " 'INCLUDE_AS_ACTUAL', 2026, 'BUSAN', 'SINGAPORE', 1000, 1010, 12, 'MANUAL')"
            ),
            {"id": voyage_id, "vid": DEMO_VESSEL},
        )
        await s.execute(
            text(
                "INSERT INTO voyage_fuel_use "
                "(voyage_id, fuel_type, planned_fuel_ton, actual_fuel_ton, cf_used, source) "
                "VALUES (CAST(:id AS uuid), 'HFO', 80, 82, 3.114, 'USER_INPUT')"
            ),
            {"id": voyage_id},
        )
        await s.commit()


async def _seed_planned_voyage(voyage_id: str) -> None:
    """확정과 무관한 전환을 시험할 항차 — `PLANNED → IN_PROGRESS`.

    `COMPLETED`에서 갈 수 있는 곳은 `CONFIRMED`뿐이라(`PRD §8.1.1`), 「확정이 아닌
    전환」을 보려면 다른 상태에서 출발해야 한다.
    """
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "INSERT INTO voyage (id, vessel_id, voyage_no, status, "
                " annual_inclusion_policy, regulation_year, departure_port_name, "
                " arrival_port_name, planned_distance_nm, planned_speed_kn, created_from) "
                "VALUES (CAST(:id AS uuid), CAST(:vid AS uuid), 'V-AUDIT-2', 'PLANNED', "
                " 'INCLUDE_AS_PLAN', 2026, 'BUSAN', 'SINGAPORE', 1000, 12, 'MANUAL')"
            ),
            {"id": voyage_id, "vid": DEMO_VESSEL},
        )
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
# IT-AUDIT-001 · 항차 확정
# ─────────────────────────────────────────────────────────────────────────────


async def test_voyage_confirm_records_an_audit_event(migrated_db, app_fresh_engine):
    """IT-AUDIT-001 — `action=VOYAGE_CONFIRM` 행이 남는다.

    확정은 **되돌릴 수 없는 선언**이다. 그 시점의 실적이 연말 보고의 근거가 되고
    이후 수정은 상태 가드가 막는다 — 「누가 언제 확정했나」에 답할 수 없으면 그 근거의
    출처가 사라진다.
    """
    voyage_id = str(uuid4())
    try:
        await _seed_completed_voyage(voyage_id)

        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            response = client.post(
                f"/api/v1/voyages/{voyage_id}/transition",
                json={"to_status": "CONFIRMED"},
                headers=_csrf(client),
            )
            assert response.status_code == 200, response.text

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            events = await _fetch_events(s, "VOYAGE_CONFIRM")
            assert len(events) == 1
            event = events[0]
            assert event["user_id"], "주체가 비어 있다"
            assert event["entity_type"] == "voyage"
            assert str(event["entity_id"]) == voyage_id
            assert event["ip_address"]
    finally:
        await _cleanup(voyage_id)


async def test_confirm_event_carries_before_and_after(migrated_db, app_fresh_engine):
    """**변경 전/후가 함께 남는다.**

    「확정됐다」만 남기면 어떤 상태에서 왔는지 다시 조회해야 알 수 있고, 그때는 이미
    현재 상태만 남아 있다.
    """
    voyage_id = str(uuid4())
    try:
        await _seed_completed_voyage(voyage_id)

        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            client.post(
                f"/api/v1/voyages/{voyage_id}/transition",
                json={"to_status": "CONFIRMED"},
                headers=_csrf(client),
            )

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            (event,) = await _fetch_events(s, "VOYAGE_CONFIRM")
            details = event["details_json"]
            assert details["from_status"] == "COMPLETED"
            assert details["to_status"] == "CONFIRMED"
            assert details["annual_inclusion_policy"] == "INCLUDE_AS_ACTUAL"
    finally:
        await _cleanup(voyage_id)


async def test_other_transitions_do_not_write_confirm_events(migrated_db, app_fresh_engine):
    """확정이 아닌 전환은 이 스트림에 들어오지 않는다.

    되돌릴 수 있는 전환까지 같은 action으로 남기면 **무엇이 중요한지가 흐려진다** —
    정본(`TECH_SPEC §13.1`)이 지목한 것은 확정이다.
    """
    voyage_id = str(uuid4())
    try:
        await _seed_planned_voyage(voyage_id)

        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            response = client.post(
                f"/api/v1/voyages/{voyage_id}/transition",
                json={"to_status": "IN_PROGRESS"},
                headers=_csrf(client),
            )
            assert response.status_code == 200, response.text

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            assert await _fetch_events(s, "VOYAGE_CONFIRM") == []
    finally:
        await _cleanup(voyage_id)


async def test_response_does_not_leak_the_internal_field(migrated_db, app_fresh_engine):
    """`_from_status`는 감사용 내부 값이라 응답에 나가지 않는다.

    `_duration_ms`와 같은 규약이다 — 내부 키가 응답에 남으면 클라이언트가 그것을
    계약으로 읽는다.
    """
    voyage_id = str(uuid4())
    try:
        await _seed_completed_voyage(voyage_id)

        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            response = client.post(
                f"/api/v1/voyages/{voyage_id}/transition",
                json={"to_status": "CONFIRMED"},
                headers=_csrf(client),
            )

        assert "_from_status" not in response.json()["data"]
    finally:
        await _cleanup(voyage_id)


# ─────────────────────────────────────────────────────────────────────────────
# IT-AUDIT-003 · 계산 실행
# ─────────────────────────────────────────────────────────────────────────────


async def test_calculation_run_records_hashes(migrated_db, app_fresh_engine):
    """IT-AUDIT-003 — 계산 실행 행에 `input_hash`·`parameter_hash`가 담긴다.

    **재현성 계약과 감사 로그가 만나는 지점**이다(`TECH_SPEC §5.4` · `§13.1`).
    해시가 없으면 「그때 무슨 입력과 파라미터로 돌렸나」를 로그만으로는 알 수 없다.

    이 배선은 `#277`이 이미 넣었으나 **테스트가 없었다** — 지워도 아무것도 실패하지
    않는 상태였다.
    """
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            response = client.post(
                "/api/v1/calculations/voyage-cii",
                json={
                    "vessel_id": DEMO_VESSEL,
                    "regulation_year": 2026,
                    "distance_nm": 1000,
                    "speed_kn": 14.2,
                    "fuel_uses": [{"fuel_type": "HFO", "fuel_ton": 80}],
                },
                headers=_csrf(client),
            )
            assert response.status_code == 200, response.text
            body = response.json()

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            events = await _fetch_events(s, "CALCULATION_RUN")
            assert len(events) == 1
            details = events[0]["details_json"]
            assert details["input_hash"] == body["input_hash"]
            assert details["parameter_hash"] == body["parameter_hash"]
            # `TECH_SPEC §13.1` 필드 표 — 나머지도 함께 확인한다.
            assert details["calculation_type"] == "VOYAGE_ESTIMATE"
            assert details["status"] == "SUCCESS"
            assert isinstance(details["duration_ms"], int)
            assert events[0]["user_id"]
    finally:
        await _cleanup()
