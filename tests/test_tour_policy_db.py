"""둘러보기 세션의 읽기 전용 정책 — 중앙 가드 실동작 (#1486 후속).

설계 근거는 `src/cii_platform/auth/tour_policy.py`의 모듈 독스트링이다. 이 파일은
**그 정책이 실제 요청 경로에서 발동하는지**를 본다 — 정책 함수의 순수 성질이 아니라,
미들웨어에 배선돼 있어 라우트를 가리지 않고 걸리는지가 관심사다.

## 왜 이 검사가 필요한가

둘러보기 계정은 **관리자**이고(그래야 리포트·시뮬레이션이 잠기지 않는다), 공개 스위치
(`TOUR_PUBLIC`)를 켜면 인터넷의 누구나 그 세션을 받는다. 데이터 격리는 범위 밖이라
(`PRD §5.2`) 공유 데모 자료를 **고치거나 지울 수 있고**, 관리자 전용 조회로 **실제
가입자 이메일**까지 볼 수 있다. 막는 것은 계정 수가 아니라 쓰기와 민감 조회다.

## 양방향으로 잠근다

「막힌다」만 검사하면 **전부 막아도 통과한다.** 둘러보기의 목적은 열람이므로 읽기가
열려 있다는 것도 같은 무게로 고정한다.

1. 읽기(`GET /fleet/summary`)는 **200** — 둘러보기가 제 목적을 한다
2. 쓰기(`POST /vessels`)는 **403** — 메서드 기반 차단
3. 민감 조회(`GET /auth/users`)는 **403** — ``GET``이라고 통과하지 않는다
4. 감사 로그(`GET /audit-logs`)도 **403** — 같은 이유
5. 탈퇴(`DELETE /auth/me`)는 **403** — 막지 않으면 한 사람이 **모두의 둘러보기를 끊는다**
6. 로그아웃(`POST /auth/logout`)은 **통과** — 자기 세션만 닫는다. 막으면 공유 계정이라
   다음 방문자가 남의 세션을 물려받는다
7. 🔴 **같은 요청이 일반 관리자에게는 통과한다** — 정책이 「둘러보기에만」 걸리는지.
   이 대조군이 없으면 서비스 전체를 읽기 전용으로 만들어도 위 검사들이 통과한다
8. AI 어시스턴트(`POST /chat` · `DELETE /chat/sessions/…`)는 **403이되 전용 문구**다 (#2110).
   질문은 자료를 바꾸는 일이 아니라 범용 「자료를 바꿀 수 없습니다」가 뜨면 오류로 읽힌다.
   `GET /chat/status`는 조회라 종전대로 통과한다

케이스: (`TEST_PLAN §14.5` 정의 없음 — #1486 후속으로 신설)
"""

from __future__ import annotations

import pytest
from conftest import issue_email_verify_token
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.auth import tour_gate
from cii_platform.auth.session import CSRF_COOKIE_NAME
from cii_platform.auth.tour_policy import (
    CHAT_BLOCKED_MESSAGE,
    DENIED_MESSAGE,
    READ_ONLY_MESSAGE,
)

_BASE = "https://testserver"
_CODE = "harbour-tour-readonly-9x"
_TOUR_EMAIL = "tour@bluelog.local"

#: 쓰기 시도에 쓸 선박 — **실제로 생성되면 안 된다**(정책이 그 앞에서 막는다).
_VESSEL_PAYLOAD = {
    "imo_number": "9999991",
    "name": "TOUR WRITE ATTEMPT",
    "ship_type": "BULK_CARRIER",
    "gross_tonnage": "10000",
    "deadweight": "20000",
}


async def _cleanup() -> None:
    from cii_platform.db.session import get_engine, get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = :e)"
            ),
            {"e": _TOUR_EMAIL},
        )
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": _TOUR_EMAIL})
        await s.execute(
            text("DELETE FROM vessel WHERE imo_number = :imo"),
            {"imo": _VESSEL_PAYLOAD["imo_number"]},
        )
        await s.commit()
    await get_engine().dispose()


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


def _enter_tour(client: TestClient, monkeypatch) -> None:
    """둘러보기 세션을 연다 — 이후 요청은 그 쿠키로 나간다."""
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    resp = client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": _CODE})
    assert resp.status_code == 200, resp.text


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies[CSRF_COOKIE_NAME]}


async def test_tour_can_read_fleet_summary(client, monkeypatch):
    """둘러보기는 **읽을 수 있다** — 이 검사가 없으면 전부 막아도 나머지가 통과한다."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.get(f"{API_V1_PREFIX}/fleet/summary", params={"year": 2026})
        assert resp.status_code == 200, resp.text
    finally:
        await _cleanup()


async def test_tour_cannot_create_vessel(client, monkeypatch):
    """쓰기는 403이고, **행이 만들어지지 않는다**."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.post(f"{API_V1_PREFIX}/vessels", json=_VESSEL_PAYLOAD, headers=_csrf(client))
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["message"] == READ_ONLY_MESSAGE

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            count = await s.execute(
                text("SELECT COUNT(*) FROM vessel WHERE imo_number = :imo"),
                {"imo": _VESSEL_PAYLOAD["imo_number"]},
            )
            assert count.scalar_one() == 0, "403인데 행이 생겼다 — 정책이 라우트 뒤에서 돌았다"
    finally:
        await _cleanup()


async def test_tour_cannot_read_account_list(client, monkeypatch):
    """`GET /auth/users`는 **GET이지만** 막힌다 — 실제 가입자 이메일이 실린다."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.get(f"{API_V1_PREFIX}/auth/users")
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["message"] == DENIED_MESSAGE
    finally:
        await _cleanup()


async def test_tour_cannot_read_audit_logs(client, monkeypatch):
    """감사 로그도 같은 이유로 막힌다 — 이메일·IP·행동 이력이 섞인다."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.get(f"{API_V1_PREFIX}/audit-logs")
        assert resp.status_code == 403, resp.text
    finally:
        await _cleanup()


async def test_tour_cannot_delete_its_own_account(client, monkeypatch):
    """🔴 탈퇴가 열려 있으면 **한 사람이 모두의 둘러보기를 끊는다**(공유 계정)."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.request("DELETE", f"{API_V1_PREFIX}/auth/me", headers=_csrf(client))
        assert resp.status_code == 403, resp.text

        still_in = client.get(f"{API_V1_PREFIX}/auth/me")
        assert still_in.status_code == 200, "탈퇴는 막혔는데 세션까지 끊겼다"
    finally:
        await _cleanup()


async def test_tour_can_log_out(client, monkeypatch):
    """로그아웃은 통과한다 — 자기 세션 한 줄만 닫는다."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.post(f"{API_V1_PREFIX}/auth/logout", headers=_csrf(client))
        assert resp.status_code in (200, 204), resp.text
    finally:
        await _cleanup()


# --- AI 어시스턴트 — 막되 문구는 전용 (#2110) ------------------------------------------------


async def test_tour_cannot_ask_the_assistant(client, monkeypatch):
    """질문은 403이고 **문구가 어시스턴트 전용**이다 — 범용 쓰기 거절 문구가 아니다.

    키를 지워 둔다 — 정책이 빠지면 이 요청은 외부 모델 대신 503(`CHAT_UNAVAILABLE`)으로
    떨어져야 한다. 키가 있는 환경에서 정책이 빠지면 실제로 외부를 부르게 된다.
    """
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    _enter_tour(client, monkeypatch)
    try:
        resp = client.post(
            f"{API_V1_PREFIX}/chat",
            json={"message": "올해 연말 예상 등급은 어떻게 되나요?"},
            headers=_csrf(client),
        )
        assert resp.status_code == 403, resp.text
        body = resp.json()["error"]
        assert body["code"] == "FORBIDDEN_ROLE"
        assert body["message"] == CHAT_BLOCKED_MESSAGE
        assert body["message"] != READ_ONLY_MESSAGE
    finally:
        await _cleanup()


async def test_tour_cannot_delete_a_chat_session(client, monkeypatch):
    """대화 삭제도 어시스턴트 경로라 같은 전용 문구다 — 공유 계정의 대화를 지우지 못한다."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.request(
            "DELETE",
            f"{API_V1_PREFIX}/chat/sessions/00000000-0000-0000-0000-000000000000",
            headers=_csrf(client),
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["message"] == CHAT_BLOCKED_MESSAGE
    finally:
        await _cleanup()


async def test_tour_can_read_chat_status(client, monkeypatch):
    """`GET /chat/status`는 조회라 통과한다 — 막는 것은 질문과 삭제뿐이다."""
    _enter_tour(client, monkeypatch)
    try:
        resp = client.get(f"{API_V1_PREFIX}/chat/status")
        assert resp.status_code == 200, resp.text
    finally:
        await _cleanup()


_ADMIN_EMAIL = "tour-policy-control@bluelog.kr"
_ADMIN_PASSWORD = "Control-Account-2026!x"


async def _cleanup_admin() -> None:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        for table, column in (
            ("user_session", "user_id"),
            ("user_token", "user_id"),
        ):
            await s.execute(
                text(
                    f"DELETE FROM {table} WHERE {column} IN "  # noqa: S608
                    "(SELECT id FROM app_user WHERE email = :e)"
                ),
                {"e": _ADMIN_EMAIL},
            )
        await s.execute(
            text(
                "DELETE FROM audit_log WHERE entity_type = 'app_user' AND entity_id IN "
                "(SELECT id FROM app_user WHERE email = :e)"
            ),
            {"e": _ADMIN_EMAIL},
        )
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": _ADMIN_EMAIL})
        await s.commit()


async def test_policy_applies_only_to_the_tour_principal(client, monkeypatch):
    """🔴 대조군 — 같은 요청이 **일반 관리자에게는 통과한다**.

    이 검사가 없으면 「서비스 전체를 읽기 전용으로 만든 구현」도 위 검사를 전부 통과한다.
    정책이 걸려야 하는 것은 **둘러보기 주체 하나**다.
    """
    monkeypatch.setenv("INITIAL_ADMIN_EMAILS", _ADMIN_EMAIL)
    try:
        signed = client.post(
            f"{API_V1_PREFIX}/auth/signup",
            json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD},
        )
        assert signed.status_code == 201, signed.text
        # 가입은 현장직이고, 인증 링크를 누르면 관리자가 된다 (#2108)
        assert signed.json()["data"]["role"] == "FIELD"
        token = await issue_email_verify_token(_ADMIN_EMAIL)
        confirmed = client.post(f"{API_V1_PREFIX}/auth/verify-email/confirm", json={"token": token})
        assert confirmed.status_code == 200, confirmed.text

        listed = client.get(f"{API_V1_PREFIX}/auth/users")
        assert listed.status_code == 200, listed.text

        created = client.post(
            f"{API_V1_PREFIX}/vessels", json=_VESSEL_PAYLOAD, headers=_csrf(client)
        )
        assert created.status_code != 403, created.text

        # 어시스턴트도 일반 관리자에게는 정책이 걸리지 않는다 (#2110). 빈 질문이라 외부
        # 모델에 닿지 않고 스키마 검증(422)에서 끝난다 — 403만 아니면 된다.
        asked = client.post(f"{API_V1_PREFIX}/chat", json={"message": ""}, headers=_csrf(client))
        assert asked.status_code != 403, asked.text
    finally:
        await _cleanup_admin()
        await _cleanup()


# --- 공개 스위치 — 코드 없이 들어오는 문 (#1486 후속) -----------------------------------------


async def test_public_switch_lets_empty_code_in(client, monkeypatch):
    """🔴 공개 스위치가 켜지면 **빈 코드로 들어온다**.

    스키마에 길이 하한이 있으면 이 요청은 ``tour_is_public()`` 판정까지 닿지 못하고
    **422로 먼저 잘린다** — 배포에서 실제로 그렇게 막혔다. 화면의 상시 버튼이 보내는 것이
    바로 이 모양이라, 하한을 되돌리면 버튼이 조용히 죽는다.
    """
    monkeypatch.setenv(tour_gate.PUBLIC_ENV_NAME, "true")
    monkeypatch.delenv(tour_gate.ENV_NAME, raising=False)
    try:
        resp = client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": ""})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["role"] == "ADMIN"
    finally:
        await _cleanup()


async def test_empty_code_is_rejected_when_switch_is_off(client, monkeypatch):
    """스위치가 꺼져 있으면 빈 코드는 거절된다 — 하한을 없앤 것이 문을 열지 않는다."""
    monkeypatch.delenv(tour_gate.PUBLIC_ENV_NAME, raising=False)
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        resp = client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": ""})
        assert resp.status_code == 422, resp.text
    finally:
        await _cleanup()
