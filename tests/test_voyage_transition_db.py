"""항차 상태 전이 — DB 실동작 (`API_SPEC §3.5`, #688).

**스텁으로는 이 결함을 잡을 수 없다.** `chk_status_policy`(`DB_SCHEMA §2.2`)는
`status`와 `annual_inclusion_policy` **두 컬럼의 조합**에 걸린 DB 제약이라,
파이썬 객체만 다루는 테스트에는 존재하지 않는다.

`test_voyage_state_machine.py`는 `_StubVoyage`를, `test_voyages_api.py`는
`_FakeSession`을 쓴다. 둘 다 전이 규칙 자체는 잘 잠그지만 **제약은 못 본다.**
그래서 `IN_PROGRESS → COMPLETED`에 `INCLUDE_AS_ACTUAL`을 실어 보내면 500이 나는
상태가 테스트 2,638건을 통과했다 — 화면의 「항해 완료」 버튼이 정확히 그 값을
보내는데도(`frontend/src/features/voyage-management/voyageRules.ts`).

## 왜 그 조합만 터졌나

`_POLICY_BY_STATUS`는 정책을 상태 그룹으로 묶는다.

    PLANNED · IN_PROGRESS    EXCLUDE · INCLUDE_AS_PLAN
    COMPLETED · CONFIRMED    EXCLUDE · INCLUDE_AS_ACTUAL

**그룹을 건너뛰는 유일한 전이가 `IN_PROGRESS → COMPLETED`**다. `EXCLUDE`는 모든
그룹에 있어 중간 상태가 만들어져도 제약을 통과하므로, 터지는 것은 목표 상태에서만
유효한 값을 실어 보낼 때뿐이다.

## 라우트를 지나가야 의미가 있다

서비스만 부르면 트랜잭션 경계가 테스트의 것이 되어 flush 시점이 실제 요청과
달라진다. `test_voyage_actuals_db.py`·`test_audit_actions_db.py`와 같은 이유로
실제 요청을 보낸다.

케이스 (`TEST_PLAN §3.1`):
    IT-STATE-008
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import app

_BASE = "https://testserver"

#: 데모 seed의 BULK_CARRIER 1번 선박 — 규정 파라미터가 갖춰진 조합이다.
_VESSEL = "00000000-0000-4000-8000-000000000001"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("csrf", "")}


def _make_voyage(client: TestClient, voyage_no: str) -> str:
    """DRAFT 항차 하나. 계획 연료까지 넣어 이후 실적 입력이 가능하게 한다."""
    resp = client.post(
        f"/api/v1/vessels/{_VESSEL}/voyages",
        json={
            "voyage_no": voyage_no,
            "departure_port_name": "BUSAN",
            "arrival_port_name": "TOKYO",
            "planned_distance_nm": 900,
            "planned_speed_kn": 13.0,
            "regulation_year": 2026,
            "fuel_uses": [{"fuel_type": "HFO", "planned_fuel_ton": 90}],
        },
        headers=_csrf(client),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


def _transition(client: TestClient, voyage_id: str, **body):
    return client.post(f"/api/v1/voyages/{voyage_id}/transition", json=body, headers=_csrf(client))


def _put_actuals(client: TestClient, voyage_id: str) -> None:
    resp = client.put(
        f"/api/v1/voyages/{voyage_id}/actuals",
        json={
            "actual_distance_nm": 905,
            "actual_avg_speed_kn": 12.6,
            "fuel_uses": [{"fuel_type": "HFO", "actual_fuel_ton": 92}],
        },
        headers=_csrf(client),
    )
    assert resp.status_code == 200, resp.text


def _advance_to_in_progress(client: TestClient, voyage_no: str) -> str:
    """`INCLUDE_AS_PLAN`으로 계획을 잡아 둔 `IN_PROGRESS` 항차 하나.

    이것이 화면에서 「항해 완료」를 누르기 직전의 상태다.
    """
    vid = _make_voyage(client, voyage_no)
    assert (
        _transition(
            client, vid, to_status="PLANNED", annual_inclusion_policy="INCLUDE_AS_PLAN"
        ).status_code
        == 200
    )
    assert _transition(client, vid, to_status="IN_PROGRESS").status_code == 200
    return vid


async def _cleanup(voyage_no: str) -> None:
    """이 테스트가 만든 항차를 지운다. 데모 seed 행은 건드리지 않는다."""
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "DELETE FROM voyage_fuel_use WHERE voyage_id IN "
                "(SELECT id FROM voyage WHERE voyage_no = :n)"
            ),
            {"n": voyage_no},
        )
        await s.execute(text("DELETE FROM voyage WHERE voyage_no = :n"), {"n": voyage_no})
        await s.commit()


async def test_in_progress_to_completed_with_include_as_actual(migrated_db, app_fresh_engine):
    """IT-STATE-008 — 「항해 완료」의 정상 경로가 200이다.

    **이 저장소에서 500이 났던 바로 그 요청이다.** 정책이 상태보다 먼저 flush되면
    `IN_PROGRESS` + `INCLUDE_AS_ACTUAL`이라는 금지 조합이 잠깐 만들어지고 DB가
    거부한다. 두 필드가 **함께** 새 값이어야 통과한다.
    """
    no = "IT-STATE-008-A"
    try:
        with TestClient(app, base_url=_BASE) as client:
            assert client.post("/api/v1/auth/dev-login").status_code == 200
            vid = _advance_to_in_progress(client, no)
            _put_actuals(client, vid)

            resp = _transition(
                client, vid, to_status="COMPLETED", annual_inclusion_policy="INCLUDE_AS_ACTUAL"
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["status"] == "COMPLETED"
            assert data["annual_inclusion_policy"] == "INCLUDE_AS_ACTUAL"
    finally:
        await _cleanup(no)


async def test_completed_policy_is_persisted_not_just_echoed(migrated_db, app_fresh_engine):
    """응답이 아니라 **DB 행**이 바뀌었는지 본다.

    응답은 커밋 전 객체로 만들어도 그럴듯하게 나온다. 다시 조회해 저장된 값을
    확인하지 않으면 「응답만 맞는」 상태를 통과시킨다.
    """
    no = "IT-STATE-008-B"
    try:
        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            vid = _advance_to_in_progress(client, no)
            _put_actuals(client, vid)
            _transition(
                client, vid, to_status="COMPLETED", annual_inclusion_policy="INCLUDE_AS_ACTUAL"
            )

            again = client.get(f"/api/v1/voyages/{vid}")
            assert again.status_code == 200, again.text
            saved = again.json()["data"]
            assert saved["status"] == "COMPLETED"
            assert saved["annual_inclusion_policy"] == "INCLUDE_AS_ACTUAL"
    finally:
        await _cleanup(no)


async def test_exclude_crosses_every_group(migrated_db, app_fresh_engine):
    """`EXCLUDE`로 내리는 전이는 종전에도 통과했다 — 되돌아가지 않았는지 본다.

    `EXCLUDE`는 모든 상태 그룹에 있어 중간 상태가 만들어져도 제약을 통과한다.
    이 경로는 수정 전에도 200이었으므로, **여기가 깨지면 수정이 과했다는 신호**다.
    """
    no = "IT-STATE-008-C"
    try:
        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            vid = _advance_to_in_progress(client, no)
            _put_actuals(client, vid)

            resp = _transition(
                client, vid, to_status="COMPLETED", annual_inclusion_policy="EXCLUDE"
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["annual_inclusion_policy"] == "EXCLUDE"
    finally:
        await _cleanup(no)


async def test_rejected_policy_leaves_row_untouched(migrated_db, app_fresh_engine):
    """거부될 정책을 보내면 **상태도 바뀌지 않는다.**

    422를 받았는데 서버만 전이해 있으면 클라이언트와 DB가 갈린다. 대입을 한 자리로
    모은 뒤에도 그 경계가 유지되는지 본다.
    """
    no = "IT-STATE-008-D"
    try:
        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            vid = _advance_to_in_progress(client, no)
            _put_actuals(client, vid)

            resp = _transition(
                client,
                vid,
                to_status="COMPLETED",
                annual_inclusion_policy="INCLUDE_AS_PLAN",  # COMPLETED에서 금지
            )
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "STATE_TRANSITION_ERROR"

            saved = client.get(f"/api/v1/voyages/{vid}").json()["data"]
            assert saved["status"] == "IN_PROGRESS"
            assert saved["annual_inclusion_policy"] == "INCLUDE_AS_PLAN"
    finally:
        await _cleanup(no)


async def test_actual_guard_blocks_before_any_write(migrated_db, app_fresh_engine):
    """실적 없이 COMPLETED로 가면 거부되고 **정책도 남지 않는다.**

    가드가 대입보다 앞에 있으므로, 실패한 요청은 행을 건드리지 않아야 한다.
    """
    no = "IT-STATE-008-E"
    try:
        with TestClient(app, base_url=_BASE) as client:
            client.post("/api/v1/auth/dev-login")
            vid = _advance_to_in_progress(client, no)  # 실적을 넣지 않는다

            resp = _transition(
                client, vid, to_status="COMPLETED", annual_inclusion_policy="INCLUDE_AS_ACTUAL"
            )
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "STATE_TRANSITION_ERROR"

            saved = client.get(f"/api/v1/voyages/{vid}").json()["data"]
            assert saved["status"] == "IN_PROGRESS"
            assert saved["annual_inclusion_policy"] == "INCLUDE_AS_PLAN"
    finally:
        await _cleanup(no)
