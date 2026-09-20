"""둘러보기 로그인 라우트 실동작 검증 — `POST /api/v1/auth/tour-login` (#1486).

`src/cii_platform/auth/tour_gate.py`·`api/routes/auth.py::tour_login`의 독스트링이
설계 근거다. 게이트 함수 자체의 성질(fail-closed·strip·대소문자 등)은
``test_tour_gate.py``가 순수 단위로 잠그므로 여기서 되풀이하지 않는다 — 이 파일은
**라우트가 그 게이트를 배선대로 쓰는지, 그리고 그 뒤의 계정·세션·감사 로그가
설계대로 도는지**만 본다.

잠그는 것:

1. 🔴 코드가 **설정되지 않은** 상태에서 아무 코드나 보내면 422다(200이 아니다) —
   `test_tour_gate.py`의 fail-closed가 라우트에도 그대로 이어지는지.
2. 코드가 맞으면 200 · `data.role == "ADMIN"` · `sid`·`csrf` 쿠키 · `email_verified_at`
   채움.
3. 틀린 코드는 422, 응답 문구가 `tour_gate.REJECTED_MESSAGE`와 **글자 단위로 같다**
   (「꺼져 있음」과 「불일치」를 구분하지 않는 설계를 실제 응답에서 고정).
4. 🔴 두 번째 호출이 계정을 중복 생성하지 않는다 — 고정 UUID 행을 재사용한다(행 수로
   확인).
5. 🔴 스텁 계정은 `POST /auth/login`으로 열리지 않는다 — 비밀번호 해시가 Argon2
   형식이 아니라 어떤 입력도 401로 떨어진다.
6. 🔴 계정을 강등해 두면 다음 둘러보기 로그인이 ADMIN으로 되돌린다.
7. 감사 로그 — 성공은 `details_json == {"tour": True}`, 실패는
   `details_json == {"reason": "tour_code_rejected"}`이고, **코드 원문은 어느 쪽에도
   남지 않는다**(`services/audit.py`의 자격 증명 미기록 원칙).

``app_fresh_engine``(NullPool) + 커밋 기반으로 검증한다 — `conn` fixture 세션을
TestClient 안에서 쓰면 요청의 포털 루프와 fixture 루프가 엔진 연결을 공유해
"attached to a different loop"로 실패한다(`test_dev_auth.py`·`test_audit_events_db.py`와
같은 이유).

케이스: (`TEST_PLAN §14.5` 정의 없음 — 둘러보기 접근 코드는 #1486에서 신설된 기능이다)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cii_platform.api.main import API_V1_PREFIX, app
from cii_platform.auth import tour_gate
from cii_platform.auth.session import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from cii_platform.db.types import JSONText

_BASE = "https://testserver"
_CODE = "harbour-tour-9x"
_TOUR_EMAIL = "tour@bluelog.local"

#: 둘러보기 계정의 고정 UUID — `api/routes/auth.py::_TOUR_USER_ID`와 같은 값이다.
#:
#: **문자열 그대로 쓴다.** `audit_log.user_id`는 `UuidText`가 아니라
#: `sa.String(length=100)`이고(`db/models/audit_log.py`), 라우트가 `str(user.id)`(대시
#: 36자)를 그대로 적는다. 반면 `app_user.id`는 `UuidText`(하이픈 없는 32자 hex
#: 저장)다 — 두 컬럼의 저장 형식이 다르므로, `app_user`에서 하위 조회로 id를 끌어와
#: `audit_log.user_id`와 비교하면 **형식이 달라 한 건도 맞지 않는다**(`#1058`이 이
#: 종류의 불일치를 여러 번 겪었다). 그래서 정리는 이 대시 형식 상수를 직접 쓴다.
_TOUR_USER_ID = "00000000-0000-4000-8000-000000000700"


async def _fetch_tour_success_events(session) -> list:
    """이 계정의 `LOGIN_SUCCESS` 행만 — `user_id`로 좁힌다.

    ``action``만으로 거르면 이 파일 밖의(예: `dev-login`) 성공 이벤트까지 함께
    걸린다. 이 DB는 CUBRID 인스턴스 하나를 여러 테스트 파일이 공유하고, 대부분의
    파일은 ``audit_log``를 정리하지 않으므로(이 파일이 그 위에서 도는 검사는 아니다)
    다른 파일이 남긴 행이 그대로 남아 있을 수 있다 — `user_id`로 좁혀야 이 라우트가
    남긴 행만 본다.
    """
    rows = await session.execute(
        text(
            "SELECT user_id, details_json, ip_address FROM audit_log "
            "WHERE \"action\" = 'LOGIN_SUCCESS' AND user_id = :uid "
            'ORDER BY "timestamp" DESC'
            # raw SQL에는 컬럼 타입이 붙지 않아 `JSONText`의 result processor가 돌지
            # 않는다 — 붙이지 않으면 문자열이 와서 dict 비교가 어긋난다 (`#1058`).
        ).columns(details_json=JSONText()),
        {"uid": _TOUR_USER_ID},
    )
    return rows.mappings().all()


async def _fetch_tour_failure_events(session) -> list:
    """`reason = 'tour_code_rejected'`인 `LOGIN_FAILURE` 행만 — 이 라우트만 이 사유를 남긴다."""
    rows = await session.execute(
        text(
            "SELECT user_id, details_json, ip_address FROM audit_log "
            "WHERE \"action\" = 'LOGIN_FAILURE' "
            "AND details_json LIKE '%tour_code_rejected%' "
            'ORDER BY "timestamp" DESC'
        ).columns(details_json=JSONText()),
    )
    return rows.mappings().all()


async def _tour_user_row_count() -> int:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        result = await s.execute(
            text("SELECT COUNT(*) FROM app_user WHERE email = :e"), {"e": _TOUR_EMAIL}
        )
        return result.scalar_one()


async def _soft_delete_tour_user() -> None:
    """둘러보기 세션이 스스로 탈퇴한 상황을 흉내 낸다 (#1486).

    이 세션은 **관리자**라 `DELETE /auth/me`를 누를 수 있다. 그러면 이 행에
    ``is_deleted``가 선다.
    """
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text("UPDATE app_user SET is_deleted = 1 WHERE email = :e"), {"e": _TOUR_EMAIL}
        )
        await s.commit()


async def _tour_user_is_deleted() -> bool:
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        result = await s.execute(
            text("SELECT is_deleted FROM app_user WHERE email = :e"), {"e": _TOUR_EMAIL}
        )
        return bool(result.scalar_one())


async def _demote_tour_user() -> None:
    """화면에서 강등한 상황을 흉내 낸다 — `auth_dev`가 겪은 것과 같은 시나리오(#1301)."""
    from cii_platform.db.session import get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(
            text("""UPDATE app_user SET "role" = 'FIELD' WHERE email = :e"""),
            {"e": _TOUR_EMAIL},
        )
        await s.commit()


async def _cleanup() -> None:
    """이 파일이 만든 행만 지운다 — `audit_log`는 둘러보기 계정에 걸린 것만 지운다.

    `test_audit_events_db.py`처럼 테이블 전체를 비우면, 병렬 실행이 아니어도 이 파일
    안의 여러 테스트가 서로의 `LOGIN_SUCCESS`/`LOGIN_FAILURE` 행을 침범한다. 성공 행은
    `user_id`가 위 `_TOUR_USER_ID` 리터럴과 정확히 같은 것만 지운다. 실패 행은
    `user_id`가 비어 있어(계정 존재를 노출하지 않으므로) 같은 방식으로 좁힐 수 없고,
    그 행은 테이블 전체에서 `reason = 'tour_code_rejected'`인 것만 지운다 — 이 사유
    문자열은 이 라우트만 남긴다.
    """
    from cii_platform.db.session import get_engine, get_sessionmaker

    async with get_sessionmaker()() as s:
        await s.execute(text("DELETE FROM audit_log WHERE user_id = :uid"), {"uid": _TOUR_USER_ID})
        await s.execute(
            text(
                "DELETE FROM audit_log WHERE \"action\" = 'LOGIN_FAILURE' "
                "AND details_json LIKE '%tour_code_rejected%'"
            )
        )
        await s.execute(
            text(
                "DELETE FROM user_session WHERE user_id IN "
                "(SELECT id FROM app_user WHERE email = :e)"
            ),
            {"e": _TOUR_EMAIL},
        )
        await s.execute(text("DELETE FROM app_user WHERE email = :e"), {"e": _TOUR_EMAIL})
        await s.commit()
    await get_engine().dispose()


def _tour_login(client: TestClient, code: str):
    return client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": code})


@pytest.fixture
def client(migrated_db, app_fresh_engine):
    with TestClient(app, base_url=_BASE) as c:
        yield c


# --- 1. fail-closed — 코드가 설정되지 않은 배포 ----------------------------------------------


async def test_tour_login_rejects_any_code_when_not_configured(client, monkeypatch):
    """🔴 `TOUR_ACCESS_CODE`가 없으면 아무 코드나 보내도 422다(200이 아니다)."""
    monkeypatch.delenv(tour_gate.ENV_NAME, raising=False)
    try:
        resp = _tour_login(client, "some-code-a-visitor-might-guess")
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["message"] == tour_gate.REJECTED_MESSAGE
        assert await _tour_user_row_count() == 0, "거절된 시도가 계정을 만들면 안 된다"
        assert SESSION_COOKIE_NAME not in client.cookies
    finally:
        await _cleanup()


# --- 2·3. 코드 검증 -----------------------------------------------------------------------


async def test_tour_login_rejects_wrong_code_with_shared_rejection_message(client, monkeypatch):
    """틀린 코드 — 422·정본 거절 문구, 계정은 만들어지지 않는다."""
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        resp = _tour_login(client, _CODE + "-wrong")
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["message"] == tour_gate.REJECTED_MESSAGE
        assert await _tour_user_row_count() == 0
    finally:
        await _cleanup()


async def test_tour_login_succeeds_and_issues_admin_session(client, monkeypatch):
    """코드가 맞으면 200 · ADMIN · 세션 쿠키 · 인증 완료 시각 채움."""
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        resp = _tour_login(client, _CODE)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["email"] == _TOUR_EMAIL
        assert data["role"] == "ADMIN"
        assert data["email_verified_at"] is not None
        assert SESSION_COOKIE_NAME in client.cookies
        assert CSRF_COOKIE_NAME in client.cookies
        assert await _tour_user_row_count() == 1
    finally:
        await _cleanup()


# --- 4. 재호출이 계정을 중복 생성하지 않는다 --------------------------------------------------


async def test_second_login_reuses_the_same_account(client, monkeypatch):
    """🔴 두 번째 호출도 같은 고정 UUID 행을 쓴다 — INSERT를 다시 시도하지 않는다."""
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        first = _tour_login(client, _CODE)
        assert first.status_code == 200, first.text
        assert await _tour_user_row_count() == 1

        with TestClient(app, base_url=_BASE) as second_client:
            second = second_client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": _CODE})
        assert second.status_code == 200, second.text
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert await _tour_user_row_count() == 1, "재호출이 새 행을 만들었다"
    finally:
        await _cleanup()


# --- 5. 스텁 계정은 일반 로그인으로 열리지 않는다 ----------------------------------------------


async def test_tour_stub_account_cannot_log_in_with_a_password(client, monkeypatch):
    """🔴 `tour@bluelog.local` + 아무 비밀번호 → 401. 비밀번호 해시가 Argon2가 아니다."""
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        created = _tour_login(client, _CODE)
        assert created.status_code == 200, created.text

        with TestClient(app, base_url=_BASE) as login_client:
            resp = login_client.post(
                f"{API_V1_PREFIX}/auth/login",
                json={"email": _TOUR_EMAIL, "password": "any-password-at-all-1"},
            )
        assert resp.status_code == 401, resp.text
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"
        assert SESSION_COOKIE_NAME not in login_client.cookies
    finally:
        await _cleanup()


# --- 6. 강등된 계정도 다음 로그인에서 ADMIN으로 되돌아간다 ---------------------------------------


async def test_demoted_stub_account_is_restored_to_admin_on_next_tour_login(client, monkeypatch):
    """🔴 화면에서 강등해 두어도 다음 둘러보기 로그인이 ADMIN으로 되돌린다(#1301과 같은 판단)."""
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        first = _tour_login(client, _CODE)
        assert first.status_code == 200, first.text
        await _demote_tour_user()

        with TestClient(app, base_url=_BASE) as second_client:
            second = second_client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": _CODE})
        assert second.status_code == 200, second.text
        assert second.json()["data"]["role"] == "ADMIN"
        assert await _tour_user_row_count() == 1
    finally:
        await _cleanup()


async def test_soft_deleted_stub_account_is_revived_on_next_tour_login(client, monkeypatch):
    """🔴 탈퇴해 둔 계정도 다음 둘러보기 로그인이 되살린다 (#1486).

    ## 무엇을 막는가

    둘러보기 세션은 관리자라 `DELETE /auth/me`를 누를 수 있다. 그 뒤에도 라우트는
    **PK로 행을 직접 가져오므로** `is_deleted`를 보지 않는다 — 되살리지 않으면
    **탈퇴한 계정이 살아 있는 세션을 갖는다.**

    ## 왜 조용한가

    화면은 멀쩡히 열린다. 어긋나는 것은 `is_deleted == 0`으로 거르는 **다른 경로**들이라
    (로그인 조회·계정 목록) 「대시보드는 보이는데 계정 관리에는 내가 없다」처럼 나타난다.
    """
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        first = _tour_login(client, _CODE)
        assert first.status_code == 200, first.text
        await _soft_delete_tour_user()
        assert await _tour_user_is_deleted() is True

        with TestClient(app, base_url=_BASE) as second_client:
            second = second_client.post(f"{API_V1_PREFIX}/auth/tour-login", json={"code": _CODE})
        assert second.status_code == 200, second.text
        assert await _tour_user_is_deleted() is False
        assert await _tour_user_row_count() == 1
    finally:
        await _cleanup()


async def test_tour_stub_does_not_count_as_the_last_admin(client, monkeypatch):
    """🔴 둘러보기 스텁은 「마지막 관리자」 계수에 들지 않는다 (#1486).

    ## 무엇을 막는가

    스텁도 `ADMIN`이라 그냥 세면 **사람 관리자가 한 명뿐일 때도 「둘」로 읽혀** 강등·탈퇴가
    통과한다. 그런데 둘러보기는 `TOUR_ACCESS_CODE`가 설정돼 있을 때만 들어갈 수 있는
    **런타임 설정**이다 — 인터뷰가 끝나 코드를 비우면 그 관리자는 닿을 수 없는 행이 되고,
    역할을 되돌릴 사람이 아무도 남지 않는다.

    가드가 막으려는 것은 「관리자 행이 0개」가 아니라 **「역할을 되돌릴 사람이 없는 상태」**다.
    """
    from cii_platform.api.routes.auth import _lock_admin_users
    from cii_platform.db.session import get_sessionmaker

    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        async with get_sessionmaker()() as s:
            before = await _lock_admin_users(s)

        assert _tour_login(client, _CODE).status_code == 200

        async with get_sessionmaker()() as s:
            after = await _lock_admin_users(s)

        # 스텁이 생겼는데도 사람 관리자 수는 그대로다.
        assert after == before
    finally:
        await _cleanup()


# --- 7. 감사 로그 -------------------------------------------------------------------------


async def test_success_is_audited_with_tour_flag_and_no_code_leak(client, monkeypatch):
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        resp = _tour_login(client, _CODE)
        assert resp.status_code == 200, resp.text

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            events = await _fetch_tour_success_events(s)
            assert len(events) == 1
            assert events[0]["details_json"] == {"tour": True}
            assert events[0]["user_id"]
            assert _CODE not in str(events[0]["details_json"])
    finally:
        await _cleanup()


async def test_failure_is_audited_with_rejection_reason_and_no_code_leak(client, monkeypatch):
    monkeypatch.setenv(tour_gate.ENV_NAME, _CODE)
    try:
        resp = _tour_login(client, _CODE + "-wrong")
        assert resp.status_code == 422, resp.text

        from cii_platform.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            events = await _fetch_tour_failure_events(s)
            assert len(events) == 1
            # 실패는 주체를 특정할 수 없다 — 계정 존재 여부를 노출하지 않는다.
            assert events[0]["user_id"] is None
            serialized = str(events[0]["details_json"])
            assert _CODE not in serialized
            assert (_CODE + "-wrong") not in serialized
    finally:
        await _cleanup()
